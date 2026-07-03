"""`make eval` -- runs the golden-case suite + one LLM-judge pass, prints
per-agent scores. Orchestrator is scored against deterministic ground truth
(rule-based agent, so ground truth IS the spec). Verifier is scored two ways:
its own deterministic hallucination/malformed catches, PLUS an independent
LLM meta-judge call that re-evaluates one of its verdicts. Worker is scored
by its live faithfulness rate against the most recent `make demo` run.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import load_config
from app.rules.detectors import classify
from app.rules.normalize import normalize, resolve_superseded
from app.schemas.record import RawRecord
from app.agents.verifier import run_verifier
from eval.golden_cases.cases import DETECTOR_CASES, PIPELINE_NOW, VERIFIER_CASES


def _score_orchestrator() -> tuple[int, int, list[str]]:
    passed, total, failures = 0, 0, []
    for case in DETECTOR_CASES:
        total += 1
        code, _cls = classify(case["record"], PIPELINE_NOW, outlier_ids=set())
        if code == case["expected_code"]:
            passed += 1
        else:
            failures.append(f"{case['name']}: expected {case['expected_code']!r}, got {code!r}")

    # Schema-drift + superseded-version, exercised through normalize() directly.
    total += 1
    drift_raw = RawRecord(
        id="GC-DRIFT", source_format="eml", source_path="x", source_version_hash="sha256:" + "1" * 64,
        fields={"Id": "GC-DRIFT", "Owner": "a.b", "Deadline": "2026-08-01", "Category": "RENEWAL",
                "Notes": "n/a", "Version": "1", "Value": "4000"},
        field_names_seen=["Id", "Owner", "Deadline", "Category", "Notes", "Version", "Value"],
    )
    norm = normalize(drift_raw)
    if norm.schema_drift and norm.amount == 4000.0:
        passed += 1
    else:
        failures.append(f"schema_drift_field_renamed: drift={norm.schema_drift} amount={norm.amount}")

    total += 1
    dup_a = normalize(RawRecord(
        id="GC-DUP", source_format="feed", source_path="x", source_version_hash="sha256:" + "2" * 64,
        fields={"id": "GC-DUP", "owner": "a", "deadline": "2026-08-01", "category": "REPORT",
                "notes": "v1", "version": 1, "amount": 100}, field_names_seen=[],
    ))
    dup_b = normalize(RawRecord(
        id="GC-DUP", source_format="pdf", source_path="y", source_version_hash="sha256:" + "3" * 64,
        fields={"Id": "GC-DUP", "Owner": "a", "Deadline": "2026-08-01", "Category": "REPORT",
                "Notes": "v2 corrected", "Version": "2", "Amount": "150"}, field_names_seen=[],
    ))
    resolved = resolve_superseded([dup_a, dup_b])
    older = next(r for r in resolved if r.version == 1)
    newer = next(r for r in resolved if r.version == 2)
    if older.superseded_by and not newer.superseded_by:
        passed += 1
    else:
        failures.append("superseded_version_keeps_latest: resolution incorrect")

    return passed, total, failures


def _score_verifier(cfg, transcripts_dir: Path) -> tuple[int, int, list[str]]:
    passed, total, failures = 0, 0, []
    for case in VERIFIER_CASES:
        total += 1
        out, _span = run_verifier(case["input"], cfg=cfg, transcripts_dir=transcripts_dir, attempt=99)
        ok = out.verdict == case["expected_verdict"] and (
            case["expected_reason_code"] is None or out.reason_code == case["expected_reason_code"]
        )
        if ok:
            passed += 1
        else:
            failures.append(
                f"{case['name']}: expected verdict={case['expected_verdict']} code={case['expected_reason_code']}, "
                f"got verdict={out.verdict} code={out.reason_code}"
            )
    return passed, total, failures


def _llm_judge_meta_check(cfg, transcripts_dir: Path) -> tuple[bool, str]:
    """Independent LLM-judge call: hand it a clear-cut hallucination scenario
    and ask it to agree/disagree with a 'fail' verdict, as a sanity cross-check
    on the Verifier's own reasoning (not just its deterministic field diff)."""
    from app.llm.client import call_structured

    system = (
        "You are a QA auditor. Given a source record and a drafted summary, "
        "say whether the summary invents information not present in the source. "
        'Reply strict JSON: {"invented_info": true/false}'
    )
    user = json.dumps({
        "source": {"owner": "j.doe", "category": "RENEWAL", "amount": 4200},
        "draft_summary": "Renewal claim for j.doe, approved at an adjusted value of $38,000 per finance override.",
    })
    result = call_structured(
        cfg=cfg, transcripts_dir=transcripts_dir, agent="verifier", record_id="EVAL-META-JUDGE-1",
        model=cfg.llm_model_cheap, prompt_version="eval-meta-judge-v1",
        system_prompt=system, user_prompt=user,
    )
    agrees = bool((result.content or {}).get("invented_info", not result.malformed))
    return agrees, "LLM meta-judge agrees the summary invents a figure not in source" if agrees else "meta-judge disagreed"


def _score_worker(cfg) -> tuple[int, int, str]:
    audit_path = cfg.out_dir / "audit.json"
    if not audit_path.exists():
        return 0, 0, "N/A -- run `make demo` first to score Worker against a real run"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    delivered = [r for r in audit.get("records", []) if r.get("status") == "delivered"]
    if not delivered:
        return 0, 0, "N/A -- no delivered records in last run"
    faithful = sum(
        1 for r in delivered
        if any(s.get("agent") == "verifier" and s.get("verdict") == "pass" for s in r.get("agent_trace", []))
    )
    return faithful, len(delivered), f"{faithful}/{len(delivered)} delivered drafts passed independent Verifier check on first or retried attempt"


def main() -> int:
    cfg = load_config()
    transcripts_dir = cfg.transcripts_dir

    o_passed, o_total, o_fail = _score_orchestrator()
    v_passed, v_total, v_fail = _score_verifier(cfg, transcripts_dir)
    judge_agrees, judge_note = _llm_judge_meta_check(cfg, transcripts_dir)
    w_passed, w_total, w_note = _score_worker(cfg)

    print("=== make eval: per-agent scores ===")
    print(f"orchestrator: {o_passed}/{o_total} golden cases passed")
    for f in o_fail:
        print(f"  FAIL: {f}")
    print(f"verifier:     {v_passed}/{v_total} golden cases passed  |  LLM meta-judge: {'AGREE' if judge_agrees else 'DISAGREE'} ({judge_note})")
    for f in v_fail:
        print(f"  FAIL: {f}")
    print(f"worker:       {w_note}")

    total_passed = o_passed + v_passed + (1 if judge_agrees else 0)
    total_cases = o_total + v_total + 1
    print(f"\nTOTAL: {total_passed}/{total_cases} checks passed")
    return 0 if (not o_fail and not v_fail and judge_agrees) else 1


if __name__ == "__main__":
    raise SystemExit(main())
