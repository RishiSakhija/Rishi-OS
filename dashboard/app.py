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
    initial_sidebar_state="collapsed",
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
# Default Agent Fleet (7 built-in agents) — Always available, never empty
# ---------------------------------------------------------------------------
DEFAULT_AGENTS_LIST = DEFAULT_AGENTS  # alias for compatibility
DEFAULT_BRANDS_LIST = [b["key"] for b in DEFAULT_BRANDS]

# ---------------------------------------------------------------------------
# Design System CSS — Bespoke $10K Executive SaaS Aesthetic (Linear/Arc/Luxury Editorial)
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ============================================================
   GOOGLE FONTS IMPORT
============================================================ */
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Instrument+Serif:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {
  /* ============================================================
     REFINED COLOR PALETTE — Multi-Layered Depth
  ============================================================ */
  /* Main Canvas */
  --bg-warm: #F6F3EC;
  --bg-alabaster: #FAF8F3;
  --card-porcelain: #FCFBF9;
  --card-border: #E6E0D4;
  
  /* Dark Executive Modules */
  --panel-obsidian: #141518;
  --panel-obsidian-elevated: #1E2025;
  --panel-border: rgba(255,255,255,0.08);
  --panel-specular: rgba(255,255,255,0.06);
  
  /* Text & Accents */
  --ink: #1A1A2E;
  --muted: #71717A;
  --silver: #A1A1AA;
  --silver-dim: #71717A;
  --ochre: #D4AF37;
  --ochre-gold: #C9A227;
  --ochre-wash: rgba(212, 175, 55, 0.12);
  --ochre-border: rgba(212, 175, 55, 0.5);
  --emerald: #10B981;
  --emerald-dim: #059669;
  --emerald-glow: rgba(16, 185, 129, 0.35);
  --forest: #166534;
  
  /* Semantic */
  --ink: #1A1A2E;
  --muted: #71717A;
  --silver: #A1A1AA;
  --line: #E6E0D4;
  --white: #FAF9F6;
  --bg-warm: #F6F3EC;
  --bg-alabaster: #FAF8F3;
  --card-porcelain: #FCFBF9;
  --card-border: #E6E0D4;
  
  /* Shadows — Multi-Layered */
  --shadow-xs: 0 1px 2px rgba(20, 20, 30, 0.03);
  --shadow-sm: 0 1px 3px rgba(20, 20, 30, 0.04), 0 1px 2px rgba(20, 20, 30, 0.03);
  --shadow-md: 0 4px 12px rgba(20, 20, 30, 0.05), 0 2px 4px rgba(20, 20, 30, 0.03);
  --shadow-lg: 0 10px 30px rgba(20, 20, 30, 0.06), 0 4px 8px rgba(20, 20, 30, 0.03);
  --shadow-xl: 0 20px 50px -12px rgba(0, 0, 0, 0.25), 0 8px 20px rgba(0, 0, 0, 0.1);
  --shadow-inner: inset 0 1px 0 rgba(255, 255, 255, 0.06);
  --shadow-gold: 0 0 0 3px rgba(212, 175, 55, 0.15);
  --shadow-emerald: 0 0 8px rgba(16, 185, 129, 0.35);
  
  /* Radii */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-pill: 999px;
  
  /* Transitions */
  --ease-smooth: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-snappy: cubic-bezier(0.16, 1, 0.3, 1);
  --duration-fast: 150ms;
  --duration-normal: 220ms;
  --duration-slow: 320ms;
}

/* ============================================================
   GOOGLE FONTS & EDITORIAL TYPOGRAPHY HIERARCHY
============================================================ */

/* Global Font Loading & Smoothing */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-warm) !important;
  background-image: radial-gradient(ellipse 80% 50% at 100% 0%, #FAF8F3 0%, #F4F0E8 60%, #F6F3EC 100%) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  -webkit-font-smoothing: antialiased !important;
  -moz-osx-font-smoothing: grayscale !important;
  text-rendering: optimizeLegibility !important;
}

