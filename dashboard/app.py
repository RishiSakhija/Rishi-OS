"""Rishi-OS Control Room — Executive SaaS Dashboard

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

import json
import os
import subprocess
import sys
from datetime import datetime
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
# Sanitize Supabase credentials (strip whitespace/quotes) — Bug A fix
# ---------------------------------------------------------------------------
_SUPABASE_URL = (os.getenv("SUPABASE_URL", "") or "").strip().strip('"').strip("'")
_SUPABASE_KEY = (os.getenv("SUPABASE_KEY", "") or "").strip().strip('"').strip("'")

# Monkey-patch config so core.db uses sanitized values
config.SUPABASE_URL = _SUPABASE_URL
config.SUPABASE_KEY = _SUPABASE_KEY

# ---------------------------------------------------------------------------
# Local Runtime State Mirror (dashboard/.runtime_state.json)
# Provides seamless offline/fallback with ZERO error banners
# ---------------------------------------------------------------------------
_RUNTIME_STATE_PATH = ROOT_DIR / "dashboard" / ".runtime_state.json"

def _load_local_state() -> dict:
    """Load local JSON mirror. Returns empty structure if missing/corrupt."""
    try:
        if _RUNTIME_STATE_PATH.exists():
            return json.loads(_RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "agents": [],
        "brands": [],
        "outputs": [],
        "tasks": [],
        "notes": [],
        "logs": [],
        "usage": [],
        "last_sync": None,
    }

def _save_local_state(state: dict) -> None:
    """Persist local mirror atomically."""
    try:
        state["last_sync"] = datetime.utcnow().isoformat()
        tmp = _RUNTIME_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(_RUNTIME_STATE_PATH)
    except Exception:
        pass

def _merge_remote_into_local(remote_data: list, local_list: list, key: str = "id") -> list:
    """Merge remote data into local list, preferring remote for matching keys."""
    if not remote_data:
        return local_list
    remote_map = {item.get(key): item for item in remote_data if item.get(key)}
    merged = {item.get(key): item for item in local_list if item.get(key)}
    merged.update(remote_map)
    return list(merged.values())

# Initialize local state in session_state
if "local_state" not in st.session_state:
    st.session_state.local_state = _load_local_state()

# ---------------------------------------------------------------------------
# Default Agent Fleet (7 built-in agents) — Always available, never empty
# ---------------------------------------------------------------------------
DEFAULT_AGENTS = [
    {"name": "research_agent", "purpose": "Find fresh, deduped signal on a topic", "enabled": False, "daily_cap": 1, "schedule": "daily", "runs_today": 0},
    {"name": "growth_coach_agent", "purpose": "Personal progress and habit coaching", "enabled": False, "daily_cap": 1, "schedule": "daily", "runs_today": 0},
    {"name": "summarize_librarian", "purpose": "Compress long-form input into a library entry", "enabled": False, "daily_cap": 6, "schedule": "every-20-min", "runs_today": 0},
    {"name": "idea_strategist", "purpose": "Turn signal into ranked content angles", "enabled": False, "daily_cap": 1, "schedule": "daily", "runs_today": 0},
    {"name": "packaging_studio", "purpose": "Draft platform-ready posts from one angle", "enabled": False, "daily_cap": 1, "schedule": "daily", "runs_today": 0},
    {"name": "analytics_auditor", "purpose": "Read metrics, report what worked", "enabled": False, "daily_cap": 1, "schedule": "weekly", "runs_today": 0},
    {"name": "ceo_supervisor", "purpose": "Daily cross-agent review and prioritisation", "enabled": False, "daily_cap": 1, "schedule": "daily", "runs_today": 0},
]

DEFAULT_BRANDS = [
    {"key": "edivic", "name": "EDIVIC", "voice": "direct and technical; explains the mechanism, not the hype", "audience": "technical founders and operators evaluating AI tooling", "platforms": "linkedin, x, newsletter", "always": "concrete numbers, working examples, plain language", "never": "buzzwords, unsupported claims, engagement bait"},
    {"key": "nowrides", "name": "NowRides", "voice": "warm and practical; speaks to operators, not investors", "audience": "mobility operators and small fleet owners", "platforms": "linkedin, x, newsletter", "always": "real operational detail, cost per unit, plain language", "never": "hype, vanity metrics, jargon"},
    {"key": "velvet", "name": "Velvet", "voice": "elegant and understated; luxury without pretension", "audience": "premium lifestyle audience", "platforms": "linkedin, instagram, newsletter", "always": "refined tone, quality signals, restraint", "never": "loud, mass-market, discount language"},
    {"key": "personal", "name": "Rishi (Personal)", "voice": "first-person, honest, builds in public, admits what broke", "audience": "founders and builders following the journey", "platforms": "x, linkedin, newsletter", "always": "specific lessons, real numbers, one clear takeaway", "never": "guru tone, fake certainty, emoji walls"},
]

# ---------------------------------------------------------------------------
# Data Access Layer — Silent Supabase + Local Mirror (ZERO st.error banners)
# ---------------------------------------------------------------------------
def _supabase_available() -> bool:
    """Quick check if Supabase credentials look valid."""
    return bool(_SUPABASE_URL and _SUPABASE_KEY and not _SUPABASE_URL.startswith("https://your-project"))

def safe_select(table: str, *, eq: dict | None = None, order: str | None = None, desc: bool = True, limit: int | None = None) -> list[dict]:
    """Select from Supabase silently; fall back to local mirror on any error."""
    if not _supabase_available():
        return st.session_state.local_state.get(table, [])
    try:
        client = db.client()
        query = client.table(table).select("*")
        if eq:
            for k, v in eq.items():
                query = query.eq(k, v)
        if order:
            query = query.order(order, desc=desc)
        if limit:
            query = query.limit(limit)
        data = query.execute().data or []
        # Sync to local mirror
        state = st.session_state.local_state
        state[table] = _merge_remote_into_local(data, state.get(table, []))
        _save_local_state(state)
        return data
    except Exception:
        return st.session_state.local_state.get(table, [])

def safe_insert(table: str, row: dict) -> dict | None:
    """Insert row to Supabase silently; always write to local mirror."""
    row = dict(row)
    row.setdefault("created_at", datetime.utcnow().isoformat())
    # Always write to local first
    state = st.session_state.local_state
    state.setdefault(table, []).insert(0, row)
    _save_local_state(state)
    if not _supabase_available():
        return row
    try:
        result = db.client().table(table).insert(row).execute()
        if result.data:
            return result.data[0]
    except Exception:
        pass
    return row

def safe_update(table: str, match_col: str, match_val: str, payload: dict) -> bool:
    """Update row in Supabase silently; always update local mirror."""
    state = st.session_state.local_state
    local_list = state.get(table, [])
    for item in local_list:
        if item.get(match_col) == match_val:
            item.update(payload)
            break
    _save_local_state(state)
    if not _supabase_available():
        return True
    try:
        db.client().table(table).update(payload).eq(match_col, match_val).execute()
        return True
    except Exception:
        return True

def safe_upsert(table: str, row: dict, on_conflict: str) -> bool:
    """Upsert row in Supabase silently; always upsert local mirror."""
    state = st.session_state.local_state
    local_list = state.get(table, [])
    conflict_val = row.get(on_conflict)
    found = False
    for i, item in enumerate(local_list):
        if item.get(on_conflict) == conflict_val:
            local_list[i] = {**item, **row}
            found = True
            break
    if not found:
        local_list.insert(0, row)
    _save_local_state(state)
    if not _supabase_available():
        return True
    try:
        db.client().table(table).upsert(row, on_conflict=on_conflict).execute()
        return True
    except Exception:
        return True

def safe_delete(table: str, match_col: str, match_val: str) -> bool:
    """Delete row from Supabase silently; always delete from local mirror."""
    state = st.session_state.local_state
    state[table] = [item for item in state.get(table, []) if item.get(match_col) != match_val]
    _save_local_state(state)
    if not _supabase_available():
        return True
    try:
        db.client().table(table).delete().eq(match_col, match_val).execute()
        return True
    except Exception:
        return True

# Seed local state with defaults if empty
if not st.session_state.local_state.get("agents"):
    for a in DEFAULT_AGENTS:
        a = dict(a)
        a.setdefault("id", f"local-{a['name']}")
        a.setdefault("created_at", datetime.utcnow().isoformat())
    st.session_state.local_state["agents"] = DEFAULT_AGENTS[:]
if not st.session_state.local_state.get("brands"):
    for b in DEFAULT_BRANDS:
        b = dict(b)
        b.setdefault("id", f"local-{b['key']}")
        b.setdefault("created_at", datetime.utcnow().isoformat())
    st.session_state.local_state["brands"] = DEFAULT_BRANDS[:]
_save_local_state(st.session_state.local_state)

# ---------------------------------------------------------------------------
# Design System CSS — Executive SaaS Aesthetic
# ---------------------------------------------------------------------------
_CSS = """
<style>
:root {
  --bg-warm: #F7F4EF;
  --bg-alabaster: #FAF9F6;
  --card-ivory: #FAF9F6;
  --card-border: #E5DFD3;
  --panel-dark: #18181B;
  --panel-navy: #1E2025;
  --ink: #1F1A17;
  --muted: #6B645C;
  --silver: #A1A1AA;
  --ochre: #D4AF37;
  --ochre-dim: #B8952E;
  --emerald: #10B981;
  --emerald-dim: #059669;
  --line: #E5DFD3;
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
  animation: fadeIn 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards !important;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
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
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
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

/* Native Streamlit containers as cards (light) */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  padding: 1.25rem !important;
  box-shadow: var(--card-shadow) !important;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:hover {
  box-shadow: var(--card-shadow-hover) !important;
  transform: translateY(-2px) !important;
}

/* ============================================================
   DARK CARD STYLING FOR AGENT FLEET, LOGIN, KPI, PIPELINE
   Uses :has() to detect marker elements inside containers
============================================================ */

/* Agent Fleet Dark Cards */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) {
  background: #18181B !important;
  border: 1px solid #2A2E37 !important;
  border-radius: 14px !important;
  padding: 18px !important;
  color: #FAF9F6 !important;
  box-shadow: 0 4px 20px rgba(0,0,0,0.35) !important;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker):hover {
  border-color: #D4AF37 !important;
  box-shadow: 0 8px 32px rgba(212, 175, 55, 0.15) !important;
  transform: translateY(-2px) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) * {
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) h3,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) h4,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) strong {
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stMarkdown {
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stCaption {
  color: #A1A1AA !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stTextInput label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stNumberInput label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stToggle label {
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stProgress > div > div > div {
  background: #D4AF37 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="primary"] {
  background: #D4AF37 !important;
  border-color: #D4AF37 !important;
  color: #18181B !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="primary"]:hover {
  background: #B8952E !important;
  border-color: #B8952E !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="secondary"] {
  background: #27272A !important;
  border-color: #3F3F46 !important;
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="secondary"]:hover {
  border-color: #D4AF37 !important;
  color: #18181B !important;
  background: #D4AF37 !important;
}

/* Login Card Dark */
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) {
  background: #18181B !important;
  border: 1px solid #2A2E37 !important;
  border-radius: 16px !important;
  padding: 2rem 1.5rem !important;
  color: #FAF9F6 !important;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) * {
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) h1,
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) h2,
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) h3,
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) h4,
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) p,
[data-testid="stVerticalBlockWrapper"]:has(.login-marker) label {
  color: #FAF9F6 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) .stTextInput > div > div > input {
  background: #27272A !important;
  border: 1px solid #3F3F46 !important;
  color: #FAF9F6 !important;
  border-radius: 10px !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) .stFormSubmitButton > button {
  background: #D4AF37 !important;
  border-color: #D4AF37 !important;
  color: #18181B !important;
  border-radius: 10px !important;
  font-weight: 700 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) .stFormSubmitButton > button:hover {
  background: #B8952E !important;
  border-color: #B8952E !important;
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
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.kpi-card:hover { border-color: var(--ochre) !important; transform: translateY(-2px) !important; }
.kpi-card .value { font-size: 1.85rem !important; font-weight: 700 !important; color: var(--white) !important; display: block !important; margin-bottom: 0.25rem !important; line-height: 1.1 !important; }
.kpi-card .label { font-size: 0.7rem !important; text-transform: uppercase !important; letter-spacing: 0.08em !important; color: #A8A296 !important; display: block !important; }
.kpi-card .sub { font-size: 0.75rem !important; color: var(--ochre) !important; font-weight: 600 !important; display: block !important; margin-top: 0.35rem !important; }

/* Pipeline Stepper */
.pipeline-stepper {
  display: flex !important;
  gap: 0.5rem !important;
  padding: 1rem !important;
  background: #18181B !important;
  border: 1px solid #2A2E37 !important;
  border-radius: 14px !important;
  overflow-x: auto !important;
}
.pipeline-step {
  flex: 1 !important;
  min-width: 120px !important;
  text-align: center !important;
  padding: 0.75rem 0.5rem !important;
  position: relative !important;
}
.pipeline-step:not(:last-child)::after {
  content: "→" !important;
  position: absolute !important;
  right: -0.75rem !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  color: #D4AF37 !important;
  font-weight: 700 !important;
}
.pipeline-dot {
  width: 14px !important; height: 14px !important; border-radius: 50% !important;
  margin: 0 auto 0.5rem !important; border: 2px solid #3F3F46 !important;
  background: #18181B !important; transition: all 0.22s ease !important;
}
.pipeline-step.armed .pipeline-dot { background: #10B981 !important; border-color: #10B981 !important; box-shadow: 0 0 8px #10B981 !important; }
.pipeline-step.queued .pipeline-dot { background: #D4AF37 !important; border-color: #D4AF37 !important; box-shadow: 0 0 8px #D4AF37 !important; }
.pipeline-step.standby .pipeline-dot { background: #18181B !important; border-color: #3F3F46 !important; }
.pipeline-label { font-size: 0.7rem !important; text-transform: uppercase !important; letter-spacing: 0.06em !important; color: #A1A1AA !important; font-weight: 600 !important; }
.pipeline-step.armed .pipeline-label { color: #10B981 !important; }
.pipeline-step.queued .pipeline-label { color: #D4AF37 !important; }

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
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
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
.stSelectbox > div > div,
.stNumberInput > div > div > input {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  color: var(--ink) !important;
}
.stToggle > label { color: var(--ink) !important; }

/* Dataframes */
[data-testid="stDataFrame"] {
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  overflow: hidden !important;
}

/* Dark card self-contained HTML (fallback) */
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

/* Output cards (light) */
.output-card {
  background: #FFFFFF !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  padding: 1.25rem !important;
  margin-bottom: 1rem !important;
  transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
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

/* ============================================================
   SIDEBAR TOGGLE BUTTON — Keep visible (Fix 2)
============================================================ */
header[data-testid="stHeader"] {
  background: transparent !important;
  height: 3.2rem !important;
}
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
button[kind="header"] {
  background: #18181B !important;
  color: #D4AF37 !important;
  border: 1px solid rgba(212,175,55,0.45) !important;
  border-radius: 8px !important;
  padding: 0.35rem 0.6rem !important;
  font-size: 1.1rem !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  opacity: 1 !important;
  visibility: visible !important;
}
[data-testid="stSidebarCollapseButton"]:hover,
[data-testid="collapsedControl"]:hover {
  background: #D4AF37 !important;
  color: #18181B !important;
  border-color: #D4AF37 !important;
}

/* Hide Streamlit chrome (but keep header for sidebar toggle) */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""

# ---------------------------------------------------------------------------
# Imports
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


def set_output_status(output_id: str, status: str) -> None:
    safe_update("outputs", "id", output_id, {"status": status})


def update_output_text(output_id: str, clean: str) -> None:
    safe_update("outputs", "id", output_id, {"clean": clean, "hash": db.content_hash(clean)})


def upsert_agent(name: str, enabled: bool, daily_cap: int) -> None:
    safe_upsert("agents", {"name": name, "enabled": enabled, "daily_cap": int(daily_cap)}, "name")


def upsert_brand(key: str, name: str, voice: str, audience: str, platforms: str, always: str, never: str) -> None:
    safe_upsert("brands", {"key": key, "name": name, "voice": voice, "audience": audience, "platforms": platforms, "always": always, "never": never}, "key")


def upsert_note(body: str, brand: str | None, kind: str) -> dict | None:
    row = {"body": body.strip(), "brand": brand, "kind": kind, "created_at": datetime.utcnow().isoformat()}
    return safe_insert("notes", row)


def upsert_task(agent: str, payload: dict, status: str = "queued") -> dict | None:
    row = {"agent": agent, "payload": payload, "status": status, "created_at": datetime.utcnow().isoformat()}
    return safe_insert("tasks", row)


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


# ---------------------------------------------------------------------------
# Data fetch helpers using safe layer (ZERO st.error)
# ---------------------------------------------------------------------------
def fetch_agents() -> list[dict]:
    agents = safe_select("agents", order="name")
    if not agents:
        for a in DEFAULT_AGENTS:
            a = dict(a)
            a.setdefault("id", f"local-{a['name']}")
            a.setdefault("created_at", datetime.utcnow().isoformat())
        return DEFAULT_AGENTS[:]
    return agents


def fetch_brands() -> list[dict]:
    brands = safe_select("brands", order="key")
    if not brands:
        for b in DEFAULT_BRANDS:
            b = dict(b)
            b.setdefault("id", f"local-{b['key']}")
            b.setdefault("created_at", datetime.utcnow().isoformat())
        return DEFAULT_BRANDS[:]
    return brands


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
# SIDEBAR — Dark Charcoal with Gold Accent + Sidebar Toggle Fixed
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
    conn_label = "SUPABASE CONNECTED" if supabase_ok else "LOCAL SYNC MODE"
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
    tasks = safe_select("tasks", eq={"status": "queued"}, limit=1)
    queued_count = len(safe_select("tasks", eq={"status": "queued"}))

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
            except Exception as exc:
                status.update(label=f"Runner error: {exc}", state="error")
        safe_rerun()

    st.divider()
    st.caption("Zero AI. Zero agent execution.")

    # Providers status
    providers = config.available_providers()
    ready_count = len(providers)
    total_count = len(config.PROVIDERS)
    st.markdown(
        f'<div style="background:#18181B;border:1px solid #2A2A2E;border-radius:14px;padding:1rem;margin-top:0.5rem;">'
        f'<div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.08em;color:#A8A296;margin-bottom:0.5rem;">Providers</div>'
        f'<div style="font-size:0.85rem;font-weight:600;">{len(config.available_providers())} / {len(config.PROVIDERS)} reachable</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sign out", key="nav_signout", use_container_width=True):
        st.session_state["authed"] = False
        safe_rerun()


# ===========================================================================
# AUTH GATE — Unified Login Card inside centered column
# ===========================================================================
def require_password() -> None:
    if st.session_state.get("authed"):
        return

    # Centered column for the login card
    _, col, _ = st.columns([1, 1.3, 1])
    with col:
        with st.container(border=True):
            # Login card marker for CSS targeting
            st.markdown('<div class="login-marker"></div>', unsafe_allow_html=True)
            
            st.markdown(
                '<div style="text-align:center;padding:1rem 0.5rem 0.5rem 0.5rem;">'
                '<div style="font-size:2.5rem;margin-bottom:0.5rem;">⚡</div>'
                '<h1 style="margin:0 0 0.25rem 0;font-size:1.5rem;color:#FAF9F6;">Rishi-OS Control Room</h1>'
                '<p style="color:#B8B0A4;margin:0 0 1.5rem 0;font-size:0.9rem;">Executive Console</p>'
                '</div>',
                unsafe_allow_html=True,
            )

            if not config.DASHBOARD_PASSWORD:
                st.warning("DASHBOARD_PASSWORD is not set. Add it to `.env` before using the Control Room.")
                st.stop()

            with st.form("login"):
                supplied = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="••••••••")
                submitted = st.form_submit_button("Unlock Console", use_container_width=True, type="primary")

            if submitted:
                if supplied == config.DASHBOARD_PASSWORD:
                    st.session_state["authed"] = True
                    safe_rerun()
                else:
                    st.warning("Incorrect password.")
    st.stop()


require_password()


# ===========================================================================
# PAGE 1 — COMMAND CENTER
# ===========================================================================
def render_command_center() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Command Center")
    st.caption("Dispatch, monitor, and run the agent fleet from one console.")

    # ---- Data fetch (silent, zero errors) ----
    agents = fetch_agents()
    outputs = safe_select("outputs", order="created_at", desc=True, limit=200)
    tasks_q = safe_select("tasks", eq={"status": "queued"}, order="created_at", limit=50)

    # ---- KPI Row (4 Dark Charcoal Cards) ----
    enabled_count = sum(1 for a in fetch_agents() if a.get("enabled"))
    total_agents = len(fetch_agents())
    queued_count = len(safe_select("tasks", eq={"status": "queued"}))
    review_count = sum(1 for o in safe_select("outputs", limit=200) if o.get("status") in ("draft", "needs_review"))
    daily_cap_total = sum(int(a.get("daily_cap") or 0) for a in fetch_agents())
    daily_used_total = sum(int(a.get("runs_today") or 0) for a in fetch_agents())
    cap_pct = int((daily_used_total / daily_cap_total) * 100) if daily_cap_total else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{enabled_count}/{total_agents}</span>'
            f'<span class="label">Active Agents</span>'
            f'<span class="sub">{enabled_count} armed</span></div>',
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{len(safe_select("tasks", eq={"status": "queued"}))}</span>'
            f'<span class="label">Queued Tasks</span>'
            f'<span class="sub">Waiting for runner</span></div>',
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f'<div class="kpi-card"><span class="value">{review_count}</span>'
            f'<span class="label">Drafts Ready</span>'
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

    # ---- Visual Pipeline Stepper ----
    pipeline_agents = [
        ("Research", "research_agent"),
        ("Strategist", "idea_strategist"),
        ("Packaging", "packaging_studio"),
        ("Outreach", "outreach_agent"),
        ("Librarian", "summarize_librarian"),
        ("Growth Coach", "growth_coach_agent"),
        ("Watchdog", "system_watchdog"),
    ]
    agent_map = {a["name"]: a for a in fetch_agents()}
    
    st.markdown('<div class="pipeline-stepper">', unsafe_allow_html=True)
    for label, name in pipeline_agents:
        agent = agent_map.get(name)
        if agent:
            state = "armed" if agent.get("enabled") else "standby"
        else:
            state = "standby"
        st.markdown(
            f'<div class="pipeline-step {state}">'
            f'<div class="pipeline-dot"></div>'
            f'<div class="pipeline-label">{label}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    with st.expander("🔗 Queue Full End-to-End Pipeline", expanded=False):
        st.caption("Queue a single topic across the full 7-agent pipeline.")
        with st.form("pipeline_form"):
            pipe_brand = st.selectbox("Brand", [b.get("key") for b in fetch_brands() if b.get("key")] or ["edivic"], key="pipe_brand")
            pipe_topic = st.text_area("Topic / Instructions", height=100, key="pipe_topic", placeholder="e.g. Zero-budget growth tactics for early-stage AI startups")
            if st.form_submit_button("🔗 Queue Full Pipeline", type="primary", use_container_width=True):
                if pipe_topic.strip():
                    # Queue research_agent first with pipeline flag
                    safe_insert("tasks", {"agent": "research_agent", "payload": {"text": pipe_topic.strip(), "brand": pipe_brand, "pipeline": True}, "status": "queued", "created_at": datetime.utcnow().isoformat()})
                    st.toast("Full pipeline queued!")
                    safe_rerun()
                else:
                    st.warning("Provide a topic.")

    st.divider()

    # ---- 2-Column Bento Grid: Live Agent Fleet (Left) | Task Dispatch (Right) ----
    left, right = st.columns([1.5, 1], gap="large")

    with left:
        with st.container(border=True):
            # Agent Fleet marker for CSS dark card styling
            st.markdown('<div class="agent-card-marker"></div>', unsafe_allow_html=True)
            
            st.markdown("### Live Agent Fleet")
            st.caption("Toggle caps and enablement. Changes apply to the next cron tick.")
            
            agents = fetch_agents()
            if not agents:
                st.caption("No agents registered.")
            else:
                cols = st.columns(2)
                for idx, agent in enumerate(agents):
                    name = agent.get("name", "?")
                    enabled = bool(agent.get("enabled"))
                    cap = int(agent.get("daily_cap") or 1)
                    used = int(agent.get("runs_today") or 0)
                    schedule = agent.get("schedule") or "unspecified"
                    purpose = agent.get("purpose") or ""
                    progress = int((used / cap) * 100) if cap else 0

                    with cols[idx % 2]:
                        with st.container(border=True):
                            st.markdown('<div class="agent-card-marker"></div>', unsafe_allow_html=True)
                            
                            c_info, c_ctrl = st.columns([1.8, 1.2])
                            with c_info:
                                st.markdown(f"**{name}**")
                                st.markdown(tag_html("armed" if enabled else "standby"), unsafe_allow_html=True)
                                st.caption(purpose)
                                st.caption(f"⏱️ Cron: {schedule}  |  📊 Runs Today: {used} / {cap}")
                                st.progress(progress / 100)
                            
                            with c_ctrl:
                                new_enabled = st.toggle("Armed", value=enabled, key=f"cmd_en_{name}")
                                new_cap = st.number_input("Daily Cap", min_value=0, max_value=50, value=cap, key=f"cmd_cap_{name}", label_visibility="visible")
                                if st.button("💾 Save", key=f"cmd_save_{name}", use_container_width=True, type="primary"):
                                    safe_upsert("agents", {"name": name, "enabled": new_enabled, "daily_cap": int(new_cap)}, "name")
                                    st.toast(f"✅ {name} updated")
                                    safe_rerun()
                                if st.button("⚡ Run", key=f"cmd_run_{name}", use_container_width=True, type="secondary"):
                                    safe_insert("tasks", {"agent": name, "payload": {"quick_run": True}, "status": "queued", "created_at": datetime.utcnow().isoformat()})
                                    st.toast(f"⚡ {name} queued")
                                    safe_rerun()

    with right:
        with st.container(border=True):
            st.markdown("### Task Dispatch Studio")
            st.caption("Queue a natural-language instruction for any agent. Brand links the task to a voice profile.")

            brands = fetch_brands()
            brand_keys = [b.get("key") for b in fetch_brands() if b.get("key")]
            agent_names = [a.get("name") for a in fetch_agents() if a.get("name")]

            with st.form("cmd_task_form"):
                c_brand, c_agent = st.columns(2)
                with c_brand:
                    target_brand = st.selectbox("Brand", brand_keys or ["edivic"], key="cmd_brand")
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
                    saved = safe_insert("tasks", {"agent": target_agent, "payload": payload, "status": "queued", "created_at": datetime.utcnow().isoformat()})
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
                                except Exception as exc:
                                    status.update(label=f"Error: {exc}", state="error")
                        safe_rerun()

        st.divider()

        # ---- Active Task Queue ----
        with st.container(border=True):
            st.markdown("### Active Task Queue")
            tasks_q = safe_select("tasks", eq={"status": "queued"}, order="created_at", limit=20)
            if not tasks_q:
                st.caption("Queue is empty.")
            else:
                for task in tasks_q:
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
                            if st.button("🗑️ Remove", key=f"task_del_{task.get('id', '?')}", use_container_width=True):
                                safe_delete("tasks", "id", task.get("id", ""))
                                st.toast("Task removed.")
                                safe_rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 2 — REVIEW INBOX (Split-Screen Master-Detail)
# ===========================================================================
def render_review_inbox() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Review Inbox")
    st.caption("Split-screen curated deliverables vault — read, approve, hand off.")

    # ---- Filters ----
    brands = fetch_brands()
    brand_keys = ["(all brands)"] + [b.get("key") for b in fetch_brands() if b.get("key")]
    statuses = ["all", "needs_review", "draft", "approved", "rejected", "failed", "skipped"]

    f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.2, 1])
    with f1:
        filter_brand = st.selectbox("Brand", brand_keys, key="rib_brand")
    with f2:
        filter_status = st.selectbox("Status", statuses, index=0, key="rib_status")
    with f3:
        filter_agent = st.selectbox("Agent", ["(all agents)"] + [a.get("name") for a in fetch_agents() if a.get("name")], key="rib_agent")
    with f4:
        st.write("")
        if st.button("🔄 Refresh", key="rib_refresh", use_container_width=True):
            safe_rerun()

    search_query = st.text_input("Search", placeholder="Search in deliverables…", key="rib_search")

    # ---- Fetch ----
    rows = safe_select("outputs", order="created_at", desc=True, limit=300)
    if filter_brand != "(all brands)":
        rows = [r for r in rows if r.get("brand") == filter_brand]
    if filter_status != "all":
        rows = [r for r in rows if r.get("status") == filter_status]
    if filter_agent != "(all agents)":
        rows = [r for r in rows if r.get("agent") == filter_agent]
    if search_query:
        rows = [r for r in rows if search_query.lower() in (r.get("clean") or r.get("raw") or "").lower()]

    if not rows:
        with st.container(border=True):
            st.markdown(
                '<div style="text-align:center;padding:3rem;">'
                '<div style="font-size:2.5rem;margin-bottom:0.5rem;">📭</div>'
                '<h3 style="margin:0 0 0.5rem;color:#71717A;">No deliverables match</h3>'
                '<p style="color:#A1A1AA;margin:0;">Adjust filters or wait for agents to produce output.</p>'
                '</div>',
                unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # ---- Split-Screen Master-Detail ----
    if "selected_output_id" not in st.session_state:
        st.session_state.selected_output_id = rows[0].get("id") if rows else None

    col_list, col_reader = st.columns([1.1, 1.9], gap="large")

    with col_list:
        with st.container(border=True):
            st.markdown("### Deliverable Feed")
            st.caption(f"{len(rows)} items · click to open")
            for row in rows:
                oid = row.get("id", "?")
                selected = st.session_state.selected_output_id == oid
                status = row.get("status", "draft")
                agent = row.get("agent", "—")
                brand = row.get("brand") or "—"
                ts = (row.get("created_at") or "")[:16]
                title = (row.get("clean") or row.get("raw") or "")[:80]
                
                card_style = "background:#18181B;border-color:#D4AF37;" if selected else ""
                with st.container(border=True):
                    st.markdown(
                        f'<div style="{card_style}">'
                        f'{tag_html(status)} '
                        f'<span style="font-weight:600;">{agent}</span> '
                        f'<span style="opacity:0.7;">· {brand}</span><br>'
                        f'<span style="opacity:0.6;font-size:0.75rem;">{ts}</span><br>'
                        f'<span style="font-size:0.85rem;">{title}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Open", key=f"rib_open_{oid}", use_container_width=True, type="primary" if selected else "secondary"):
                        st.session_state.selected_output_id = oid
                        safe_rerun()

    with col_reader:
        selected_row = next((r for r in rows if r.get("id") == st.session_state.selected_output_id), None)
        if not selected_row:
            st.caption("Select a deliverable from the feed.")
        else:
            row = selected_row
            oid = row.get("id", "?")
            clean_text = row.get("clean") or row.get("raw") or ""
            raw_text = row.get("raw") or ""
            status = row.get("status", "draft")
            brand = row.get("brand") or "—"
            agent = row.get("agent") or "—"
            provider = row.get("provider") or "—"
            model = row.get("model") or "—"
            source_url = row.get("source_url")
            ts = row.get("created_at") or ""

            with st.container(border=True):
                st.markdown(
                    f'<div class="meta-row">'
                    f'{tag_html(status)} '
                    f'<span style="font-weight:600;">{agent}</span> '
                    f'<span style="font-weight:400;opacity:0.7;">· {brand}</span>'
                    f'<span style="float:right;">{model} · {provider} · {ts[:16]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if source_url:
                    st.caption(f"Source: {source_url}")
                st.markdown(clean_text, unsafe_allow_html=False)

                b1, b2, b3, b4 = st.columns(4)
                with b1:
                    if status != "approved":
                        if st.button("🏆 Approve Winner", key=f"rib_ap_{oid}", use_container_width=True, type="primary"):
                            safe_update("outputs", "id", oid, {"status": config.STATUS_APPROVED})
                            st.toast("Approved.")
                            safe_rerun()
                    else:
                        st.button("✅ Approved", key=f"rib_ap_done_{oid}", use_container_width=True, disabled=True)
                with b2:
                    if status != "draft":
                        if st.button("🔄 Move to Draft", key=f"rib_df_{oid}", use_container_width=True):
                            safe_update("outputs", "id", oid, {"status": config.STATUS_DRAFT})
                            st.toast("Reset to draft.")
                            safe_rerun()
                    else:
                        st.button("📝 Draft", key=f"rib_df_done_{oid}", use_container_width=True, disabled=True)
                with b3:
                    if status != "rejected":
                        if st.button("🗑️ Reject", key=f"rib_rj_{oid}", use_container_width=True):
                            safe_update("outputs", "id", oid, {"status": config.STATUS_REJECTED})
                            st.toast("Rejected.")
                            safe_rerun()
                    else:
                        st.button("⛔ Rejected", key=f"rib_rj_done_{oid}", use_container_width=True, disabled=True)
                with b4:
                    # Hand off to next agent
                    next_agent = "idea_strategist" if agent == "research_agent" else "packaging_studio"
                    if st.button(f"➡️ Hand Off to {next_agent}", key=f"rib_next_{oid}", use_container_width=True):
                        safe_insert("tasks", {"agent": next_agent, "payload": {"source_output": oid, "brand": brand, "topic": clean_text[:200]}, "status": "queued", "created_at": datetime.utcnow().isoformat()})
                        st.toast(f"Handed off to {next_agent}.")
                        safe_rerun()

                with st.expander("📋 1-Click Raw Copy / Edit", expanded=False):
                    edited = st.text_area("Clean text", value=clean_text, height=180, key=f"rib_edit_{oid}")
                    if st.button("💾 Save edit", key=f"rib_sv_{oid}", use_container_width=True):
                        safe_update("outputs", "id", oid, {"clean": edited})
                        st.toast("Edit saved.")
                        safe_rerun()
                    st.code(raw_text or "", language="markdown")

    st.markdown('</div>', unsafe_allow_html=True)


# ===========================================================================
# PAGE 3 — STUDIO & NOTES (2-Column Split)
# ===========================================================================
def render_creative_studio() -> None:
    st.markdown('<div class="page-fade">', unsafe_allow_html=True)
    st.title("Studio & Notes")
    st.caption("Brand voice directory and the executive note vault.")

    brands = fetch_brands()
    brand_keys = [b.get("key") for b in fetch_brands() if b.get("key")]

    col_brands, col_notes = st.columns([1, 1], gap="large")

    with col_brands:
        with st.container(border=True):
            st.markdown("### Brand Voice Directory")
            st.caption("View, edit, and create platform profiles.")

            for brand in fetch_brands():
                bkey = brand.get("key", "?")
                with st.container(border=True):
                    st.markdown(f"**{brand.get('name', bkey)}** `({bkey})`")
                    with st.form(f"brand_form_{bkey}"):
                        name = st.text_input("Name", value=brand.get("name") or "", key=f"brand_name_{bkey}")
                        voice = st.text_area("Voice", value=brand.get("voice") or "", height=80, key=f"brand_voice_{bkey}")
                        audience = st.text_area("Audience", value=brand.get("audience") or "", height=80, key=f"brand_aud_{bkey}")
                        platforms = st.text_input("Platforms", value=brand.get("platforms") or "", key=f"brand_plt_{bkey}")
                        always = st.text_area("Always", value=brand.get("always") or "", height=70, key=f"brand_alw_{bkey}")
                        never = st.text_area("Never", value=brand.get("never") or "", height=70, key=f"brand_nev_{bkey}")
                        if st.form_submit_button("💾 Save Brand", use_container_width=True, type="primary"):
                            safe_upsert("brands", {"key": bkey, "name": name, "voice": voice, "audience": audience, "platforms": platforms, "always": always, "never": never}, "key")
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
                        safe_upsert("brands", {"key": n_key, "name": n_name, "voice": n_voice, "audience": n_audience, "platforms": n_platforms, "always": n_always, "never": n_never}, "key")
                        st.toast(f"Brand {n_key} created.")
                        safe_rerun()
                    else:
                        st.warning("Key and Name are required.")

    with col_notes:
        with st.container(border=True):
            st.markdown("### Executive Notes & Journal Vault")
            st.caption("Save thoughts, ideas, strategies, and prompt drafts linked to brands.")

            brand_keys = ["(none)"] + [b.get("key") for b in fetch_brands() if b.get("key")]

            with st.form("note_form"):
                n_brand = st.selectbox("Link to brand", brand_keys, key="note_brand")
                n_kind = st.selectbox("Kind", ["Idea", "Strategy", "Prompt", "Todo"], key="note_kind")
                n_body = st.text_area("Note", height=160, key="note_body", placeholder="Capture a thought, idea, or strategy draft…")
                n_submit = st.form_submit_button("✨ Save Note", use_container_width=True, type="primary")

            if n_submit:
                if not n_body.strip():
                    st.warning("Write something before saving.")
                else:
                    row = {"body": n_body.strip(), "brand": None if n_brand == "(none)" else n_brand, "kind": n_kind.lower(), "created_at": datetime.utcnow().isoformat()}
                    safe_insert("notes", row)
                    st.toast("Note saved.")
                    safe_rerun()

            st.divider()
            st.markdown("#### Recent Notes")
            notes = safe_select("notes", order="created_at", desc=True, limit=30)

            if not notes:
                st.caption("No notes yet.")
            else:
                kind_filter = st.selectbox("Filter by kind", ["All", "Idea", "Strategy", "Prompt", "Todo"], key="note_filter")
                filtered = notes if kind_filter == "All" else [n for n in notes if n.get("kind", "").lower() == kind_filter.lower()]
                
                for note in filtered:
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
                            safe_delete("notes", "id", n_id)
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
    logs = safe_select("logs", order="time", desc=True, limit=200)
    usage = safe_select("usage", order="created_at", desc=True, limit=200)

    # ---- KPI Strip (5 Dark Charcoal Cards) ----
    total_calls = sum(int(u.get("calls") or 0) for u in usage)
    total_chars_in = sum(int(u.get("chars_in") or 0) for u in usage)
    total_chars_out = sum(int(u.get("chars_out") or 0) for u in usage)
    total_logs = len(logs)
    success_logs = sum(1 for l in logs if l.get("status") == "ok")
    success_rate = int((success_logs / total_logs) * 100) if total_logs else 0

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
        st.markdown(f'<div class="kpi-card"><span class="value">{success_rate}%</span><span class="label">Success Rate</span></div>', unsafe_allow_html=True)

    st.divider()

    # ---- Visual Charts Row ----
    if usage:
        usage_df = pd.DataFrame(usage)
        usage_df["provider"] = usage_df["provider"].fillna("unknown")
        usage_df["agent"] = usage_df["agent"].fillna("unknown")
        provider_counts = usage_df.groupby("provider").size().reset_index(name="runs")
        agent_calls = usage_df.groupby("agent")["calls"].sum().reset_index(name="total_calls")

        c_left, c_right = st.columns(2)
        with c_left:
            with st.container(border=True):
                st.markdown("### Calls by Provider")
                st.bar_chart(provider_counts, x="provider", y="runs", use_container_width=True)
        with c_right:
            with st.container(border=True):
                st.markdown("### Calls by Agent")
                st.bar_chart(agent_calls, x="agent", y="total_calls", use_container_width=True)
    else:
        with st.container(border=True):
            st.caption("No usage recorded yet.")

    st.divider()

    # ---- Bottom 2-Column Data Tables ----
    l_col, r_col = st.columns([1.1, 1], gap="large")

    with l_col:
        with st.container(border=True):
            st.markdown("### Execution Log Stream")
            st.caption("Real-time backend agent telemetry (logs ordered by `time` DESC).")
            if not logs:
                st.caption("No log entries yet.")
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
                st.caption("No usage recorded yet.")
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