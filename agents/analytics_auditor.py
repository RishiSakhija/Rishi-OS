"""6. Analytics Auditor -- read the numbers, report what actually worked.

Every number here is counted in plain Python. The model is asked only to
interpret, never to compute (AGENTS.md Rule 1).

Runs weekly (Sunday evening) per the blueprint -- see `.github/workflows/weekly.yml`.
"""

from __future__ import annotations

from collections import Counter

from core import brands, config, db, logger

from . import _pattern

NAME = "analytics_auditor"
BRAND = "nowrides"
STATUS = "draft"
REQUIRED = ("What Shipped", "What Worked", "Do Next")

WINDOW = 50

# Fallback if prompts/analytics_auditor.md is missing.
FALLBACK_TEMPLATE = """{{BRAND}}

MEASURED METRICS (counted in plain Python, trust these):
{{CONTEXT}}

TASK -- performance review. Interpret the metrics above. Do not invent numbers
that are not listed. Use exactly these markdown headings:

## What Shipped
What actually got produced. 2-3 sentences.

## What Worked
What the numbers suggest is working, and what looks like noise. 3-5 sentences.

## Do Next
Two or three concrete changes for the next cycle, ranked.
"""


def _metrics() -> str:
    """Count outputs and spend with plain code. No model involved."""
    try:
        outputs = (
            db.client()
            .table("outputs")
            .select("agent,status,provider,created_at")
            .order("created_at", desc=True)
            .limit(WINDOW)
            .execute()
            .data
        )
        usage = (
            db.client()
            .table("usage")
            .select("provider,model,calls")
            .order("created_at", desc=True)
            .limit(WINDOW)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.log_run(NAME, "skipped", notes=f"metrics_unavailable: {exc}")
        return ""

    by_agent = Counter(row.get("agent") for row in outputs)
    by_status = Counter(row.get("status") for row in outputs)
    by_provider = Counter(
        row.get("provider") for row in usage if row.get("provider")
    )
    total_calls = sum(int(row.get("calls") or 0) for row in usage)
    approved = by_status.get("approved", 0)
    total = len(outputs)
    rate = f"{(approved / total * 100):.0f}%" if total else "n/a"

    lines = [
        f"Outputs in last {WINDOW}: {total}",
        f"Approval rate: {rate} ({approved}/{total})",
        "By agent: " + (", ".join(f"{k}={v}" for k, v in by_agent.most_common()) or "none"),
        "By status: " + (", ".join(f"{k}={v}" for k, v in by_status.most_common()) or "none"),
        "By provider: " + (", ".join(f"{k}={v}" for k, v in by_provider.most_common()) or "none"),
        f"Total model calls: {total_calls}",
    ]
    return "\n".join(lines)


def _template() -> str:
    """Prompt from prompts/analytics_auditor.md, falling back to the inline copy."""
    return config.load_prompt(NAME) or FALLBACK_TEMPLATE


def build_prompt(brand: dict) -> str:
    metrics = _metrics()
    if not metrics:
        return ""
    return config.render_prompt(
        _template(),
        brand=brands.describe(brand),
        context=metrics,
    )


def main() -> int:
    return _pattern.execute(
        agent=NAME,
        brand_key=BRAND,
        prompt_builder=build_prompt,
        required_sections=REQUIRED,
        status=STATUS,
        max_tokens=900,
        temperature=0.3,
    )


if __name__ == "__main__":
    raise SystemExit(main())
