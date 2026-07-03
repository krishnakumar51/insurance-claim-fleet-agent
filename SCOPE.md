# SCOPE — push this during the live call (tracer checkpoint)

> Rename to `SCOPE.md`, fill in, commit + push during the Zoom. We record your
> GitHub **push receive-time** server-side as your authorship anchor.

- **Candidate name:** _TODO: fill in your name_
- **CASE_ID (assigned live):** CEDX-EB3505
- **Industry chosen (from cedxsystems.com/workflows):** Insurance (Commercial / Specialty) — Claims Intake
- **Tier:** Tier 2 — High-value professional services
- **Stack / language:** Python 3.13, LangGraph (agent orchestration), Pydantic (typed contracts), OpenAI-compatible client via OpenRouter (gpt-4o-mini / claude-3.5-haiku)

## Amendment (compute from your CASE_ID)
```
H = sha256(CASE_ID)
role R      = ["risk_officer","legal_counsel","compliance","finance_controller"][ int(H[0],16) % 4 ]
threshold T = 10000 + (int(H[1:3],16) % 50) * 1000
```
- **My role R:** finance_controller
- **My threshold T:** 35000

## What I will build (the 5 governed stages)
- [x] Sources/Intake (parse feed.json + inbox PDF/email)
- [x] Orchestration (declarative normalize + exception queue, all reason codes)
- [x] Assembly (LLM structured output + abstain path)
- [x] Review (operator surface + approval state machine + my CASE_ID amendment)
- [x] Delivery (branded package + append-only audit + replay)

## What I will deliberately NOT build (and why)
- No hosted backend for the pipeline itself -- it runs via `docker compose up` and exits, which is the natural shape for a batch job. A companion dashboard is deployed separately (https://insurance-claim-fleet-agent.streamlit.app/) purely for visualizing runs.
- No multi-tenant auth/user accounts -- out of scope for a single-CASE_ID demo pipeline.
- No support for LLM providers beyond the OpenAI-compatible surface -- `gpt-4o-mini` and `claude-3.5-haiku` via OpenRouter cover what's needed without adding provider-specific SDKs.
