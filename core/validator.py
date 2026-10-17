"""Template validation (AGENTS.md Rule 7, Step 4).

Plain code only. No AI, and deliberately no "let the model fix it" escape
hatch -- a second model call would break Rule 2.

`validate_output` is the gate between model text and the `outputs` table.
It normalises, strips fences, enforces length, and checks that the sections
the agent's template promised actually came back.
"""

from __future__ import annotations

import re

from . import config

MAX_OUTPUT_CHARS = 12000
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*$", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", re.MULTILINE)


class ValidationError(ValueError):
    """Raised when model output does not satisfy its template."""


def strip_fences(text: str) -> str:
    """Remove markdown code fences the model wrapped around its answer."""
    return _FENCE.sub("", text or "").strip()


def normalise(text: str) -> str:
    """Collapse runs of blank lines and trailing spaces. Deterministic."""
    text = strip_fences(text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sections(text: str) -> dict[str, str]:
    """Split markdown headings into {heading_lowercase: body}."""
    found: dict[str, str] = {}
    matches = list(_HEADING.finditer(text or ""))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[match.group(1).strip().lower()] = text[start:end].strip()
    return found


def validate_output(
    text: str,
    *,
    required_sections: tuple[str, ...] = (),
    min_chars: int = 40,
) -> str:
    """Return cleaned output, or raise ValidationError.

    Checks, in order:
      1. the model returned something at all
      2. it clears `min_chars` (guards against one-word replies)
      3. it fits under MAX_OUTPUT_CHARS
      4. every `required_sections` heading is present
    """
    clean = normalise(text)

    if not clean:
        raise ValidationError("empty output")

    if len(clean) < min_chars:
        raise ValidationError(f"output too short ({len(clean)} chars, min {min_chars})")

    if len(clean) > MAX_OUTPUT_CHARS:
        raise ValidationError(
            f"output too long ({len(clean)} chars, max {MAX_OUTPUT_CHARS})"
        )

    if required_sections:
        present = sections(clean)
        missing = [
            name for name in required_sections
            if not _matches_section(present, name)
        ]
        if missing:
            raise ValidationError(f"missing required sections: {', '.join(missing)}")

    return clean


def _matches_section(present: dict[str, str], wanted: str) -> bool:
    """Loose heading match: 'Angle' matches '## The Angle' and '**Angle**'."""
    wanted = wanted.strip().lower().strip("*#: ").strip()
    if wanted in present:
        return True
    return any(wanted in heading for heading in present)


def summarise(text: str, limit: int = 180) -> str:
    """One-line preview for the dashboard and logs."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "..."


def fit(text: str) -> tuple[str, bool]:
    """Trim prompt input to the hard ceiling (Rule 3)."""
    return config.trim(text, config.MAX_INPUT_CHARS)
