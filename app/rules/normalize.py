"""Stage 2 (part 1) -- declarative normalization.

Field mapping lives in field_map.json (a separate declarative artifact, not
buried in code) so the accepted field names per canonical field are visible
and extensible without touching logic. A field matched via `synonyms` (not
`primary`) is SCHEMA_DRIFT: mapped to canonical, logged, record still proceeds
(Class B, non-blocking) -- this is what catches REC-016's 'Value' -> 'amount'.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.schemas.record import NormalizedRecord, RawRecord

_FIELD_MAP_PATH = Path(__file__).parent / "field_map.json"
_FIELD_MAP: dict[str, dict[str, list[str]]] = json.loads(_FIELD_MAP_PATH.read_text(encoding="utf-8"))
_KNOWN_NAMES: set[str] = {
    name.lower()
    for spec in _FIELD_MAP.values()
    for name in spec.get("primary", []) + spec.get("synonyms", [])
}

_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _looks_numeric(v: Any) -> bool:
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        return bool(_NUMERIC_RE.match(v.strip()))
    return False


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any, default: int = 1) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def normalize(raw: RawRecord) -> NormalizedRecord:
    lower_to_original = {str(k).lower(): k for k in raw.fields}
    claimed: set[str] = set()
    canonical_values: dict[str, Any] = {}
    field_map_applied: dict[str, str] = {}
    schema_drift = False

    for canonical, spec in _FIELD_MAP.items():
        matched_key = None
        via_synonym = False

        for candidate in spec.get("primary", []):
            k = lower_to_original.get(candidate.lower())
            if k is not None and k not in claimed:
                matched_key = k
                break

        if matched_key is None:
            for candidate in spec.get("synonyms", []):
                k = lower_to_original.get(candidate.lower())
                if k is not None and k not in claimed:
                    matched_key = k
                    via_synonym = True
                    break

        # Last-resort heuristic for held-out rename patterns we didn't
        # anticipate: an unclaimed field whose value shape fits (numeric for
        # amount/version) is treated as a renamed match rather than dropped.
        if matched_key is None and canonical in ("amount", "version"):
            for k, v in raw.fields.items():
                if k in claimed or k.lower() in _KNOWN_NAMES:
                    continue
                if _looks_numeric(v):
                    matched_key = k
                    via_synonym = True
                    break

        if matched_key is not None:
            claimed.add(matched_key)
            canonical_values[canonical] = raw.fields.get(matched_key)
            if via_synonym:
                field_map_applied[canonical] = matched_key
                schema_drift = True

    return NormalizedRecord(
        id=raw.id,
        owner=(str(canonical_values["owner"]).strip() if canonical_values.get("owner") not in (None, "") else None),
        deadline=(str(canonical_values["deadline"]).strip() if canonical_values.get("deadline") not in (None, "") else None),
        category=(str(canonical_values["category"]).strip() if canonical_values.get("category") not in (None, "") else None),
        notes=(str(canonical_values["notes"]) if canonical_values.get("notes") not in (None, "") else None),
        version=_to_int(canonical_values.get("version"), default=1),
        amount=_to_float(canonical_values.get("amount")),
        source_format=raw.source_format,
        source_version_hash=raw.source_version_hash,
        raw_fields=raw.fields,
        field_map_applied=field_map_applied,
        schema_drift=schema_drift,
    )


def resolve_superseded(records: list[NormalizedRecord]) -> list[NormalizedRecord]:
    """SUPERSEDED_VERSION: same id appears more than once -> keep the highest
    `version`, mark the rest superseded (Class B, logged, doesn't block)."""
    by_id: dict[str, list[NormalizedRecord]] = {}
    for r in records:
        by_id.setdefault(r.id, []).append(r)

    resolved: list[NormalizedRecord] = []
    for rid, group in by_id.items():
        if len(group) == 1:
            resolved.append(group[0])
            continue
        group_sorted = sorted(group, key=lambda r: r.version, reverse=True)
        latest = group_sorted[0]
        resolved.append(latest)
        for older in group_sorted[1:]:
            older.superseded_by = f"{latest.source_format}:v{latest.version}"
            resolved.append(older)
    return resolved
