from __future__ import annotations

from typing import Any, TypedDict

from app.schemas.contracts import VerifierOutput, WorkerOutput
from app.schemas.record import AgentTraceSpan, NormalizedRecord


class PipelineState(TypedDict):
    record: NormalizedRecord
    attempt: int
    steps: int
    cost_so_far: float
    worker_output: WorkerOutput | None
    verifier_output: VerifierOutput | None
    agent_trace: list[AgentTraceSpan]

    # terminal fields, set once the graph reaches END
    terminal_status: str  # "ready_for_approval" | "exception"
    reason_code: str | None
    reason_class: str | None
    delivered_fields: dict[str, Any] | None
    transcript_hash: str | None
