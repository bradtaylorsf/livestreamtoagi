#!/usr/bin/env python3
"""Export a simulation's memory state to a portable JSON snapshot.

Usage:
    python scripts/snapshot_memory.py --simulation-id <uuid> --output snapshots/day3.json
    python scripts/snapshot_memory.py --simulation-id <uuid> --output my.json --agents rex,fork
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def run_export(args: argparse.Namespace) -> None:
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.memory.snapshot import MemorySnapshotExporter

    svc = await bootstrap_services(auto_migrate=True)
    try:
        exporter = MemorySnapshotExporter(
            db=svc.db,
            memory_repo=svc.memory_repo,
            relationship_repo=svc.relationship_repo,
        )

        agents = None
        if args.agents:
            agents = [a.strip() for a in args.agents.split(",")]

        snapshot = await exporter.export(args.simulation_id, agents=agents)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(snapshot, indent=2, default=str))
        print(f"Snapshot exported to {output_path}")
        print(f"  Agents: {list(snapshot.get('agents', {}).keys())}")
        print(f"  Relationships: {len(snapshot.get('relationships', []))}")
    finally:
        await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export simulation memory snapshot")
    parser.add_argument(
        "--simulation-id", type=str, required=True,
        help="UUID of the simulation to snapshot",
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Output file path for the JSON snapshot",
    )
    parser.add_argument(
        "--agents", type=str, default=None,
        help="Comma-separated agent IDs to include (default: all)",
    )
    asyncio.run(run_export(parser.parse_args()))


if __name__ == "__main__":
    main()
