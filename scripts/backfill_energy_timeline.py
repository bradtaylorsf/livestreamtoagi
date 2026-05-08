#!/usr/bin/env python3
"""Backfill agent_energy_log rows for completed simulations.

For every completed simulation that has zero ``agent_energy_log`` rows,
read the matching ``conversations`` rows and ``energy_change_log`` deltas
and reconstruct an approximate per-agent, per-turn energy series. Each
conversation seeds its participants at ``initial_energy`` and applies any
deltas recorded in ``energy_change_log.changes`` (looking only at the
``conversation`` channel since per-agent decay is not stored).

When a simulation has neither energy_change_log entries nor any
conversations, the simulation is skipped with a warning marker.

The writer is idempotent — the unique index on
``(simulation_id, agent_id, conversation_id, turn_number)`` lets us re-run
this safely.

Usage:
    python scripts/backfill_energy_timeline.py
    python scripts/backfill_energy_timeline.py --dry-run
    python scripts/backfill_energy_timeline.py --simulation-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid as uuid_mod
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def _backfill_simulation(svc, sim_id: uuid_mod.UUID, dry_run: bool) -> int:
    """Backfill a single simulation. Returns the number of rows written."""
    from core.models import AgentEnergyLogCreate
    from core.repos.conversation_repo import ConversationRepo

    repo = ConversationRepo(svc.db)

    convos = await svc.db.fetch(
        """SELECT id, started_at, initial_energy, participating_agents
               FROM conversations
               WHERE simulation_id = $1
               ORDER BY started_at ASC""",
        sim_id,
    )
    if not convos:
        print(f"  [skip] {sim_id}: no conversations recorded")
        return 0

    entries: list[AgentEnergyLogCreate] = []
    for convo in convos:
        convo_id = convo["id"]
        initial = float(convo["initial_energy"]) if convo["initial_energy"] is not None else 0.0
        participants = convo["participating_agents"] or []
        if isinstance(participants, str):
            participants = json.loads(participants)
        if not participants:
            continue

        deltas = await svc.db.fetch(
            """SELECT turn_number, changes, timestamp
                   FROM energy_change_log
                   WHERE conversation_id = $1
                   ORDER BY turn_number ASC""",
            convo_id,
        )

        running = initial
        # Seed turn 0 at conversation start
        for agent_id in participants:
            entries.append(
                AgentEnergyLogCreate(
                    simulation_id=sim_id,
                    agent_id=agent_id,
                    conversation_id=convo_id,
                    turn_number=0,
                    energy=running,
                )
            )

        for delta in deltas:
            change_blob = delta["changes"]
            if isinstance(change_blob, str):
                try:
                    change_blob = json.loads(change_blob)
                except json.JSONDecodeError:
                    change_blob = {}
            change_blob = change_blob or {}
            # changes is a {reason -> magnitude} dict; sum yields the net delta
            net = sum(float(v) for v in change_blob.values() if isinstance(v, (int, float)))
            running += net
            for agent_id in participants:
                entries.append(
                    AgentEnergyLogCreate(
                        simulation_id=sim_id,
                        agent_id=agent_id,
                        conversation_id=convo_id,
                        turn_number=delta["turn_number"],
                        energy=running,
                    )
                )

    if dry_run:
        print(f"  [dry-run] {sim_id}: would write {len(entries)} rows")
        return 0

    written = await repo.log_agent_energy_bulk(entries)
    print(f"  [ok] {sim_id}: wrote {written} rows (across {len(convos)} convos)")
    return written


async def run_backfill(dry_run: bool, simulation_id: str | None) -> int:
    from core.bootstrap import bootstrap_services, shutdown_services

    svc = await bootstrap_services(auto_migrate=True)
    try:
        if simulation_id:
            sim_ids = [uuid_mod.UUID(simulation_id)]
        else:
            rows = await svc.db.fetch(
                """SELECT s.id FROM simulations s
                       LEFT JOIN agent_energy_log e
                           ON e.simulation_id = s.id
                       WHERE s.completed_at IS NOT NULL
                       GROUP BY s.id
                       HAVING COUNT(e.id) = 0
                       ORDER BY s.completed_at DESC""",
            )
            sim_ids = [r["id"] for r in rows]

        print(f"Simulations needing backfill: {len(sim_ids)}")
        total = 0
        for sid in sim_ids:
            total += await _backfill_simulation(svc, sid, dry_run)
        return total
    finally:
        await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--simulation-id",
        type=str,
        default=None,
        help="Backfill only this simulation_id (UUID).",
    )
    args = parser.parse_args()
    total = asyncio.run(run_backfill(args.dry_run, args.simulation_id))
    if not args.dry_run:
        print(f"Wrote {total} agent_energy_log rows")


if __name__ == "__main__":
    main()
