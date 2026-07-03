# Uniform probe interface — graders invoke THESE targets identically on every repo,
# whatever language you build in. Wired to app/cli/*.py. Exit codes matter.
SEED_DIR ?= seed

.PHONY: demo verify trace eval replay probe-approval probe-agent-failure probe-budget \
        probe-append-only probe-idempotency probe-crash clean dashboard demo-ui

# Full multi-agent pipeline, offline replay, on $(SEED_DIR). Writes out/package/,
# out/audit.json (agents roster + per-record agent_trace + cost), out/exception_queue.json.
demo:
	SEED_DIR=$(SEED_DIR) python3 -m app.cli.main

# Run the PROVIDED gate on your audit bundle. Do not modify verify_audit.py.
verify:
	python3 verify_audit.py --audit out/audit.json --transcripts transcripts --schema audit.schema.json

# Print one record's FULL agent decision path from the log alone:
# which agent ran, model, tokens/cost, retries, Verifier verdict, where it routed.
trace:
	python3 -m app.cli.trace $(ID)

# Run the agent eval harness: golden cases + an LLM-judge per agent. Prints per-agent scores.
eval:
	python3 -m app.cli.eval_cmd

# Reconstruct one delivered output's DATA lineage from the append-only log alone.
replay:
	python3 -m app.cli.replay_cmd $(ID)

# Exit 0 ONLY if delivery of a NON-approved item (incl. CASE_ID amendment role) is refused + logged.
probe-approval:
	python3 -m app.cli.probes.probe_approval

# Exit 0 ONLY if a hallucinated/malformed WORKER output is caught by the Verifier and routed
# (AGENT_HALLUCINATION / AGENT_MALFORMED) — never delivered.
probe-agent-failure:
	python3 -m app.cli.probes.probe_agent_failure

# Exit 0 ONLY if a record exceeding the per-record cost/step ceiling raises BUDGET_EXCEEDED
# and is downgraded or routed — never silently overspent.
probe-budget:
	python3 -m app.cli.probes.probe_budget

# Exit 0 ONLY if mutating/deleting a past audit entry is refused.
probe-append-only:
	python3 -m app.cli.probes.probe_append_only

# Exit 0 ONLY if running demo twice produces no duplicate outputs/exceptions/approvals.
probe-idempotency:
	python3 -m app.cli.probes.probe_idempotency

# BONUS — not implemented, see DECISIONS.md.
probe-crash:
	@echo "TODO (bonus, not implemented -- see DECISIONS.md)"; false

# Optional visualization dashboard (not part of the graded path), run locally.
dashboard:
	streamlit run frontend/streamlit_app.py --server.address=0.0.0.0

# Optional: spin up BOTH the pipeline and the dashboard in Docker, for a human
# to watch (NOT the graded command -- graders run plain `docker compose up`,
# which only starts the pipeline and exits; this one keeps the dashboard alive).
demo-ui:
	docker compose --profile dashboard up

clean:
	rm -rf out
