#!/usr/bin/env python3
"""Post-run validation: check that all 21 agent tools were exercised.

Usage:
    python scripts/check_tool_coverage.py --name "tool-coverage"
    python scripts/check_tool_coverage.py --simulation-id <uuid>

Exits with code 0 if 21/21 tools found, 1 otherwise.
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

# All 21 tools that should be exercised
ALL_TOOLS = sorted([
    "send_message",
    "get_world_state",
    "get_audience_status",
    "send_chat_message",
    "create_poll",
    "get_poll_results",
    "recall_memory",
    "retrieve_transcript",
    "update_core_memory",
    "execute_code",
    "generate_tilemap",
    "web_search",
    "fetch_url",
    "draft_social_post",
    "draft_email",
    "get_revenue_status",
    "dispatch_alpha",
    "propose_self_modification",
    "view_evolution_log",
])


async def check_coverage(args: argparse.Namespace) -> bool:
    """Query artifacts table and report tool coverage."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.simulation_repo import SimulationRepo

    svc = await bootstrap_services()
    sim_repo = SimulationRepo(svc.db)

    # Resolve simulation ID
    simulation_id = None
    if args.simulation_id:
        import uuid

        simulation_id = uuid.UUID(args.simulation_id)
    elif args.name:
        sims = await sim_repo.list(limit=100)
        for s in sims:
            if s.name == args.name:
                simulation_id = s.id
                break
        if simulation_id is None:
            print(f"ERROR: No simulation found with name '{args.name}'")
            await shutdown_services(svc)
            return False
    else:
        print("ERROR: Provide --name or --simulation-id")
        await shutdown_services(svc)
        return False

    # Query artifacts for this simulation
    query = """
        SELECT DISTINCT tool_name, agent_id, status,
               MIN(created_at) as first_used
        FROM artifacts
        WHERE simulation_id = $1
        GROUP BY tool_name, agent_id, status
        ORDER BY tool_name
    """
    rows = await svc.db.fetch(query, simulation_id)
    await shutdown_services(svc)

    # Build coverage map
    found_tools: dict[str, dict] = {}
    for row in rows:
        tool = row["tool_name"]
        if tool not in found_tools:
            found_tools[tool] = {
                "agent": row["agent_id"],
                "status": row["status"],
                "first_used": row["first_used"],
            }

    # Report
    print(f"\n{'Tool Coverage Report':=^60}")
    print(f"Simulation: {simulation_id}\n")

    found_count = 0
    error_count = 0

    for tool in ALL_TOOLS:
        if tool in found_tools:
            info = found_tools[tool]
            status_marker = "OK" if info["status"] == "executed" else "ERR"
            if info["status"] != "executed":
                error_count += 1
            found_count += 1
            print(f"  [{status_marker}] {tool:<30} agent={info['agent']}")
        else:
            print(f"  [--] {tool:<30} MISSING")

    # Check for tools in artifacts not in our expected list
    extra = set(found_tools.keys()) - set(ALL_TOOLS)
    if extra:
        print(f"\nExtra tools found (not in expected list): {extra}")

    print(f"\n{'Summary':=^60}")
    print(f"  Coverage: {found_count}/{len(ALL_TOOLS)} tools exercised")
    if error_count:
        print(f"  Errors:   {error_count} tools had non-executed status")
    print()

    return found_count == len(ALL_TOOLS) and error_count == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check tool coverage for a simulation run"
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Simulation name to check",
    )
    parser.add_argument(
        "--simulation-id",
        type=str,
        help="Simulation UUID to check",
    )

    args = parser.parse_args()
    if not args.name and not args.simulation_id:
        parser.error("Either --name or --simulation-id must be provided")

    success = asyncio.run(check_coverage(args))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
