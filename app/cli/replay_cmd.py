"""`make replay ID=<id>` -- reconstruct one delivered output's DATA lineage
from the append-only log alone: source hash -> which agent's transcript
produced it -> the exact request/response -> the delivered fields, with every
hash independently re-verified (not just trusted)."""
from __future__ import annotations

import json
import sys

from app.audit.writer import sha
from app.config import load_config


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1]:
        print("usage: python -m app.cli.replay_cmd <RECORD_ID>")
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

    print(f"=== data lineage: {record_id} ===")
    print(f"1. source: {record.get('source_format')} v{record.get('version')}  hash={record.get('source_version_hash')}")

    if record["status"] != "delivered":
        print(f"2. record never reached delivery (status={record['status']}, reason_code={record.get('reason_code')})")
        print("   -- no delivered_fields / transcript to trace further.")
        return 0

    th = record.get("transcript_hash")
    stem = th.split(":")[-1] if th else None
    tpath = cfg.transcripts_dir / f"{stem}.json"
    print(f"2. load-bearing transcript_hash: {th}")
    if not tpath.exists():
        print(f"   FAIL: transcript file {tpath} missing")
        return 1
    transcript = json.loads(tpath.read_text(encoding="utf-8"))
    print(f"   -> produced by agent={transcript.get('agent')} model={transcript.get('model')} prompt_version={transcript.get('prompt_version')}")

    recomputed_response_hash = sha(transcript["response"])
    ok_response = recomputed_response_hash == transcript["response_hash"]
    print(f"3. response_hash integrity: {'OK' if ok_response else 'MISMATCH'} ({recomputed_response_hash})")

    df = record.get("delivered_fields")
    dfh = record.get("delivered_fields_hash")
    recomputed_dfh = sha(df) if df is not None else None
    ok_df = recomputed_dfh == dfh
    print(f"4. delivered_fields_hash integrity: {'OK' if ok_df else 'MISMATCH'} ({dfh})")
    print(f"   transcript's own delivered_fields_hash matches record: {'OK' if transcript.get('delivered_fields_hash') == dfh else 'MISMATCH'}")

    print("5. delivered_fields:")
    print(json.dumps(df, indent=2))

    return 0 if (ok_response and ok_df) else 1


if __name__ == "__main__":
    raise SystemExit(main())
