"""make probe-agent-failure: exit 0 ONLY if a hallucinated/malformed WORKER
output is caught by the Verifier and routed (AGENT_HALLUCINATION /
AGENT_MALFORMED) -- never delivered. Feeds bad Worker output directly (no LLM
call needed for the Worker side; only the Verifier's deterministic layer is
under test, matching how `verify_audit.py` check #15 evaluates the trace)."""
from __future__ import annotations

from app.agents.orchestrator import MAX_RETRIES
from app.agents.verifier import run_verifier
from app.config import load_config
from app.schemas.contracts import VerifierInput, WorkerOutput
from app.schemas.record import NormalizedRecord


def _source() -> NormalizedRecord:
    return NormalizedRecord(
        id="PROBE-AGENT-FAIL-1", owner="j.doe", deadline="2026-08-01", category="RENEWAL",
        notes="Routine renewal.", version=1, amount=4200.0,
        source_format="feed", source_version_hash="sha256:" + "9" * 64,
    )


def main() -> int:
    cfg = load_config()
    ok = True

    # Case 1: hallucinated figure not present in source.
    hallucinated = WorkerOutput(
        claim_owner="j.doe", claim_category="RENEWAL", claim_amount=99999.0,
        sla_date="2026-08-01", summary="Renewal claim.", model_used="probe",
    )
    out, span = run_verifier(VerifierInput(record=_source(), worker_output=hallucinated), cfg=cfg, transcripts_dir=cfg.transcripts_dir, attempt=MAX_RETRIES)
    caught = out.verdict == "fail" and out.reason_code == "AGENT_HALLUCINATION" and span.status in ("overruled", "rejected", "routed")
    print(f"  {'PASS' if caught else 'FAIL'}: hallucinated amount -> verdict={out.verdict} reason_code={out.reason_code} span.status={span.status}")
    ok &= caught

    # Case 2: malformed (unparseable) worker output.
    malformed = WorkerOutput(malformed=True)
    out2, span2 = run_verifier(VerifierInput(record=_source(), worker_output=malformed), cfg=cfg, transcripts_dir=cfg.transcripts_dir, attempt=MAX_RETRIES)
    caught2 = out2.verdict == "fail" and out2.reason_code == "AGENT_MALFORMED"
    print(f"  {'PASS' if caught2 else 'FAIL'}: malformed output -> verdict={out2.verdict} reason_code={out2.reason_code} span.status={span2.status}")
    ok &= caught2

    # Simulate the orchestrator's routing decision after MAX_RETRIES exhausted:
    # a 'fail' verdict at the retry ceiling must become an exception, never delivered.
    would_deliver = out.verdict == "pass"
    ok &= not would_deliver
    print(f"  {'PASS' if not would_deliver else 'FAIL'}: hallucinated record would NOT be delivered")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
