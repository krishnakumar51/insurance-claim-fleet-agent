"""Stage 5 -- branded output package: the actual deliverable, built only
from records that reached 'delivered' in the approval state machine."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.audit.writer import sha


def build_package(*, industry: str, case_id: str, delivered: list[dict[str, Any]]) -> dict:
    return {
        "industry": industry,
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "claim_count": len(delivered),
        "claims": delivered,
    }


def write_package(out_dir: Path, package: dict) -> str:
    """Writes the branded package to disk, returns its output_package_hash."""
    pkg_dir = out_dir / "package"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "claims_package.json").write_text(
        json.dumps(package, sort_keys=True, indent=2), encoding="utf-8"
    )
    return sha(package)
