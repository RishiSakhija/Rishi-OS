"""5. Packaging Studio -- draft platform-ready posts from one angle.

Takes the top angle from the Idea Strategist and drafts for each platform.
Output is always `needs_review`: a human decides what ships (AGENTS.md Rule 6).
"""

from __future__ import annotations

from core import brands, config, db, logger

from . import _pattern

NAME = "packaging_studio"
BRAND = "edivic"
STATUS = "needs_review"
REQUIRED = ("LinkedIn", "X Post", "Newsletter Hook")

UPSTREAM = "idea_strategist"
ANGLE_CHARS = 1800

# Fallback if prompts/packaging_studio.md is missing.
FALLBACK_TEMPLATE = """{{BRAND}}

ANGLE TO PACKAGE:
{{CONTEXT}}

TASK -- draft platform-ready posts for this one angle. Use exactly these
markdown headings:

## LinkedIn
One post, 120-200 words. Opens with a specific claim, no throat-clearing.

## X Post
One post, under 260 characters. No hashtags.

## Newsletter Hook
3-5 sentences that would make someone open the email. Ends with the payoff.
"""


def _top_angle() -> str:
    """Most recent strategist output. Plain code only."""
    try:
        rows = (
            db.client()
            .table("outputs")
            .select("clean,created_at")
            .eq("agent", UPSTREAM)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.log_run(NAME, "skipped", notes=f"outputs_unavailable: {exc}")
        return ""

    if not rows:
        return ""
    return (rows[0].get("clean") or "").strip()[:ANGLE_CHARS]


def _template() -> str:
    """Prompt from prompts/packaging_studio.md, falling back to the inline copy."""
    return config.load_prompt(NAME) or FALLBACK_TEMPLATE


def build_prompt(brand: dict) -> str:
    angle = _top_angle()
    if not angle:
        return ""
    return config.render_prompt(
        _template(),
        brand=brands.describe(brand),
        context=angle,
    )


def main() -> int:
    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=build_prompt,
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=1000,
        temperature=0.7,
    )


if __name__ == "__main__":
    raise SystemExit(main())
