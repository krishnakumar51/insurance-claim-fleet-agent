from __future__ import annotations

import hashlib
from email import policy
from email.parser import BytesParser
from pathlib import Path

from app.intake.kv_parser import parse_kv_block
from app.schemas.record import RawRecord


def parse_eml(path: Path) -> RawRecord | None:
    raw_bytes = path.read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body is not None else msg.get_payload()

    fields = parse_kv_block(text)
    rec_id = fields.get("Id") or fields.get("ID")
    if not rec_id:
        return None

    return RawRecord(
        id=rec_id,
        source_format="eml",
        source_path=str(path),
        source_version_hash="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        fields=fields,
        field_names_seen=list(fields.keys()),
    )
