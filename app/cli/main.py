"""Entry point: runs Intake -> Orchestration -> Assembly -> Review -> Delivery
for every record in SEED_DIR, then writes out/audit.json + exception_queue.json
+ the branded package. This is what `make demo` calls."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from app.agents.specs import build_roster
from app.approval.state_machine import ApprovalTrail, DeliveryRefused
from app.audit.package import build_package, write_package
from app.audit.writer import AppendOnlyLog, build_audit, sha
from app.config import Config, load_config
from app.graph.pipeline_graph import build_graph, run_record
from app.intake.persist import ingest
from app.rules.amendment import requires_second_approval
from app.rules.detectors import classify, compute_outlier_ids
from app.rules.normalize import normalize, resolve_superseded
from app.schemas.record import AgentTraceSpan, ApprovalEvent, ProcessedRecord


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return round(s[idx], 3)


def run_pipeline(cfg: Config) -> dict:
    log = AppendOnlyLog()
    log.append("system", "pipeline_start")
    print(f"[intake] parsing SEED_DIR={cfg.seed_dir}")

    raw = ingest(cfg.seed_dir, cfg.out_dir.parent / "state" / "intake.db")
    log.append("orchestrator", "intake_complete")
    print(f"[intake] {len(raw)} raw records persisted")

    normalized = resolve_superseded([normalize(r) for r in raw])
    log.append("orchestrator", "normalize_complete")

    active = [r for r in normalized if not r.superseded_by]
    outlier_ids = compute_outlier_ids(active)
    pipeline_now = datetime.strptime(cfg.pipeline_now, "%Y-%m-%d").date()

    roster = build_roster(cfg)
    roster_dicts = [a.model_dump() for a in roster]

    compiled_graph = build_graph(cfg, cfg.transcripts_dir)

    processed: list[ProcessedRecord] = []
    total_cost = 0.0
    latencies: list[float] = []

    print(f"[orchestration] classifying {len(normalized)} records")
    for r in normalized:
        if r.superseded_by:
            processed.append(
                ProcessedRecord(
                    id=r.id, version=r.version, source_format=r.source_format,
                    source_version_hash=r.source_version_hash, status="superseded",
                    reason_code="SUPERSEDED_VERSION", reason_class="B",
                    agent_trace=[], approval_trail=[],
                )
            )
            log.append("orchestrator", "superseded", r.id)
            continue

        code, cls = classify(r, pipeline_now, outlier_ids)
        orch_span = AgentTraceSpan(agent="orchestrator", status="routed" if code else "ok")

        if code:
            processed.append(
                ProcessedRecord(
                    id=r.id, version=r.version, source_format=r.source_format,
                    source_version_hash=r.source_version_hash, status="exception",
                    reason_code=code, reason_class=cls,
                    agent_trace=[orch_span], approval_trail=[],
                )
            )
            log.append("orchestrator", f"exception:{code}", r.id)
            print(f"  {r.id}: EXCEPTION ({code})")
            continue

        # Clean (or Class-B schema-drift, non-blocking) -> run the fleet.
        result = run_record(r, cfg=cfg, transcripts_dir=cfg.transcripts_dir, compiled=compiled_graph)
        trace = [orch_span] + result["agent_trace"]
        total_cost += result["cost_so_far"]
        for span in result["agent_trace"]:
            if span.latency_ms:
                latencies.append(span.latency_ms)

        if result["terminal_status"] == "ready_for_approval":
            trail = ApprovalTrail(actor="orchestrator")
            trail.submit_for_review("orchestrator")
            trail.approve("operator:auto_approver", reason="worker draft passed independent verifier check")

            needs_second = requires_second_approval(r, cfg.amendment_threshold)
            if needs_second:
                trail.approve(f"{cfg.amendment_role}:auto_approver", reason="CASE_ID amendment: amount >= threshold")

            try:
                trail.attempt_delivery(
                    "orchestrator", requires_second_approval=needs_second, second_approver_role=cfg.amendment_role
                )
                status = "delivered"
                reason_code = "SCHEMA_DRIFT" if r.schema_drift else None
                reason_class = "B" if r.schema_drift else None
                delivered_fields = result["delivered_fields"]
            except DeliveryRefused as exc:
                status = "exception"
                reason_code = "UNVERIFIED_ANOMALY"
                reason_class = "A"
                delivered_fields = None
                log.append("orchestrator", f"delivery_refused:{exc}", r.id)

            processed.append(
                ProcessedRecord(
                    id=r.id, version=r.version, source_format=r.source_format,
                    source_version_hash=r.source_version_hash, status=status,
                    reason_code=reason_code, reason_class=reason_class,
                    transcript_hash=result["transcript_hash"] if status == "delivered" else None,
                    delivered_fields=delivered_fields,
                    delivered_fields_hash=sha(delivered_fields) if delivered_fields is not None else None,
                    agent_trace=trace, approval_trail=trail.events,
                )
            )
            log.append("verifier", "pass", r.id)
            if status == "delivered":
                log.append("operator", "approved", r.id)
                log.append("orchestrator", "delivered", r.id)
            print(f"  {r.id}: {status.upper()}" + (f" ({reason_code})" if reason_code else ""))
        else:
            processed.append(
                ProcessedRecord(
                    id=r.id, version=r.version, source_format=r.source_format,
                    source_version_hash=r.source_version_hash, status="exception",
                    reason_code=result["reason_code"], reason_class=result["reason_class"],
                    agent_trace=trace, approval_trail=[],
                )
            )
            log.append("orchestrator", f"exception:{result['reason_code']}", r.id)
            print(f"  {r.id}: EXCEPTION ({result['reason_code']})")

    delivered_records = [p for p in processed if p.status == "delivered"]
    package = build_package(
        industry=cfg.industry,
        case_id=cfg.case_id,
        delivered=[{"id": p.id, **(p.delivered_fields or {})} for p in delivered_records],
    )
    output_package_hash = write_package(cfg.out_dir, package)
    log.append("orchestrator", "package_written")

    n = len(processed) or 1
    cost_summary = {
        "total_usd": round(total_cost, 8),
        "avg_usd_per_record": round(total_cost / n, 8),
        "p95_latency_ms": _p95(latencies),
        "records": len(processed),
        "projected_usd_per_10k": round((total_cost / n) * 10000, 4),
    }

    audit = build_audit(
        case_id=cfg.case_id,
        pipeline_version=cfg.pipeline_version,
        seed_dir=str(cfg.seed_dir),
        pipeline_now=cfg.pipeline_now,
        amendment_role=cfg.amendment_role,
        amendment_threshold=cfg.amendment_threshold,
        agents=roster_dicts,
        cost_summary=cost_summary,
        output_package_hash=output_package_hash,
        records=[json.loads(p.model_dump_json()) for p in processed],
        events=log.events(),
    )

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    (cfg.out_dir / "audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    exception_records = [json.loads(p.model_dump_json()) for p in processed if p.status == "exception"]
    (cfg.out_dir / "exception_queue.json").write_text(
        json.dumps(exception_records, indent=2, sort_keys=True), encoding="utf-8"
    )

    delivered_n = len(delivered_records)
    exc_n = sum(1 for p in processed if p.status == "exception")
    sup_n = sum(1 for p in processed if p.status == "superseded")
    print(f"\n[delivery] {delivered_n} delivered, {exc_n} exceptions, {sup_n} superseded")
    print(f"[cost] total=${cost_summary['total_usd']:.6f} avg/record=${cost_summary['avg_usd_per_record']:.6f} "
          f"p95_latency={cost_summary['p95_latency_ms']}ms projected@10k=${cost_summary['projected_usd_per_10k']:.2f}")
    print(f"[audit] AMENDMENT: role={cfg.amendment_role} threshold={cfg.amendment_threshold}")
    print(f"[audit] wrote {cfg.out_dir / 'audit.json'}")

    return audit


def main() -> int:
    cfg = load_config()
    print(f"CASE_ID={cfg.case_id}")
    print(f"AMENDMENT: role={cfg.amendment_role} threshold={cfg.amendment_threshold}")
    print(f"REPLAY_LLM={cfg.replay_llm} SEED_DIR={cfg.seed_dir}")
    run_pipeline(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
