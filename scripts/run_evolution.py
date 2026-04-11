#!/usr/bin/env python3
"""Run the evolution loop: simulate → eval → analyze → improve → repeat.

Usage:
    pnpm chat evolve --cycles 3 --auto-apply --max-cost 15.00
    pnpm chat evolve --cycles 1 --review-only
    pnpm chat evolve --history
    pnpm chat evolve --rollback --version 3
    pnpm chat evolve --reset-to-seed
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid as uuid_mod
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table

from core.constants import LIVE_SIMULATION_ID

console = Console()
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evolution loop orchestrator")
    parser.add_argument("--cycles", type=int, default=3, help="Max evolution cycles")
    parser.add_argument("--auto-apply", action="store_true", help="Auto-apply changes (default: review-only)")
    parser.add_argument("--review-only", action="store_true", help="Propose changes without applying")
    parser.add_argument("--max-cost", type=float, default=15.0, help="Max total cost ($)")
    parser.add_argument("--convergence-threshold", type=float, default=2.0)
    parser.add_argument("--regression-threshold", type=float, default=10.0)
    parser.add_argument("--history", action="store_true", help="View evolution history")
    parser.add_argument("--compare", nargs=2, metavar="CYCLE_ID", help="Compare two cycles")
    parser.add_argument("--rollback", action="store_true", help="Rollback to a config version")
    parser.add_argument("--version", type=int, help="Config version to rollback to")
    parser.add_argument("--reset-to-seed", action="store_true", help="Reset all configs to YAML seed defaults")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


async def run_history() -> None:
    """Display evolution loop history."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.evolution_repo import EvolutionRepo

    services = await bootstrap_services()
    try:
        assert services.db is not None
        repo = EvolutionRepo(services.db)
        loops = await repo.get_all_loops(limit=20)

        if not loops:
            console.print("[dim]No evolution loops found.[/dim]")
            return

        table = Table(title="Evolution Loop History", border_style="dim")
        table.add_column("Loop ID", width=10)
        table.add_column("Cycles", justify="right")
        table.add_column("Best Score", justify="right")
        table.add_column("Total Cost", justify="right")
        table.add_column("Status")
        table.add_column("Started")

        for loop in loops:
            table.add_row(
                str(loop["loop_run_id"])[:8],
                str(loop["cycle_count"]),
                f"{float(loop['best_score']):.1f}" if loop.get("best_score") else "N/A",
                f"${float(loop['total_cost']):.4f}" if loop.get("total_cost") else "$0",
                loop.get("final_status", ""),
                str(loop.get("started_at", ""))[:19],
            )

        console.print(table)
    finally:
        await shutdown_services(services)


async def run_compare(cycle_a_id: str, cycle_b_id: str) -> None:
    """Compare two evolution cycles."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.evolution_repo import EvolutionRepo

    services = await bootstrap_services()
    try:
        assert services.db is not None
        repo = EvolutionRepo(services.db)
        try:
            result = await repo.compare_cycles(
                uuid_mod.UUID(cycle_a_id), uuid_mod.UUID(cycle_b_id)
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return

        console.print(f"\n[bold]Cycle A:[/bold] score={result['cycle_a'].get('overall_score')}")
        console.print(f"[bold]Cycle B:[/bold] score={result['cycle_b'].get('overall_score')}")
        console.print(f"[bold]Improvement:[/bold] {result['score_improvement']:.2f}")
    finally:
        await shutdown_services(services)


async def run_rollback(version: int) -> None:
    """Rollback all agents to a specific config version."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.config_version_repo import ConfigVersionRepo

    services = await bootstrap_services()
    try:
        assert services.db is not None
        repo = ConfigVersionRepo(services.db)
        configs = await repo.get_all_active_configs(simulation_id=LIVE_SIMULATION_ID)
        for ac in configs:
            try:
                await repo.rollback_prompt(ac.agent_id, version, simulation_id=LIVE_SIMULATION_ID)
                console.print(f"  [green]Rolled back {ac.agent_id} to v{version}[/green]")
            except ValueError:
                console.print(f"  [yellow]Skipping {ac.agent_id} (v{version} not found)[/yellow]")
        console.print("[bold]Rollback complete.[/bold]")
    finally:
        await shutdown_services(services)


