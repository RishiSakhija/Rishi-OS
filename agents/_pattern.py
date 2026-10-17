"""The standard 5-step agent pattern, implemented exactly once.

AGENTS.md Rule 7 defines a fixed shape for every agent in `/agents`. Rather
than copy-paste that shape seven times and drift, it lives here. Each agent
supplies only what is genuinely agent-specific:

    NAME, BRAND, STATUS, REQUIRED_SECTIONS, build_prompt(brand) -> str

Order of operations, always:

    1. caps.check_can_run      (enabled + daily_cap)
    2. brands.load_brand       + plain-code fetch assembled in build_prompt
    3. router.call_llm         (exactly one call)
    4. validator.validate_output, then save raw AND clean to `outputs`
    5. logger.log_run          (telemetry)

`execute` always returns 0. Always. A failed run logs `status="failed"` and
exits clean so GitHub Actions never loops (AGENTS.md Rule 5).
"""

from __future__ import annotations

import time
from typing import Callable

from core import brands, caps, config, db, logger, router, validator


def execute(
    *,
    agent: str,
    brand_key: str,
    prompt_builder: Callable[[dict], str],
    required_sections: tuple[str, ...] = (),
    status: str = config.STATUS_NEEDS_REVIEW,
    max_tokens: int = 900,
    temperature: float = 0.4,
    source_url: str | None = None,
) -> int:
    """Run one agent, once. Returns 0 in every case."""
    started = time.monotonic()

    if status not in config.WRITE_STATUSES:
        logger.log_failure(
            agent,
            ValueError(f"agent declared non-publishable status {status!r}"),
            started_at=started,
        )
        return 0

    # ---- Step 1: hard caps -------------------------------------------------
    allowed, reason = caps.explain(agent)
    if not allowed:
        logger.log_skip(agent, reason)
        return 0

    result = None
    try:
        # ---- Step 2: brand + plain-code fetch ------------------------------
        brand = brands.load_brand(brand_key)
        prompt, truncated = validator.fit(prompt_builder(brand))
        if not prompt.strip():
            logger.log_run(agent, config.STATUS_SKIPPED, notes="nothing_to_do",
                           started_at=started)
            return 0

        # ---- Step 3: exactly one model call --------------------------------
        result = router.call_llm(
            prompt,
            agent=agent,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not result.ok:
            logger.log_run(
                agent,
                config.STATUS_FAILED,
                calls=result.calls,
                notes=result.notes or "router returned no text",
                started_at=started,
            )
            return 0

        # ---- Step 4: validate, then persist raw AND clean ------------------
        clean = validator.validate_output(
            result.text, required_sections=required_sections
        )
        db.save_output(
            agent=agent,
            brand=brand_key,
            raw=result.text,
            clean=clean,
            status=status,
            source_url=source_url,
            model=result.model,
            provider=result.provider,
            meta={"input_truncated": truncated, "attempts": result.attempts},
        )
        db.bump_agent_run(agent)

        # ---- Step 5: telemetry --------------------------------------------
        logger.log_run(
            agent,
            "ok",
            model=result.model,
            provider=result.provider,
            calls=result.calls,
            notes=validator.summarise(result.notes)
            + (f" | truncated" if truncated else ""),
            started_at=started,
        )

    except Exception as exc:  # noqa: BLE001 - fail cheap, never re-raise
        logger.log_run(
            agent,
            config.STATUS_FAILED,
            model=getattr(result, "model", None),
            provider=getattr(result, "provider", None),
            calls=getattr(result, "calls", 0),
            notes=f"{type(exc).__name__}: {exc}",
            started_at=started,
        )

    return 0
