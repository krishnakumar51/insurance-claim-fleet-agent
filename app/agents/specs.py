"""The agent roster -- declared once, referenced by audit.json's `agents`
array and by every agent module's `can_call` check. Orchestrator is the only
agent that calls others (supervisor pattern); Worker and Verifier never call
each other directly."""
from __future__ import annotations

from app.config import Config
from app.schemas.contracts import AgentSpec


def build_roster(cfg: Config) -> list[AgentSpec]:
    return [
        AgentSpec(
            name="orchestrator",
            role="orchestrator",
            models=[],
            prompt_version="n/a",  # policy-only agent, no LLM prompt of its own
            can_call=["worker", "verifier"],
        ),
        AgentSpec(
            name="worker",
            role="worker",
            models=[cfg.llm_model_cheap, cfg.llm_model_strong],
            prompt_version="worker-v1",
            can_call=[],
        ),
        AgentSpec(
            name="verifier",
            role="verifier",
            models=[cfg.llm_model_cheap],
            prompt_version="verifier-v1",
            can_call=[],
        ),
    ]