[data-testid="stMainBlockContainer"] {
  background: transparent !important;
  padding-top: 0 !important;
  max-width: 1600px !important;
  animation: fadeIn 0.55s var(--ease-smooth) forwards !important;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Editorial Typography Hierarchy */
h1, h2, h3, h4, h5, h6 {
  font-family: 'Instrument Serif', Georgia, 'Iowan Old Style', serif !important;
  color: var(--ink) !important;
  letter-spacing: -0.02em !important;
  line-height: 1.15 !important;
}

h1 { 
  font-size: clamp(1.85rem, 3vw, 2.35rem) !important; 
  font-weight: 600 !important;
  letter-spacing: -0.03em !important;
  margin-bottom: 0.375rem !important; 
}
h1 + .stMarkdown > p:first-child,
h1 + .stCaption {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.95rem !important;
  color: var(--muted) !important;
  font-weight: 400 !important;
  margin-top: -0.25rem !important;
  margin-bottom: 1.75rem !important;
  line-height: 1.6 !important;
}

h2 { 
  font-size: clamp(1.25rem, 2vw, 1.5rem) !important; 
  font-weight: 500 !important; 
  color: var(--ink) !important; 
  margin-top: 2.25rem !important; 
  margin-bottom: 1.125rem !important; 
}

h3 { 
  font-size: 1.05rem !important; 
  font-weight: 500 !important; 
  color: var(--ink) !important; 
  margin-bottom: 0.75rem !important; 
}

/* Global UI Font */
.stButton > button,
.stFormSubmitButton > button,
.stSelectbox, .stTextInput, .stTextArea, .stNumberInput,
.stToggle, .stCheckbox, .stRadio,
.stMarkdown, .stCaption, .stAlert,
[data-testid="stDataFrame"] {
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* Monospace for Technical Data */
code, kbd, samp,
[data-testid="stCodeBlock"],
.stCodeBlock,
.log-line,
.stMarkdown code,
.stNumberInput input,
.stTextInput input[type="text"],
[data-testid="stMetricValue"],
[data-testid="stMetricLabel"],
.stMetric [data-testid="stMetricValue"],
.stMetric [data-testid="stMetricLabel"] {
  font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace !important;
  font-variant-numeric: tabular-nums !important;
  font-feature-settings: "tnum" "liga" "calt" !important;
}

/* ============================================================
   GLOBAL CANVAS & AMBIENT BACKGROUND
============================================================ */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-warm) !important;
  background-image: radial-gradient(ellipse 80% 50% at 100% 0%, #FAF8F3 0%, #F4F0E8 60%, #F6F3EC 100%) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
  -webkit-font-smoothing: antialiased !important;
  -moz-osx-font-smoothing: grayscale !important;
}

[data-testid="stMainBlockContainer"] {
  background: transparent !important;
  padding-top: 0 !important;
  max-width: 1600px !important;
  animation: fadeIn 0.55s var(--ease-smooth) forwards !important;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ============================================================
   REMOVE SIDEBAR COMPLETELY
============================================================ */
[data-testid="stSidebar"] {
  display: none !important;
}
[data-testid="stSidebar"] > div {
  display: none !important;
}
[data-testid="stSidebarCollapseButton"] {
  display: none !important;
}
[data-testid="collapsedControl"] {
  display: none !important;
}
[data-testid="stSidebarNav"] {
  display: none !important;
}

/* ============================================================
   EXECUTIVE TOP NAVIGATION BAR
============================================================ */
.executive-top-bar {
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  height: 56px !important;
  background: var(--panel-obsidian) !important;
  border-bottom: 2px solid var(--ochre-border) !important;
  z-index: 10000 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  padding: 0 24px !important;
  box-shadow: var(--shadow-inner), 0 4px 24px rgba(0,0,0,0.3) !important;
}

.executive-top-bar-left {
  display: flex !important;
  align-items: center !important;
  gap: 16px !important;
}

.executive-brand {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
}

.executive-brand-icon {
  font-size: 28px !important;
  line-height: 1 !important;
}

.executive-brand-text {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 700 !important;
  font-size: 1.1rem !important;
  color: var(--white) !important;
  letter-spacing: 0.06em !important;
  text-transform: uppercase !important;
}

.executive-brand-sub {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.62rem !important;
  color: var(--ochre-gold) !important;
  font-weight: 600 !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  margin-top: -4px !important;
}

.executive-top-bar-right {
  display: flex !important;
  align-items: center !important;
  gap: 16px !important;
}

.executive-status-pill {
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  padding: 6px 14px !important;
  border-radius: var(--radius-pill) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.68rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
}
.conn-ok { background: rgba(16, 185, 129, 0.15) !important; color: var(--emerald) !important; border: 1px solid rgba(16, 185, 129, 0.3) !important; }
.conn-warn { background: var(--ochre-wash) !important; color: var(--ochre-gold) !important; border: 1px solid var(--ochre-border) !important; }

.executive-nav-strip {
  position: fixed !important;
  top: 56px !important;
  left: 0 !important;
  right: 0 !important;
  height: 56px !important;
  background: var(--bg-warm) !important;
  background-image: radial-gradient(ellipse 80% 50% at 100% 0%, #FAF8F3 0%, #F4F0E8 60%, #F6F3EC 100%) !important;
  border-bottom: 1px solid var(--card-border) !important;
  z-index: 9999 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  padding: 0 24px !important;
  gap: 8px !important;
}

.executive-nav-btn {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 8px !important;
  flex: 1 !important;
  max-width: 200px !important;
  min-height: 40px !important;
  padding: 0 16px !important;
  border-radius: var(--radius-lg) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.82rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.01em !important;
  transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1) !important;
  border: 1px solid transparent !important;
  cursor: pointer !important;
  text-decoration: none !important;
}

.executive-nav-btn:focus {
  outline: none !important;
  box-shadow: var(--shadow-gold) !important;
}

.executive-nav-btn.active {
  background: var(--panel-obsidian) !important;
  color: var(--ochre-gold) !important;
  border: 1px solid var(--ochre-border) !important;
  box-shadow: var(--shadow-inner), 0 0 0 1px var(--ochre-border) inset !important;
}

.executive-nav-btn:not(.active) {
  background: #FFFFFF !important;
  color: var(--ink) !important;
  border: 1px solid #E6E0D4 !important;
}

.executive-nav-btn:not(.active):hover {
  background: #FEFEF8 !important;
  border-color: var(--ochre-border) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 16px rgba(212, 175, 55, 0.15) !important;
}

/* Adjust main container to account for fixed top bars */
[data-testid="stMainBlockContainer"] {
  padding-top: 128px !important;
  max-width: 1580px !important;
  animation: fadeIn 0.55s var(--ease-smooth) forwards !important;
}

/* ============================================================
   GLOBAL CANVAS & AMBIENT BACKGROUND
============================================================ */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-warm) !important;
  background-image: radial-gradient(ellipse 80% 50% at 100% 0%, #FAF8F3 0%, #F4F0E8 60%, #F6F3EC 100%) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
  -webkit-font-smoothing: antialiased !important;
  -moz-osx-font-smoothing: grayscale !important;
}

[data-testid="stMainBlockContainer"] {
  background: transparent !important;
  padding-top: 128px !important;
  max-width: 1600px !important;
  animation: fadeIn 0.55s var(--ease-smooth) forwards !important;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ============================================================
   EDITORIAL TYPOGRAPHY HIERARCHY
============================================================ */
h1, h2, h3, h4, h5, h6 {
  font-family: 'Instrument Serif', Georgia, 'Iowan Old Style', serif !important;
  color: var(--ink) !important;
  letter-spacing: -0.02em !important;
  line-height: 1.15 !important;
}

h1 { 
  font-size: clamp(1.85rem, 3vw, 2.35rem) !important; 
  font-weight: 600 !important;
  letter-spacing: -0.03em !important;
  margin-bottom: 0.375rem !important; 
}
h1 + .stMarkdown > p:first-child,
h1 + .stCaption {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.95rem !important;
  color: var(--muted) !important;
  font-weight: 400 !important;
  margin-top: -0.25rem !important;
  margin-bottom: 1.75rem !important;
  line-height: 1.6 !important;
}

h2 { 
  font-size: clamp(1.25rem, 2vw, 1.5rem) !important; 
  font-weight: 500 !important; 
  color: var(--ink) !important; 
  margin-top: 2.25rem !important; 
  margin-bottom: 1.125rem !important; 
}

h3 { 
  font-size: 1.05rem !important; 
  font-weight: 500 !important; 
  color: var(--ink) !important; 
  margin-bottom: 0.75rem !important; 
}

/* Global UI Font */
.stButton > button,
.stFormSubmitButton > button,
.stSelectbox, .stTextInput, .stTextArea, .stNumberInput,
.stToggle, .stCheckbox, .stRadio,
.stMarkdown, .stCaption, .stAlert,
[data-testid="stDataFrame"] {
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* Monospace for Technical Data */
code, kbd, samp,
[data-testid="stCodeBlock"],
.stCodeBlock,
.log-line,
.stMarkdown code,
.stNumberInput input,
.stTextInput input[type="text"],
[data-testid="stMetricValue"],
[data-testid="stMetricLabel"],
.stMetric [data-testid="stMetricValue"],
.stMetric [data-testid="stMetricLabel"] {
  font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace !important;
  font-variant-numeric: tabular-nums !important;
  font-feature-settings: "tnum" "liga" "calt" !important;
}

/* ============================================================
   GLOBAL CANVAS & AMBIENT BACKGROUND
============================================================ */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-warm) !important;
  background-image: radial-gradient(ellipse 80% 50% at 100% 0%, #FAF8F3 0%, #F4F0E8 60%, #F6F3EC 100%) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
  -webkit-font-smoothing: antialiased !important;
  -moz-osx-font-smoothing: grayscale !important;
}

[data-testid="stMainBlockContainer"] {
  background: transparent !important;
  padding-top: 128px !important;
  max-width: 1600px !important;
  animation: fadeIn 0.55s var(--ease-smooth) forwards !important;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ============================================================
   HIDE SIDEBAR COMPLETELY
============================================================ */
[data-testid="stSidebar"] {
  display: none !important;
}
[data-testid="stSidebar"] > div {
  display: none !important;
}
[data-testid="stSidebarCollapseButton"] {
  display: none !important;
}
[data-testid="collapsedControl"] {
  display: none !important;
}
[data-testid="stSidebarNav"] {
  display: none !important;
}

/* ============================================================
   PRESERVE MATERIAL SYMBOLS ROUNDED FONT FOR ICONS
============================================================ */
[data-testid="stIconMaterial"],
.material-symbols-rounded,
span[class*="material-symbol"],
span[class*="material-icons"],
.stButton > button span[data-testid="stIconMaterial"],
.stButton > button .material-symbols-rounded,
.stButton > button .material-icons,
.stButton > button [data-testid="stIconMaterial"] {
  font-family: "Material Symbols Rounded", sans-serif !important;
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24 !important;
  font-weight: normal !important;
  font-style: normal !important;
  font-size: 1.25rem !important;
  line-height: 1 !important;
  letter-spacing: normal !important;
  text-transform: none !important;
  white-space: nowrap !important;
  direction: ltr !important;
}

/* ============================================================
   EXECUTIVE KPI METRIC CARDS — Dark Charcoal with Gold/Ivory
============================================================ */
.kpi-card {
  background: var(--panel-obsidian) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: var(--radius-lg) !important;
  padding: 1.35rem 1.5rem !important;
  text-align: center !important;
  color: var(--white) !important;
  box-shadow: var(--shadow-inner), var(--shadow-lg) !important;
  transition: all var(--duration-normal) var(--ease-smooth) !important;
}
.kpi-card:hover { 
  border-color: var(--ochre-border) !important; 
  transform: translateY(-2px) !important; 
  box-shadow: var(--shadow-inner), 0 16px 48px -16px rgba(212, 175, 55, 0.15) !important;
}
.kpi-card .value { 
  font-family: 'JetBrains Mono', monospace !important;
  font-variant-numeric: tabular-nums !important;
  font-size: clamp(1.75rem, 3vw, 2.1rem) !important; 
  font-weight: 700 !important; 
  color: var(--ochre-gold) !important; 
  display: block !important; 
  margin-bottom: 0.25rem !important; 
  line-height: 1.1 !important; 
  letter-spacing: -0.02em !important;
}
.kpi-card .label { 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.68rem !important; 
  text-transform: uppercase !important; 
  letter-spacing: 0.1em !important; 
  color: var(--silver) !important; 
  display: block !important; 
  font-weight: 600 !important; 
}
.kpi-card .sub { 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.72rem !important; 
  color: var(--ochre-gold) !important; 
  font-weight: 600 !important; 
  display: block !important; 
  margin-top: 0.5rem !important; 
}

/* ============================================================
   PIPELINE STEPPER — Refined Horizontal Progress Track
============================================================ */
.pipeline-stepper {
  display: flex !important;
  gap: 0 !important;
  padding: 1.25rem 1.5rem !important;
  background: var(--panel-obsidian) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: var(--radius-lg) !important;
  overflow-x: auto !important;
  position: relative !important;
}
.pipeline-stepper::before {
  content: '' !important;
  position: absolute !important;
  top: 50% !important;
  left: 3.5rem !important;
  right: 3.5rem !important;
  height: 2px !important;
  background: linear-gradient(90deg, var(--panel-border) 0%, var(--ochre-border) 50%, var(--panel-border) 100%) !important;
  transform: translateY(-50%) !important;
  z-index: 0 !important;
}
.pipeline-step {
  flex: 1 !important;
  min-width: 110px !important;
  text-align: center !important;
  padding: 0.75rem 0.5rem !important;
  position: relative !important;
  z-index: 1 !important;
}
.pipeline-dot {
  width: 14px !important; 
  height: 14px !important; 
  border-radius: 50% !important;
  margin: 0 auto 0.5rem !important; 
  border: 2px solid rgba(255,255,255,0.12) !important;
  background: var(--panel-obsidian) !important; 
  transition: all var(--duration-normal) var(--ease-smooth) !important;
  position: relative !important;
  box-shadow: 0 0 0 4px var(--panel-obsidian) !important;
}
.pipeline-step.armed .pipeline-dot { 
  background: var(--emerald) !important; 
  border-color: var(--emerald) !important; 
  box-shadow: 0 0 0 4px var(--panel-obsidian), 0 0 12px var(--emerald-glow) !important; 
}
.pipeline-step.queued .pipeline-dot { 
  background: var(--ochre-gold) !important; 
  border-color: var(--ochre-gold) !important; 
  box-shadow: 0 0 0 4px var(--panel-obsidian), 0 0 12px var(--ochre-wash) !important; 
}
.pipeline-step.standby .pipeline-dot { 
  background: var(--panel-obsidian) !important; 
  border-color: rgba(255,255,255,0.12) !important; 
}
.pipeline-label { 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.68rem !important; 
  text-transform: uppercase !important; 
  letter-spacing: 0.08em !important; 
  color: var(--silver-dim) !important; 
  font-weight: 600 !important; 
  white-space: nowrap !important;
}
.pipeline-step.armed .pipeline-label { color: var(--emerald) !important; font-weight: 700 !important; }
.pipeline-step.queued .pipeline-label { color: var(--ochre-gold) !important; font-weight: 700 !important; }
.pipeline-step.standby .pipeline-label { color: var(--silver-dim) !important; }

/* ============================================================
   STATUS BADGES — Refined Editorial Style
============================================================ */
.tag {
  display: inline-flex !important;
  align-items: center !important;
  padding: 0.175rem 0.625rem !important;
  border-radius: var(--radius-pill) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.65rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  margin-right: 0.35rem !important;
  margin-bottom: 0.25rem !important;
}
.tag-armed { background: rgba(16, 185, 129, 0.18) !important; color: #34D399 !important; border: 1px solid rgba(52, 211, 153, 0.4) !important; }
.tag-standby { background: rgba(255, 255, 255, 0.08) !important; color: #E2E8F0 !important; border: 1px solid rgba(255, 255, 255, 0.18) !important; }
.tag-draft { background: rgba(212, 175, 55, 0.12) !important; color: #B88A1A !important; border: 1px solid rgba(212, 175, 55, 0.25) !important; }
.tag-needs_review { background: rgba(212, 175, 55, 0.12) !important; color: #C9A227 !important; border: 1px solid rgba(212, 175, 55, 0.25) !important; }
.tag-approved { background: rgba(16, 185, 129, 0.12) !important; color: #059669 !important; border: 1px solid rgba(16, 185, 129, 0.25) !important; }
.tag-rejected { background: rgba(239, 68, 68, 0.1) !important; color: #DC2626 !important; border: 1px solid rgba(239, 68, 68, 0.2) !important; }
.tag-failed { background: rgba(148, 163, 184, 0.1) !important; color: #64748B !important; border: 1px solid rgba(148, 163, 184, 0.2) !important; }
.tag-queued { background: rgba(212, 175, 55, 0.12) !important; color: #C9A227 !important; border: 1px solid rgba(212, 175, 55, 0.25) !important; }
.tag-done { background: rgba(16, 185, 129, 0.12) !important; color: #059669 !important; border: 1px solid rgba(16, 185, 129, 0.25) !important; }

/* ============================================================
   BUTTONS — Tactile Micro-Interactions
============================================================ */
.stButton > button, .stFormSubmitButton > button {
  border-radius: var(--radius-md) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  letter-spacing: 0.01em !important;
  transition: all var(--duration-normal) var(--ease-smooth) !important;
  border: 1px solid var(--card-border) !important;
  background: #FFFFFF !important;
  color: var(--ink) !important;
  padding: 0.625rem 1.375rem !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: var(--ochre-gold) !important;
  color: var(--ink) !important;
  background: #FEFEF8 !important;
  transform: translateY(-1px) !important;
  box-shadow: var(--shadow-sm) !important;
}
.stButton > button:active, .stFormSubmitButton > button:active {
  transform: translateY(0) !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: var(--panel-obsidian) !important;
  border-color: var(--ochre-border) !important;
  color: var(--white) !important;
  box-shadow: 0 0 0 1px var(--ochre-border) inset !important;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
  background: var(--panel-obsidian-elevated) !important;
  border-color: var(--ochre-gold) !important;
  color: var(--white) !important;
  box-shadow: 0 4px 20px rgba(212, 175, 55, 0.25) !important;
}
.stButton > button[kind="secondary"] {
  background: var(--card-porcelain) !important;
  border-color: var(--card-border) !important;
  color: var(--ink) !important;
}
.stButton > button[kind="secondary"]:hover {
  background: #F3EFE6 !important;
  border-color: var(--ochre-border) !important;
  color: var(--ink) !important;
}

/* ============================================================
   INPUTS — Clean, Consistent, High-Contrast
============================================================ */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div,
.stNumberInput > div > div > input {
  background: #FFFFFF !important;
  border: 1px solid var(--card-border) !important;
  border-radius: var(--radius-md) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.9rem !important;
  padding: 0.625rem 0.875rem !important;
  transition: all var(--duration-fast) var(--ease-smooth) !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus,
.stSelectbox > div > div:focus-within,
.stNumberInput > div > div > input:focus {
  border-color: var(--ochre-gold) !important;
  box-shadow: var(--shadow-gold) !important;
  outline: none !important;
}
.stSelectbox > div > div {
  background: #FFFFFF !important;
  border: 1px solid var(--card-border) !important;
  border-radius: var(--radius-md) !important;
}
.stTextArea > div > div > textarea {
  min-height: 100px !important;
  resize: vertical !important;
  line-height: 1.6 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
}
.stToggle > label { 
  color: var(--ink) !important; 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 500 !important;
}

/* ============================================================
   DARK EXECUTIVE CARDS — via :has() markers (FIX 2)
   True Dark Obsidian Charcoal cards on Pure White/Alabaster background
============================================================ */

/* Agent Fleet Dark Cards - True Dark Obsidian Charcoal */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker),
div[data-testid="stContainer"]:has(.agent-card-marker),
div:has(> div > .agent-card-marker),
div:has(> div > div > .agent-card-marker) {
  background: #141518 !important;
  background-color: #141518 !important;
  border: 1px solid #2A2D35 !important;
  border-radius: 16px !important;
  padding: 18px !important;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.16) !important;
}

/* Force high-contrast typography inside every dark agent card */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) *,
div[data-testid="stContainer"]:has(.agent-card-marker) *,
div:has(> div > .agent-card-marker) *,
div:has(> div > div > .agent-card-marker) * {
  color: #FAF9F6 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) h3,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) h4,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) strong,
div[data-testid="stContainer"]:has(.agent-card-marker) h3,
div[data-testid="stContainer"]:has(.agent-card-marker) h4,
div[data-testid="stContainer"]:has(.agent-card-marker) strong,
div:has(> div > .agent-card-marker) h3,
div:has(> div > .agent-card-marker) h4,
div:has(> div > .agent-card-marker) strong,
div:has(> div > div > .agent-card-marker) h3,
div:has(> div > div > .agent-card-marker) h4,
div:has(> div > div > .agent-card-marker) strong {
  color: #FAF9F6 !important;
  font-weight: 600 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stMarkdown,
div[data-testid="stContainer"]:has(.agent-card-marker) .stMarkdown {
  color: #FAF9F6 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stCaption,
div[data-testid="stContainer"]:has(.agent-card-marker) .stCaption {
  color: #CBD5E1 !important;
  font-size: 0.86rem !important;
  opacity: 1 !important;
}

/* Toggle labels, input labels, captions */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stToggle label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stNumberInput label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stTextInput label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stSelectbox label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stTextInput > div > label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stNumberInput > div > label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stToggle > label,
div[data-testid="stContainer"]:has(.agent-card-marker) .stToggle label,
div[data-testid="stContainer"]:has(.agent-card-marker) .stNumberInput label,
div[data-testid="stContainer"]:has(.agent-card-marker) .stTextInput label,
div[data-testid="stContainer"]:has(.agent-card-marker) .stSelectbox label {
  color: #FAF9F6 !important;
  font-weight: 600 !important;
  opacity: 1 !important;
}

/* Status badges */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .tag-armed,
div[data-testid="stContainer"]:has(.agent-card-marker) .tag-armed {
  background: rgba(16, 185, 129, 0.18) !important;
  color: #34D399 !important;
  border: 1px solid rgba(52, 211, 153, 0.4) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .tag-standby,
div[data-testid="stContainer"]:has(.agent-card-marker) .tag-standby {
  background: rgba(255, 255, 255, 0.08) !important;
  color: #E2E8F0 !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
}

/* Number Input inside Dark Agent Card */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stNumberInput > div > div > input,
div[data-testid="stContainer"]:has(.agent-card-marker) .stNumberInput > div > div > input {
  background: #1E2028 !important;
  color: #FAF9F6 !important;
  border: 1px solid #383C47 !important;
  border-radius: var(--radius-md) !important;
}

/* Save button inside Dark Agent Card */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="primary"],
div[data-testid="stContainer"]:has(.agent-card-marker) .stButton > button[kind="primary"] {
  background: #1E2028 !important;
  color: #D4AF37 !important;
  border: 1px solid rgba(212, 175, 55, 0.55) !important;
  font-weight: 600 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="primary"]:hover,
div[data-testid="stContainer"]:has(.agent-card-marker) .stButton > button[kind="primary"]:hover {
  background: #272C35 !important;
  border-color: #D4AF37 !important;
}

/* Run button inside Dark Agent Card */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="secondary"],
div[data-testid="stContainer"]:has(.agent-card-marker) .stButton > button[kind="secondary"] {
  background: #D4AF37 !important;
  color: #141518 !important;
  font-weight: 700 !important;
  border: none !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stButton > button[kind="secondary"]:hover,
div[data-testid="stContainer"]:has(.agent-card-marker) .stButton > button[kind="secondary"]:hover {
  background: #C9A227 !important;
}

/* Number Input inside Dark Agent Card */
[data-testid="stVerticalBlockBorderWrapper"]:has(.agent-card-marker) .stNumberInput > div > div > input,
div[data-testid="stContainer"]:has(.agent-card-marker) .stNumberInput > div > div > input {
  background: #1E2028 !important;
  color: #FAF9F6 !important;
  border: 1px solid #383C47 !important;
  border-radius: var(--radius-md) !important;
}

/* ============================================================
   LIGHT PANEL CARDS — Task Dispatch Studio & Task Queue (FIX 3)
============================================================ */

/* Light Panel Cards — Clean White/Alabaster */
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker),
div[data-testid="stContainer"]:has(.light-panel-marker),
div:has(> div > .light-panel-marker) {
  background: #FFFFFF !important;
  background-color: #FFFFFF !important;
  border: 1px solid #E2DDD2 !important;
  border-radius: 16px !important;
  padding: 20px !important;
  box-shadow: 0 4px 20px rgba(24, 24, 27, 0.06) !important;
}

/* Force high-contrast dark text inside light panels */
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) *,
div[data-testid="stContainer"]:has(.light-panel-marker) * {
  color: #18181B !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stSelectbox label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stTextInput label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stTextArea label,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stNumberInput label,
div[data-testid="stContainer"]:has(.light-panel-marker) label,
div[data-testid="stContainer"]:has(.light-panel-marker) .stSelectbox label,
div[data-testid="stContainer"]:has(.light-panel-marker) .stTextInput label,
div[data-testid="stContainer"]:has(.light-panel-marker) .stTextArea label,
div[data-testid="stContainer"]:has(.light-panel-marker) .stNumberInput label {
  color: #18181B !important;
  font-weight: 600 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stSelectbox > div > div,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stTextInput > div > div > input,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stTextArea > div > div > textarea,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stNumberInput > div > div > input,
div[data-testid="stContainer"]:has(.light-panel-marker) .stSelectbox > div > div,
div[data-testid="stContainer"]:has(.light-panel-marker) .stTextInput > div > div > input,
div[data-testid="stContainer"]:has(.light-panel-marker) .stTextArea > div > div > textarea,
div[data-testid="stContainer"]:has(.light-panel-marker) .stNumberInput > div > div > input {
  background: #F8FAFC !important;
  border: 1px solid #CBD5E1 !important;
  color: #18181B !important;
  border-radius: 12px !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stTextInput > div > div > input::placeholder,
[data-testid="stVerticalBlockBorderWrapper"]:has(.light-panel-marker) .stTextArea > div > div > textarea::placeholder,
div[data-testid="stContainer"]:has(.light-panel-marker) .stTextInput > div > div > input::placeholder,
div[data-testid="stContainer"]:has(.light-panel-marker) .stTextArea > div > div > textarea::placeholder {
  color: #64748B !important;
}

/* ============================================================
   LOGIN CARD DARK
============================================================ */
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) {
  background: #141518 !important;
  border: 1px solid #272A30 !important;
  border-radius: 20px !important;
  padding: 2.5rem 2rem !important;
  color: #FAF9F6 !important;
  box-shadow: 0 10px 40px rgba(0,0,0,0.35) !important;
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
  background: #1E2025 !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  color: #FAF9F6 !important;
  border-radius: 12px !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) .stTextInput > div > div > input:focus {
  border-color: #D4AF37 !important;
  box-shadow: 0 0 0 3px rgba(212, 175, 55, 0.15) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) .stFormSubmitButton > button {
  background: #D4AF37 !important;
  border-color: #D4AF37 !important;
  color: #141518 !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
  padding: 0.875rem 2rem !important;
  font-size: 1rem !important;
  letter-spacing: 0.02em !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) .stFormSubmitButton > button:hover {
  background: #C9A227 !important;
  border-color: #C9A227 !important;
}

/* ============================================================
   KPI METRIC CARDS — Dark Charcoal with Gold/Ivory
============================================================ */
.kpi-card {
  background: var(--panel-obsidian) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: var(--radius-lg) !important;
  padding: 1.35rem 1.5rem !important;
  text-align: center !important;
  color: var(--white) !important;
  box-shadow: var(--shadow-inner), var(--shadow-lg) !important;
  transition: all var(--duration-normal) var(--ease-smooth) !important;
}
.kpi-card:hover { 
  border-color: var(--ochre-border) !important; 
  transform: translateY(-2px) !important; 
  box-shadow: var(--shadow-inner), 0 16px 48px -16px rgba(212, 175, 55, 0.15) !important;
}
.kpi-card .value { 
  font-family: 'JetBrains Mono', monospace !important;
  font-variant-numeric: tabular-nums !important;
  font-size: clamp(1.75rem, 3vw, 2.1rem) !important; 
  font-weight: 700 !important; 
  color: var(--ochre-gold) !important; 
  display: block !important; 
  margin-bottom: 0.25rem !important; 
  line-height: 1.1 !important; 
  letter-spacing: -0.02em !important;
}
.kpi-card .label { 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.68rem !important; 
  text-transform: uppercase !important; 
  letter-spacing: 0.1em !important; 
  color: var(--silver) !important; 
  display: block !important; 
  font-weight: 600 !important; 
}
.kpi-card .sub { 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.72rem !important; 
  color: var(--ochre-gold) !important; 
  font-weight: 600 !important; 
  display: block !important; 
  margin-top: 0.5rem !important; 
}

/* ============================================================
   PIPELINE STEPPER — Refined Horizontal Progress Track
============================================================ */
.pipeline-stepper {
  display: flex !important;
  gap: 0 !important;
  padding: 1.25rem 1.5rem !important;
  background: var(--panel-obsidian) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: var(--radius-lg) !important;
  overflow-x: auto !important;
  position: relative !important;
}
.pipeline-stepper::before {
  content: '' !important;
  position: absolute !important;
  top: 50% !important;
  left: 3.5rem !important;
  right: 3.5rem !important;
  height: 2px !important;
  background: linear-gradient(90deg, var(--panel-border) 0%, var(--ochre-border) 50%, var(--panel-border) 100%) !important;
  transform: translateY(-50%) !important;
  z-index: 0 !important;
}
.pipeline-step {
  flex: 1 !important;
  min-width: 110px !important;
  text-align: center !important;
  padding: 0.75rem 0.5rem !important;
  position: relative !important;
  z-index: 1 !important;
}
.pipeline-dot {
  width: 14px !important; 
  height: 14px !important; 
  border-radius: 50% !important;
  margin: 0 auto 0.5rem !important; 
  border: 2px solid rgba(255,255,255,0.12) !important;
  background: var(--panel-obsidian) !important; 
  transition: all var(--duration-normal) var(--ease-smooth) !important;
  position: relative !important;
  box-shadow: 0 0 0 4px var(--panel-obsidian) !important;
}
.pipeline-step.armed .pipeline-dot { 
  background: var(--emerald) !important; 
  border-color: var(--emerald) !important; 
  box-shadow: 0 0 0 4px var(--panel-obsidian), 0 0 12px var(--emerald-glow) !important; 
}
.pipeline-step.queued .pipeline-dot { 
  background: var(--ochre-gold) !important; 
  border-color: var(--ochre-gold) !important; 
  box-shadow: 0 0 0 4px var(--panel-obsidian), 0 0 12px var(--ochre-wash) !important; 
}
.pipeline-step.standby .pipeline-dot { 
  background: var(--panel-obsidian) !important; 
  border-color: rgba(255,255,255,0.12) !important; 
}
.pipeline-label { 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.68rem !important; 
  text-transform: uppercase !important; 
  letter-spacing: 0.08em !important; 
  color: var(--silver-dim) !important; 
  font-weight: 600 !important; 
  white-space: nowrap !important;
}
.pipeline-step.armed .pipeline-label { color: var(--emerald) !important; font-weight: 700 !important; }
.pipeline-step.queued .pipeline-label { color: var(--ochre-gold) !important; font-weight: 700 !important; }
.pipeline-step.standby .pipeline-label { color: var(--silver-dim) !important; }

/* ============================================================
   STATUS BADGES — Refined Editorial Style
============================================================ */
.tag {
  display: inline-flex !important;
  align-items: center !important;
  padding: 0.175rem 0.625rem !important;
  border-radius: var(--radius-pill) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.65rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  margin-right: 0.35rem !important;
  margin-bottom: 0.25rem !important;
}
.tag-armed { background: rgba(16, 185, 129, 0.18) !important; color: #34D399 !important; border: 1px solid rgba(52, 211, 153, 0.4) !important; }
.tag-standby { background: rgba(255, 255, 255, 0.08) !important; color: #E2E8F0 !important; border: 1px solid rgba(255, 255, 255, 0.18) !important; }
.tag-draft { background: rgba(212, 175, 55, 0.12) !important; color: #B88A1A !important; border: 1px solid rgba(212, 175, 55, 0.25) !important; }
.tag-needs_review { background: rgba(212, 175, 55, 0.12) !important; color: #C9A227 !important; border: 1px solid rgba(212, 175, 55, 0.25) !important; }
.tag-approved { background: rgba(16, 185, 129, 0.12) !important; color: #059669 !important; border: 1px solid rgba(16, 185, 129, 0.25) !important; }
.tag-rejected { background: rgba(239, 68, 68, 0.1) !important; color: #DC2626 !important; border: 1px solid rgba(239, 68, 68, 0.2) !important; }
.tag-failed { background: rgba(148, 163, 184, 0.1) !important; color: #64748B !important; border: 1px solid rgba(148, 163, 184, 0.2) !important; }
.tag-queued { background: rgba(212, 175, 55, 0.12) !important; color: #C9A227 !important; border: 1px solid rgba(212, 175, 55, 0.25) !important; }
.tag-done { background: rgba(16, 185, 129, 0.12) !important; color: #059669 !important; border: 1px solid rgba(16, 185, 129, 0.25) !important; }

/* ============================================================
   BUTTONS — Tactile Micro-Interactions
============================================================ */
.stButton > button, .stFormSubmitButton > button {
  border-radius: var(--radius-md) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  letter-spacing: 0.01em !important;
  transition: all var(--duration-normal) var(--ease-smooth) !important;
  border: 1px solid var(--card-border) !important;
  background: #FFFFFF !important;
  color: var(--ink) !important;
  padding: 0.625rem 1.375rem !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: var(--ochre-gold) !important;
  color: var(--ink) !important;
  background: #FEFEF8 !important;
  transform: translateY(-1px) !important;
  box-shadow: var(--shadow-sm) !important;
}
.stButton > button:active, .stFormSubmitButton > button:active {
  transform: translateY(0) !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: var(--panel-obsidian) !important;
  border-color: var(--ochre-border) !important;
  color: var(--white) !important;
  box-shadow: 0 0 0 1px var(--ochre-border) inset !important;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
  background: var(--panel-obsidian-elevated) !important;
  border-color: var(--ochre-gold) !important;
  color: var(--white) !important;
  box-shadow: 0 4px 20px rgba(212, 175, 55, 0.25) !important;
}
.stButton > button[kind="secondary"] {
  background: var(--card-porcelain) !important;
  border-color: var(--card-border) !important;
  color: var(--ink) !important;
}
.stButton > button[kind="secondary"]:hover {
  background: #F3EFE6 !important;
  border-color: var(--ochre-border) !important;
  color: var(--ink) !important;
}

/* ============================================================
   INPUTS — Clean, Consistent, High-Contrast
============================================================ */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div,
.stNumberInput > div > div > input {
  background: #FFFFFF !important;
  border: 1px solid var(--card-border) !important;
  border-radius: var(--radius-md) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 0.9rem !important;
  padding: 0.625rem 0.875rem !important;
  transition: all var(--duration-fast) var(--ease-smooth) !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus,
.stSelectbox > div > div:focus-within,
.stNumberInput > div > div > input:focus {
  border-color: var(--ochre-gold) !important;
  box-shadow: var(--shadow-gold) !important;
  outline: none !important;
}
.stSelectbox > div > div {
  background: #FFFFFF !important;
  border: 1px solid var(--card-border) !important;
  border-radius: var(--radius-md) !important;
}
.stTextArea > div > div > textarea {
  min-height: 100px !important;
  resize: vertical !important;
  line-height: 1.6 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
}
.stToggle > label { 
  color: var(--ink) !important; 
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 500 !important;
}

/* ============================================================
   DATAFRAMES — Clean Tables
============================================================ */
[data-testid="stDataFrame"] {
  border: 1px solid var(--card-border) !important;
  border-radius: var(--radius-lg) !important;
  overflow: hidden !important;
  background: var(--card-porcelain) !important;
}

/* ============================================================
   LOG LINES — Monospace Terminal Style
============================================================ */
.log-line { 
  font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace !important; 
  font-variant-numeric: tabular-nums !important;
  font-size: 0.725rem !important; 
  padding: 0.25rem 0.625rem !important; 
  border-bottom: 1px solid rgba(255,255,255,0.04) !important; 
  color: #C0C0C8 !important; 
  line-height: 1.5 !important;
}
.log-line.ok { color: var(--emerald) !important; }
.log-line.err { color: #EF4444 !important; }
.log-line.inf { color: var(--ochre-gold) !important; }

/* ============================================================
   HIDE STREAMLIT CHROME
============================================================ */
#MainMenu {visibility: hidden !important;}
footer {visibility: hidden !important;}
[data-testid="stDeployButton"] {visibility: hidden !important;}
[data-testid="stToolbar"] {visibility: hidden !important;}
[data-testid="stSidebar"] {display: none !important;}
[data-testid="stSidebarCollapseButton"] {display: none !important;}
[data-testid="collapsedControl"] {display: none !important;}
[data-testid="stSidebarNav"] {display: none !important;}
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
if "active_page" not in st.session_state:
    st.session_state.active_page = "command_center"

PAGES = [
    ("command_center", "🎯 Command Center"),
    ("review_inbox", "📥 Review Inbox"),
    ("creative_studio", "📝 Studio & Notes"),
    ("analytics_ledger", "📈 Analytics & Ledger"),
]


# ---------------------------------------------------------------------------
# AUTH GATE — Unified Login Card inside centered column
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# EXECUTIVE TOP NAVIGATION BAR
# ---------------------------------------------------------------------------
def render_top_nav():
    """Render the executive top navigation bar and horizontal page tabs."""
    # Top Header Bar
    st.markdown(
        f"""
        <div class="executive-top-bar">
            <div class="executive-top-bar-left">
                <div class="executive-brand">
                    <span class="executive-brand-icon">⚡</span>
                    <div>
                        <div class="executive-brand-text">RISHI-OS // EXECUTIVE CONSOLE</div>
                        <div class="executive-brand-sub">Zero AI • Zero Agent Execution</div>
                    </div>
                </div>
            </div>
            <div class="executive-top-bar-right">
                <div class="executive-status-pill {'conn-ok' if bool(_SUPABASE_URL and _SUPABASE_KEY and not _SUPABASE_URL.startswith('https://your-project')) else 'conn-warn'}">
                    {'🟢 ONLINE' if bool(_SUPABASE_URL and _SUPABASE_KEY and not _SUPABASE_URL.startswith('https://your-project')) else '🟡 LOCAL SYNC'}
                </div>
            </div>
        </div>
        <div class="executive-nav-strip">
        """,
        unsafe_allow_html=True,
    )
    
    # Horizontal page navigation
    nav_cols = st.columns(4)
    page_keys = [p[0] for p in PAGES]
    page_labels = [p[1] for p in PAGES]
    
    for i, (key, label) in enumerate(PAGES):
        with nav_cols[i]:
            active = st.session_state.active_page == key
            if st.button(
                label, 
                key=f"nav_{key}", 
                use_container_width=True, 
                type="primary" if active else "secondary"
            ):
                st.session_state.active_page = key
                safe_rerun()
    
    st.markdown('</div>', unsafe_allow_html=True)


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
# Top Navigation
# ---------------------------------------------------------------------------
render_top_nav()


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
    
    # Build entire pipeline stepper as single HTML string (FIX 3)
    stepper_html = ['<div class="pipeline-stepper">']
    for label, name in pipeline_agents:
        agent = agent_map.get(name)
        state = "armed" if (agent and agent.get("enabled")) else "standby"
        stepper_html.append(
            f'<div class="pipeline-step {state}">'
            f'<div class="pipeline-dot"></div>'
            f'<div class="pipeline-label">{label}</div>'
            f'</div>'
        )
    stepper_html.append('</div>')
    st.markdown(''.join(stepper_html), unsafe_allow_html=True)

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
            # Task Dispatch Studio marker for CSS light card styling
            st.markdown('<div class="light-panel-marker"></div>', unsafe_allow_html=True)
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
            # Task Queue marker for CSS light card styling
            st.markdown('<div class="light-panel-marker"></div>', unsafe_allow_html=True)
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
if st.session_state.active_page == "command_center":
    render_command_center()
elif st.session_state.active_page == "review_inbox":
    render_review_inbox()
elif st.session_state.active_page == "creative_studio":
    render_creative_studio()
elif st.session_state.active_page == "analytics_ledger":
    render_analytics_ledger()
else:
    st.session_state.active_page = "command_center"
    safe_rerun()