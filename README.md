# Tiny CEDX Agent Fleet — Insurance Claims Intake

**CASE_ID: `CEDX-EB3505`**

## 1. Industry & Scope

- **Industry:** Insurance (Commercial / Specialty) — Claims Intake (Tier 2, cedxsystems.com/workflows)
- **CASE_ID:** `CEDX-EB3505`
- **What this is:** a small, real, running multi-agent pipeline that takes in raw work-request records (two formats: a JSON feed and an inbox of emails/PDFs), classifies and blocks bad ones, drafts a branded claim summary for the good ones via an LLM, has a second independent LLM-backed agent check that draft before anything is delivered, and writes an append-only, hash-chained audit trail of everything that happened.
- Not graded on insurance domain depth — the seed data is a generic `id/owner/deadline/category/amount/notes` work-request shape; "insurance claim" is the branding wrapper around the same generic pipeline.

## 2. Agent topology

Three agents, supervisor pattern (Orchestrator is the only one that calls anyone else):

| Agent | Role | Models | Can call | Code |
|---|---|---|---|---|
| **orchestrator** | Owns the run: classifies records, enforces cost/step budgets, routes exceptions, retries. No domain judgment. | — (rule-based) | `worker`, `verifier` | [app/agents/orchestrator.py](app/agents/orchestrator.py), [app/graph/pipeline_graph.py](app/graph/pipeline_graph.py) |
| **worker** | Drafts the branded claim summary (Assembly). Router picks cheap vs strong model. Can abstain. | `openai/gpt-4o-mini` (cheap), `anthropic/claude-3.5-haiku` (strong, on retry/high-value) | — | [app/agents/worker.py](app/agents/worker.py) |
| **verifier** | Independently checks the Worker's draft against the source record; can overrule it. 4 deterministic field checks + 1 LLM semantic faithfulness check. | `openai/gpt-4o-mini` | — | [app/agents/verifier.py](app/agents/verifier.py) |

Typed contracts: [app/schemas/contracts.py](app/schemas/contracts.py) (`WorkerInput`/`WorkerOutput`, `VerifierInput`/`VerifierOutput`, `AgentSpec` with `can_call`). The graph wiring lives in [app/graph/pipeline_graph.py](app/graph/pipeline_graph.py) as a LangGraph `StateGraph` — Worker and Verifier are separate nodes; they never call each other directly, only the Orchestrator's conditional edges route between them.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full topology diagram and where the Verifier overrules the Worker.

## 3. How to run

```bash
docker compose up          # or: make demo
make verify                # runs the official grading gate
make trace ID=REC-001      # full agent decision path for one record
make replay ID=REC-001     # data lineage reconstruction from the log alone
make eval                  # golden cases + LLM-judge, per-agent scores
make probe-approval
make probe-agent-failure
make probe-budget
make probe-append-only
make probe-idempotency
```

Default path (`REPLAY_LLM=true`) is fully offline — no API key needed, replays the committed `transcripts/`. Set `REPLAY_LLM=false` with `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` for a real run (see §10).

Optional dashboard (not part of the graded path): `pip install -r frontend/requirements.txt && streamlit run frontend/streamlit_app.py`.

## 4. Controls

All 5 required probes pass (run individually above); summary:

| Probe | Proves |
|---|---|
| `probe-approval` | Delivery refused server-side with zero approvals, AND refused when the CASE_ID amendment's second `finance_controller` approval is missing on a high-value record. Control case (both approvals present) delivers normally. |
| `probe-agent-failure` | A hallucinated Worker output (invented dollar amount) and a malformed Worker output are both caught by the Verifier's deterministic field-diff, tagged `AGENT_HALLUCINATION`/`AGENT_MALFORMED`, and never delivered. |
| `probe-budget` | An artificially low cost ceiling raises `BUDGET_EXCEEDED` and routes to exception *before* any LLM spend occurs (pre-call estimate, not post-hoc). Control case with a normal ceiling proceeds. |
| `probe-append-only` | The event log is hash-chained (`prev_hash`/`event_hash` per event). Editing, deleting, or reordering a past event is independently detected and refused by `verify_chain`. |
| `probe-idempotency` | Running the full pipeline twice produces identical record counts, ids, and statuses; the intake SQLite store doesn't grow duplicate rows. |

