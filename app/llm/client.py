"""LLM client: OpenAI-Chat-Completions-compatible, so the same code path works
against OpenRouter today (dev/replay generation, open-source + free models,
no Anthropic/OpenAI/Gemini key needed) and against a real gpt-4o-mini key at
grading time (TASK.md Step 7) -- only LLM_BASE_URL/LLM_API_KEY/LLM_MODEL
change, the client code doesn't.

REPLAY_LLM=true (default) never calls the network: it looks up a committed
transcript. REPLAY_LLM=false calls OpenRouter/OpenAI for real and commits a
new transcript as a side effect, so the run is replayable next time.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Config
from app.llm.replay import TranscriptNotFound, load_transcript, record_transcript

# Rough per-1M-token USD pricing, used only for the cost/budget accounting the
# task requires -- not billing-accurate, documented estimate (DECISIONS.md).
_PRICING_PER_1M = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-3.5-haiku": (0.80, 4.00),
    "meta-llama/llama-3.3-70b-instruct:free": (0.0, 0.0),
    "deepseek/deepseek-chat": (0.14, 0.28),
}
_DEFAULT_PRICING = (0.50, 1.50)  # gpt-4o-mini-ish fallback for unlisted models


def _price(model: str) -> tuple[float, float]:
    return _PRICING_PER_1M.get(model, _DEFAULT_PRICING)


def _cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = _price(model)
    return round(tokens_in / 1_000_000 * p_in + tokens_out / 1_000_000 * p_out, 8)


@dataclass
class LLMCallResult:
    content: dict
    model: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    transcript_hash: str
    malformed: bool = False


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _real_call(cfg: Config, model: str, system_prompt: str, user_prompt: str) -> tuple[dict | None, int, int, float]:
    from openai import OpenAI

    client = OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    latency_ms = (time.monotonic() - t0) * 1000
    raw_text = resp.choices[0].message.content or ""
    usage = resp.usage
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    parsed = _extract_json(raw_text)
    return parsed, tokens_in, tokens_out, latency_ms


def call_structured(
    *,
    cfg: Config,
    transcripts_dir: Path,
    agent: str,
    record_id: str,
    model: str,
    prompt_version: str,
    system_prompt: str,
    user_prompt: str,
    delivered_fields_fn=None,
    attempt: int = 0,
) -> LLMCallResult:
    """delivered_fields_fn(content: dict) -> dict|None lets the caller derive
    the load-bearing delivered_fields from the parsed response, so its hash
    can be embedded in the transcript for verify_audit.py check #8/#14."""
    if cfg.replay_llm:
        t = load_transcript(transcripts_dir, record_id=record_id, agent=agent, prompt_version=prompt_version, attempt=attempt)
        return LLMCallResult(
            content=t["response"],
            model=t["model"],
            prompt_version=t["prompt_version"],
            tokens_in=t["tokens_in"],
            tokens_out=t["tokens_out"],
            cost_usd=t["cost_usd"],
            latency_ms=t["latency_ms"],
            transcript_hash=t["response_hash"],
            malformed=t["response"] is None,
        )

    parsed, tokens_in, tokens_out, latency_ms = _real_call(cfg, model, system_prompt, user_prompt)
    cost = _cost_usd(model, tokens_in, tokens_out)
    delivered_fields = delivered_fields_fn(parsed) if (delivered_fields_fn and parsed is not None) else None
    response_hash = record_transcript(
        transcripts_dir,
        record_id=record_id,
        agent=agent,
        model=model,
        prompt_version=prompt_version,
        request={"system": system_prompt, "user": user_prompt},
        response=parsed if parsed is not None else {},
        delivered_fields=delivered_fields,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        latency_ms=latency_ms,
        attempt=attempt,
    )
    return LLMCallResult(
        content=parsed or {},
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        latency_ms=latency_ms,
        transcript_hash=response_hash,
        malformed=parsed is None,
    )
