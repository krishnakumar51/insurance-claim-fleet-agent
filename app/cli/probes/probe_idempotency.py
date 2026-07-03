"""make probe-idempotency: exit 0 ONLY if running demo twice produces no
duplicate outputs/exceptions/approvals. Runs the real pipeline twice
end-to-end (offline, via REPLAY_LLM=true) and diffs the results."""
from __future__ import annotations

import sqlite3

from app.cli.main import run_pipeline
from app.config import load_config


def main() -> int:
    cfg = load_config()
    ok = True

    def _keys(records):
        # (id, source_format, version) -- NOT just id: a superseded record
        # legitimately shares its id with the version that superseded it
        # (e.g. REC-017 v1/feed superseded by REC-017 v2/pdf), that's correct
        # data lineage, not a duplicate.
        return [(r["id"], r["source_format"], r.get("version")) for r in records]

    audit1 = run_pipeline(cfg)
    ids1 = _keys(audit1["records"])

    db_path = cfg.out_dir.parent / "state" / "intake.db"
    conn = sqlite3.connect(db_path)
    count_after_run1 = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()

    audit2 = run_pipeline(cfg)
    ids2 = _keys(audit2["records"])

    conn = sqlite3.connect(db_path)
    count_after_run2 = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()

    no_dupes_within_run = len(ids1) == len(set(ids1)) and len(ids2) == len(set(ids2))
    print(f"  {'PASS' if no_dupes_within_run else 'FAIL'}: no duplicate (id, source_format, version) rows within a single run")
    ok &= no_dupes_within_run

    same_count = len(ids1) == len(ids2)
    print(f"  {'PASS' if same_count else 'FAIL'}: record count stable across two runs ({len(ids1)} vs {len(ids2)})")
    ok &= same_count

    same_ids = set(ids1) == set(ids2)
    print(f"  {'PASS' if same_ids else 'FAIL'}: identical record id set across two runs")
    ok &= same_ids

    same_statuses = all(
        r1["status"] == r2["status"] and r1.get("reason_code") == r2.get("reason_code")
        for r1, r2 in zip(sorted(audit1["records"], key=lambda r: r["id"]), sorted(audit2["records"], key=lambda r: r["id"]))
    )
    print(f"  {'PASS' if same_statuses else 'FAIL'}: identical status/reason_code per record across two runs")
    ok &= same_statuses

    intake_stable = count_after_run1 == count_after_run2
    print(f"  {'PASS' if intake_stable else 'FAIL'}: intake store row count didn't grow on rerun ({count_after_run1} -> {count_after_run2})")
    ok &= intake_stable

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