## 5. Planted-problem handling

**Data layer** (all 7 required reason codes fire correctly on the dev seed — see [app/rules/detectors.py](app/rules/detectors.py)):

| Code | Seed example | Detection logic |
|---|---|---|
| `STALE` | REC-011 (deadline before `PIPELINE_NOW`) | date comparison |
| `MISSING_INPUT` | REC-012 (`amount: null`) | required-field presence |
| `OUTLIER` | REC-013 ($250,000 vs ~$4-6k batch) | robust median/MAD z-score over the batch — not a hardcoded threshold |
| `INJECTION_BLOCKED` | REC-014, REC-022 (notes tell the agent to "ignore instructions"/"skip review"/override a field) | lexical pattern class, not literal string match |
| `LOW_CONFIDENCE` | REC-015 (self-admitted inconsistent record), REC-021 (unrecognized category `"?"`) | unknown category OR ambiguity-signal phrasing |
| `SCHEMA_DRIFT` (Class B, non-blocking) | REC-016 (email uses `Value` instead of `Amount`) | declarative field-mapping ([app/rules/field_map.json](app/rules/field_map.json)): primary names vs. synonym names |
| `SUPERSEDED_VERSION` (Class B, non-blocking) | REC-017 (v1 in feed, corrected v2 in PDF) | same id, multiple versions → keep highest version, mark rest superseded |
| `UNVERIFIED_ANOMALY` | (catch-all, not in dev seed by design) | structural sanity net: non-positive amount, unparseable deadline, invalid version |

