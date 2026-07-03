r"""Stage 4 -- Review: explicit approval state machine.
draft -> in_review -> (changes_requested -> in_review)* -> approved -> delivered
                                                          \-> blocked

Delivery is refused server-side for anything that hasn't reached 'approved'
(and, when the CASE_ID amendment applies, a second approval by the amendment
role) -- `attempt_delivery` is the only path that writes a 'delivered' event,
and it enforces this itself rather than trusting the caller.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.record import ApprovalEvent


class DeliveryRefused(RuntimeError):
    pass


class ApprovalTrail:
    def __init__(self, actor: str = "system"):
        self._events: list[ApprovalEvent] = []
        self._append("draft", actor=actor)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append(self, state: str, *, actor: str, reason: str | None = None) -> None:
        self._events.append(ApprovalEvent(state=state, actor=actor, ts=self._now(), reason=reason))

    @property
    def events(self) -> list[ApprovalEvent]:
        return list(self._events)

    @property
    def current_state(self) -> str:
        return self._events[-1].state

    def submit_for_review(self, actor: str) -> None:
        self._append("in_review", actor=actor)

    def request_changes(self, actor: str, reason: str) -> None:
        self._append("changes_requested", actor=actor, reason=reason)

    def approve(self, actor: str, reason: str | None = None) -> None:
        self._append("approved", actor=actor, reason=reason)

    def block(self, actor: str, reason: str) -> None:
        self._append("blocked", actor=actor, reason=reason)

    def has_approval_by(self, actor_prefix: str) -> bool:
        return any(e.state == "approved" and e.actor.startswith(actor_prefix) for e in self._events)

    def has_any_approval(self) -> bool:
        return any(e.state == "approved" for e in self._events)

    def attempt_delivery(
        self,
        actor: str,
        *,
        requires_second_approval: bool = False,
        second_approver_role: str | None = None,
    ) -> None:
        """The single, server-side-enforced gate. Raises DeliveryRefused
        instead of appending 'delivered' if approval is missing -- this is
        what `make probe-approval` exercises."""
        if not self.has_any_approval():
            self.block(actor, reason="delivery refused: no approval on file")
            raise DeliveryRefused("record has never reached 'approved'")
        if requires_second_approval and not self.has_approval_by(f"{second_approver_role}:"):
            self.block(
                actor,
                reason=f"delivery refused: missing required second approval by {second_approver_role} (CASE_ID amendment)",
            )
            raise DeliveryRefused(f"missing required second approval by {second_approver_role}")
        self._append("delivered", actor=actor)
