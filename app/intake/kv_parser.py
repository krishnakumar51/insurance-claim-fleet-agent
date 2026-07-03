"""Shared 'Key: Value' line-format parser used by both the .eml and .pdf intake
adapters -- both source formats in the seed serialize records the same way,
just wrapped in different containers (RFC822 email vs PDF text layer)."""
from __future__ import annotations

import re

_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _-]*)\s*:\s*(.*)$")


def parse_kv_block(text: str) -> dict[str, str]:
    """Parse lines like 'Amount: 5300' into {'Amount': '5300'}, preserving the
    original key casing/spelling so schema-drift (e.g. 'Value' vs 'Amount')
    survives into the raw record for the normalize stage to detect."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if key.lower() in ("from", "to", "subject", "content-type"):
            continue
        fields[key] = value
    return fields