**Agent layer** (proven via `probe-agent-failure` / `probe-budget`, since an honest pipeline doesn't naturally hallucinate on the dev seed): `AGENT_HALLUCINATION`, `AGENT_MALFORMED` caught by the Verifier's 4-field deterministic diff against source; `AGENT_LOOP` and `BUDGET_EXCEEDED` enforced by the Orchestrator's step/cost ceiling checks *before* any call is made.

Exceptions never reach the Worker — 6 of the 7 blocking codes are decided by the Orchestrator's rule layer alone (zero LLM cost on bad records).

## 6. Generalization

Nothing here is keyed to a specific record id or literal value:
- Outlier detection is relative to the batch (median/MAD), so it still works if next run's normal range is 10x bigger.
- Injection detection matches a *class* of override phrasing (`ignore ...`, `skip review`, `approve immediately`, `disregard`, `bypass`, `override rules`), not the literal seed sentences.
- Schema-drift field mapping is a declarative synonym list plus a last-resort "unclaimed numeric field" heuristic, not a special case for `Value`.
- `UNVERIFIED_ANOMALY` is a structural catch-all specifically designed to catch whatever the held-out seed's undocumented anomaly turns out to be.

## 7. LLM/agent contract & eval

`REPLAY_LLM=true` (default): every agent's LLM call is replaced by a committed, content-addressed transcript in `transcripts/*.json`, each tagged with the calling agent, hashed request/response, and cross-checked against `delivered_fields_hash` (see `verify_audit.py` checks #8/#14). `REPLAY_LLM=false`: OpenAI-Chat-Completions-compatible client ([app/llm/client.py](app/llm/client.py)) — reads `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` per the official contract; our own dev/demo runs point this at OpenRouter with `gpt-4o-mini` + `claude-3.5-haiku` (2 of the 3 named supported models) since we don't hold direct OpenAI/Anthropic keys — see §10 for proof these are real calls.

`make eval` ([app/cli/eval_cmd.py](app/cli/eval_cmd.py), cases in [eval/golden_cases/cases.py](eval/golden_cases/cases.py)): 12 Orchestrator detector golden cases (one per reason code + schema-drift + supersede resolution) + 4 Verifier golden cases (hallucination, owner-mismatch, malformed, abstain-routing) + 1 independent LLM meta-judge call cross-checking a Verifier verdict. Current score: **17/17**.

## 8. Cost & scale

From the latest `make demo` run (23 records, real LLM generation, replayed thereafter):

- Total cost: **$0.0022**
- Avg cost/record: **$0.000095**
- p95 latency/record (LLM steps only): **~3.7s**
- **Projected cost at 10,000 records/day: ~$0.95**

Router policy: cheap model (`gpt-4o-mini`) by default; escalates to the strong model (`claude-3.5-haiku`) on a Verifier-rejected retry, or proactively for claims at ≥50% of the amendment threshold (higher stakes). 6 of 7 blocked records in the dev run cost $0 (rejected before reaching the Worker). Per-record ceilings (`MAX_COST_USD_PER_RECORD`, `MAX_STEPS_PER_RECORD`) are enforced *before* a call is made, not after.

## 9. Amendment

`CASE_ID = CEDX-EB3505` → `sha256` → **role = `finance_controller`, threshold = `$35,000`**. Any record whose normalized amount is ≥ $35,000 requires a recorded approval by `finance_controller`, in addition to the normal approval, before delivery ([app/rules/amendment.py](app/rules/amendment.py), enforced server-side in [app/approval/state_machine.py](app/approval/state_machine.py)). None of the dev seed's clean records reach that threshold (all ~$3.9k–$6.1k), so it never fires organically in `make demo` — it's proven instead by `make probe-approval`, which simulates a high-value record and confirms delivery is refused without the second sign-off, and succeeds once granted.

## 10. AI usage / real vs. faked

- Code was written with AI assistance (Claude), as expected per the task brief.
- LLM calls are real and load-bearing: `transcripts/` contains actual OpenRouter API responses (not fabricated) — every transcript's `response_hash` is independently re-verifiable (`sha256(response) == response_hash`), and `delivered_fields` on every delivered record hash back to its transcript.
- We don't hold direct OpenAI/Anthropic/Gemini keys, so real calls (used once to generate the committed transcripts, and available any time via `REPLAY_LLM=false`) go through OpenRouter, which proxies to the genuine upstream provider (confirmed via the raw API response's `provider` and `system_fingerprint` fields — see DECISIONS.md) using `openai/gpt-4o-mini` and `anthropic/claude-3.5-haiku`, i.e. 2 of the 3 models TASK.md names as acceptable. If graded with a direct OpenAI/Anthropic key instead, `config.py` falls back to the kit's official `LLM_MODEL` env var unprefixed, so it still resolves correctly against a direct provider endpoint.
- Nothing is templated per-record: the Worker/Verifier system prompts are fixed strings identical across all 23 records; only the data varies. Two records with similar dollar amounts get genuinely different generated prose (verifiable in `transcripts/`).

## 11. Tradeoffs & next week

**Didn't build:** live-hosted deployment (not required — run contract is `docker compose up` locally); multi-tenant auth; support for LLM providers beyond the OpenAI-compatible surface; a crash-resume probe (`probe-crash`, bonus, not implemented).

**What breaks first at 10k records/day:** the SQLite intake store (single-file, single-writer) would need to move to a real database under concurrent write load; the in-memory per-run cost/step tracking would need to move to a shared store if multiple pipeline workers run in parallel; OpenRouter's free-tier rate limits would need a paid tier or provider fallback.

**Next week:** add a 4th agent (Redactor, PII-stripping before delivery) behind the same typed-contract pattern; widen the golden-case suite with more held-out-style unseen field-rename variants; add `probe-crash` (SIGKILL mid-run, resume without duplication) using the intake store's idempotent upserts as the resumability primitive.
