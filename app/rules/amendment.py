"""Step 8 amendment: CASE_ID-derived second-approver gate. Role/threshold are
computed once in config.py (single source of truth); this module just applies
the rule to a record."""
from __future__ import annotations

from app.schemas.record import NormalizedRecord


def requires_second_approval(record: NormalizedRecord, threshold: float) -> bool:
    return record.amount is not None and record.amount >= threshold
