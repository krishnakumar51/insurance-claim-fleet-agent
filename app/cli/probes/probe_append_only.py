"""make probe-append-only: exit 0 ONLY if mutating/deleting a past audit
entry is refused. Loads the real out/audit.json event log, tampers with it
three different ways, and confirms the hash-chain verifier (the same one
that must be trusted at grading time) rejects every tampered variant while
still accepting the untouched original."""
from __future__ import annotations

import copy
import json

from app.audit.writer import verify_chain
from app.config import load_config


def main() -> int:
    cfg = load_config()
    audit_path = cfg.out_dir / "audit.json"
    if not audit_path.exists():
        print(f"FAIL: {audit_path} not found -- run `make demo` first")
        return 1
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    events = audit.get("events", [])
    if len(events) < 3:
        print("FAIL: not enough events in audit.json to probe")
        return 1

    ok = True

    original_intact = verify_chain(events)
    print(f"  {'PASS' if original_intact else 'FAIL'}: untouched log verifies as intact (control case)")
    ok &= original_intact

    edited = copy.deepcopy(events)
    edited[1]["actor"] = "attacker"
    edit_refused = not verify_chain(edited)
    print(f"  {'PASS' if edit_refused else 'FAIL'}: editing a past event's actor is detected and refused")
    ok &= edit_refused

    deleted = copy.deepcopy(events)
    del deleted[1]
    delete_refused = not verify_chain(deleted)
    print(f"  {'PASS' if delete_refused else 'FAIL'}: deleting a past event is detected and refused")
    ok &= delete_refused

    reordered = copy.deepcopy(events)
    if len(reordered) > 2:
        reordered[1], reordered[2] = reordered[2], reordered[1]
        reorder_refused = not verify_chain(reordered)
        print(f"  {'PASS' if reorder_refused else 'FAIL'}: reordering past events is detected and refused")
        ok &= reorder_refused

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
