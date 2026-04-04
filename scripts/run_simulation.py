#!/usr/bin/env python3
"""CLI entry point for the full-day simulation orchestrator.

Usage:
    python scripts/run_simulation.py \\
      --name "test-run-001" \\
      --description "First full day test" \\
      --seed-file scenarios/full_day.yaml \\
      --agents vera,rex,aurora,pixel,fork,sentinel,grok \\
      --max-cost 10.00 \\
      --verbose

    python scripts/run_simulation.py \\
      --name "dry-run" \\
      --seed-file scenarios/full_day.yaml \\
      --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_AGENTS = "vera,rex,aurora,pixel,fork,sentinel,grok"


async def run_simulation(args: argparse.Namespace) -> None:
    """Main async entry point."""
    verbose = getattr(args, "verbose", False)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from core.bootstrap import bootstrap_services, shutdown_services
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.event_bus import event_bus
    from core.memory.reflection import ReflectionManager
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.display import SimulationDisplay
    from core.simulation.orchestrator import SimulationConfig, SimulationOrchestrator

    # ── Parse simulation config ───────────────────────────
    agents = [a.strip() for a in args.agents.split(",")]

    sim_config = SimulationConfig(
        name=args.name,
        description=args.description,
        seed_file=args.seed_file,
        agents=agents,
        max_cost=args.max_cost,
        speed=args.speed,
        dry_run=args.dry_run,
        verbose=verbose,
        overseer_shadow=args.overseer_shadow,
    )
    sim_config.load_seed_file()

    # ── Connect services ──────────────────────────────────
    svc = await bootstrap_services()
    cfg = svc.config_loader.config

    conversation_repo = ConversationRepo(svc.db)
    simulation_repo = SimulationRepo(svc.db)

    if sim_config.overseer_shadow:
        from core.overseer import Overseer

        overseer = Overseer(
            redis_client=svc.redis,
            llm_client=svc.llm_client,
            event_bus=event_bus,
            shadow_mode=True,
            db=svc.db,
        )
    else:
        overseer = svc.overseer

    proximity = ProximityManager(svc.redis, cfg, event_bus)
    trigger_system = TriggerSystem(cfg.triggers, svc.recall_memory)
    selection_logger = SelectionLogger(conversation_repo, cfg.logging)

    reflection_manager = ReflectionManager(
        memory_repo=svc.memory_repo,
        llm_client=svc.llm_client,
        core_memory_mgr=svc.core_memory,
        token_counter=svc.token_counter,
        agent_registry=svc.agent_registry,
    )

    display = SimulationDisplay(verbose=verbose)

    # ── Build orchestrator ────────────────────────────────
    orchestrator = SimulationOrchestrator(
        config=sim_config,
        db=svc.db,
        redis_client=svc.redis,
        simulation_repo=simulation_repo,
        config_loader=svc.config_loader,
        agent_registry=svc.agent_registry,
        event_bus=event_bus,
        llm_client=svc.llm_client,
        overseer=overseer,
        context_assembler=svc.context_assembler,
        conversation_repo=conversation_repo,
        archival_memory=svc.archival_memory,
        proximity=proximity,
        trigger_system=trigger_system,
        selection_logger=selection_logger,
        reflection_manager=reflection_manager,
        display=display,
    )

    # ── Signal handling ───────────────────────────────────
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        from core.simulation.display import console
        console.print("\n[dim]Cancelling simulation...[/dim]")
        orchestrator.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # ── Run ───────────────────────────────────────────────
    await orchestrator.run()

    # ── Cleanup ───────────────────────────────────────────
    await shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a full-day simulation of the AI reality show"
    )
    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="Name for this simulation run",
    )
    parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Description of the simulation",
    )
    parser.add_argument(
        "--seed-file",
        type=str,
        required=True,
        help="Path to the YAML seed file defining phases",
    )
    parser.add_argument(
        "--agents",
        type=str,
        default=DEFAULT_AGENTS,
        help=f"Comma-separated agent names (default: {DEFAULT_AGENTS})",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=10.0,
        help="Maximum cost in dollars before stopping (default: 10.00)",
    )
    parser.add_argument(
        "--speed",
        type=str,
        choices=["fast", "normal"],
        default="fast",
        help="Simulation speed (fast=skip idle, normal=real pacing)",
    )
    parser.add_argument(
        "--overseer-shadow",
        action="store_true",
        default=True,
        help="Run Overseer in shadow/log-only mode (default: True)",
    )
    parser.add_argument(
        "--no-overseer-shadow",
        action="store_false",
        dest="overseer_shadow",
        help="Run Overseer in full enforcement mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would execute without making LLM calls",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    asyncio.run(run_simulation(args))


if __name__ == "__main__":
    main()
