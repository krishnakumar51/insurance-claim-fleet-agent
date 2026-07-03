"""Stage 5 -- append-only audit log + final audit.json assembly.

Append-only is enforced with a hash chain, not just "we didn't write a
delete method": every event embeds prev_hash + its own event_hash, so
mutating or deleting any past event breaks the chain from that point
forward and `verify_chain` catches it deterministically. This is what
`make probe-append-only` exercises.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

GENESIS_HASH = "sha256:" + "0" * 64


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(_canon(obj)).hexdigest()


class AppendOnlyLog:
    """In-memory event log for a single run. `events()` returns the final,
    schema-conformant + hash-chained list ready to embed in audit.json."""

    def __init__(self):
        self._raw: list[dict] = []

    def append(self, actor: str, action: str, record_id: str | None = None) -> None:
        self._raw.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "action": action,
                "record_id": record_id,
            }
        )

    def events(self) -> list[dict]:
        chained = []
        prev_hash = GENESIS_HASH
        for i, e in enumerate(self._raw):
            row = {"seq": i, "ts": e["ts"], "actor": e["actor"], "action": e["action"], "record_id": e["record_id"]}
            row["prev_hash"] = prev_hash
            event_hash = sha(row)
            row["event_hash"] = event_hash
            chained.append(row)
            prev_hash = event_hash
        return chained


def verify_chain(events: list[dict]) -> bool:
    """Re-derives every event_hash from its content + prev_hash. Any past
    mutation (field edit, deletion, reorder) breaks the chain at or after
    the tampered index -> returns False."""
    prev_hash = GENESIS_HASH
    for i, e in enumerate(events):
        if e.get("seq") != i:
            return False
        if e.get("prev_hash") != prev_hash:
            return False
        row = {k: e[k] for k in ("seq", "ts", "actor", "action", "record_id")}
        row["prev_hash"] = prev_hash
        expected_hash = sha(row)
        if e.get("event_hash") != expected_hash:
            return False
        prev_hash = expected_hash
    return True


def build_audit(
    *,
    case_id: str,
    pipeline_version: str,
    seed_dir: str,
    pipeline_now: str,
    amendment_role: str,
    amendment_threshold: float,
    agents: list[dict],
    cost_summary: dict,
    output_package_hash: str,
    records: list[dict],
    events: list[dict],
) -> dict:
    return {
        "case_id": case_id,
        "pipeline_version": pipeline_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed_dir": seed_dir,
        "pipeline_now": pipeline_now,
        "amendment": {"role": amendment_role, "threshold": amendment_threshold},
        "agents": agents,
        "cost": cost_summary,
        "output_package_hash": output_package_hash,
        "records": records,
        "events": events,
    }
