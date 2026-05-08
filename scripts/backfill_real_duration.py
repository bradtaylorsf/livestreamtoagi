#!/usr/bin/env python3
"""Backfill simulations.real_duration from started_at and completed_at.

Earlier versions of the orchestrator persisted the duration of the in-process
tick loop instead of wall-clock time, so legacy rows show ``Real: 0s`` /
``Real: 1s`` even when the simulation took hours.  This script repopulates
``real_duration`` for every row where the column is NULL (or zero) but both
``started_at`` and ``completed_at`` are set.

Usage:
    python scripts/backfill_real_duration.py
    python scripts/backfill_real_duration.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def run_backfill(dry_run: bool) -> int:
    from core.bootstrap import bootstrap_services, shutdown_services

    svc = await bootstrap_services(auto_migrate=True)
    try:
        candidates = await svc.db.fetch(
            """SELECT id, name, started_at, completed_at, real_duration
               FROM simulations
               WHERE completed_at IS NOT NULL
                 AND started_at IS NOT NULL
                 AND (real_duration IS NULL
                      OR real_duration < INTERVAL '2 seconds')""",
        )
        print(f"Candidates for backfill: {len(candidates)}")
        for row in candidates:
            delta = row["completed_at"] - row["started_at"]
            print(
                f"  {row['name']} ({row['id']}): "
                f"current={row['real_duration']} -> {delta}"
            )

        if dry_run:
            print("Dry run — no rows updated.")
            return 0

        result = await svc.db.execute(
            """UPDATE simulations
               SET real_duration = completed_at - started_at
               WHERE completed_at IS NOT NULL
                 AND started_at IS NOT NULL
                 AND (real_duration IS NULL
                      OR real_duration < INTERVAL '2 seconds')""",
        )
        try:
            updated = int(result.split()[-1])
        except (ValueError, IndexError, AttributeError):
            updated = -1
        print(f"Updated {updated} simulation rows.")
        return updated
    finally:
        await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidate rows without updating.",
    )
    args = parser.parse_args()
    asyncio.run(run_backfill(args.dry_run))


if __name__ == "__main__":
    main()
