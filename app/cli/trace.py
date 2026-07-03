"""`make trace ID=<id>` -- print one record's full agent decision path,
reconstructed purely from out/audit.json (which agent ran, model, cost,
retries, Verifier verdict, where it routed)."""
from __future__ import annotations

import json
import sys

from app.config import load_config


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1]:
        print("usage: python -m app.cli.trace <RECORD_ID>")
        return 1
    record_id = sys.argv[1]

    cfg = load_config()
    audit_path = cfg.out_dir / "audit.json"
    if not audit_path.exists():
        print(f"FAIL: {audit_path} not found -- run `make demo` first")
        return 1
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    record = next((r for r in audit.get("records", []) if r.get("id") == record_id), None)
    if record is None:
        print(f"FAIL: no record with id {record_id!r} in {audit_path}")
        return 1

    print(f"=== agent decision path: {record_id} ===")
    print(f"status: {record['status']}   reason_code: {record.get('reason_code')}   reason_class: {record.get('reason_class')}")
    print(f"source: {record.get('source_format')}  version={record.get('version')}  hash={record.get('source_version_hash')}")
    print()
    print("agent_trace:")
    for i, span in enumerate(record.get("agent_trace", [])):
        print(
            f"  [{i}] agent={span['agent']:<12} model={span.get('model') or '-':<28} "
            f"status={span['status']:<10} verdict={span.get('verdict') or '-':<12} "
            f"tokens_in={span.get('tokens_in')} tokens_out={span.get('tokens_out')} "
            f"cost=${span.get('cost_usd') or 0:.6f} latency={span.get('latency_ms') or 0:.0f}ms "
            f"retries={span.get('retries')} transcript={span.get('transcript_hash')}"
        )
    print()
    print("approval_trail:")
    for e in record.get("approval_trail", []):
        print(f"  {e['state']:<18} actor={e['actor']:<32} ts={e['ts']}" + (f"  reason={e['reason']}" if e.get("reason") else ""))

    if record.get("delivered_fields"):
        print()
        print("delivered_fields:")
        print(json.dumps(record["delivered_fields"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
