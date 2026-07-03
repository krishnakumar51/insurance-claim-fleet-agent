"""Transcript store: committed, content-addressed LLM call recordings.

Each transcript file is named `<sha256-of-response>.json` (content-addressed,
so verify_audit.py's "filename must match response_hash" check holds by
construction). A small `index.json` alongside them maps the call-site key
(record_id, agent, prompt_version) -> filename, so REPLAY_LLM=true can find
the right transcript deterministically without re-hashing anything.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(_canon(obj)).hexdigest()


def _index_path(transcripts_dir: Path) -> Path:
    return transcripts_dir / "index.json"


def _load_index(transcripts_dir: Path) -> dict[str, str]:
    p = _index_path(transcripts_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _save_index(transcripts_dir: Path, index: dict[str, str]) -> None:
    _index_path(transcripts_dir).write_text(
        json.dumps(index, sort_keys=True, indent=2), encoding="utf-8"
    )


def _key(record_id: str, agent: str, prompt_version: str, attempt: int = 0) -> str:
    suffix = f"#{attempt}" if attempt else ""
    return f"{record_id}:{agent}:{prompt_version}{suffix}"


class TranscriptNotFound(RuntimeError):
    pass


def record_transcript(
    transcripts_dir: Path,
    *,
    record_id: str,
    agent: str,
    model: str,
    prompt_version: str,
    request: dict,
    response: dict,
    delivered_fields: dict | None,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    latency_ms: float,
    attempt: int = 0,
) -> str:
    """Writes a transcript, returns its transcript_hash (sha256:<hex>)."""
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    response_hash = sha(response)
    stem = response_hash.split(":")[-1]

    payload = {
        "record_id": record_id,
        "agent": agent,
        "model": model,
        "prompt_version": prompt_version,
        "request": request,
        "response": response,
        "response_hash": response_hash,
        "delivered_fields_hash": sha(delivered_fields) if delivered_fields is not None else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (transcripts_dir / f"{stem}.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
    )

    index = _load_index(transcripts_dir)
    index[_key(record_id, agent, prompt_version, attempt)] = f"{stem}.json"
    _save_index(transcripts_dir, index)

    return response_hash


def load_transcript(
    transcripts_dir: Path, *, record_id: str, agent: str, prompt_version: str, attempt: int = 0
) -> dict:
    index = _load_index(transcripts_dir)
    fname = index.get(_key(record_id, agent, prompt_version, attempt))
    if fname is None:
        raise TranscriptNotFound(
            f"no committed transcript for record={record_id} agent={agent} "
            f"prompt_version={prompt_version} attempt={attempt}"
        )
    path = transcripts_dir / fname
    if not path.exists():
        raise TranscriptNotFound(f"transcript index points at missing file {fname}")
    return json.loads(path.read_text(encoding="utf-8"))
