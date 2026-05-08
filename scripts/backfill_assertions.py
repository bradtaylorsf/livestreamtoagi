#!/usr/bin/env python3
"""Backfill baseline phase_assertions for recent completed simulations.

Older simulations were run before the orchestrator emitted baseline
conversation assertions for every phase, so their Assertions tab is empty.
This script synthesizes a PhaseResult per recent simulation (aggregated
from the conversations + simulation rows) and writes the four baseline
assertions (min_turns, max_cost, no_errors, management_flags) to the
phase_assertions table so the UI immediately shows non-empty results.

Usage:
    python scripts/backfill_assertions.py
    python scripts/backfill_assertions.py --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def run_backfill(*, limit: int, dry_run: bool) -> int:
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.assertion_repo import AssertionRepo
    from core.simulation.assertions import AssertionEngine
    from core.simulation.phases import PhaseResult

    svc = await bootstrap_services(auto_migrate=True)
    try:
        rows = await svc.db.fetch(
            """SELECT id, name, total_turns, total_cost, total_overseer_flags,
                      total_artifacts, agents_participated
               FROM simulations
               WHERE status = 'completed'
               ORDER BY started_at DESC
               LIMIT $1""",
            limit,
        )
        print(f"Backfill candidates: {len(rows)}")

        repo = AssertionRepo(svc.db) if not dry_run else None
        engine = AssertionEngine(assertion_repo=repo)
        written = 0
        for row in rows:
            sim_id = row["id"]
            existing = await svc.db.fetchval(
                "SELECT COUNT(*) FROM phase_assertions WHERE simulation_id = $1",
                sim_id,
            )
            if existing and int(existing) > 0:
                print(f"  skip {row['name']} ({sim_id}): {existing} existing rows")
                continue

            agents = list(row["agents_participated"] or [])
            phase_result = PhaseResult(
                status="completed",
                turns=int(row["total_turns"] or 0),
                cost=Decimal(row["total_cost"] or 0),
                artifacts=int(row["total_artifacts"] or 0),
                management_flags=int(row["total_overseer_flags"] or 0),
                agents_participated=agents,
            )
            if dry_run:
                print(f"  would write 4 assertions for {row['name']} ({sim_id})")
                written += 4
                continue

            results = await engine.evaluate_conversation_defaults(
                phase_result,
                sim_id,
                config={},
                phase_name="backfill_summary",
            )
            written += len(results)
            print(f"  wrote {len(results)} assertions for {row['name']} ({sim_id})")

        print(f"Total assertions written: {written}")
        return written
    finally:
        await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="How many recent completed simulations to backfill (default: 5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without inserting rows.",
    )
    args = parser.parse_args()
    asyncio.run(run_backfill(limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
