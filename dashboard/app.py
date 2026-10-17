"""Rishi-OS Control Room -- Streamlit dashboard.

AGENTS.md Rule 6: this file contains ZERO AI.

  * It imports only `core.config` and `core.db` (plain datahouse plumbing).
  * It NEVER imports `core.router`, `core.validator`, or anything under
    `agents/`.
  * It NEVER executes an agent. To trigger work it writes a row or flips a
    flag, and GitHub Actions picks it up on the next tick.

Run from the repository root:

    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from core import config, db

# ---------------------------------------------------------------------------
# Structural guarantee: the dashboard must never gain AI.
# If someone adds a model import, this module refuses to start.
# ---------------------------------------------------------------------------
_FORBIDDEN = ("core.router", "agents", "core.validator")
_LEAKED = [m for m in _FORBIDDEN if m in sys.modules]
if _LEAKED:
    raise RuntimeError(
        f"Control Room must contain zero AI; unexpected modules loaded: {_LEAKED}"
    )

st.set_page_config(
    page_title="Rishi-OS Control Room",
    page_icon="🛰️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------
def require_password() -> None:
    if st.session_state.get("authed"):
        return

    st.title("🛰️ Rishi-OS Control Room")
    st.caption("Read, approve, and queue. Nothing here thinks.")

    if not config.DASHBOARD_PASSWORD:
        st.error(
            "DASHBOARD_PASSWORD is not set. Add it to `.env` before using the "
            "Control Room."
        )
        st.stop()

    with st.form("login"):
        supplied = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock")

    if submitted:
        if supplied == config.DASHBOARD_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


require_password()


# ---------------------------------------------------------------------------
# Helpers -- plain code only
# ---------------------------------------------------------------------------
def to_frame(rows: list[dict], columns: list[str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(rows or [])
    if columns and not frame.empty:
        keep = [c for c in columns if c in frame.columns]
        frame = frame[keep]
    return frame


def guard(call, label: str):
    """Run a datahouse call, surfacing failures as UI errors instead of crashes."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001
        st.error(f"{label} failed: {type(exc).__name__}: {exc}")
        return None


def set_output_status(output_id: str, status: str) -> None:
    db.client().table("outputs").update({"status": status}).eq("id", output_id).execute()


def update_output_text(output_id: str, clean: str) -> None:
    db.client().table("outputs").update(
        {"clean": clean, "hash": db.content_hash(clean)}
    ).eq("id", output_id).execute()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🛰️ Rishi-OS")
    st.caption("Control Room v1 -- zero AI, zero agent execution")
    st.divider()
    providers = config.available_providers()
    st.metric("Providers reachable", f"{len(providers)}/{len(config.PROVIDERS)}")
    for provider in config.PROVIDERS:
        ready = provider in providers
        st.write(f"{'🟢' if ready else '⚪'} {provider['label']} -- `{provider['id']}`")
    st.divider()
    if st.button("Sign out"):
        st.session_state["authed"] = False
        st.rerun()

st.title("Rishi-OS Control Room")
st.caption(
    "Human approval layer. This dashboard reads and writes Supabase only -- "
    "it never runs an agent and contains no AI."
)

tabs = st.tabs(
    ["📊 Overview", "📝 Outputs", "🤖 Agents", "➕ Queue", "💸 Usage", "🗒️ Notes"]
)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
with tabs[0]:
    outputs = guard(lambda: db.recent_outputs(limit=200), "Loading outputs")
    agents = guard(db.list_agents, "Loading agents")
    usage = guard(
        lambda: db.client().table("usage").select("*").order(
            "created_at", desc=True
        ).limit(200).execute().data,
        "Loading usage",
    )

    if outputs is not None and agents is not None:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Outputs", len(outputs))
        c2.metric(
            "Awaiting review",
            sum(1 for o in outputs if o.get("status") == "needs_review"),
        )
        c3.metric(
            "Approved", sum(1 for o in outputs if o.get("status") == "approved")
        )
        c4.metric(
            "Agents enabled",
            sum(1 for a in agents if a.get("enabled")),
        )

    if outputs:
        st.subheader("Recent activity")
        frame = to_frame(
            outputs,
            ["created_at", "agent", "status", "provider", "model", "source_url"],
        )
        st.dataframe(frame, width="stretch", hide_index=True)

    if usage:
        st.subheader("Model calls by provider (this window)")
        counts = (
            pd.DataFrame(usage).groupby("provider").size().reset_index(name="runs")
        )
        st.bar_chart(counts, x="provider", y="runs")


# ---------------------------------------------------------------------------
# Outputs -- the approval queue
# ---------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Approval queue")
    status_filter = st.selectbox(
        "Filter by status",
        ["needs_review", "draft", "approved", "rejected", "failed", "all"],
        index=0,
    )

    rows = guard(
        lambda: db.recent_outputs(limit=100), "Loading outputs"
    ) or []
    if status_filter != "all":
        rows = [r for r in rows if r.get("status") == status_filter]

    if not rows:
        st.info("Nothing here. Either everything is approved, or no agent has run yet.")

    for row in rows:
        label = (
            f"{row.get('created_at', '')} | {row.get('agent')} | "
            f"{row.get('status')} | {db.normalise(row.get('clean') or '')[:70]}"
        )
        with st.expander(label):
            left, right = st.columns([2, 1])
            with left:
                st.markdown("**Clean (what a human would use)**")
                st.markdown(row.get("clean") or "_(empty)_")
                with st.expander("Raw model output"):
                    st.code(row.get("raw") or "", language="markdown")
            with right:
                st.caption(f"provider: {row.get('provider')}")
                st.caption(f"model: {row.get('model')}")
                st.caption(f"hash: `{(row.get('hash') or '')[:12]}`")
                if row.get("source_url"):
                    st.caption(f"source: {row['source_url']}")

                edited = st.text_area(
                    "Edit clean text",
                    value=row.get("clean") or "",
                    height=160,
                    key=f"edit_{row['id']}",
                )
                b1, b2, b3 = st.columns(3)
                if b1.button("✅ Approve", key=f"ap_{row['id']}"):
                    set_output_status(row["id"], config.STATUS_APPROVED)
                    st.rerun()
                if b2.button("🚫 Reject", key=f"rj_{row['id']}"):
                    set_output_status(row["id"], config.STATUS_REJECTED)
                    st.rerun()
                if b3.button("💾 Save edit", key=f"sv_{row['id']}"):
                    update_output_text(row["id"], edited)
                    st.rerun()


