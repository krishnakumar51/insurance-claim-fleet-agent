from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.schemas.record import RawRecord


def _hash(obj) -> str:
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def parse_feed(feed_path: Path) -> list[RawRecord]:
    if not feed_path.exists():
        return []
    entries = json.loads(feed_path.read_text(encoding="utf-8"))
    out: list[RawRecord] = []
    for entry in entries:
        rec_id = str(entry.get("id") or entry.get("Id") or "").strip()
        if not rec_id:
            continue
        out.append(
            RawRecord(
                id=rec_id,
                source_format="feed",
                source_path=str(feed_path),
                source_version_hash=_hash(entry),
                fields=entry,
                field_names_seen=list(entry.keys()),
            )
        )
    return out
