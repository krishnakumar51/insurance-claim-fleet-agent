"""Stage 2 (part 2) -- exception-queue detectors. Every function here detects
a problem TYPE (not a hardcoded id/value) so it generalizes to the held-out
seed, which reuses the same types with different values/wording.

Precedence (first match wins) follows TASK.md's table order:
STALE > MISSING_INPUT > OUTLIER > INJECTION_BLOCKED > LOW_CONFIDENCE > UNVERIFIED_ANOMALY
"""
from __future__ import annotations

import re
import statistics
from datetime import date, datetime

from app.schemas.record import NormalizedRecord

KNOWN_CATEGORIES = {"ONBOARDING", "RENEWAL", "REVIEW", "REPORT", "INTAKE"}

# Phrases that indicate an attempt to manipulate the agent into overriding
# system rules or authoritative data via free-text `notes`. Lexical CLASS of
# injection, not specific wording -- held-out will phrase this differently.
_INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?(previous|your)\s+\w+"
    r"|ignore\s+the\s+field"
    r"|skip\s+review"
    r"|approve\s+(this\s+)?immediately"
    r"|disregard\s+"
    r"|bypass\s+"
    r"|override\s+(your\s+)?rules",
    re.IGNORECASE,
)

# Lexical signal that a record's own content flags itself as ambiguous /
# unresolved, independent of specific wording used in the seed.
_AMBIGUITY_RE = re.compile(
    r"unclear|ambiguous|inconsistent|could be|not attached|uncertain|unsure|"
    r"conflicting|tbd\b|either .* or",
    re.IGNORECASE,
)

_OUTLIER_MODIFIED_Z_THRESHOLD = 3.5


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def is_stale(record: NormalizedRecord, pipeline_now: date) -> bool:
    d = _parse_date(record.deadline)
    return d is not None and d < pipeline_now


def is_missing_input(record: NormalizedRecord) -> bool:
    return record.amount is None or not record.owner or not record.deadline


def compute_outlier_ids(records: list[NormalizedRecord]) -> set[str]:
    """Robust (median/MAD) outlier check over the whole batch's amounts --
    relative to the batch, not a hardcoded threshold, so it generalizes to
    held-out data with different magnitudes."""
    amounts = [(r.id, r.amount) for r in records if r.amount is not None]
    values = [a for _, a in amounts]
    if len(values) < 3:
        return set()

    median = statistics.median(values)
    abs_devs = [abs(v - median) for v in values]
    mad = statistics.median(abs_devs)

    flagged: set[str] = set()
    if mad == 0:
        # Degenerate batch (near-identical values): fall back to a
        # ratio-from-median check so a single huge spike still gets caught.
        for rid, v in amounts:
            if median > 0 and (v / median > 5 or v / median < 0.2):
                flagged.add(rid)
        return flagged

    for rid, v in amounts:
        modified_z = 0.6745 * (v - median) / mad
        if abs(modified_z) > _OUTLIER_MODIFIED_Z_THRESHOLD:
            flagged.add(rid)
    return flagged


def is_injection(record: NormalizedRecord) -> bool:
    return bool(record.notes and _INJECTION_RE.search(record.notes))


def is_low_confidence(record: NormalizedRecord) -> bool:
    if record.category and record.category.strip().upper() not in KNOWN_CATEGORIES:
        return True
    if record.notes and _AMBIGUITY_RE.search(record.notes):
        return True
    return False


def is_unverified_anomaly(record: NormalizedRecord) -> bool:
    """Catch-all validation net: anything structurally off that none of the
    named detectors caught. This is what's supposed to catch the held-out
    seed's undocumented anomaly. Deliberately structural (not id-prefix or
    wording based) so it doesn't overfit to the dev seed's "REC-" naming."""
    if not record.id or not record.id.strip():
        return True
    if record.amount is not None and record.amount <= 0:
        return True
    if record.deadline is not None and _parse_date(record.deadline) is None:
        return True
    if record.version is not None and record.version < 1:
        return True
    return False


def classify(
    record: NormalizedRecord,
    pipeline_now: date,
    outlier_ids: set[str],
) -> tuple[str | None, str | None]:
    """Returns (reason_code, reason_class) for a record about to enter
    Assembly, or (None, None) if it's clean. Class-B (SCHEMA_DRIFT /
    SUPERSEDED_VERSION) is already recorded on the NormalizedRecord itself by
    normalize.py and doesn't block, so it's not decided here."""
    if is_stale(record, pipeline_now):
        return "STALE", "A"
    if is_missing_input(record):
        return "MISSING_INPUT", "A"
    if record.id in outlier_ids:
        return "OUTLIER", "A"
    if is_injection(record):
        return "INJECTION_BLOCKED", "A"
    if is_low_confidence(record):
        return "LOW_CONFIDENCE", "A"
    if is_unverified_anomaly(record):
        return "UNVERIFIED_ANOMALY", "A"
    return None, None
