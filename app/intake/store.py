"""SQLite-backed persistence for Intake. Records are upserted keyed on
(id, source_format, source_version_hash) so re-running Intake on the same
seed is idempotent -- no duplicate rows, no hardcoded in-memory array."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.record import RawRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT NOT NULL,
    source_format TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_version_hash TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    field_names_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (id, source_format, source_version_hash)
);
"""


class IntakeStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(_SCHEMA)
        self.conn.commit()

    def upsert(self, records: list[RawRecord]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                r.id, r.source_format, r.source_path, r.source_version_hash,
                json.dumps(r.fields, sort_keys=True),
                json.dumps(r.field_names_seen),
                now,
            )
            for r in records
        ]
        self.conn.executemany(
            "INSERT OR IGNORE INTO records "
            "(id, source_format, source_path, source_version_hash, fields_json, field_names_json, ingested_at) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def all(self) -> list[RawRecord]:
        cur = self.conn.execute(
            "SELECT id, source_format, source_path, source_version_hash, fields_json, field_names_json "
            "FROM records ORDER BY id, source_format"
        )
        out = []
        for id_, fmt, path, vhash, fields_json, names_json in cur.fetchall():
            out.append(
                RawRecord(
                    id=id_,
                    source_format=fmt,
                    source_path=path,
                    source_version_hash=vhash,
                    fields=json.loads(fields_json),
                    field_names_seen=json.loads(names_json),
                )
            )
        return out

    def close(self) -> None:
        self.conn.close()
