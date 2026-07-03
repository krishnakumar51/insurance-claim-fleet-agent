"""AGENT 1 -- Orchestrator: owns the run. Holds routing/budget POLICY only --
no domain judgment about whether a claim summary is good (that's the Worker's
/ Verifier's job). The LangGraph wiring in app/graph/pipeline_graph.py calls
these functions from its nodes; this module has no LangGraph dependency so it
stays independently testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.schemas.record import NormalizedRecord

MAX_RETRIES = 1  # bounded retry: one repair attempt, then abstain -> human

# Rough token-count assumption used only to PRE-ESTIMATE a call's cost before
# spending it, so budget enforcement never happens after the fact (STEP 5 /
# BUDGET_EXCEEDED must never silently overspend).
_EST_TOKENS_IN, _EST_TOKENS_OUT = 400, 200


@dataclass
class RouteDecision:
    escalate: bool
    model: str


def route_worker_model(cfg: Config, record: NormalizedRecord, attempt: int) -> RouteDecision:
    """Cheap by default; escalate to the strong model on a retry, or
    proactively for high-value claims (the amendment threshold is the
    natural "this one matters more" signal already in the domain)."""
    high_value = record.amount is not None and record.amount >= cfg.amendment_threshold * 0.5
    escalate = attempt > 0 or high_value
    model = cfg.llm_model_strong if escalate else cfg.llm_model_cheap
    return RouteDecision(escalate=escalate, model=model)


def estimate_call_cost(cfg: Config, model: str) -> float:
    from app.llm.client import _cost_usd

    return _cost_usd(model, _EST_TOKENS_IN, _EST_TOKENS_OUT)


def would_exceed_budget(cfg: Config, cost_so_far: float, next_model: str) -> bool:
    return cost_so_far + estimate_call_cost(cfg, next_model) > cfg.max_cost_usd_per_record


def would_exceed_steps(cfg: Config, steps_so_far: int) -> bool:
    return steps_so_far + 1 > cfg.max_steps_per_record