async def run_reset_to_seed() -> None:
    """Reset all configs to YAML seed defaults."""
    from scripts.seed_config import seed_agent_configs

    console.print("[bold]Resetting to seed config...[/bold]")
    # Delete existing versions and re-seed
    from core.bootstrap import bootstrap_services, shutdown_services

    services = await bootstrap_services()
    try:
        assert services.db is not None
        await services.db.execute("DELETE FROM active_config")
        await services.db.execute("DELETE FROM agent_prompt_versions")
        await services.db.execute("DELETE FROM conversation_param_versions")
        console.print("  [dim]Cleared existing config versions[/dim]")
    finally:
        await shutdown_services(services)

    await seed_agent_configs()


async def run_evolution(args: argparse.Namespace) -> None:
    """Run the evolution loop."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.eval.analyzer import EvalAnalyzer
    from core.eval.change_applier import ChangeApplier
    from core.eval.engine import EvalEngine
    from core.eval.evolution_loop import EvolutionLoop
    from core.models import EvolutionConfig
    from core.repos.config_version_repo import ConfigVersionRepo
    from core.repos.eval_repo import EvalRepo
    from core.repos.evolution_repo import EvolutionRepo

    services = await bootstrap_services(auto_migrate=True)
    try:
        assert services.db is not None
        assert services.llm_client is not None

        eval_repo = EvalRepo(services.db)
        config_version_repo = ConfigVersionRepo(services.db)
        evolution_repo = EvolutionRepo(services.db)

        eval_engine = EvalEngine(
            db=services.db,
            llm_client=services.llm_client,
            eval_repo=eval_repo,
        )
        analyzer = EvalAnalyzer(
            db=services.db,
            eval_repo=eval_repo,
            llm_client=services.llm_client,
        )
        change_applier = ChangeApplier(config_version_repo, simulation_id=LIVE_SIMULATION_ID)

        config = EvolutionConfig(
            max_cycles=args.cycles,
            auto_apply=args.auto_apply and not args.review_only,
            cost_cap_per_cycle=args.max_cost / args.cycles,
            convergence_threshold=args.convergence_threshold,
            regression_threshold=args.regression_threshold,
        )

        loop = EvolutionLoop(
            eval_engine=eval_engine,
            analyzer=analyzer,
            change_applier=change_applier,
            config_version_repo=config_version_repo,
            evolution_repo=evolution_repo,
            agent_registry=services.agent_registry,
        )

        console.print(f"\n[bold bright_cyan]Starting evolution loop[/bold bright_cyan]")
        console.print(f"[dim]Cycles: {config.max_cycles} | Auto-apply: {config.auto_apply} | "
                       f"Max cost: ${args.max_cost:.2f}[/dim]\n")

        report = await loop.run(config)

        # Display results
        console.print(f"\n[bold]Evolution Complete[/bold]")
        console.print(f"  Cycles: {report.total_cycles}")
        console.print(f"  Cost: ${report.total_cost:.4f}")
        console.print(f"  Baseline: {report.baseline_score or 'N/A'}")
        console.print(f"  Final: {report.final_score or 'N/A'}")
        console.print(f"  Stop reason: {report.stop_reason}")

        if report.cycles:
            table = Table(title="Cycle Results", border_style="dim")
            table.add_column("#", justify="right")
            table.add_column("Score", justify="right")
            table.add_column("Changes", justify="right")
            table.add_column("Issues", justify="right")
            table.add_column("Cost", justify="right")
            table.add_column("Status")

            for c in report.cycles:
                table.add_row(
                    str(c.cycle_number + 1),
                    f"{c.overall_score:.1f}" if c.overall_score else "N/A",
                    str(c.changes_applied),
                    str(c.issues_filed),
                    f"${c.cost:.4f}",
                    c.status,
                )
            console.print(table)

    finally:
        await shutdown_services(services)


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.history:
        asyncio.run(run_history())
        return

    if args.compare:
        asyncio.run(run_compare(args.compare[0], args.compare[1]))
        return

    if args.rollback:
        if args.version is None:
            console.print("[red]--version required with --rollback[/red]")
            return
        asyncio.run(run_rollback(args.version))
        return

    if args.reset_to_seed:
        asyncio.run(run_reset_to_seed())
        return

    asyncio.run(run_evolution(args))


if __name__ == "__main__":
    main()
