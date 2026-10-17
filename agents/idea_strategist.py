"""4. Idea Strategist -- turn raw signal into ranked content angles.

Plain code pulls the most recent research briefings out of `outputs` and fetches
fresh web results; the model only ranks and reframes them.
"""

from __future__ import annotations

from core import brands, config, db, logger, search

from . import _pattern

NAME = "idea_strategist"
BRAND = "nowrides"
STATUS = "needs_review"
REQUIRED = ("Angles", "Why These", "First Move")

UPSTREAM = "research_agent"
MAX_SOURCES = 3
CHARS_PER_SOURCE = 1100
DEFAULT_QUERY = "startup content strategy angles"

# Fallback if prompts/idea_strategist.md is missing.
FALLBACK_TEMPLATE = """{{BRAND}}

UPSTREAM SIGNAL (recent research briefings):
{{CONTEXT}}

FRESH WEB RESULTS (fetched moments ago):
{{RESULTS}}

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


def _template() -> str:
    """Prompt from prompts/idea_strategist.md, falling back to the inline copy."""
    return config.load_prompt(NAME) or FALLBACK_TEMPLATE


def build_prompt(brand: dict) -> str:
    signal = _recent_signal()
    context = (
        "\n\n---\n\n".join(signal)
        if signal
        else "(no upstream research found -- reason from first principles)"
    )
    query = _first_heading(signal) or DEFAULT_QUERY
    results = search.web_search(query, max_results=5, agent=NAME)
    return config.render_prompt(
        _template(),
        brand=brands.describe(brand),
        context=context,
        results=search.as_prompt_block(results),
    )


def _first_heading(signal: list[str]) -> str:
    """Derive a search query from the newest briefing's first heading."""
    if not signal:
        return ""
    for line in signal[0].splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("##"):
            return line[:120]
    return ""


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
