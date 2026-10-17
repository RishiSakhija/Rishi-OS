"""Append-only run telemetry (AGENTS.md Rule 5).

`log_run` must NEVER raise. Telemetry failing to write is annoying; telemetry
crashing a run and breaking the cron exit code is unacceptable. Every failure
path here degrades to stderr.
"""

from __future__ import annotations

import sys
import time

from . import config, db


def _truncate(value: str | None) -> str:
    value = "" if value is None else str(value)
    if len(value) <= config.MAX_NOTE_CHARS:
        return value
    return value[: config.MAX_NOTE_CHARS - 3] + "..."


def log_run(
    agent: str,
    status: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    calls: int = 0,
    notes: str | None = None,
    started_at: float | None = None,
) -> None:
    """Write one row to `logs`. Swallows every error by design.

    `started_at` is a `time.monotonic()` reading; when given, duration is
    recorded. Returns None always -- callers must not branch on telemetry.
    """
    duration_ms = None
    if started_at is not None:
        duration_ms = int((time.monotonic() - started_at) * 1000)

    row = {
        "agent": agent,
        "time": db.utcnow(),
        "status": status,
        "model": model,
        "provider": provider,
        "calls": int(calls or 0),
        "notes": _truncate(notes),
        "duration_ms": duration_ms,
    }

    try:
        db.client().table("logs").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 - intentional: telemetry never raises
        print(
            f"[logger] could not persist telemetry for {agent}: {exc}",
            file=sys.stderr,
        )


def log_failure(agent: str, error: BaseException, *, started_at: float | None = None) -> None:
    """Convenience wrapper: record a failed run (AGENTS.md Rule 5)."""
    log_run(
        agent,
        config.STATUS_FAILED,
        notes=f"{type(error).__name__}: {error}",
        started_at=started_at,
    )


def log_skip(agent: str, reason: str) -> None:
    """Convenience wrapper: record a skipped run (cap reached / disabled)."""
    log_run(agent, config.STATUS_SKIPPED, notes=reason)
