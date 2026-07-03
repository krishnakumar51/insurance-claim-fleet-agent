"""Stage 1 -- Intake: parse both seed formats and persist every record."""
from __future__ import annotations

from pathlib import Path

from app.intake.parse_eml import parse_eml
from app.intake.parse_feed import parse_feed
from app.intake.parse_pdf import parse_pdf
from app.intake.store import IntakeStore
from app.schemas.record import RawRecord


def parse_seed_dir(seed_dir: Path) -> list[RawRecord]:
    records: list[RawRecord] = []
    records.extend(parse_feed(seed_dir / "feed.json"))

    inbox = seed_dir / "inbox"
    if inbox.exists():
        for path in sorted(inbox.iterdir()):
            if path.suffix.lower() == ".eml":
                rec = parse_eml(path)
            elif path.suffix.lower() == ".pdf":
                rec = parse_pdf(path)
            else:
                continue
            if rec is not None:
                records.append(rec)
    return records


def ingest(seed_dir: Path, db_path: Path) -> list[RawRecord]:
    """Parse the seed pack and persist every record (idempotent). Returns the
    full current set of persisted raw records, read back from the store."""
    parsed = parse_seed_dir(seed_dir)
    store = IntakeStore(db_path)
    try:
        store.upsert(parsed)
        return store.all()
    finally:
        store.close()
