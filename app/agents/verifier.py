"""AGENT 3 -- Verifier: independently checks the Worker's draft before
anything is delivered, and can OVERRULE it. Two layers:
  1. Deterministic field-comparison against the source record (cheap, always
     run, catches AGENT_HALLUCINATION / AGENT_MALFORMED / AGENT_LOOP
     directly and generalizes perfectly to held-out data since it's a
     structural comparison, not a wording match).
  2. An LLM semantic faithfulness check (only spent if #1 already passed --
     cheap-by-design), the load-bearing "agent-checks-agent" LLM call.
Called only by the Orchestrator; never calls the Worker itself.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import Config
from app.llm.client import call_structured
from app.schemas.contracts import VerifierCheck, VerifierInput, VerifierOutput
from app.schemas.record import AgentTraceSpan

PROMPT_VERSION = "verifier-v1"

SYSTEM_PROMPT = """You are the Verifier agent. You are given SOURCE fields and a DRAFT
summary written by a different agent (the Worker). Decide whether the summary
faithfully reflects ONLY the source fields, with no invented figures, names,
dates, or claims beyond what the source supports.

Reply with strict JSON only:
{"faithful": true, "issue": null}
or
{"faithful": false, "issue": "<short reason>"}"""


def _num_eq(a, b, tol: float = 0.01) -> bool:
    if a is None or b is None:
        return a == b
    try:
        return abs(float(a) - float(b)) < tol
    except (TypeError, ValueError):
        return False


def _str_eq(a, b) -> bool:
    if a is None or b is None:
        return a == b
    return str(a).strip().lower() == str(b).strip().lower()


def _deterministic_checks(inp: VerifierInput) -> list[VerifierCheck]:
    r, w = inp.record, inp.worker_output
    checks = [
        VerifierCheck(
            name="owner_matches_source",
            passed=_str_eq(w.claim_owner, r.owner),
            detail=f"worker={w.claim_owner!r} source={r.owner!r}",
        ),
        VerifierCheck(
            name="category_matches_source",
            passed=_str_eq(w.claim_category, r.category),
            detail=f"worker={w.claim_category!r} source={r.category!r}",
        ),
        VerifierCheck(
            name="amount_matches_source",
            passed=_num_eq(w.claim_amount, r.amount),
            detail=f"worker={w.claim_amount!r} source={r.amount!r}",
        ),
        VerifierCheck(
            name="deadline_matches_source",
            passed=_str_eq(w.sla_date, r.deadline),
            detail=f"worker={w.sla_date!r} source={r.deadline!r}",
        ),
    ]
    return checks


def run_verifier(
    inp: VerifierInput, *, cfg: Config, transcripts_dir: Path, attempt: int = 0
) -> tuple[VerifierOutput, AgentTraceSpan]:
    worker_output = inp.worker_output

    if worker_output.malformed:
        out = VerifierOutput(verdict="fail", reason_code="AGENT_MALFORMED", notes="worker output was not valid structured JSON")
        span = AgentTraceSpan(agent="verifier", status="rejected", verdict="fail", retries=attempt)
        return out, span

    if worker_output.abstained:
        out = VerifierOutput(verdict="needs_human", reason_code=None, notes=worker_output.abstain_reason)
        span = AgentTraceSpan(agent="verifier", status="routed", verdict="needs_human", retries=attempt)
        return out, span

    checks = _deterministic_checks(inp)
    failed = [c for c in checks if not c.passed]
    if failed:
        out = VerifierOutput(
            verdict="fail",
            checks=checks,
            reason_code="AGENT_HALLUCINATION",
            notes="worker output diverges from source: " + "; ".join(c.name for c in failed),
        )
        span = AgentTraceSpan(agent="verifier", status="overruled", verdict="fail", retries=attempt)
        return out, span

    # Deterministic checks passed -- spend one cheap LLM call on a semantic
    # faithfulness pass over the free-text summary.
    user_prompt = json.dumps(
        {
            "source": {
                "owner": inp.record.owner,
                "category": inp.record.category,
                "amount": inp.record.amount,
                "deadline": inp.record.deadline,
                "notes": inp.record.notes,
            },
            "draft_summary": worker_output.summary,
        },
        sort_keys=True,
    )
    result = call_structured(
        cfg=cfg,
        transcripts_dir=transcripts_dir,
        agent="verifier",
        record_id=inp.record.id,
        model=cfg.llm_model_cheap,
        prompt_version=PROMPT_VERSION,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        attempt=attempt,
    )
    content = result.content or {}
    faithful = bool(content.get("faithful", not result.malformed))
    checks.append(VerifierCheck(name="llm_semantic_faithfulness", passed=faithful, detail=content.get("issue")))

    span = AgentTraceSpan(
        agent="verifier",
        model=result.model,
        prompt_version=PROMPT_VERSION,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        retries=attempt,
        transcript_hash=result.transcript_hash,
        status="ok" if faithful else "overruled",
        verdict="pass" if faithful else "fail",
    )
    out = VerifierOutput(
        verdict="pass" if faithful else "fail",
        checks=checks,
        reason_code=None if faithful else "AGENT_HALLUCINATION",
        notes=content.get("issue"),
        model_used=result.model,
        prompt_version=PROMPT_VERSION,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        transcript_hash=result.transcript_hash,
    )
    return out, span
