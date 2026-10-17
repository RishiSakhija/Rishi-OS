"""Supabase datahouse access + de-duplication.

Plain code only (AGENTS.md Rule 1). No AI here, ever.

The client is created lazily so that importing `core` never requires
credentials -- only actually touching the database does.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from . import config

_client: Any = None


class DatahouseError(RuntimeError):
    """Raised when the datahouse is unreachable or misconfigured."""


def client() -> Any:
    """Return the shared Supabase client, creating it on first use."""
    global _client
    if _client is not None:
        return _client

    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        raise DatahouseError(
            "SUPABASE_URL and SUPABASE_KEY must be set in .env before "
            "the datahouse can be used."
        )

    from supabase import create_client

    _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def utcnow() -> str:
    """ISO-8601 UTC timestamp, seconds precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# De-duplication (AGENTS.md Rule 8 / Data Conventions)
#
# Both keys are used, not either: content hash catches reposts, URL match
# catches the same source re-fetched.
# --------------------------------------------------------------------------
_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip. Deterministic, no model."""
    return _WS.sub(" ", (text or "").lower()).strip()


def content_hash(text: str) -> str:
    """SHA-256 of normalised content."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def seen_url(url: str) -> bool:
    """True when this source URL has already produced an output."""
    if not url:
        return False
    rows = (
        client()
        .table("outputs")
        .select("id")
        .eq("source_url", url)
        .limit(1)
        .execute()
    )
    return bool(rows.data)


def seen_hash(digest: str) -> bool:
    """True when this content hash has already been stored."""
    if not digest:
        return False
    rows = (
        client()
        .table("outputs")
        .select("id")
        .eq("hash", digest)
        .limit(1)
        .execute()
    )
    return bool(rows.data)


def is_duplicate(text: str = "", url: str = "") -> bool:
    """Dedupe on content hash *and* URL match."""
    return seen_hash(content_hash(text)) or seen_url(url)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------
def get_agent(name: str) -> dict | None:
    """Fetch one row from `agents`, or None when the agent is unregistered."""
    rows = client().table("agents").select("*").eq("name", name).limit(1).execute()
    return rows.data[0] if rows.data else None


def get_brand(key: str) -> dict | None:
    """Fetch one row from `brands`, or None."""
    rows = client().table("brands").select("*").eq("key", key).limit(1).execute()
    return rows.data[0] if rows.data else None


def recent_outputs(agent: str | None = None, limit: int = 20) -> list[dict]:
    """Most recent outputs, newest first."""
    query = client().table("outputs").select("*")
    if agent:
        query = query.eq("agent", agent)
    return query.order("created_at", desc=True).limit(limit).execute().data


def list_agents() -> list[dict]:
    """Entire agent registry."""
    return client().table("agents").select("*").order("name").execute().data


def list_brands() -> list[dict]:
    """Entire brand registry."""
    return client().table("brands").select("*").order("key").execute().data


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------
def save_output(
    *,
    agent: str,
    raw: str,
    clean: str,
    status: str = config.STATUS_DRAFT,
    brand: str | None = None,
    source_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    meta: dict | None = None,
) -> dict | None:
    """Persist a generated output.

    Refuses any status outside WRITE_STATUSES -- agents never publish
    (AGENTS.md Rule 6). Returns the inserted row.
    """
    if status not in config.WRITE_STATUSES:
        raise ValueError(
            f"refusing to save status={status!r}; agents may only write "
            f"{sorted(config.WRITE_STATUSES)}"
        )

    row = {
        "agent": agent,
        "brand": brand,
        "raw": raw,
        "clean": clean,
        "hash": content_hash(clean or raw),
        "source_url": source_url,
        "model": model,
        "provider": provider,
        "status": status,
        "meta": meta or {},
        "created_at": utcnow(),
    }
    result = client().table("outputs").insert(row).execute()
    return result.data[0] if result.data else None


def bump_agent_run(agent: str) -> None:
    """Increment the agent's run counter for today."""
    row = get_agent(agent)
    if not row:
        return
    client().table("agents").update(
        {"runs_today": int(row.get("runs_today") or 0) + 1}
    ).eq("name", agent).execute()


def save_task(*, agent: str, payload: dict, status: str = "queued") -> dict | None:
    """Queue a unit of work for a future cron tick."""
    result = (
        client()
        .table("tasks")
        .insert(
            {
                "agent": agent,
                "payload": payload,
                "status": status,
                "created_at": utcnow(),
            }
        )
        .execute()
    )
    return result.data[0] if result.data else None


def save_note(*, body: str, brand: str | None = None, kind: str = "note") -> dict | None:
    """Append a human note / growth journal entry."""
    result = (
        client()
        .table("notes")
        .insert(
            {
                "brand": brand,
                "kind": kind,
                "body": body,
                "created_at": utcnow(),
            }
        )
        .execute()
    )
    return result.data[0] if result.data else None


def record_usage(*, agent: str, provider: str, model: str, calls: int = 1,
                 chars_in: int = 0, chars_out: int = 0) -> None:
    """Append to the zero-budget usage ledger."""
    client().table("usage").insert(
        {
            "agent": agent,
            "provider": provider,
            "model": model,
            "calls": calls,
            "chars_in": chars_in,
            "chars_out": chars_out,
            "created_at": utcnow(),
        }
    ).execute()
