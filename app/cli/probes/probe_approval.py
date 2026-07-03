"""make probe-approval: exit 0 ONLY if delivery of a non-approved item
(including a record subject to the CASE_ID amendment's second-approver gate)
is refused + logged."""
from __future__ import annotations

from app.approval.state_machine import ApprovalTrail, DeliveryRefused
from app.config import load_config


def _check(label: str, fn) -> bool:
    try:
        fn()
    except DeliveryRefused as exc:
        print(f"  PASS: {label} -- refused as expected ({exc})")
        return True
    print(f"  FAIL: {label} -- delivery was NOT refused")
    return False


def main() -> int:
    cfg = load_config()
    ok = True

    # 1. Never-approved record.
    trail = ApprovalTrail(actor="orchestrator")
    trail.submit_for_review("orchestrator")
    ok &= _check("delivery with zero approvals", lambda: trail.attempt_delivery("orchestrator"))
    ok &= trail.current_state == "blocked"

    # 2. Approved once, but the CASE_ID amendment's second approval is missing
    #    (simulates a high-value record: normalized amount >= amendment.threshold).
    trail2 = ApprovalTrail(actor="orchestrator")
    trail2.submit_for_review("orchestrator")
    trail2.approve("operator:auto_approver", reason="worker+verifier passed")
    ok &= _check(
        f"high-value record missing {cfg.amendment_role} sign-off",
        lambda: trail2.attempt_delivery(
            "orchestrator", requires_second_approval=True, second_approver_role=cfg.amendment_role
        ),
    )
    ok &= trail2.current_state == "blocked"

    # 3. Sanity: WITH both approvals, delivery succeeds (proves refusal above
    #    wasn't just a broken code path always raising).
    trail3 = ApprovalTrail(actor="orchestrator")
    trail3.submit_for_review("orchestrator")
    trail3.approve("operator:auto_approver")
    trail3.approve(f"{cfg.amendment_role}:auto_approver")
    try:
        trail3.attempt_delivery(
            "orchestrator", requires_second_approval=True, second_approver_role=cfg.amendment_role
        )
        print("  PASS: fully-approved record delivers normally (control case)")
    except DeliveryRefused:
        print("  FAIL: fully-approved record was refused (control case broken)")
        ok = False

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
