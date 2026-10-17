"""4. Idea Strategist -- turn raw signal into ranked content angles.

Plain code pulls the most recent research briefings out of `outputs`; the model
only ranks and reframes them.
"""

from __future__ import annotations

from core import brands, db, logger

from . import _pattern

NAME = "idea_strategist"
BRAND = "nowrides"
STATUS = "needs_review"
REQUIRED = ("Angles", "Why These", "First Move")

UPSTREAM = "research_agent"
MAX_SOURCES = 3
CHARS_PER_SOURCE = 1100


def _recent_signal() -> list[str]:
    """Latest research briefings, newest first. Plain code only."""
    try:
        rows = (
            db.client()
            .table("outputs")
            .select("clean,created_at")
            .eq("agent", UPSTREAM)
            .order("created_at", desc=True)
            .limit(MAX_SOURCES)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.log_run(NAME, "skipped", notes=f"outputs_unavailable: {exc}")
        return []

    signal = []
    for row in rows:
        clean = (row.get("clean") or "").strip()
        if clean:
            signal.append(clean[:CHARS_PER_SOURCE])
    return signal


def build_prompt(brand: dict) -> str:
    signal = _recent_signal()
    context = (
        "\n\n---\n\n".join(signal)
        if signal
        else "(no upstream research found -- reason from first principles)"
    )
    return f"""{brands.describe(brand)}

UPSTREAM SIGNAL (recent research briefings):
{context}

TASK -- content strategy. Convert the signal above into ranked angles using
exactly these markdown headings:

## Angles
Numbered list of 4-6 content angles. Each: one line naming the angle, then one
short line on the specific claim it makes.

## Why These
2-4 sentences on why this ranking, and what was deliberately rejected.

## First Move
The single angle to write first, and the first sentence to open with.
"""


def main() -> int:
    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=build_prompt,
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=900,
        temperature=0.7,
    )


if __name__ == "__main__":
    raise SystemExit(main())
