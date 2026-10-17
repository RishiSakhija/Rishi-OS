"""Drain the task queue: run the named agent for each queued task, then
mark that task `done` or `failed`.

Called by `.github/workflows/poller.yml` every 20 minutes.

Outcome is judged from the agent's own telemetry (AGENTS.md Rule 7, Step 5):
the latest `logs` row for that agent decides the task's fate --

    ok       -> task becomes `done`
    failed   -> task becomes `failed`
    anything else (skipped / cap reached) -> task stays `queued` for later

An agent is run at most once per tick even if it has several queued tasks,
because AGENTS.md Rule 2 allows one model call per run. Remaining tasks stay
queued and drain on later ticks.

Always exits 0 (AGENTS.md Rule 5).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import db

# Task agent name -> importable module path.
AGENT_MODULES = {
    "research_agent": "agents.research_agent",
    "growth_coach_agent": "agents.growth_coach_agent",
    "summarize_librarian": "agents.summarize_librarian",
    "idea_strategist": "agents.idea_strategist",
    "packaging_studio": "agents.packaging_studio",
    "analytics_auditor": "agents.analytics_auditor",
    "ceo_supervisor": "agents.ceo_supervisor",
}

MAX_TASKS = 20


def _run(agent: str) -> bool:
    """Import and run an agent's main(). Returns False if it cannot be run."""
    module_path = AGENT_MODULES.get(agent)
    if not module_path:
        print(f"[queue] unknown agent {agent!r}; leaving queued", file=sys.stderr)
        return False

    try:
        module = importlib.import_module(module_path)
        module.main()
    except Exception as exc:  # noqa: BLE001 - a bad agent must not kill the tick
        print(f"[queue] {agent} raised: {type(exc).__name__}: {exc}", file=sys.stderr)
    return True


def _outcome(agent: str) -> str:
    """Map the agent's latest telemetry status to a task status."""
    try:
        row = db.latest_log(agent) or {}
    except Exception:  # noqa: BLE001 - cannot judge => leave queued
        return "queued"

    status = (row.get("status") or "").strip().lower()
    if status == "ok":
        return "done"
    if status == "failed":
        return "failed"
    return "queued"


def main() -> int:
    try:
        tasks = db.queued_tasks(limit=MAX_TASKS)
    except Exception as exc:  # noqa: BLE001
        print(f"[queue] could not read tasks: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0

    if not tasks:
        print("[queue] nothing queued")
        return 0

    seen: set[str] = set()
    for task in tasks:
        agent = task.get("agent") or ""
        task_id = task.get("id")
        if not task_id:
            continue

        if agent in seen:
            # Already ran this agent once this tick; leave the rest for later.
            print(f"[queue] {agent}: extra task left queued")
            continue

        if not _run(agent):
            continue
        seen.add(agent)

        outcome = _outcome(agent)
        try:
            db.mark_task(task_id, outcome)
        except Exception as exc:  # noqa: BLE001
            print(f"[queue] could not mark {task_id}: {exc}", file=sys.stderr)
            continue
        print(f"[queue] {agent}: task -> {outcome}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - never fail the cron job
        print(f"[queue] fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
