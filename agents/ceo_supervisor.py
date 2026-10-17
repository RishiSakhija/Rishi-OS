"""7. CEO Supervisor -- weekly cross-agent review and prioritisation.

The only agent that looks at the whole system. It reads run telemetry and
recent outputs, then decides what the other six should do next.
"""

from __future__ import annotations

from collections import Counter

from core import brands, db, logger

from . import _pattern

NAME = "ceo_supervisor"
BRAND = "personal"
STATUS = "needs_review"
REQUIRED = ("Week In Review", "Priorities", "Risks")

LOG_WINDOW = 60
OUTPUT_WINDOW = 12
CHARS_PER_OUTPUT = 700


def _system_state() -> str:
    """Aggregate telemetry and recent output. Plain code only."""
    try:
        logs = (
            db.client()
            .table("logs")
            .select("agent,status,model,provider")
            .order("time", desc=True)
            .limit(LOG_WINDOW)
            .execute()
            .data
        )
        outputs = (
            db.client()
            .table("outputs")
            .select("agent,status,clean")
            .order("created_at", desc=True)
            .limit(OUTPUT_WINDOW)
            .execute()
            .data
        )
        agents = db.list_agents()
    except Exception as exc:  # noqa: BLE001
        logger.log_run(NAME, "skipped", notes=f"state_unavailable: {exc}")
        return ""

    run_status = Counter(row.get("status") for row in logs)
    per_agent = Counter(row.get("agent") for row in logs)
    failures = [row for row in logs if row.get("status") == "failed"]

    blocks = [
        f"Registered agents: {len(agents)} "
        f"({sum(1 for a in agents if a.get('enabled'))} enabled)",
        "Recent run statuses: "
        + (", ".join(f"{k}={v}" for k, v in run_status.most_common()) or "none"),
        "Runs by agent: "
        + (", ".join(f"{k}={v}" for k, v in per_agent.most_common()) or "none"),
        f"Failures in window: {len(failures)}",
    ]

    if failures:
        blocks.append("Failure notes:")
        for row in failures[:5]:
            blocks.append(
                f"- {row.get('agent')}: {(row.get('notes') or '')[:160]}"
            )

    if outputs:
        blocks.append("Recent outputs:")
        for row in outputs:
            preview = " ".join((row.get("clean") or "").split())[:CHARS_PER_OUTPUT]
            blocks.append(f"- [{row.get('agent')}/{row.get('status')}] {preview}")

    return "\n".join(blocks)


def build_prompt(brand: dict) -> str:
    state = _system_state()
    if not state:
        return ""
    return f"""{brands.describe(brand)}

SYSTEM STATE (measured, trust these counts):
{state}

TASK -- weekly executive review. You are accountable for the whole system, not
TASK output. Use exactly these markdown headings:

## Week In Review
What the system actually did, and whether the cadence is right. 3-5 sentences.

## Priorities
The next 3 decisions, ranked, each one line with the reason.

## Risks
Where this system is failing, drifting, or wasting money. 2-4 bullets, honest.
"""


def main() -> int:
    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=build_prompt,
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=1000,
        temperature=0.4,
    )


if __name__ == "__main__":
    raise SystemExit(main())
