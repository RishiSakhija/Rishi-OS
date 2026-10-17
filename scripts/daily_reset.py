"""Reset per-agent daily run counters. Called once per day by daily.yml.

Plain code, no AI. Fails cheap: a failed reset must never break the workflow
(AGENTS.md Rule 5).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import db


def main() -> int:
    try:
        db.client().rpc("reset_daily_counters").execute()
        print("daily counters reset")
    except Exception as exc:  # noqa: BLE001 - never fail the cron job
        print(f"counter reset skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
