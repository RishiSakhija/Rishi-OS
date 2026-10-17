"""2. Growth Coach Agent -- personal progress and habit coaching.

Plain code pulls the last few `notes` for the person; the model only does the
thinking about what to focus on next.
"""

from __future__ import annotations

from core import brands, config, db, logger

from . import _pattern

NAME = "growth_coach_agent"
BRAND = "personal"
STATUS = "needs_review"
REQUIRED = ("Focus", "Today's Action", "Watch Out For")

MAX_NOTES = 5

# Fallback if prompts/growth_coach_agent.md is missing.
FALLBACK_TEMPLATE = """{{BRAND}}

CONTEXT -- recent journal entries, newest first:
{{CONTEXT}}

TASK -- daily growth coaching.

Identify the single highest-leverage thing to work on next. Use exactly these
markdown headings:

## Focus
The one thing that matters most right now, and why. 2-4 sentences.

## Today's Action
A concrete action completable today. One paragraph, no hedging.

## Watch Out For
The most likely way this goes wrong, and the guardrail. 1-3 sentences.
"""


def _recent_notes(limit: int = MAX_NOTES) -> list[str]:
    """Recent journal notes, plain code only."""
    try:
        rows = (
            db.client()
            .table("notes")
            .select("body,created_at,kind")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.log_run(NAME, "skipped", notes=f"notes_unavailable: {exc}")
        return []

    notes = []
    for row in rows:
        body = (row.get("body") or "").strip()
        if body:
            notes.append(f"- [{row.get('kind', 'note')}] {body}")
    return notes


def _template() -> str:
    """Prompt from prompts/growth_coach_agent.md, falling back to the inline copy."""
    return config.load_prompt(NAME) or FALLBACK_TEMPLATE


def build_prompt(brand: dict) -> str:
    notes = _recent_notes()
    context = "\n".join(notes) if notes else "- (no recent journal entries)"
    return config.render_prompt(
        _template(),
        brand=brands.describe(brand),
        context=context,
    )


def main() -> int:
    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=build_prompt,
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=800,
        temperature=0.6,
    )


if __name__ == "__main__":
    raise SystemExit(main())
