"""Rishi-OS Control Room — Executive SaaS Dashboard (Design 4)

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

import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# CRITICAL: Load .env FIRST, before ANY core imports, to avoid getaddrinfo errors
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env", override=True)

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
    page_title="Rishi-OS",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sanitize Supabase credentials (strip quotes/newlines) — Bug A fix
# ---------------------------------------------------------------------------
_SUPABASE_URL = (os.getenv("SUPABASE_URL", "") or "").strip().strip('"').strip("'")
_SUPABASE_KEY = (os.getenv("SUPABASE_KEY", "") or "").strip().strip('"').strip("'")

# Monkey-patch config so core.db uses sanitized values
config.SUPABASE_URL = _SUPABASE_URL
config.SUPABASE_KEY = _SUPABASE_KEY

# ---------------------------------------------------------------------------
# Default Agent Fleet (7 built-in agents) — Fallback for empty DB — Bug A fix
# ---------------------------------------------------------------------------
DEFAULT_AGENTS = [
    {"name": "research_agent", "purpose": "Find fresh, deduped signal on a topic", "enabled": False, "daily_cap": 1, "schedule": "daily"},
    {"name": "growth_coach_agent", "purpose": "Personal progress and habit coaching", "enabled": False, "daily_cap": 1, "schedule": "daily"},
    {"name": "summarize_librarian", "purpose": "Compress long-form input into a library entry", "enabled": False, "daily_cap": 6, "schedule": "every-20-min"},
    {"name": "idea_strategist", "purpose": "Turn signal into ranked content angles", "enabled": False, "daily_cap": 1, "schedule": "daily"},
    {"name": "packaging_studio", "purpose": "Draft platform-ready posts from one angle", "enabled": False, "daily_cap": 1, "schedule": "daily"},
    {"name": "analytics_auditor", "purpose": "Read metrics, report what worked", "enabled": False, "daily_cap": 1, "schedule": "weekly"},
    {"name": "ceo_supervisor", "purpose": "Daily cross-agent review and prioritisation", "enabled": False, "daily_cap": 1, "schedule": "daily"},
]

DEFAULT_BRANDS = ["edivic", "nowrides", "velvet", "personal"]

# ---------------------------------------------------------------------------
# Design 4 — Premium CSS (Light-meets-Dark Executive)
# ---------------------------------------------------------------------------
_CSS = """
<style>
:root {
  --bg-warm: #F7F5F0;
  --bg-alabaster: #FAF9F6;
  --panel-dark: #18181B;
  --panel-navy: #1E2229;
  --forest: #242B1E;
  --sage: #586450;
  --ochre: #D4AF37;
  --ochre-dim: #B8952E;
  --ink: #1F1A17;
  --muted: #6B645C;
  --line: #E6E1D6;
  --white: #FAF9F6;
  --card-shadow: 0 2px 12px rgba(24, 24, 27, 0.06);
  --card-shadow-hover: 0 8px 28px rgba(24, 24, 27, 0.10);
}

/* Global background */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-warm) !important;
  color: var(--ink) !important;
  font-family: "Georgia", "Iowan Old Style", "Apple Garamond", serif !important;
}

[data-testid="stMainBlockContainer"] {
  background: var(--bg-alabaster) !important;
  padding-top: 1.25rem !important;
  max-width: 1520px !important;
}

/* Sidebar — Dark Charcoal */
[data-testid="stSidebar"] {
  background: var(--panel-dark) !important;
  border-right: 1px solid #2A2A2E !important;
  width: 280px !important;
  min-width: 280px !important;
}

[data-testid="stSidebar"] * {
  color: var(--white) !important;
  font-family: "Inter", "Helvetica Neue", sans-serif !important;
}

[data-testid="stSidebar"] .stButton > button {
  background: transparent !important;
  border: 1px solid #333338 !important;
  color: var(--white) !important;
  border-radius: 10px !important;
  padding: 0.65rem 1rem !important;
  width: 100% !important;
  text-align: left !important;
  font-size: 0.85rem !important;
  font-weight: 600 !important;
  transition: all 0.25s ease !important;
  margin-bottom: 0.35rem !important;
}

[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--ochre) !important;
  border-color: var(--ochre) !important;
  color: #18181B !important;
  transform: translateX(4px) !important;
  box-shadow: 0 4px 16px rgba(212, 175, 55, 0.25) !important;
}

