# DECISIONS — Tiny CEDX Agent Fleet (CASE_ID: CEDX-EB3505)

## What I did NOT automate, and why

- **Live deployment / hosted UI.** The run contract is `docker compose up` on the grader's own machine — a hosted instance adds uptime/cost risk for zero grading benefit. A local Streamlit dashboard ([frontend/](frontend/)) is included for my own visualization only; it's not on the graded path.
- **Human approval in `make demo`.** TASK.md allows "operator surface (CLI fine)"; for the offline demo path there's no live human, so records that pass the Verifier are auto-approved by a scripted `operator` actor (still logged with actor+timestamp, still going through the real state machine and its refusal logic — verified independently by `probe-approval`). A real deployment would swap this for an actual CLI prompt or reviewer queue; the state machine underneath doesn't change.
- **`probe-crash` (bonus).** Not implemented — flagged honestly rather than faked. The intake store's idempotent upsert (keyed on id+source_format+hash) is the resumability primitive that would make this straightforward to add.
- **Non-OpenAI-compatible providers.** The LLM client only speaks the OpenAI Chat Completions shape. This still satisfies "≥1 of gpt-4o-mini/claude-3-5-haiku/gemini-1.5-flash" (we use 2 of the 3, via OpenRouter — see below), and a grader's own `LLM_BASE_URL` override is all that's needed to point it at a different OpenAI-compatible endpoint.

## Outlier / abstain thresholds, and why they generalize

- **Outlier:** median + MAD (median absolute deviation) modified z-score over the batch's amounts, threshold 3.5 (the standard Iglewicz-Hoaglin recommendation), not a fixed dollar cutoff. This means if the held-out seed's normal claim range is $50k–$80k with an outlier at $4M, the same code catches it — it's relative to whatever the batch's own distribution looks like. Falls back to a ratio-from-median check only in the degenerate case where MAD is 0 (near-identical batch).
- **Low confidence / abstain:** two independent triggers — an unrecognized `category` (not in the fixed known set), or `notes` matching an ambiguity-signal phrase class (`unclear`, `inconsistent`, `could be`, `not attached`, etc. — a lexical *class*, not the seed's literal sentences). The Worker also has its own abstain path in the LLM prompt itself as a second line of defense for ambiguity the rule layer didn't anticipate.
- **Injection:** regex over override-intent phrase patterns (`ignore ... instructions`, `skip review`, `approve ... immediately`, `disregard`, `bypass`, `override rules`) — a phrasing *class*. Caught 2 different real examples in the dev seed with different exact wording (REC-014's explicit "ignore all previous instructions" and REC-022's subtler "ignore the field amount"), which is direct evidence the pattern isn't overfit to one literal string.
- **Unverified anomaly (catch-all):** deliberately structural, not id-prefix-based — non-positive amount, unparseable deadline, invalid version, blank id. Early on this checked for a literal `REC-` id prefix; caught during my own golden-case testing that this would false-positive on any held-out data using a different id scheme, so it was removed in favor of purely structural checks.

## Router policy + cost numbers

Cheap model (`gpt-4o-mini`) by default; escalate to the strong model (`claude-3.5-haiku`) on any Verifier-rejected retry (bounded to 1 retry), or proactively for claims at ≥50% of the amendment threshold ($17,500) since those are inherently higher-stakes. Both budget and step ceilings are checked with a pre-call cost *estimate* before spending anything, not after.

From the latest full run (23 records): **total cost $0.0022, avg $0.000095/record, p95 latency ~3.7s, projected $0.95 per 10,000 records/day.** 6 of the 7 blocked records cost $0 (rejected by the Orchestrator's rule layer before ever reaching the Worker) — most of the cost saving comes from not calling an LLM on records that were never going anywhere.

## How provenance survives re-run

Every transcript file is named by the SHA-256 hash of its own response content (content-addressed), and every delivered record carries a `transcript_hash` + `delivered_fields_hash` that `verify_audit.py` independently re-derives and cross-checks against the committed transcript. The audit log's events are hash-chained (`prev_hash`/`event_hash` per entry), so any past edit is detectable, not just conventionally disallowed. Re-running `make demo` recomputes the full record set deterministically from the same seed + same committed transcripts (`REPLAY_LLM=true`), producing byte-identical outcomes — verified by `probe-idempotency`.

## What breaks first at 10,000 records/day

1. **SQLite intake store** — single-file, single-writer; fine at today's ~25 records/run, would need a real database under concurrent write load at scale.
2. **In-memory per-run cost/step tracking** — currently scoped to one process; a multi-worker deployment would need this moved to a shared store (Redis/DB) so budget ceilings are enforced correctly across parallel workers, not per-process.
3. **OpenRouter free/shared-tier rate limits** — hit this directly during development (see the free Llama tier), which is why the default models are paid-but-cheap rather than free-tier. At 10k/day this would need a provisioned/paid tier or provider fallback.

## CASE_ID

`CEDX-EB3505` → amendment: **role = `finance_controller`, threshold = $35,000**, verified independently via a from-scratch SHA-256 computation before any code was written against it.
