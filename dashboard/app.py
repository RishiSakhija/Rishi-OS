"""Rishi-OS Control Room — Design 4 (Premium Executive UI)

AGENTS.md Rule 6: this file contains ZERO AI.

  * Imports only `core.config` and `core.db` (plain datahouse plumbing).
  * NEVER imports `core.router`, `core.validator`, or anything under `agents/`.
  * NEVER executes an agent directly. It writes tasks to Supabase for GitHub
    Actions to pick up, or optionally runs the queue-drainer script via
    subprocess.

Run from the repository root:

    streamlit run dashboard/app.py
"""

from __future__ import annotations

import subprocess
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
# ---------------------------------------------------------------------------
_FORBIDDEN = ("core.router", "agents", "core.validator")
_LEAKED = [m for m in _FORBIDDEN if m in sys.modules]
if _LEAKED:
    raise RuntimeError(
        f"Control Room must contain zero AI; unexpected modules loaded: {_LEAKED}"
    )

st.set_page_config(
    page_title="Rishi-OS Control Room",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Design 4 — premium custom CSS (light-meets-dark editorial)
# ---------------------------------------------------------------------------
_CSS = """
<style>
:root {
  --bg-offwhite: #F7F4EF;
  --bg-alabaster: #FAF9F6;
  --panel-dark: #1F1A17;
  --panel-navy: #1E2229;
  --forest: #242B1E;
  --sage: #586450;
  --ochre: #D4AF37;
  --ink: #1F1A17;
  --muted: #6B645C;
  --line: #E4DCCF;
}

html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-offwhite) !important;
  color: var(--ink) !important;
  font-family: "Georgia", "Iowan Old Style", "Apple Garamond", serif !important;
}

[data-testid="stSidebar"] {
  background: var(--panel-dark) !important;
  border-right: 1px solid var(--line) !important;
  width: 260px !important;
}

[data-testid="stSidebar"] * {
  color: #F2EEE6 !important;
  font-family: "Inter", "Helvetica Neue", sans-serif !important;
}

[data-testid="stSidebar"] .stButton > button {
  background: transparent !important;
  border: 1px solid #3A332B !important;
  color: #F2EEE6 !important;
  border-radius: 10px !important;
  padding: 0.6rem 1rem !important;
  width: 100% !important;
  text-align: left !important;
  font-size: 0.85rem !important;
  font-weight: 600 !important;
  transition: all 0.3s ease !important;
  margin-bottom: 0.4rem !important;
}

[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--ochre) !important;
  border-color: var(--ochre) !important;
  color: #1F1A17 !important;
  transform: translateX(4px) !important;
  box-shadow: 0 4px 12px rgba(212, 175, 55, 0.25) !important;
}

[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
  border-color: #3A332B !important;
}

[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
  background: var(--ochre) !important;
  border-color: var(--ochre) !important;
  color: #1F1A17 !important;
}

/* Main canvas */
[data-testid="stMainBlockContainer"] {
  background: var(--bg-alabaster) !important;
  padding-top: 1.5rem !important;
  max-width: 1400px !important;
}

h1, h2, h3, h4 {
  font-family: "Georgia", "Iowan Old Style", serif !important;
  color: var(--ink) !important;
  letter-spacing: -0.02em !important;
}

h1 {
  font-size: 2.1rem !important;
  border-bottom: 2px solid var(--ochre) !important;
  padding-bottom: 0.5rem !important;
  margin-bottom: 1.5rem !important;
}

h2 {
  font-size: 1.4rem !important;
  color: var(--panel-dark) !important;
  margin-top: 2rem !important;
}

/* Premium cards */
.card {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  padding: 1.25rem !important;
  margin-bottom: 1rem !important;
  box-shadow: 0 2px 8px rgba(31, 26, 23, 0.06) !important;
  transition: all 0.3s ease !important;
}

.card:hover {
  box-shadow: 0 8px 24px rgba(31, 26, 23, 0.12) !important;
  transform: translateY(-2px) !important;
}

.card-dark {
  background: var(--panel-navy) !important;
  border: 1px solid #3A332B !important;
  border-radius: 12px !important;
  padding: 1.25rem !important;
  margin-bottom: 1rem !important;
  color: #F2EEE6 !important;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35) !important;
  transition: all 0.3s ease !important;
}

.card-dark * {
  color: #F2EEE6 !important;
}

.card-dark h3, .card-dark h4 {
  color: var(--ochre) !important;
}

/* KPI row */
.kpi {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  padding: 1rem 1.25rem !important;
  text-align: center !important;
  box-shadow: 0 2px 6px rgba(31, 26, 23, 0.05) !important;
  transition: all 0.3s ease !important;
}

.kpi .value {
  font-size: 1.75rem !important;
  font-weight: 700 !important;
  color: var(--ink) !important;
  display: block !important;
  margin-bottom: 0.25rem !important;
}

.kpi .label {
  font-size: 0.75rem !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  color: var(--muted) !important;
  display: block !important;
}

/* Status badges / tags */
.tag {
  display: inline-block !important;
  padding: 0.15rem 0.5rem !important;
  border-radius: 6px !important;
  font-size: 0.7rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.05em !important;
  margin-right: 0.35rem !important;
}

.tag-draft { background: #F3EFE6 !important; color: #8A7F6F !important; border: 1px solid #D9D0C0 !important; }
.tag-needs_review { background: #FFF8E1 !important; color: #B88A1A !important; border: 1px solid #E8D49A !important; }
.tag-approved { background: #EAF3EC !important; color: var(--forest) !important; border: 1px solid #C9D6C2 !important; }
.tag-rejected { background: #FBEEE9 !important; color: #8A5A4A !important; border: 1px solid #DFC8C2 !important; }
.tag-failed { background: #F3EFE6 !important; color: var(--muted) !important; border: 1px solid #D9D0C0 !important; }

/* Output cards */
.output-card {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  padding: 1.25rem !important;
  margin-bottom: 1rem !important;
  transition: all 0.3s ease !important;
}

.output-card:hover {
  border-color: var(--ochre) !important;
  box-shadow: 0 6px 20px rgba(31, 26, 23, 0.08) !important;
}

.output-meta {
  font-size: 0.72rem !important;
  color: var(--muted) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  margin-bottom: 0.6rem !important;
  border-bottom: 1px solid #EFE9DE !important;
  padding-bottom: 0.5rem !important;
}

/* Buttons */
.stButton > button {
  border-radius: 8px !important;
  font-weight: 600 !important;
  transition: all 0.3s ease !important;
  border: 1px solid var(--line) !important;
  background: #FFFFFF !important;
  color: var(--ink) !important;
  padding: 0.5rem 1.1rem !important;
}

.stButton > button:hover {
  border-color: var(--ochre) !important;
  color: #1F1A17 !important;
  background: #FFF9F0 !important;
}

.stButton > button[kind="primary"] {
  background: var(--panel-dark) !important;
  border-color: var(--panel-dark) !important;
  color: #F2EEE6 !important;
}

.stButton > button[kind="primary"]:hover {
  background: var(--ochre) !important;
  border-color: var(--ochre) !important;
  color: #1F1A17 !important;
}

.stButton > button[kind="secondary"] {
  background: #FFFFFF !important;
  border-color: var(--line) !important;
}

/* Text inputs and areas */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
  color: var(--ink) !important;
}

.stSelectbox > div > div {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
}

/* Dataframes */
[data-testid="stDataFrame"] {
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  overflow: hidden !important;
}

/* Page fade */
.page-fade {
  animation: fadeIn 0.4s ease forwards !important;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Log stream */
.log-line {
  font-family: "Menlo", "Monaco", monospace !important;
  font-size: 0.75rem !important;
  padding: 0.25rem 0.5rem !important;
  border-bottom: 1px solid #2A2723 !important;
  color: #D8CFC0 !important;
}

.log-line.ok { color: var(--forest) !important; }
.log-line.err { color: #C99A7A !important; }
.log-line.inf { color: var(--sage) !important; }

/* Hide Streamlit chrome */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------
def require_password() -> None:
    if st.session_state.get("authed"):
        return

    st.markdown(
        '<div style="background:var(--panel-navy);color:#F2EEE6;padding:3rem 2rem;border-radius:16px;text-align:center;max-width:420px;margin:4rem auto;">'
        '<div style="font-size:2.5rem;margin-bottom:0.5rem;">◈</div>'
        '<h1 style="margin:0 0 0.5rem 0;font-size:1.6rem;">Rishi-OS Control Room</h1>'
        '<p style="color:#BFB5A6;margin:0 0 1.5rem 0;">Enter the dashboard password to continue.</p>'
        "</div>",
        unsafe_allow_html=True,
    )

    if not config.DASHBOARD_PASSWORD:
        st.error(
            "DASHBOARD_PASSWORD is not set. Add it to `.env` before using the "
            "Control Room."
        )
        st.stop()

    with st.form("login"):
        supplied = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="••••••••")
        submitted = st.form_submit_button("Unlock", use_container_width=True)

    if submitted:
        if supplied == config.DASHBOARD_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


require_password()


# ---------------------------------------------------------------------------
# Page navigation
# ---------------------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "command_center"

PAGES = [
    ("command_center", "🎯 Command Center"),
    ("review_inbox", "📥 Review Inbox"),
    ("creative_studio", "📝 Creative Studio & Journal"),
    ("analytics_ledger", "📈 Analytics & Ledger"),
]


# ---------------------------------------------------------------------------
# Helpers — plain code only
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


def save_note(body: str, brand: str | None, kind: str) -> dict | None:
    return db.save_note(body=body.strip(), brand=brand, kind=kind)


def save_brand(
    key: str,
    name: str,
    voice: str,
    audience: str,
    platforms: str,
    always: str,
    never: str,
) -> None:
    db.client().table("brands").upsert(
        {
            "key": key,
            "name": name,
            "voice": voice,
            "audience": audience,
            "platforms": platforms,
            "always": always,
            "never": never,
        },
        on_conflict="key",
    ).execute()


def tag_html(status: str) -> str:
    cls = f"tag-{status}" if status in (
        "draft", "needs_review", "approved", "rejected", "failed", "skipped"
    ) else "tag-draft"
    label = status.replace("_", " ").title()
    return f'<span class="tag {cls}">{label}</span>'


def safe_rerun() -> None:
    try:
        st.rerun()
    except Exception:  # pragma: no cover - older Streamlit
        st.experimental_rerun()


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '<div style="padding:1.5rem 1rem 0.5rem 1rem;">'
        '<div style="font-size:2rem;margin-bottom:0.25rem;">◈</div>'
        '<div style="font-weight:700;font-size:1.1rem;letter-spacing:0.06em;text-transform:uppercase;">Rishi-OS</div>'
        '<div style="font-size:0.68rem;color:#BFB5A6;margin-top:0.15rem;">Control Room v4</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    for key, label in PAGES:
        active = st.session_state.page == key
        btn_kind = "primary" if active else "secondary"
        if st.button(label, key=f"nav_{key}", use_container_width=True, type=btn_kind):
            st.session_state.page = key
            safe_rerun()

    st.divider()
    st.caption("Zero AI. Zero agent execution.")
    providers = config.available_providers()
    ready_count = len(providers)
    total_count = len(config.PROVIDERS)
    st.markdown(
        f'<div class="card-dark" style="margin-top:1rem;">'
        f'<div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.08em;color:#8A8278;margin-bottom:0.5rem;">Providers</div>'
        f'<div style="font-size:0.85rem;font-weight:600;">{ready_count} / {total_count} reachable</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sign out", key="nav_signout", use_container_width=True):
        st.session_state["authed"] = False
        safe_rerun()


# ===========================================================================
# PAGE 1 — COMMAND CENTER
# ===========================================================================
def render_command_center() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Command Center")
    st.caption("Dispatch, monitor, and run the agent fleet from one console.")

    # ---- Data fetch ----
    agents = guard(db.list_agents, "Loading agents") or []
    outputs = guard(lambda: db.recent_outputs(limit=200), "Loading outputs") or []
    tasks = guard(
        lambda: db.client().table("tasks")
        .select("*")
        .eq("status", "queued")
        .order("created_at")
        .limit(50)
        .execute()
        .data,
        "Loading queue",
    ) or []

    # ---- KPI row ----
    enabled_count = sum(1 for a in agents if a.get("enabled"))
    queued_count = len(tasks)
    review_count = sum(1 for o in outputs if o.get("status") == "needs_review")
    daily_cap_total = sum(int(a.get("daily_cap") or 0) for a in agents)
    daily_used_total = sum(int(a.get("runs_today") or 0) for a in agents)
    cap_pct = int((daily_used_total / daily_cap_total) * 100) if daily_cap_total else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f'<div class="kpi"><span class="value">{enabled_count}</span>'
            f'<span class="label">Active Agents</span></div>',
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f'<div class="kpi"><span class="value">{queued_count}</span>'
            f'<span class="label">Queued Tasks</span></div>',
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f'<div class="kpi"><span class="value">{review_count}</span>'
            f'<span class="label">Review Drafts</span></div>',
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            f'<div class="kpi"><span class="value">{cap_pct}%</span>'
            f'<span class="label">Daily Run Cap</span></div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ---- Global run-all bar ----
    col_run, col_spacer = st.columns([1, 4])
    with col_run:
        run_all = st.button(
            "▶️ Run All Queued Tasks",
            key="cmd_run_all",
            use_container_width=True,
            type="primary",
            disabled=queued_count == 0,
        )
    if run_all:
        with st.status("Running queue-drainer…", expanded=True) as status:
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "scripts.run_queued_tasks"],
                    capture_output=True,
                    text=True,
                )
                if proc.stdout:
                    for line in proc.stdout.splitlines():
                        st.write(f'<div class="log-line {"ok" if "ok" in line.lower() else "inf"}">{line}</div>', unsafe_allow_html=True)
                if proc.stderr:
                    for line in proc.stderr.splitlines():
                        st.write(f'<div class="log-line err">{line}</div>', unsafe_allow_html=True)
                status.update(label="Queue drained.", state="complete")
            except Exception as exc:  # noqa: BLE001
                status.update(label=f"Runner error: {exc}", state="error")
        safe_rerun()

    st.divider()

    # ---- Split view ----
    left, right = st.columns([1, 1.25], gap="large")

    with left:
        st.markdown('<div class="card-dark">', unsafe_allow_html=True)
        st.markdown("### Live Agent Fleet")
        st.caption("Toggle caps and enablement. Changes apply to the next cron tick.")
        if not agents:
            st.info("No agents registered.")
        for agent in agents:
            name = agent.get("name", "?")
            enabled = bool(agent.get("enabled"))
            cap = int(agent.get("daily_cap") or 1)
            used = int(agent.get("runs_today") or 0)
            with st.container():
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">'
                    f'<span style="font-weight:600;font-size:0.85rem;">{name}</span>'
                    f'<span class="tag-{"approved" if enabled else "draft"}">{ "ON" if enabled else "OFF" }</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                new_enabled = st.checkbox(
                    "Enabled", value=enabled, key=f"cmd_en_{name}", label_visibility="collapsed"
                )
                new_cap = st.number_input(
                    "Daily cap",
                    min_value=0,
                    max_value=48,
                    value=cap,
                    key=f"cmd_cap_{name}",
                    label_visibility="collapsed",
                )
                if st.button("Save", key=f"cmd_save_{name}", use_container_width=True):
                    db.client().table("agents").update(
                        {"enabled": new_enabled, "daily_cap": int(new_cap)}
                    ).eq("name", name).execute()
                    st.toast(f"Saved {name}.")
                    safe_rerun()
                st.markdown(
                    f'<div class="output-meta">runs today: {used} / {cap} · schedule: {agent.get("schedule") or "unspecified"}</div>',
                    unsafe_allow_html=True,
                )
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Task Builder")
        st.caption("Queue a natural-language instruction for any agent. "
                    "Brand links the task to a voice profile.")
        brands = guard(db.list_brands, "Loading brands") or []
        brand_keys = [b.get("key") for b in brands if b.get("key")]
        agent_names = [a.get("name") for a in agents if a.get("name")]

        with st.form("cmd_task_form"):
            c_brand, c_agent = st.columns(2)
            with c_brand:
                target_brand = st.selectbox("Brand", brand_keys or ["(none)"], key="cmd_brand")
            with c_agent:
                target_agent = st.selectbox("Agent", agent_names or ["research_agent"], key="cmd_agent")
            instructions = st.text_area(
                "Instructions (natural language)",
                height=120,
                key="cmd_instructions",
                placeholder="e.g. Research zero-budget growth tactics for early-stage SaaS",
            )
            submitted = st.form_submit_button("⚡ Queue Task", use_container_width=True, type="primary")

        if submitted:
            payload = {}
            if instructions.strip():
                payload["text"] = instructions.strip()
            if not payload:
                st.warning("Provide at least the instructions.")
            else:
                saved = guard(
                    lambda: db.save_task(agent=target_agent, payload=payload),
                    "Queueing task",
                )
                if saved:
                    st.toast(f"Task queued for {target_agent}.")
                    safe_rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 2 — REVIEW INBOX
# ===========================================================================
def render_review_inbox() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Review Inbox")
    st.caption("Curated deliverables vault — approve, edit, or reject agent output.")

    # ---- Filters ----
    brands = guard(db.list_brands, "Loading brands") or []
    brand_keys = ["(all brands)"] + [b.get("key") for b in brands if b.get("key")]
    statuses = ["all", "needs_review", "draft", "approved", "rejected", "failed", "skipped"]

    f1, f2, f3 = st.columns([1.2, 1.2, 1])
    with f1:
        filter_brand = st.selectbox("Brand", brand_keys, key="rib_brand")
    with f2:
        filter_status = st.selectbox("Status", statuses, index=0, key="rib_status")
    with f3:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="rib_refresh", use_container_width=True):
            safe_rerun()

    # ---- Fetch ----
    rows = guard(lambda: db.recent_outputs(limit=300), "Loading outputs") or []
    if filter_brand != "(all brands)":
        rows = [r for r in rows if r.get("brand") == filter_brand]
    if filter_status != "all":
        rows = [r for r in rows if r.get("status") == filter_status]

    if not rows:
        st.info("Nothing here. Either everything is approved, or no agent has run yet.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    st.markdown(f'<div class="output-meta">{len(rows)} deliverable(s) · filter: {filter_brand} / {filter_status}</div>', unsafe_allow_html=True)

    # ---- Cards ----
    for row in rows:
        oid = row.get("id", "?")
        clean_text = row.get("clean") or row.get("raw") or ""
        raw_text = row.get("raw") or ""
        status = row.get("status", "draft")
        brand = row.get("brand") or "—"
        agent = row.get("agent") or "—"
        provider = row.get("provider") or "—"
        model = row.get("model") or "—"
        source_url = row.get("source_url")

        st.markdown('<div class="output-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="output-meta">'
            f'{tag_html(status)} '
            f'<span style="font-weight:600;">{agent}</span> '
            f'<span style="font-weight:400;opacity:0.7;">· {brand}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown(clean_text, unsafe_allow_html=False)

        # Meta row
        m1, m2, m3, m4 = st.columns([1, 1, 1, 1])
        with m1:
            st.caption(f"Model: {model} · Provider: {provider}")
        with m2:
            if source_url:
                st.caption(f"Source: {source_url}")
        with m3:
            if st.button("📋 Copy", key=f"rib_copy_{oid}", use_container_width=True):
                st.write(
                    f'<script>navigator.clipboard.writeText({clean_text!r});</script>',
                    unsafe_allow_html=True,
                )
                st.toast("Copied to clipboard.")
        with m4:
            st.write("")

        b1, b2, b3 = st.columns(3)
        with b1:
            if status != "approved":
                if st.button("🏆 Approve (Winner)", key=f"rib_ap_{oid}", use_container_width=True, type="primary"):
                    set_output_status(oid, config.STATUS_APPROVED)
                    st.toast("Approved.")
                    safe_rerun()
            else:
                st.button("✅ Approved", key=f"rib_ap_done_{oid}", use_container_width=True, disabled=True)
        with b2:
            if status != "draft":
                if st.button("🔄 Set to Draft", key=f"rib_df_{oid}", use_container_width=True):
                    set_output_status(oid, config.STATUS_DRAFT)
                    st.toast("Reset to draft.")
                    safe_rerun()
            else:
                st.button("📝 Draft", key=f"rib_df_done_{oid}", use_container_width=True, disabled=True)
        with b3:
            if status != "rejected":
                if st.button("🗑️ Reject", key=f"rib_rj_{oid}", use_container_width=True):
                    set_output_status(oid, config.STATUS_REJECTED)
                    st.toast("Rejected.")
                    safe_rerun()
            else:
                st.button("⛔ Rejected", key=f"rib_rj_done_{oid}", use_container_width=True, disabled=True)

        with st.expander("Edit clean text / raw output", expanded=False):
            edited = st.text_area(
                "Clean text",
                value=clean_text,
                height=180,
                key=f"rib_edit_{oid}",
            )
            if st.button("💾 Save edit", key=f"rib_sv_{oid}", use_container_width=True):
                update_output_text(oid, edited)
                st.toast("Edit saved.")
                safe_rerun()
            with st.expander("Raw model output", expanded=False):
                st.code(raw_text or "", language="markdown")

        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 3 — CREATIVE STUDIO & JOURNAL
# ===========================================================================
def render_creative_studio() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Creative Studio & Journal")
    st.caption("Brand voice directory and the note vault.")

    brands = guard(db.list_brands, "Loading brands") or []
    brand_keys = [b.get("key") for b in brands if b.get("key")]

    left, right = st.columns([1, 1], gap="large")

    # ---- Left: Brands & Voice Directory ----
    with left:
        st.markdown('<div class="card-dark">', unsafe_allow_html=True)
        st.markdown("### Brands & Voice Directory")
        st.caption("View and edit platform profiles.")

        if not brands:
            st.info("No brands registered. Run `schema.sql` to seed.")
        else:
            for brand in brands:
                bkey = brand.get("key", "?")
                with st.expander(f"{brand.get('name', bkey)} ({bkey})", expanded=False):
                    with st.form(f"brand_form_{bkey}"):
                        name = st.text_input("Name", value=brand.get("name") or "", key=f"brand_name_{bkey}")
                        voice = st.text_area("Voice", value=brand.get("voice") or "", height=80, key=f"brand_voice_{bkey}")
                        audience = st.text_area("Audience", value=brand.get("audience") or "", height=80, key=f"brand_aud_{bkey}")
                        platforms = st.text_input("Platforms", value=brand.get("platforms") or "", key=f"brand_plt_{bkey}")
                        always = st.text_area("Always", value=brand.get("always") or "", height=70, key=f"brand_alw_{bkey}")
                        never = st.text_area("Never", value=brand.get("never") or "", height=70, key=f"brand_nev_{bkey}")
                        if st.form_submit_button("💾 Save Brand", use_container_width=True, type="primary"):
                            save_brand(bkey, name, voice, audience, platforms, always, never)
                            st.toast(f"Brand {bkey} saved.")
                            safe_rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # ---- Right: Note Vault ----
    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Note Vault")
        st.caption("Save thoughts, brain dumps, and journal entries linked to brands.")

        with st.form("note_form"):
            n_brand = st.selectbox(
                "Link to brand",
                ["(none)"] + brand_keys,
                key="note_brand",
            )
            n_kind = st.selectbox(
                "Kind",
                ["note", "idea", "journal", "decision"],
                key="note_kind",
            )
            n_body = st.text_area(
                "Note",
                height=160,
                key="note_body",
                placeholder="Capture a thought, idea, or journal entry…",
            )
            n_submit = st.form_submit_button("✨ Save Note", use_container_width=True, type="primary")

        if n_submit:
            if not n_body.strip():
                st.warning("Write something before saving.")
            else:
                saved = save_note(
                    n_body.strip(),
                    None if n_brand == "(none)" else n_brand,
                    n_kind,
                )
                if saved:
                    st.toast("Note saved.")
                    safe_rerun()

        st.divider()
        st.markdown("#### Recent Journal")
        notes = guard(
            lambda: db.client().table("notes")
            .select("*")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data,
            "Loading notes",
        ) or []

        if not notes:
            st.info("No notes yet.")
        else:
            for note in notes:
                n_id = note.get("id", "?")
                n_body_text = note.get("body") or ""
                n_kind_val = note.get("kind") or "note"
                n_brand_val = note.get("brand") or "—"
                n_time = note.get("created_at") or ""
                with st.container():
                    st.markdown(
                        f'<div class="card" style="padding:0.9rem 1rem;">'
                        f'<div class="output-meta">'
                        f'<span class="tag-{n_kind_val}">{n_kind_val.title()}</span> '
                        f'<span style="font-weight:600;">{n_brand_val}</span> '
                        f'<span style="opacity:0.6;">{n_time[:16]}</span>'
                        f'</div>'
                        f'<div style="font-size:0.9rem;line-height:1.5;">{n_body_text}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("🗑️ Delete", key=f"note_del_{n_id}", use_container_width=True):
                        db.client().table("notes").delete().eq("id", n_id).execute()
                        st.toast("Note deleted.")
                        safe_rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 4 — ANALYTICS & LEDGER
# ===========================================================================
def render_analytics_ledger() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Analytics & Ledger")
    st.caption("Executive log streams, usage metrics, and the zero-budget ledger.")

    # ---- Fetch ----
    logs = guard(
        lambda: db.client().table("logs")
        .select("*")
        .order("time", desc=True)
        .limit(200)
        .execute()
        .data,
        "Loading logs",
    ) or []
    usage = guard(
        lambda: db.client().table("usage")
        .select("*")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data,
        "Loading usage",
    ) or []

    # ---- KPI strip ----
    total_calls = sum(int(u.get("calls") or 0) for u in usage)
    total_chars_in = sum(int(u.get("chars_in") or 0) for u in usage)
    total_chars_out = sum(int(u.get("chars_out") or 0) for u in usage)
    total_logs = len(logs)
    failed_logs = sum(1 for l in logs if l.get("status") == "failed")

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f'<div class="kpi"><span class="value">{total_calls}</span><span class="label">Model Calls</span></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="kpi"><span class="value">{total_chars_in:,}</span><span class="label">Chars In</span></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="kpi"><span class="value">{total_chars_out:,}</span><span class="label">Chars Out</span></div>', unsafe_allow_html=True)
    with k4:
        st.markdown(f'<div class="kpi"><span class="value">{total_logs}</span><span class="label">Log Entries</span></div>', unsafe_allow_html=True)
    with k5:
        st.markdown(f'<div class="kpi"><span class="value">{failed_logs}</span><span class="label">Failed Runs</span></div>', unsafe_allow_html=True)

    st.divider()

    # ---- Charts ----
    if usage:
        usage_df = pd.DataFrame(usage)
        usage_df["provider"] = usage_df["provider"].fillna("unknown")
        provider_counts = usage_df.groupby("provider").size().reset_index(name="runs")
        provider_calls = usage_df.groupby("provider")["calls"].sum().reset_index(name="total_calls")

        c_left, c_right = st.columns(2)
        with c_left:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("### Calls by Provider")
            st.bar_chart(provider_counts, x="provider", y="runs", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        with c_right:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("### Total Calls by Provider")
            st.bar_chart(provider_calls, x="provider", y="total_calls", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("No usage recorded yet.")

    st.divider()

    # ---- Split view: logs + usage table ----
    l_col, r_col = st.columns([1.1, 1], gap="large")

    with l_col:
        st.markdown('<div class="card-dark">', unsafe_allow_html=True)
        st.markdown("### Execution Stream")
        st.caption("Real-time backend agent telemetry (logs ordered by `time` DESC).")
        if not logs:
            st.info("No log entries yet.")
        else:
            for log in logs[:40]:
                l_status = log.get("status") or "—"
                l_agent = log.get("agent") or "—"
                l_model = log.get("model") or "—"
                l_provider = log.get("provider") or "—"
                l_time = (log.get("time") or "")[:16]
                l_notes = (log.get("notes") or "")[:120]
                cls = "ok" if l_status == "ok" else ("err" if l_status == "failed" else "inf")
                st.markdown(
                    f'<div class="log-line {cls}">'
                    f'<strong>{l_time}</strong> · {l_agent} · {l_status} '
                    f'({l_provider}/{l_model})'
                    f'{(" — " + l_notes) if l_notes else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        st.markdown('</div>', unsafe_allow_html=True)

    with r_col:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Usage Ledger")
        st.caption("Provider accounting (ordered by `created_at` DESC).")
        if not usage:
            st.info("No usage recorded yet.")
        else:
            u_frame = to_frame(
                usage,
                ["created_at", "agent", "provider", "model", "calls", "chars_in", "chars_out"],
            )
            st.dataframe(u_frame, width="stretch", hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# Router
# ===========================================================================
if st.session_state.page == "command_center":
    render_command_center()
elif st.session_state.page == "review_inbox":
    render_review_inbox()
elif st.session_state.page == "creative_studio":
    render_creative_studio()
elif st.session_state.page == "analytics_ledger":
    render_analytics_ledger()
else:
    st.session_state.page = "command_center"
    safe_rerun()
