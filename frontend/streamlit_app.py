"""Tiny CEDX dashboard -- reads out/audit.json directly (no API, no backend).
Pure visualization on top of the append-only audit bundle the fleet already
writes; `make demo` / the pipeline itself is unaffected by this file."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"
AUDIT_PATH = OUT_DIR / "audit.json"
EXC_PATH = OUT_DIR / "exception_queue.json"

st.set_page_config(page_title="Tiny CEDX -- Insurance Claims Fleet", layout="wide", page_icon="🛡️")

STATUS_COLOR = {"delivered": "#16a34a", "exception": "#dc2626", "superseded": "#6b7280"}


def load_audit() -> dict | None:
    if not AUDIT_PATH.exists():
        return None
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- header + controls (main page, not sidebar)
st.title("🛡️ Tiny CEDX -- Insurance Claims Agent Fleet")
st.caption("Insurance Claims Intake -- Agent Fleet")

run_col, log_col = st.columns([1, 3])
with run_col:
    if st.button("▶️  Run pipeline (make demo)", use_container_width=True, type="primary"):
        with st.spinner("Running Orchestrator -> Worker -> Verifier over the seed pack..."):
            proc = subprocess.run(
                [sys.executable, "-m", "app.cli.main"],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
        st.session_state["last_run_log"] = (proc.stdout or "") + (proc.stderr or "")
        st.session_state["last_run_ok"] = proc.returncode == 0
        st.rerun()

if "last_run_log" in st.session_state:
    icon = "✅" if st.session_state.get("last_run_ok") else "❌"
    with st.expander(f"{icon} Last run log", expanded=False):
        st.code(st.session_state["last_run_log"], language="text")

st.caption("Reads `out/audit.json` directly -- no backend, no API.")

audit = load_audit()
if audit is None:
    st.warning("No `out/audit.json` yet. Click **Run pipeline** above (or run `make demo` / `python -m app.cli.main`).")
    st.stop()

records = audit["records"]
delivered = [r for r in records if r["status"] == "delivered"]
exceptions = [r for r in records if r["status"] == "exception"]
superseded = [r for r in records if r["status"] == "superseded"]
cost = audit["cost"]
amendment = audit["amendment"]

h1, h2, h3 = st.columns([2, 2, 3])
h1.markdown(f"**CASE_ID** `{audit['case_id']}`")
h2.markdown(f"**Generated** {audit['generated_at'][:19].replace('T', ' ')}")
h3.markdown(f"**Amendment** second approval required from **{amendment['role']}** for claims &ge; **${amendment['threshold']:,.0f}**")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Delivered", len(delivered))
m2.metric("Exceptions", len(exceptions))
m3.metric("Superseded", len(superseded))
m4.metric("Total cost", f"${cost['total_usd']:.4f}")
m5.metric("Avg $/record", f"${cost['avg_usd_per_record']:.6f}")
m6.metric("Projected $/10k", f"${cost['projected_usd_per_10k']:.2f}")

st.divider()

tab_overview, tab_records, tab_detail, tab_exceptions, tab_examples, tab_agents, tab_log = st.tabs(
    ["📊 Overview", "📋 All records", "🔍 Record trace", "🚫 Exception queue", "📦 Example outputs", "🤖 Agent roster", "📜 Audit log"]
)

# --------------------------------------------------------------------------- overview
with tab_overview:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Status breakdown")
        status_counts = pd.Series([r["status"] for r in records]).value_counts()
        st.bar_chart(status_counts)
    with c2:
        st.subheader("Exception reason codes")
        codes = [r["reason_code"] for r in records if r.get("reason_code")]
        if codes:
            st.bar_chart(pd.Series(codes).value_counts())
        else:
            st.info("No reason codes in this run.")

    st.subheader("Per-agent cost")
    agent_cost: dict[str, float] = {}
    for r in records:
        for span in r.get("agent_trace", []):
            agent_cost[span["agent"]] = agent_cost.get(span["agent"], 0.0) + (span.get("cost_usd") or 0.0)
    if agent_cost:
        st.bar_chart(pd.Series(agent_cost, name="cost_usd"))

# --------------------------------------------------------------------------- all records
with tab_records:
    df = pd.DataFrame([
        {
            "id": r["id"], "status": r["status"], "reason_code": r.get("reason_code") or "-",
            "reason_class": r.get("reason_class") or "-", "source": r["source_format"],
            "version": r.get("version"), "agent_hops": len(r.get("agent_trace", [])),
        }
        for r in records
    ])
    status_filter = st.multiselect("Filter by status", options=sorted(df["status"].unique()), default=list(df["status"].unique()))
    st.dataframe(df[df["status"].isin(status_filter)], use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- record detail / trace
with tab_detail:
    ids = [r["id"] for r in records]
    selected = st.selectbox("Pick a record to see its full agent decision path", ids)
    rec = next(r for r in records if r["id"] == selected)

    badge = STATUS_COLOR.get(rec["status"], "#000000")
    st.markdown(
        f"### {rec['id']}  &nbsp; <span style='color:{badge};font-weight:700'>{rec['status'].upper()}</span>"
        + (f" &nbsp; `{rec['reason_code']}`" if rec.get("reason_code") else ""),
        unsafe_allow_html=True,
    )
    st.caption(f"source={rec['source_format']} v{rec.get('version')}  ·  hash={rec.get('source_version_hash')}")

    st.markdown("**Agent decision path**")
    trace = rec.get("agent_trace", [])
    if not trace:
        st.info("No agent_trace -- this record was superseded before reaching the fleet.")
    for i, span in enumerate(trace):
        cols = st.columns([1.2, 2, 1, 1, 1, 1.3])
        cols[0].markdown(f"**{i+1}. {span['agent']}**")
        cols[1].write(span.get("model") or "-")
        cols[2].write(span.get("status"))
        cols[3].write(span.get("verdict") or "-")
        cols[4].write(f"${span.get('cost_usd') or 0:.6f}")
        cols[5].write(f"{span.get('latency_ms') or 0:.0f} ms")

    st.markdown("**Approval trail**")
    trail = rec.get("approval_trail", [])
    if trail:
        st.dataframe(pd.DataFrame(trail), use_container_width=True, hide_index=True)
    else:
        st.info("No approval trail -- record never left the exception queue.")

    if rec.get("delivered_fields"):
        st.markdown("**Delivered fields**")
        st.json(rec["delivered_fields"])

# --------------------------------------------------------------------------- exception queue
with tab_exceptions:
    if not exceptions:
        st.success("No exceptions in this run.")
    for r in exceptions:
        with st.expander(f"{r['id']}  --  {r.get('reason_code')}  (class {r.get('reason_class')})"):
            st.write(f"source: {r['source_format']} v{r.get('version')}")
            trace = r.get("agent_trace", [])
            if trace:
                st.dataframe(pd.DataFrame(trace), use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- example outputs
with tab_examples:
    st.caption("Branded claim summaries the Worker drafted and the Verifier independently passed.")
    for r in delivered[:8]:
        df_fields = r.get("delivered_fields") or {}
        with st.container(border=True):
            st.markdown(f"**{r['id']}**  --  {df_fields.get('claim_category', '-')}  --  ${df_fields.get('claim_amount', 0):,.2f}")
            st.write(f"Owner: {df_fields.get('claim_owner', '-')}  ·  SLA: {df_fields.get('sla_date', '-')}")
            st.write(df_fields.get("summary", ""))
            if r.get("reason_code"):
                st.caption(f"note: {r['reason_code']} (Class {r.get('reason_class')}) -- auto-resolved, still delivered")

# --------------------------------------------------------------------------- agent roster
with tab_agents:
    st.dataframe(pd.DataFrame(audit["agents"]), use_container_width=True, hide_index=True)
    st.caption("`can_call` is the typed contract: who each agent is permitted to invoke.")

# --------------------------------------------------------------------------- audit log
with tab_log:
    st.caption("Append-only, hash-chained event log (`events`). Any past edit breaks the chain from that point forward.")
    events_df = pd.DataFrame(audit["events"])
    st.dataframe(events_df, use_container_width=True, hide_index=True)
