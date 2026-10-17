"""1. Research Agent -- find fresh, deduped signal on a topic.

Step 2 is pure plain code: pull queued topics from `tasks`, drop anything
already seen (URL match + content hash), and only then build the prompt.
"""

from __future__ import annotations

from core import brands, db, logger

from . import _pattern

NAME = "research_agent"
BRAND = "edivic"
STATUS = "draft"
REQUIRED = ("Signal", "Why It Matters", "Next Step")

# Used when `tasks` is empty so the agent still does something useful.
DEFAULT_TOPICS = (
    "zero-budget growth tactics for early-stage startups",
    "AI agents that replace paid SaaS tooling",
    "founder-led distribution channels that still work in 2026",
)


def _load_topics(limit: int = 5) -> list[str]:
    """Queued topics from the datahouse, de-duplicated, plain code only."""
    topics: list[str] = []
    try:
        rows = (
            db.client()
            .table("tasks")
            .select("*")
            .eq("agent", NAME)
            .eq("status", "queued")
            .order("created_at")
            .limit(limit)
            .execute()
            .data
        )
        for row in rows:
            payload = row.get("payload") or {}
            topic = (payload.get("topic") or "").strip()
            if topic and topic not in topics and not db.seen_url(topic):
                topics.append(topic)
    except Exception as exc:  # noqa: BLE001 - degrade to the default topic list
        logger.log_run(NAME, "skipped", notes=f"tasks_unavailable: {exc}")

    return topics[:limit] or list(DEFAULT_TOPICS)


def build_prompt(brand: dict) -> str:
    bullets = "\n".join(f"- {topic}" for topic in _load_topics())
    return f"""{brands.describe(brand)}

TASK -- research briefing.

Consider these queued topics:
{bullets}

Pick the single most promising topic and produce a research briefing using
exactly these markdown headings:

## Signal
What is actually happening, in 3-5 sentences. Concrete and specific.

## Why It Matters
Why this matters to this brand's audience. 2-4 sentences.

## Next Step
One concrete action to take this week.
"""


def main() -> int:
    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=build_prompt,
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=900,
        temperature=0.5,
    )


if __name__ == "__main__":
    raise SystemExit(main())
