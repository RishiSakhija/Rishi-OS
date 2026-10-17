"""Central configuration: environment loading + hard ceilings.

Plain code only. No AI, no network calls, no side effects beyond reading .env.

Every limit in this file exists to enforce AGENTS.md Rules 3 and 5. If you are
tempted to raise a ceiling, re-read the rulebook first.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --------------------------------------------------------------------------
# Hard ceilings (AGENTS.md Rule 3) -- these are not suggestions
# --------------------------------------------------------------------------
MAX_INPUT_CHARS = 4000  # every prompt body is trimmed below this
MAX_STEPS = 1  # agents are linear: read, think once, write
MAX_CALLS_PER_RUN = 1  # one model call per run, plus at most one retry
MAX_RUNS_PER_DAY_DEFAULT = 1
HTTP_TIMEOUT = 60  # seconds, per provider attempt
MAX_NOTE_CHARS = 500  # telemetry strings are truncated to this

# --------------------------------------------------------------------------
# Output lifecycle (AGENTS.md Rule 6) -- agents never publish
# --------------------------------------------------------------------------
STATUS_DRAFT = "draft"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

WRITE_STATUSES = {STATUS_DRAFT, STATUS_NEEDS_REVIEW}

# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# --------------------------------------------------------------------------
# Provider registry (AGENTS.md Rule 4)
#
# Order is the fallback chain and is the single source of truth for
# env -> provider -> URL wiring. `core/router.py` walks this list and knows
# nothing else about providers. Adding a provider means editing this list only.
#
# `key_env=None` means the provider is keyless (local Ollama).
# --------------------------------------------------------------------------
PROVIDERS: list[dict] = [
    {
        "id": "deepseek",
        "label": "Provider A",
        "kind": "openai",
        "base": "https://api.deepseek.com",
        "path": "/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    {
        "id": "nvidia",
        "label": "Provider A-fallback",
        "kind": "openai",
        "base": "https://integrate.api.nvidia.com/v1",
        "path": "/chat/completions",
        "key_env": "NVIDIA_API_KEY",
        "model": "meta/llama-3.1-8b-instruct",
    },
    {
        "id": "gemini",
        "label": "Provider B",
        "kind": "gemini",
        "base": "https://generativelanguage.googleapis.com/v1beta",
        "path": "/models/gemini-1.5-flash:generateContent",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-1.5-flash",
    },
    {
        "id": "groq",
        "label": "Provider C",
        "kind": "openai",
        "base": "https://api.groq.com/openai/v1",
        "path": "/chat/completions",
        "key_env": "GROQ_API_KEY",
        "model": "llama-3.1-8b-instant",
    },
    {
        "id": "ollama",
        "label": "Local",
        "kind": "ollama",
        "base": OLLAMA_BASE_URL,
        "path": "/api/chat",
        "key_env": None,
        "model": "llama3.1",
    },
]


def provider_key(provider: dict) -> str:
    """Return the API key for a provider, or '' when it is keyless."""
    env_name = provider.get("key_env")
    if not env_name:
        return ""
    return os.getenv(env_name, "")


def available_providers() -> list[dict]:
    """Providers that can actually be attempted right now.

    Keyless providers always qualify; keyed providers qualify only with a key.
    Plain code: this is a filter, not a judgement call.
    """
    return [
        p for p in PROVIDERS if p["key_env"] is None or provider_key(p)
    ]


def trim(text: str, limit: int = MAX_INPUT_CHARS) -> tuple[str, bool]:
    """Trim `text` to `limit` characters. Returns (text, was_truncated).

    AGENTS.md Rule 3: mark the cut, never silently lose context.
    """
    if text is None:
        return "", False
    text = str(text)
    if len(text) <= limit:
        return text, False
    return text[:limit], True