# ---------------------------------------------------------------------------
# Agents -- caps and enables
# ---------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Roster, caps, and enablement")
    st.caption(
        "Changing these does not run anything. The next cron tick reads them."
    )
    agents = guard(db.list_agents, "Loading agents") or []

    if not agents:
        st.info("No agents registered. Run `schema.sql` to seed the roster.")

    for agent in agents:
        name = agent.get("name", "?")
        with st.expander(f"{'🟢' if agent.get('enabled') else '⚪'} {name}"):
            left, right = st.columns(2)
            with left:
                st.caption(agent.get("purpose") or "")
                st.caption(f"schedule: {agent.get('schedule') or 'unspecified'}")
                st.caption(f"runs today: {agent.get('runs_today') or 0}")
            with right:
                enabled = st.checkbox(
                    "enabled", value=bool(agent.get("enabled")), key=f"en_{name}"
                )
                cap = st.number_input(
                    "daily_cap",
                    min_value=0,
                    max_value=48,
                    value=int(agent.get("daily_cap") or 1),
                    key=f"cap_{name}",
                )
                if st.button("Save", key=f"save_{name}"):
                    db.client().table("agents").update(
                        {"enabled": enabled, "daily_cap": int(cap)}
                    ).eq("name", name).execute()
                    st.success(f"Saved {name}.")
                    st.rerun()


# ---------------------------------------------------------------------------
# Queue -- write a task, never run it
# ---------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Queue work for the next cron tick")
    st.caption("This writes a row to `tasks`. It does not execute an agent.")

    agents = guard(db.list_agents, "Loading agents") or []
    names = [a.get("name") for a in agents if a.get("name")]

    with st.form("queue"):
        target = st.selectbox("Agent", names or ["research_agent"])
        topic = st.text_input("Topic (for research-style agents)")
        source_url = st.text_input("Source URL (for the librarian)")
        body = st.text_area("Inline text (for the librarian)", height=120)
        submitted = st.form_submit_button("Queue")

    if submitted:
        payload = {
            k: v
            for k, v in {"topic": topic, "url": source_url, "text": body}.items()
            if v
        }
        if not payload:
            st.warning("Provide at least one field.")
        else:
            saved = guard(
                lambda: db.save_task(agent=target, payload=payload), "Queueing task"
            )
            if saved:
                st.success(f"Queued for {target}.")

    st.divider()
    st.subheader("Queued tasks")
    tasks = guard(
        lambda: db.client().table("tasks").select("*").order(
            "created_at", desc=True
        ).limit(50).execute().data,
        "Loading tasks",
    ) or []
    if tasks:
        st.dataframe(
            to_frame(tasks, ["created_at", "agent", "status", "payload"]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Queue is empty.")


# ---------------------------------------------------------------------------
# Usage ledger
# ---------------------------------------------------------------------------
with tabs[4]:
    st.subheader("Zero-budget ledger")
    usage = guard(
        lambda: db.client().table("usage").select("*").order(
            "created_at", desc=True
        ).limit(200).execute().data,
        "Loading usage",
    ) or []

    if not usage:
        st.info("No model calls recorded yet.")
    else:
        frame = pd.DataFrame(usage)
        c1, c2, c3 = st.columns(3)
        c1.metric("Calls", int(frame["calls"].fillna(0).sum()))
        c2.metric("Chars in", int(frame["chars_in"].fillna(0).sum()))
        c3.metric("Chars out", int(frame["chars_out"].fillna(0).sum()))
        st.dataframe(
            to_frame(usage, ["created_at", "agent", "provider", "model", "calls"]),
            width="stretch",
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Journal")
    brands = guard(db.list_brands, "Loading brands") or []
    brand_keys = ["(none)"] + [b.get("key") for b in brands if b.get("key")]

    with st.form("note"):
        brand = st.selectbox("Brand", brand_keys)
        kind = st.selectbox("Kind", ["note", "idea", "journal", "decision"])
        body = st.text_area("Note", height=140)
        submitted = st.form_submit_button("Add note")

    if submitted and body.strip():
        saved = guard(
            lambda: db.save_note(
                body=body.strip(),
                brand=None if brand == "(none)" else brand,
                kind=kind,
            ),
            "Saving note",
        )
        if saved:
            st.success("Noted.")

    st.divider()
    notes = guard(
        lambda: db.client().table("notes").select("*").order(
            "created_at", desc=True
        ).limit(50).execute().data,
        "Loading notes",
    ) or []
    if notes:
        st.dataframe(
            to_frame(notes, ["created_at", "brand", "kind", "body"]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No notes yet.")
