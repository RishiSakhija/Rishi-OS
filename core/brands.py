"""Brand profile loading (AGENTS.md Rule 7, Step 2).

Plain code only. No AI.

Profiles live in the `brands` table so the dashboard can edit voice and
audience without a deploy. A sane default keeps agents runnable on a brand-new
database with an empty `brands` table.
"""

from __future__ import annotations

from . import config, db

DEFAULT_BRAND: dict = {
    "key": "default",
    "name": "Rishi-OS",
    "voice": "direct, practical, first-person; no corporate filler",
    "audience": "founders and operators building zero-budget systems",
    "platforms": "linkedin, x, newsletter",
    "always": "concrete numbers, plain language, one clear takeaway",
    "never": "hype, engagement bait, unsupported claims, emoji walls",
}


def load_brand(key: str | None = None) -> dict:
    """Return a brand profile, falling back to DEFAULT_BRAND.

    Never raises on a missing row: an agent with a generic voice is better
    than an agent that crashes because someone typo'd a brand key.
    """
    key = key or DEFAULT_BRAND["key"]
    try:
        row = db.get_brand(key)
    except Exception:  # noqa: BLE001 - degrade to the default voice
        row = None
    return row or {**DEFAULT_BRAND, "key": key}


def describe(brand: dict | None = None) -> str:
    """Render a brand profile as a compact prompt block (< 4000 chars).

    Trimmed defensively so brand data can never blow the input ceiling.
    """
    brand = brand or DEFAULT_BRAND
    lines = [
        f"BRAND: {brand.get('name', 'unnamed')}",
        f"Voice: {brand.get('voice', '')}",
        f"Audience: {brand.get('audience', '')}",
        f"Platforms: {brand.get('platforms', '')}",
        f"Always: {brand.get('always', '')}",
        f"Never: {brand.get('never', '')}",
    ]
    text = "\n".join(line for line in lines if line.split(":", 1)[-1].strip())
    trimmed, _ = config.trim(text)
    return trimmed
