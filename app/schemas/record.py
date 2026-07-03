"""Record-shaped data as it moves through Intake -> Orchestration -> Delivery."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceFormat = Literal["feed", "eml", "pdf"]

REASON_CODES = (
    "STALE", "MISSING_INPUT", "OUTLIER", "INJECTION_BLOCKED",
    "LOW_CONFIDENCE", "UNVERIFIED_ANOMALY",
    "AGENT_HALLUCINATION", "AGENT_LOOP", "AGENT_MALFORMED", "BUDGET_EXCEEDED",
    "SCHEMA_DRIFT", "SUPERSEDED_VERSION",
)
CLASS_A = {
    "STALE", "MISSING_INPUT", "OUTLIER", "INJECTION_BLOCKED",
    "LOW_CONFIDENCE", "UNVERIFIED_ANOMALY",
}
AGENT_FAIL = {"AGENT_HALLUCINATION", "AGENT_LOOP", "AGENT_MALFORMED", "BUDGET_EXCEEDED"}
CLASS_B = {"SCHEMA_DRIFT", "SUPERSEDED_VERSION"}
BLOCKING = CLASS_A | AGENT_FAIL


class RawRecord(BaseModel):
    """What Intake produces: parsed but not yet validated/normalized."""

    id: str
    source_format: SourceFormat
    source_path: str
    source_version_hash: str
    fields: dict[str, Any] = Field(default_factory=dict)
    field_names_seen: list[str] = Field(default_factory=list)


class NormalizedRecord(BaseModel):
    """Canonical, versioned output-schema artifact Orchestration normalizes into."""

    id: str
    owner: str | None = None
    deadline: str | None = None
    category: str | None = None
    notes: str | None = None
    version: int = 1
    amount: float | None = None

    source_format: SourceFormat
    source_version_hash: str
    raw_fields: dict[str, Any] = Field(default_factory=dict)

    # Class-B bookkeeping (declarative field-mapping trail)
    field_map_applied: dict[str, str] = Field(default_factory=dict)  # canonical -> original
    schema_drift: bool = False
    superseded_by: str | None = None  # set on the OLDER of a duplicate-id pair


class AgentTraceSpan(BaseModel):
    agent: str
    model: str | None = None
    prompt_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    retries: int | None = 0
    transcript_hash: str | None = None
    status: Literal["ok", "retried", "rejected", "overruled", "routed", "abstained", "killed"]
    verdict: Literal["pass", "fail", "needs_human"] | None = None


class ApprovalEvent(BaseModel):
    state: Literal["draft", "in_review", "changes_requested", "approved", "delivered", "blocked"]
    actor: str
    ts: str
    reason: str | None = None


class ProcessedRecord(BaseModel):
    """One row of audit.json's `records` array."""

    id: str
    version: int = 1
    source_format: SourceFormat
    source_version_hash: str | None = None
    status: Literal["delivered", "exception", "superseded"] = "exception"
    reason_code: str | None = None
    reason_class: Literal["A", "B"] | None = None
    transcript_hash: str | None = None
    delivered_fields: dict[str, Any] | None = None
    delivered_fields_hash: str | None = None
    agent_trace: list[AgentTraceSpan] = Field(default_factory=list)
    approval_trail: list[ApprovalEvent] = Field(default_factory=list)
