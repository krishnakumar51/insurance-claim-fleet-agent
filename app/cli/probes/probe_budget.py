"""make probe-budget: exit 0 ONLY if a record exceeding the per-record
cost/step ceiling raises BUDGET_EXCEEDED and is downgraded or routed --
never silently overspent. Forces the ceiling artificially low via env var
(the same MAX_COST_USD_PER_RECORD a real deployment would tune)."""
from __future__ import annotations

import os

from app.config import load_config
from app.graph.pipeline_graph import build_graph, run_record
from app.schemas.record import NormalizedRecord


def main() -> int:
    os.environ["MAX_COST_USD_PER_RECORD"] = "0.0000000001"  # impossible to satisfy
    cfg = load_config()
    assert cfg.max_cost_usd_per_record < 1e-9

    record = NormalizedRecord(
        id="PROBE-BUDGET-1", owner="j.doe", deadline="2026-08-01", category="RENEWAL",
        notes="Routine renewal.", version=1, amount=4200.0,
        source_format="feed", source_version_hash="sha256:" + "8" * 64,
    )

    compiled = build_graph(cfg, cfg.transcripts_dir)
    result = run_record(record, cfg=cfg, transcripts_dir=cfg.transcripts_dir, compiled=compiled)

    caught = result["terminal_status"] == "exception" and result["reason_code"] == "BUDGET_EXCEEDED"
    no_llm_spend = result["cost_so_far"] == 0.0  # must be caught BEFORE any call, not after overspending
    ok = caught and no_llm_spend

    print(f"  terminal_status={result['terminal_status']} reason_code={result['reason_code']} cost_so_far={result['cost_so_far']}")
    print(f"  {'PASS' if caught else 'FAIL'}: BUDGET_EXCEEDED raised and record routed to exception")
    print(f"  {'PASS' if no_llm_spend else 'FAIL'}: no LLM spend occurred before the ceiling was enforced")

    # Second run with a normal ceiling proves the block above wasn't a permanently broken path.
    os.environ["MAX_COST_USD_PER_RECORD"] = "0.02"
    cfg2 = load_config()
    compiled2 = build_graph(cfg2, cfg2.transcripts_dir)
    result2 = run_record(record, cfg=cfg2, transcripts_dir=cfg2.transcripts_dir, compiled=compiled2)
    normal_ok = result2["terminal_status"] != "exception" or result2["reason_code"] != "BUDGET_EXCEEDED"
    print(f"  {'PASS' if normal_ok else 'FAIL'}: with a normal ceiling, the same record is not blocked by budget (control case)")
    ok = ok and normal_ok

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
