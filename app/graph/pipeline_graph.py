"""LangGraph wiring: the Orchestrator as a supervisor over Worker <-> Verifier.

Worker and Verifier never call each other directly -- every transition is
decided by orchestrator policy functions (route/budget/retry), matching the
declared `can_call` contract (orchestrator -> [worker, verifier] only).
"""
from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from app.agents import orchestrator, verifier, worker
from app.config import Config
from app.graph.state import PipelineState
from app.schemas.contracts import VerifierInput, WorkerInput
from app.schemas.record import AgentTraceSpan, NormalizedRecord


def build_graph(cfg: Config, transcripts_dir: Path):
    def node_worker(state: PipelineState) -> dict:
        record = state["record"]
        attempt = state["attempt"]
        steps = state["steps"]
        cost_so_far = state["cost_so_far"]
        trace = list(state["agent_trace"])

        if orchestrator.would_exceed_steps(cfg, steps):
            return {
                "terminal_status": "exception",
                "reason_code": "AGENT_LOOP",
                "reason_class": "A",
                "agent_trace": trace + [AgentTraceSpan(agent="orchestrator", status="killed")],
            }

        route = orchestrator.route_worker_model(cfg, record, attempt)
        if orchestrator.would_exceed_budget(cfg, cost_so_far, route.model):
            if route.model != cfg.llm_model_cheap and not orchestrator.would_exceed_budget(
                cfg, cost_so_far, cfg.llm_model_cheap
            ):
                route = orchestrator.RouteDecision(escalate=False, model=cfg.llm_model_cheap)
            else:
                return {
                    "terminal_status": "exception",
                    "reason_code": "BUDGET_EXCEEDED",
                    "reason_class": "A",
                    "agent_trace": trace + [AgentTraceSpan(agent="orchestrator", status="routed")],
                }

        worker_input = WorkerInput(record=record, escalate=route.escalate)
        output, span = worker.run_worker(
            worker_input, cfg=cfg, transcripts_dir=transcripts_dir, attempt=attempt
        )
        new_steps = steps + 1
        new_cost = cost_so_far + (span.cost_usd or 0.0)
        trace = trace + [span]

        if output.abstained:
            return {
                "worker_output": output,
                "steps": new_steps,
                "cost_so_far": new_cost,
                "agent_trace": trace,
                "terminal_status": "exception",
                "reason_code": "LOW_CONFIDENCE",
                "reason_class": "A",
            }

        return {
            "worker_output": output,
            "steps": new_steps,
            "cost_so_far": new_cost,
            "agent_trace": trace,
        }

    def route_after_worker(state: PipelineState) -> str:
        return END if state.get("terminal_status") else "verifier"

    def node_verifier(state: PipelineState) -> dict:
        record = state["record"]
        worker_output = state["worker_output"]
        attempt = state["attempt"]
        steps = state["steps"]
        cost_so_far = state["cost_so_far"]
        trace = list(state["agent_trace"])

        if orchestrator.would_exceed_steps(cfg, steps):
            return {
                "terminal_status": "exception",
                "reason_code": "AGENT_LOOP",
                "reason_class": "A",
                "agent_trace": trace + [AgentTraceSpan(agent="orchestrator", status="killed")],
            }

        verifier_input = VerifierInput(record=record, worker_output=worker_output)
        v_output, v_span = verifier.run_verifier(
            verifier_input, cfg=cfg, transcripts_dir=transcripts_dir, attempt=attempt
        )
        new_steps = steps + 1
        new_cost = cost_so_far + (v_span.cost_usd or 0.0)
        trace = trace + [v_span]

        if v_output.verdict == "pass":
            delivered_fields = {
                "claim_owner": worker_output.claim_owner,
                "claim_category": worker_output.claim_category,
                "claim_amount": worker_output.claim_amount,
                "sla_date": worker_output.sla_date,
                "summary": worker_output.summary,
            }
            return {
                "verifier_output": v_output,
                "steps": new_steps,
                "cost_so_far": new_cost,
                "agent_trace": trace,
                "terminal_status": "ready_for_approval",
                "delivered_fields": delivered_fields,
                "transcript_hash": worker_output.transcript_hash,
            }

        if v_output.verdict == "needs_human":
            return {
                "verifier_output": v_output,
                "steps": new_steps,
                "cost_so_far": new_cost,
                "agent_trace": trace,
                "terminal_status": "exception",
                "reason_code": "LOW_CONFIDENCE",
                "reason_class": "A",
            }

        # verdict == "fail" -> bounded retry, then give up
        if attempt < orchestrator.MAX_RETRIES:
            return {
                "verifier_output": v_output,
                "steps": new_steps,
                "cost_so_far": new_cost,
                "agent_trace": trace,
                "attempt": attempt + 1,
            }
        return {
            "verifier_output": v_output,
            "steps": new_steps,
            "cost_so_far": new_cost,
            "agent_trace": trace,
            "terminal_status": "exception",
            "reason_code": v_output.reason_code or "AGENT_HALLUCINATION",
            "reason_class": "A",
        }

    def route_after_verifier(state: PipelineState) -> str:
        return END if state.get("terminal_status") else "worker"

    graph = StateGraph(PipelineState)
    graph.add_node("worker", node_worker)
    graph.add_node("verifier", node_verifier)
    graph.set_entry_point("worker")
    graph.add_conditional_edges("worker", route_after_worker, {"verifier": "verifier", END: END})
    graph.add_conditional_edges("verifier", route_after_verifier, {"worker": "worker", END: END})
    return graph.compile()


def run_record(
    record: NormalizedRecord, *, cfg: Config, transcripts_dir: Path, compiled=None
) -> PipelineState:
    app = compiled or build_graph(cfg, transcripts_dir)
    initial: PipelineState = {
        "record": record,
        "attempt": 0,
        "steps": 0,
        "cost_so_far": 0.0,
        "worker_output": None,
        "verifier_output": None,
        "agent_trace": [],
        "terminal_status": "",
        "reason_code": None,
        "reason_class": None,
        "delivered_fields": None,
        "transcript_hash": None,
    }
    return app.invoke(initial, config={"recursion_limit": 25})
