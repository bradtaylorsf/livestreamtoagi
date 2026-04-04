#!/usr/bin/env python3
"""Restore agent memory state from a JSON snapshot.

Usage:
    python scripts/restore_memory.py --snapshot snapshots/day3.json
    python scripts/restore_memory.py --snapshot snapshots/day3.json --agents rex,fork
    python scripts/restore_memory.py --snapshot snapshots/day3.json --clear-first
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


async def run_restore(args: argparse.Namespace) -> None:
    from core.bootstrap import bootstrap_services, make_embedding_fn, shutdown_services
    from core.memory.snapshot import MemorySnapshotImporter

    svc = await bootstrap_services(auto_migrate=True)
    try:
        snapshot_data = json.loads(Path(args.snapshot).read_text())

        import os

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        embedding_fn = make_embedding_fn(svc.http_client, api_key) if svc.http_client else None

        importer = MemorySnapshotImporter(
            db=svc.db,
            memory_repo=svc.memory_repo,
            core_memory_mgr=svc.core_memory,
            recall_memory_mgr=svc.recall_memory,
            relationship_repo=svc.relationship_repo,
            embedding_fn=embedding_fn,
        )

        agents = None
        if args.agents:
            agents = [a.strip() for a in args.agents.split(",")]

        result = await importer.restore(
            snapshot_data,
            simulation_id=args.simulation_id,
            agents=agents,
            clear_first=args.clear_first,
        )

        print(f"Restore complete:")
        print(f"  Agents: {result.agents_restored}")
        print(f"  Core memories: {result.core_memories_restored}")
        print(f"  Recall memories: {result.recall_memories_restored}")
        print(f"  Journal entries: {result.journal_entries_restored}")
        print(f"  Relationships: {result.relationships_restored}")
        if result.warnings:
            print(f"  Warnings ({len(result.warnings)}):")
            for w in result.warnings:
                print(f"    - {w}")
    finally:
        await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore memory from snapshot")
    parser.add_argument(
        "--snapshot", type=str, required=True,
        help="Path to the JSON snapshot file",
    )
    parser.add_argument(
        "--agents", type=str, default=None,
        help="Comma-separated agent IDs to restore (default: all)",
    )
    parser.add_argument(
        "--clear-first", action="store_true",
        help="Clear existing recall/journal state before restore",
    )
    parser.add_argument(
        "--simulation-id", type=str, default=None,
        help="Simulation ID to associate restored relationships with",
    )
    asyncio.run(run_restore(parser.parse_args()))


if __name__ == "__main__":
    main()