[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: var(--ochre) !important;
  border-color: var(--ochre) !important;
  color: #18181B !important;
}

[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
  background: var(--ochre-dim) !important;
  border-color: var(--ochre-dim) !important;
}

/* Main canvas typography */
h1, h2, h3, h4 {
  font-family: "Georgia", "Iowan Old Style", serif !important;
  color: var(--ink) !important;
  letter-spacing: -0.02em !important;
}
h1 { font-size: 2rem !important; border-bottom: 2px solid var(--ochre) !important; padding-bottom: 0.5rem !important; margin-bottom: 1.25rem !important; }
h2 { font-size: 1.35rem !important; color: var(--panel-dark) !important; margin-top: 1.75rem !important; margin-bottom: 0.75rem !important; }
h3 { font-size: 1.1rem !important; color: var(--panel-dark) !important; margin-bottom: 0.5rem !important; }

/* Native Streamlit containers as cards */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  padding: 1.25rem !important;
  box-shadow: var(--card-shadow) !important;
  transition: all 0.3s ease !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:hover {
  box-shadow: var(--card-shadow-hover) !important;
  transform: translateY(-2px) !important;
}

/* KPI Cards — Dark Charcoal with Gold/Ivory */
.kpi-card {
  background: #18181B !important;
  border: 1px solid #2A2A2E !important;
  border-radius: 14px !important;
  padding: 1.1rem 1.25rem !important;
  text-align: center !important;
  color: var(--white) !important;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35) !important;
  transition: all 0.3s ease !important;
}
.kpi-card:hover { border-color: var(--ochre) !important; transform: translateY(-2px) !important; }
.kpi-card .value { font-size: 1.85rem !important; font-weight: 700 !important; color: var(--white) !important; display: block !important; margin-bottom: 0.25rem !important; line-height: 1.1 !important; }
.kpi-card .label { font-size: 0.7rem !important; text-transform: uppercase !important; letter-spacing: 0.08em !important; color: #A8A296 !important; display: block !important; }
.kpi-card .sub { font-size: 0.75rem !important; color: var(--ochre) !important; font-weight: 600 !important; display: block !important; margin-top: 0.35rem !important; }

/* Status badges */
.tag {
  display: inline-block !important;
  padding: 0.15rem 0.55rem !important;
  border-radius: 6px !important;
  font-size: 0.68rem !important;
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
.tag-armed { background: #E8F5E9 !important; color: var(--forest) !important; border: 1px solid #C8E6C9 !important; }
.tag-standby { background: #F3EFE6 !important; color: var(--muted) !important; border: 1px solid #D9D0C0 !important; }
.tag-queued { background: #FFF8E1 !important; color: #B88A1A !important; border: 1px solid #E8D49A !important; }
.tag-done { background: #EAF3EC !important; color: var(--forest) !important; border: 1px solid #C9D6C2 !important; }

/* Buttons */
.stButton > button, .stFormSubmitButton > button {
  border-radius: 10px !important;
  font-weight: 600 !important;
  transition: all 0.25s ease !important;
  border: 1px solid var(--line) !important;
  background: #FFFFFF !important;
  color: var(--ink) !important;
  padding: 0.55rem 1.2rem !important;
  font-family: "Inter", sans-serif !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: var(--ochre) !important;
  color: #1F1A17 !important;
  background: #FFF9F0 !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: #18181B !important;
  border-color: #18181B !important;
  color: var(--white) !important;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
  background: var(--ochre) !important;
  border-color: var(--ochre) !important;
  color: #18181B !important;
}

/* Inputs */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  color: var(--ink) !important;
}

/* Dataframes */
[data-testid="stDataFrame"] {
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  overflow: hidden !important;
}

/* Dark card self-contained HTML */
.dark-card {
  background: #18181B !important;
  border: 1px solid #2A2A2E !important;
  border-radius: 14px !important;
  padding: 1.25rem !important;
  color: var(--white) !important;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35) !important;
}
.dark-card h3, .dark-card h4 { color: var(--ochre) !important; margin-top: 0 !important; margin-bottom: 0.5rem !important; }
.dark-card .muted { color: #A8A296 !important; font-size: 0.85rem !important; }
.dark-card .accent { color: var(--ochre) !important; font-weight: 600 !important; }

/* Output cards */
.output-card {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  padding: 1.25rem !important;
  margin-bottom: 1rem !important;
  transition: all 0.3s ease !important;
}
.output-card:hover { border-color: var(--ochre) !important; box-shadow: var(--card-shadow-hover) !important; }

/* Meta row */
.meta-row {
  font-size: 0.7rem !important;
  color: var(--muted) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  margin-bottom: 0.6rem !important;
  border-bottom: 1px solid #EFE9DE !important;
  padding-bottom: 0.5rem !important;
}

/* Log lines */
.log-line { font-family: "Menlo", "Monaco", monospace !important; font-size: 0.75rem !important; padding: 0.25rem 0.5rem !important; border-bottom: 1px solid #2A2A2E !important; color: #D8CFC0 !important; }
.log-line.ok { color: var(--forest) !important; }
.log-line.err { color: #C99A7A !important; }
.log-line.inf { color: var(--sage) !important; }

/* Connection pill */
.conn-pill {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.35rem 0.85rem; border-radius: 999px;
  font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
}
.conn-ok { background: #E8F5E9; color: var(--forest); border: 1px solid #C8E6C9; }
.conn-warn { background: #FFF8E1; color: #B88A1A; border: 1px solid #E8D49A; }

/* Progress bar */
.stProgress > div > div > div { background: var(--ochre) !important; }

/* Page fade */
.page-fade { animation: fadeIn 0.4s ease forwards !important; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
</style>
"""

# ---------------------------------------------------------------------------
# Imports needed for sanitization and env loading
# ---------------------------------------------------------------------------
import os

st.markdown(_CSS, unsafe_allow_html=True)


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


def upsert_agent(name: str, enabled: bool, daily_cap: int) -> None:
    db.client().table("agents").upsert(
        {"name": name, "enabled": enabled, "daily_cap": int(daily_cap)},
        on_conflict="name",
    ).execute()


def upsert_brand(key: str, name: str, voice: str, audience: str, platforms: str, always: str, never: str) -> None:
    db.client().table("brands").upsert(
        {"key": key, "name": name, "voice": voice, "audience": audience, "platforms": platforms, "always": always, "never": never},
        on_conflict="key",
    ).execute()


def upsert_note(body: str, brand: str | None, kind: str) -> dict | None:
    return db.save_note(body=body.strip(), brand=brand, kind=kind)


def upsert_task(agent: str, payload: dict, status: str = "queued") -> dict | None:
    return db.save_task(agent=agent, payload=payload, status=status)


def tag_html(status: str) -> str:
    cls = f"tag-{status}" if status in (
        "draft", "needs_review", "approved", "rejected", "failed", "skipped", "armed", "standby", "queued", "done"
    ) else "tag-draft"
    label = status.replace("_", " ").title()
    return f'<span class="tag {cls}">{label}</span>'


def safe_rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def fetch_agents_with_fallback() -> list[dict]:
    """Fetch agents from DB; if empty, return DEFAULT_AGENTS with a flag."""
    agents = guard(db.list_agents, "Loading agents") or []
    if agents:
        return agents
    # Fallback: return defaults with a flag so UI can show seed button
    for a in DEFAULT_AGENTS:
        a["_fallback"] = True
    return DEFAULT_AGENTS


def fetch_brands_with_fallback() -> list[dict]:
    brands = guard(db.list_brands, "Loading brands") or []
    if brands:
        return brands
    return [{"key": k, "name": k.title(), "_fallback": True} for k in DEFAULT_BRANDS]


# ---------------------------------------------------------------------------
# Page navigation state
# ---------------------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "command_center"

PAGES = [
    ("command_center", "🎯 Command Center"),
    ("review_inbox", "📥 Review Inbox"),
    ("creative_studio", "📝 Studio & Notes"),
    ("analytics_ledger", "📈 Analytics & Ledger"),
]


# ===========================================================================
# SIDEBAR — Dark Charcoal with Gold Accent
# ===========================================================================
with st.sidebar:
    # Brand header
    st.markdown(
        '<div style="padding:1.5rem 1rem 0.5rem 1rem;">'
        '<div style="font-size:1.8rem;margin-bottom:0.25rem;">⚡</div>'
        '<div style="font-weight:700;font-size:1rem;letter-spacing:0.08em;text-transform:uppercase;">RISHI-OS</div>'
        '<div style="font-size:0.65rem;color:#A8A296;margin-top:0.15rem;">EXECUTIVE CONSOLE</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    # Connection status pill
    supabase_ok = bool(_SUPABASE_URL and _SUPABASE_KEY and not _SUPABASE_URL.startswith("https://your-project"))
    conn_class = "conn-ok" if supabase_ok else "conn-warn"
    conn_label = "SUPABASE CONNECTED" if supabase_ok else "SUPABASE OFFLINE — CHECK .ENV"
    st.markdown(f'<div class="conn-pill {conn_class}">● {conn_label}</div>', unsafe_allow_html=True)
    st.divider()

    # Navigation
    for key, label in PAGES:
        active = st.session_state.page == key
        btn_kind = "primary" if active else "secondary"
        if st.button(label, key=f"nav_{key}", use_container_width=True, type=btn_kind):
            st.session_state.page = key
            safe_rerun()

    st.divider()

    # Global quick-action: Run Queued Tasks
    tasks = guard(
        lambda: db.client().table("tasks")
        .select("id")
        .eq("status", "queued")
        .limit(1)
        .execute()
        .data,
        "Checking queue",
    ) or []
    queued_count = len(guard(
        lambda: db.client().table("tasks")
        .select("id")
        .eq("status", "queued")
        .execute()
        .data, "Counting queue") or [])

    if st.button(f"▶️ Run Queued Tasks ({queued_count})", key="sidebar_run_all", use_container_width=True, type="primary", disabled=queued_count == 0):
        with st.status("Running queue-drainer…", expanded=True) as status:
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "scripts.run_queued_tasks"],
                    cwd=str(ROOT_DIR),
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if proc.stdout:
                    for line in proc.stdout.splitlines():
                        st.markdown(f'<div class="log-line {"ok" if "ok" in line.lower() else "inf"}">{line}</div>', unsafe_allow_html=True)
                if proc.stderr:
                    for line in proc.stderr.splitlines():
                        st.markdown(f'<div class="log-line err">{line}</div>', unsafe_allow_html=True)
                status.update(label="Queue drained.", state="complete")
            except subprocess.TimeoutExpired:
                status.update(label="Runner timed out (180s).", state="error")
            except Exception as exc:  # noqa: BLE001
                status.update(label=f"Runner error: {exc}", state="error")
        safe_rerun()

    st.divider()
    st.caption("Zero AI. Zero agent execution.")

    # Providers status
    providers = config.available_providers()
    ready_count = len(providers)
    total_count = len(config.PROVIDERS)
    st.markdown(
        f'<div class="dark-card" style="margin-top:0.5rem;">'
        f'<div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.08em;color:#A8A296;margin-bottom:0.5rem;">Providers</div>'
        f'<div style="font-size:0.85rem;font-weight:600;">{ready_count} / {total_count} reachable</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sign out", key="nav_signout", use_container_width=True):
        st.session_state["authed"] = False
        safe_rerun()


# ===========================================================================
# AUTH GATE — Unified Login Card inside centered column (Bug B fix)
# ===========================================================================
def require_password() -> None:
    if st.session_state.get("authed"):
        return

    # Centered column for the login card
    _, col, _ = st.columns([1, 1.3, 1])
    with col:
        with st.container(border=True):
            st.markdown(
                '<div style="text-align:center;padding:1rem 0.5rem 0.5rem 0.5rem;">'
                '<div style="font-size:2.5rem;margin-bottom:0.5rem;">⚡</div>'
                '<h1 style="margin:0 0 0.25rem 0;font-size:1.5rem;color:#FAF9F6;">Rishi-OS</h1>'
                '<p style="color:#B8B0A4;margin:0 0 1.5rem 0;font-size:0.9rem;">Executive Console</p>'
                '</div>',
                unsafe_allow_html=True,
            )

            if not config.DASHBOARD_PASSWORD:
                st.error("DASHBOARD_PASSWORD is not set. Add it to `.env` before using the Control Room.")
                st.stop()

            with st.form("login"):
                supplied = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="••••••••")
                submitted = st.form_submit_button("Unlock", use_container_width=True, type="primary")

            if submitted:
                if supplied == config.DASHBOARD_PASSWORD:
                    st.session_state["authed"] = True
                    safe_rerun()
                else:
                    st.error("Incorrect password.")
    st.stop()


require_password()


# ===========================================================================
# PAGE 1 — COMMAND CENTER
# ===========================================================================
def render_command_center() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Command Center")
    st.caption("Dispatch, monitor, and run the agent fleet from one console.")

    # ---- Data fetch ----
    agents = fetch_agents_with_fallback()
    outputs = guard(lambda: db.recent_outputs(limit=200), "Loading outputs") or []
    tasks_q = guard(
        lambda: db.client().table("tasks")
        .select("*")
        .eq("status", "queued")
        .order("created_at")
        .limit(50)
        .execute()
        .data,
        "Loading queue",
    ) or []

    # ---- KPI Row (4 Dark Charcoal Cards) ----
    enabled_count = sum(1 for a in agents if a.get("enabled"))
    total_agents = len([a for a in agents if not a.get("_fallback")])
    if total_agents == 0:
        total_agents = len(agents)
    queued_count = len(tasks_q)
    review_count = sum(1 for o in outputs if o.get("status") in ("draft", "needs_review"))
    daily_cap_total = sum(int(a.get("daily_cap") or 0) for a in agents)
    daily_used_total = sum(int(a.get("runs_today") or 0) for a in agents)
    cap_pct = int((daily_used_total / daily_cap_total) * 100) if daily_cap_total else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{enabled_count}/{total_agents}</span>'
            f'<span class="label">Active Agents</span>'
            f'<span class="sub">{enabled_count} enabled</span></div>',
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{queued_count}</span>'
            f'<span class="label">Queued Tasks</span>'
            f'<span class="sub">Waiting for runner</span></div>',
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{review_count}</span>'
            f'<span class="label">Review Drafts</span>'
            f'<span class="sub">Awaiting action</span></div>',
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{cap_pct}%</span>'
            f'<span class="label">Daily Run Cap</span>'
            f'<span class="sub">{daily_used_total} / {daily_cap_total} used</span></div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ---- Seed Default Fleet button if DB empty ----
    if any(a.get("_fallback") for a in agents):
        st.markdown(
            '<div class="dark-card" style="margin-bottom:1rem;">'
            '<h3>⚠️ Agent Fleet Not Seeded</h3>'
            '<p class="muted">No agents found in database. Click below to seed the default 7-agent fleet.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("⚡ Seed Default Agent Fleet", key="cmd_seed_fleet", type="primary", use_container_width=True):
            for a in DEFAULT_AGENTS:
                upsert_agent(a["name"], a["enabled"], a["daily_cap"])
            st.toast("Default agent fleet seeded.")
            safe_rerun()

    # ---- Split View: Left (Live Agent Fleet) | Right (Task Builder & Live Queue) ----
    left, right = st.columns([1, 1.25], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("### Live Agent Fleet")
            st.caption("Toggle caps and enablement. Changes apply to the next cron tick.")
            if not agents:
                st.info("No agents registered.")
            else:
                for agent in agents:
                    name = agent.get("name", "?")
                    enabled = bool(agent.get("enabled"))
                    cap = int(agent.get("daily_cap") or 1)
                    used = int(agent.get("runs_today") or 0)
                    schedule = agent.get("schedule") or "unspecified"
                    is_fallback = agent.get("_fallback", False)

                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(f"**{name}**")
                            st.caption(f"Schedule: {schedule} · Runs: {used} / {cap}")
                        with c2:
                            st.markdown(tag_html("armed" if enabled else "standby"), unsafe_allow_html=True)

                        new_enabled = st.checkbox(
                            "Enabled", value=enabled, key=f"cmd_en_{name}", label_visibility="collapsed"
                        )
                        new_cap = st.number_input(
                            "Daily cap", min_value=0, max_value=48, value=cap,
                            key=f"cmd_cap_{name}", label_visibility="collapsed"
                        )
                        if st.button("💾 Save", key=f"cmd_save_{name}", use_container_width=True):
                            upsert_agent(name, new_enabled, int(new_cap))
                            st.toast(f"Saved {name}.")
                            safe_rerun()
                        if is_fallback:
                            st.caption("⚠️ Fallback agent (not in DB)")

    with right:
        with st.container(border=True):
            st.markdown("### Task Builder")
            st.caption("Queue a natural-language instruction for any agent. Brand links the task to a voice profile.")

            brands = fetch_brands_with_fallback()
            brand_keys = [b.get("key") for b in brands if b.get("key")]
            agent_names = [a.get("name") for a in agents if a.get("name")]

            with st.form("cmd_task_form"):
                c_brand, c_agent = st.columns(2)
                with c_brand:
                    target_brand = st.selectbox("Brand", brand_keys or ["(none)"], key="cmd_brand")
                with c_agent:
                    target_agent = st.selectbox("Agent", agent_names or ["research_agent"], key="cmd_agent")
                instructions = st.text_area(
                    "Instructions / Topic",
                    height=120,
                    key="cmd_instructions",
                    placeholder="e.g. Research zero-budget growth tactics for early-stage SaaS",
                )
                b1, b2 = st.columns(2)
                with b1:
                    queued = st.form_submit_button("⚡ Queue Task", use_container_width=True, type="primary")
                with b2:
                    run_now = st.form_submit_button("🚀 Queue & Run Now", use_container_width=True, type="secondary")

            if queued or run_now:
                payload = {}
                if instructions.strip():
                    payload["text"] = instructions.strip()
                if target_brand and target_brand != "(none)":
                    payload["brand"] = target_brand
                if not payload:
                    st.warning("Provide at least the instructions.")
                else:
                    saved = guard(
                        lambda: upsert_task(target_agent, payload, "queued"),
                        "Queueing task",
                    )
                    if saved:
                        st.toast(f"Task queued for {target_agent}.")
                        if run_now:
                            with st.status("Executing agent pipeline…", expanded=True) as status:
                                try:
                                    proc = subprocess.run(
                                        [sys.executable, "-m", "scripts.run_queued_tasks"],
                                        cwd=str(ROOT_DIR),
                                        capture_output=True,
                                        text=True,
                                        timeout=180,
                                    )
                                    if proc.stdout:
                                        for line in proc.stdout.splitlines():
                                            st.markdown(f'<div class="log-line {"ok" if "ok" in line.lower() else "inf"}">{line}</div>', unsafe_allow_html=True)
                                    if proc.stderr:
                                        for line in proc.stderr.splitlines():
                                            st.markdown(f'<div class="log-line err">{line}</div>', unsafe_allow_html=True)
                                    status.update(label="Done.", state="complete")
                                except subprocess.TimeoutExpired:
                                    status.update(label="Timed out (180s).", state="error")
                                except Exception as exc:  # noqa: BLE001
                                    status.update(label=f"Error: {exc}", state="error")
                        safe_rerun()

        st.divider()

        # ---- Recent Task Queue ----
        with st.container(border=True):
            st.markdown("### Recent Task Queue")
            if not tasks_q:
                st.info("Queue is empty.")
            else:
                for task in tasks_q[:10]:
                    t_id = task.get("id", "?")[:8]
                    t_agent = task.get("agent", "?")
                    t_status = task.get("status", "?")
                    t_payload = task.get("payload", {})
                    t_topic = (t_payload.get("text") or t_payload.get("topic") or "")[:80]
                    t_brand = t_payload.get("brand", "—")
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 1, 2])
                        with c1:
                            st.markdown(f"**{t_agent}** `{t_id}`")
                            st.caption(f"Brand: {t_brand} · {t_topic}")
                        with c2:
                            st.markdown(tag_html(t_status), unsafe_allow_html=True)
                        with c3:
                            if st.button("🗑️ Remove", key=f"task_del_{t_id}", use_container_width=True):
                                db.client().table("tasks").delete().eq("id", task["id"]).execute()
                                st.toast("Task removed.")
                                safe_rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 2 — REVIEW INBOX
# ===========================================================================
def render_review_inbox() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Review Inbox")
    st.caption("Curated deliverables vault — approve, edit, or reject agent output.")

    # ---- Filters ----
    brands = fetch_brands_with_fallback()
    brand_keys = ["(all brands)"] + [b.get("key") for b in brands if b.get("key")]
    statuses = ["all", "needs_review", "draft", "approved", "rejected", "failed", "skipped"]

    f1, f2, f3 = st.columns([1.2, 1.2, 1])
    with f1:
        filter_brand = st.selectbox("Brand", brand_keys, key="rib_brand")
    with f2:
        filter_status = st.selectbox("Status", statuses, index=0, key="rib_status")
    with f3:
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

    st.markdown(f'<div class="meta-row">{len(rows)} deliverable(s) · filter: {filter_brand} / {filter_status}</div>', unsafe_allow_html=True)

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

        with st.container(border=True):
            st.markdown(
                f'<div class="meta-row">'
                f'{tag_html(status)} '
                f'<span style="font-weight:600;">{agent}</span> '
                f'<span style="font-weight:400;opacity:0.7;">· {brand}</span>'
                f'<span style="float:right;">{model} · {provider}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(clean_text, unsafe_allow_html=False)

            if source_url:
                st.caption(f"Source: {source_url}")

            b1, b2, b3, b4 = st.columns(4)
            with b1:
                if status != "approved":
                    if st.button("🏆 Approve", key=f"rib_ap_{oid}", use_container_width=True, type="primary"):
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
            with b4:
                # Send to next agent
                if st.button("➡️ Next Agent", key=f"rib_next_{oid}", use_container_width=True):
                    next_agent = "idea_strategist" if agent == "research_agent" else "packaging_studio"
                    upsert_task(next_agent, {"source_output": oid, "brand": brand, "topic": clean_text[:200]}, "queued")
                    st.toast(f"Sent to {next_agent}.")
                    safe_rerun()

            with st.expander("Edit clean text / View raw", expanded=False):
                edited = st.text_area("Clean text", value=clean_text, height=180, key=f"rib_edit_{oid}")
                if st.button("💾 Save edit", key=f"rib_sv_{oid}", use_container_width=True):
                    update_output_text(oid, edited)
                    st.toast("Edit saved.")
                    safe_rerun()
                st.code(raw_text or "", language="markdown")

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 3 — STUDIO & NOTES
# ===========================================================================
def render_creative_studio() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Studio & Notes")
    st.caption("Brand voice directory and the executive note vault.")

    brands = fetch_brands_with_fallback()
    brand_keys = [b.get("key") for b in brands if b.get("key")]

    tab_brands, tab_notes = st.tabs(["🎨 Brand Voice Studio", "📓 Executive Notes"])

    with tab_brands:
        st.markdown("### Brand Voice Studio")
        st.caption("View and edit platform profiles. Changes affect all agent output.")

        if not brands:
            st.info("No brands registered.")
        else:
            for brand in brands:
                bkey = brand.get("key", "?")
                is_fallback = brand.get("_fallback", False)
                with st.container(border=True):
                    st.markdown(f"**{brand.get('name', bkey)}** `({bkey})`" + (" · *fallback*" if is_fallback else ""))
                    with st.form(f"brand_form_{bkey}"):
                        name = st.text_input("Name", value=brand.get("name") or "", key=f"brand_name_{bkey}")
                        voice = st.text_area("Voice", value=brand.get("voice") or "", height=80, key=f"brand_voice_{bkey}")
                        audience = st.text_area("Audience", value=brand.get("audience") or "", height=80, key=f"brand_aud_{bkey}")
                        platforms = st.text_input("Platforms", value=brand.get("platforms") or "", key=f"brand_plt_{bkey}")
                        always = st.text_area("Always", value=brand.get("always") or "", height=70, key=f"brand_alw_{bkey}")
                        never = st.text_area("Never", value=brand.get("never") or "", height=70, key=f"brand_nev_{bkey}")
                        if st.form_submit_button("💾 Save Brand", use_container_width=True, type="primary"):
                            upsert_brand(bkey, name, voice, audience, platforms, always, never)
                            st.toast(f"Brand {bkey} saved.")
                            safe_rerun()

        # Add new brand
        st.divider()
        st.markdown("#### Add New Brand")
        with st.form("brand_new"):
            n_key = st.text_input("Key (slug)", key="brand_new_key", placeholder="my_brand")
            n_name = st.text_input("Name", key="brand_new_name", placeholder="My Brand")
            n_voice = st.text_area("Voice", height=70, key="brand_new_voice")
            n_audience = st.text_area("Audience", height=70, key="brand_new_aud")
            n_platforms = st.text_input("Platforms", key="brand_new_plt")
            n_always = st.text_area("Always", height=60, key="brand_new_alw")
            n_never = st.text_area("Never", height=60, key="brand_new_nev")
            if st.form_submit_button("➕ Create Brand", use_container_width=True, type="primary"):
                if n_key and n_name:
                    upsert_brand(n_key, n_name, n_voice, n_audience, n_platforms, n_always, n_never)
                    st.toast(f"Brand {n_key} created.")
                    safe_rerun()
                else:
                    st.warning("Key and Name are required.")

    with tab_notes:
        st.markdown("### Executive Notes & Brain Dump")
        st.caption("Save thoughts, ideas, strategies, and prompt drafts linked to brands.")

        with st.form("note_form"):
            n_brand = st.selectbox("Link to brand", ["(none)"] + brand_keys, key="note_brand")
            n_kind = st.selectbox("Kind", ["idea", "todo", "strategy", "prompt"], key="note_kind")
            n_body = st.text_area("Note", height=160, key="note_body", placeholder="Capture a thought, idea, or strategy draft…")
            n_submit = st.form_submit_button("✨ Save Note", use_container_width=True, type="primary")

        if n_submit:
            if not n_body.strip():
                st.warning("Write something before saving.")
            else:
                saved = upsert_note(n_body.strip(), None if n_brand == "(none)" else n_brand, n_kind)
                if saved:
                    st.toast("Note saved.")
                    safe_rerun()

        st.divider()
        st.markdown("#### Recent Notes")
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
                with st.container(border=True):
                    st.markdown(
                        f'<div class="meta-row">'
                        f'<span class="tag tag-{n_kind_val}">{n_kind_val.title()}</span> '
                        f'<span style="font-weight:600;">{n_brand_val}</span> '
                        f'<span style="opacity:0.6;">{n_time[:16]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(n_body_text)
                    if st.button("🗑️ Delete", key=f"note_del_{n_id}", use_container_width=True):
                        db.client().table("notes").delete().eq("id", n_id).execute()
                        st.toast("Note deleted.")
                        safe_rerun()

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

    # ---- KPI Strip ----
    total_calls = sum(int(u.get("calls") or 0) for u in usage)
    total_chars_in = sum(int(u.get("chars_in") or 0) for u in usage)
    total_chars_out = sum(int(u.get("chars_out") or 0) for u in usage)
    total_logs = len(logs)
    failed_logs = sum(1 for l in logs if l.get("status") == "failed")

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f'<div class="kpi-card"><span class="value">{total_calls}</span><span class="label">Model Calls</span></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="kpi-card"><span class="value">{total_chars_in:,}</span><span class="label">Chars In</span></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="kpi-card"><span class="value">{total_chars_out:,}</span><span class="label">Chars Out</span></div>', unsafe_allow_html=True)
    with k4:
        st.markdown(f'<div class="kpi-card"><span class="value">{total_logs}</span><span class="label">Log Entries</span></div>', unsafe_allow_html=True)
    with k5:
        st.markdown(f'<div class="kpi-card"><span class="value">{failed_logs}</span><span class="label">Failed Runs</span></div>', unsafe_allow_html=True)

    st.divider()

    # ---- Charts ----
    if usage:
        usage_df = pd.DataFrame(usage)
        usage_df["provider"] = usage_df["provider"].fillna("unknown")
        provider_counts = usage_df.groupby("provider").size().reset_index(name="runs")
        provider_calls = usage_df.groupby("provider")["calls"].sum().reset_index(name="total_calls")

        c_left, c_right = st.columns(2)
        with c_left:
            with st.container(border=True):
                st.markdown("### Calls by Provider")
                st.bar_chart(provider_counts, x="provider", y="runs", use_container_width=True)
        with c_right:
            with st.container(border=True):
                st.markdown("### Total Calls by Provider")
                st.bar_chart(provider_calls, x="provider", y="total_calls", use_container_width=True)
    else:
        with st.container(border=True):
            st.info("No usage recorded yet.")

    st.divider()

    # ---- Split: Execution Stream + Usage Ledger ----
    l_col, r_col = st.columns([1.1, 1], gap="large")

    with l_col:
        with st.container(border=True):
            st.markdown("### Execution Stream")
            st.caption("Real-time backend agent telemetry (logs ordered by `time` DESC).")
            if not logs:
                st.info("No log entries yet.")
            else:
                for log in logs[:50]:
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

    with r_col:
        with st.container(border=True):
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