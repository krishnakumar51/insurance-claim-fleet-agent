from __future__ import annotations

import hashlib
from pathlib import Path

from pypdf import PdfReader

from app.intake.kv_parser import parse_kv_block
from app.schemas.record import RawRecord


def parse_pdf(path: Path) -> RawRecord | None:
    raw_bytes = path.read_bytes()
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    fields = parse_kv_block(text)
    rec_id = fields.get("Id") or fields.get("ID")
    if not rec_id:
        return None

    return RawRecord(
        id=rec_id,
        source_format="pdf",
        source_path=str(path),
        source_version_hash="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        fields=fields,
        field_names_seen=list(fields.keys()),
    )
