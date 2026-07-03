"""Typed input/output contracts for each agent, and the roster entry shape.

TASK.md is explicit: "each agent has a declared input/output schema and a
declared list of which agents it may call. Free-form string passing = markdown."
These models are that declaration -- agents.py imports and uses them directly,
it does not pass raw dicts/strings between nodes.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.record import NormalizedRecord


class AgentSpec(BaseModel):
    """One entry in audit.json's `agents` roster."""

    name: str
    role: Literal["orchestrator", "worker", "verifier", "router", "operator", "other"]
    models: list[str] = Field(default_factory=list)
    prompt_version: str | None = None
    can_call: list[str] = Field(default_factory=list)


class WorkerInput(BaseModel):
    """What the Orchestrator hands the Worker for Assembly."""

    record: NormalizedRecord
    escalate: bool = False  # router decision: use strong model instead of cheap


class WorkerOutput(BaseModel):
    """What the Worker hands back. Only fields present here can ever be
    `delivered_fields` -- the Worker is not allowed to invent new top-level
    fields, only populate `summary` from source content."""

    abstained: bool = False
    abstain_reason: str | None = None

    claim_owner: str | None = None
    claim_category: str | None = None
    claim_amount: float | None = None
    sla_date: str | None = None
    summary: str | None = None

    model_used: str | None = None
    prompt_version: str = "worker-v1"
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    transcript_hash: str | None = None
    malformed: bool = False
    looped: bool = False


class VerifierInput(BaseModel):
    record: NormalizedRecord
    worker_output: WorkerOutput


class VerifierCheck(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class VerifierOutput(BaseModel):
    verdict: Literal["pass", "fail", "needs_human"]
    checks: list[VerifierCheck] = Field(default_factory=list)
    reason_code: str | None = None  # AGENT_HALLUCINATION / AGENT_MALFORMED / AGENT_LOOP / None
    notes: str | None = None

    model_used: str | None = None
    prompt_version: str = "verifier-v1"
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    transcript_hash: str | None = None


class OrchestratorDecision(BaseModel):
    """Terminal decision the Orchestrator makes for one record after running
    normalize -> (worker <-> verifier)* -> approval."""

    record_id: str
    status: Literal["delivered", "exception", "superseded"]
    reason_code: str | None = None
    reason_class: Literal["A", "B"] | None = None
    delivered_fields: dict[str, Any] | None = None
