"""Hard caps: the gate every agent passes through first (AGENTS.md Rule 3).

Plain code only. No AI.

An agent may run only when it is *registered*, `enabled` is true, and it has
not exhausted `daily_cap`. Anything else is a skip, and a skip exits 0.
"""

from __future__ import annotations

from . import config, db


def explain(agent: str) -> tuple[bool, str]:
    """Return (allowed, human_readable_reason).

    The reason is written straight into `logs.notes`, so it must be short and
    specific enough to debug the next morning.
    """
    try:
        row = db.get_agent(agent)
    except Exception as exc:  # noqa: BLE001
        # If the registry is unreachable we cannot prove the agent is allowed.
        # Deny, because a runaway agent costs more than a skipped one.
        return False, f"registry_unavailable: {exc}"

    if not row:
        return False, "not_registered"

    if not row.get("enabled", False):
        return False, "disabled"

    cap = int(row.get("daily_cap") or config.MAX_RUNS_PER_DAY_DEFAULT)
    used = int(row.get("runs_today") or 0)

    if used >= cap:
        return False, f"daily_cap_reached ({used}/{cap})"

    return True, f"ok ({used}/{cap})"


def check_can_run(agent: str) -> bool:
    """True when the agent is enabled and under its daily cap.

    This is the canonical Step 1 name used across `/agents`.
    """
    allowed, _reason = explain(agent)
    return allowed


def can_run(agent: str) -> bool:
    """Alias for `check_can_run`."""
    return check_can_run(agent)


def remaining(agent: str) -> int:
    """Runs left today, floored at zero. Useful for the dashboard."""
    row = db.get_agent(agent) or {}
    cap = int(row.get("daily_cap") or config.MAX_RUNS_PER_DAY_DEFAULT)
    used = int(row.get("runs_today") or 0)
    return max(cap - used, 0)
