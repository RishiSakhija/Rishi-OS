"""3. Summarize Librarian -- compress long-form input into a library entry.

Step 2 is the heaviest plain-code step in the roster: pull queued source text
from `tasks`, or fetch a URL and strip its HTML, then trim hard to the input
ceiling before the model ever sees it.
"""

from __future__ import annotations

import re

import requests

from core import brands, config, db, logger

from . import _pattern

NAME = "summarize_librarian"
BRAND = "personal"
STATUS = "draft"
REQUIRED = ("Summary", "Key Points", "Library Tags")

_SOURCE_BUDGET = config.MAX_INPUT_CHARS - 800  # leave room for instructions
_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

FALLBACK_SOURCE = (
    "No source was queued. Summarise the following principle instead: a system "
    "that runs on a schedule, makes one decision per run, and stores every "
    "result for human review will outperform an elaborate system that nobody "
    "trusts."
)

# Fallback if prompts/summarize_librarian.md is missing.
FALLBACK_TEMPLATE = """{{BRAND}}

SOURCE TEXT:
\"\"\"
{{CONTEXT}}
\"\"\"

TASK -- library entry. Compress the source above using exactly these markdown
headings:

## Summary
3-5 sentences capturing the argument, not the wording.

## Key Points
3-6 bullets, each one idea, each useful on its own.

## Library Tags
4-8 comma-separated lowercase tags for retrieval.
"""


def _strip_html(html: str) -> str:
    text = _TAGS.sub(" ", html or "")
    text = _ANY_TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _fetch(url: str) -> str:
    response = requests.get(
        url, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": "Rishi-OS/1.0"}
    )
    response.raise_for_status()
    return _strip_html(response.text)


def _source_text() -> tuple[str, str | None]:
    """Return (text, source_url). Plain code only."""
    try:
        rows = (
            db.client()
            .table("tasks")
            .select("*")
            .eq("agent", NAME)
            .eq("status", "queued")
            .order("created_at")
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.log_run(NAME, "skipped", notes=f"tasks_unavailable: {exc}")
        return FALLBACK_SOURCE, None

    if not rows:
        return FALLBACK_SOURCE, None

    payload = rows[0].get("payload") or {}
    inline = (payload.get("text") or "").strip()
    if inline:
        return inline, None

    url = (payload.get("url") or "").strip()
    if url:
        # Dedupe: never summarise the same URL twice (AGENTS.md Rule 8).
        try:
            if db.seen_url(url):
                logger.log_run(NAME, config.STATUS_SKIPPED, notes=f"already_seen: {url}")
                return "", url
        except Exception:  # noqa: BLE001 - if we cannot check, fetch anyway
            pass
        try:
            return _fetch(url), url
        except Exception as exc:  # noqa: BLE001
            logger.log_run(NAME, "skipped", notes=f"fetch_failed: {exc}")
            return FALLBACK_SOURCE, None

    return FALLBACK_SOURCE, None


def _template() -> str:
    """Prompt from prompts/summarize_librarian.md, falling back to the inline copy."""
    return config.load_prompt(NAME) or FALLBACK_TEMPLATE


def build_prompt(brand: dict, source: str) -> str:
    """Assemble the prompt from an already-fetched source. Plain code."""
    return config.render_prompt(
        _template(),
        brand=brands.describe(brand),
        context=source,
    )


def main() -> int:
    # Fetch once (Rule 8: never fetch or summarise the same thing twice).
    raw, url = _source_text()
    source, _ = config.trim(raw, _SOURCE_BUDGET)

    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=lambda brand: build_prompt(brand, source),
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=800,
        temperature=0.3,
        source_url=url,
    )


if __name__ == "__main__":
    raise SystemExit(main())
