#!/usr/bin/env python3
"""CLI runner for the evaluation framework.

Usage:
    # Run full eval suite on a simulation
    python scripts/run_eval.py --simulation-id <uuid>

    # Run specific categories only
    python scripts/run_eval.py --simulation-id <uuid> --categories entertainment,safety

    # Run quick eval (subset of data, faster/cheaper)
    python scripts/run_eval.py --simulation-id <uuid> --suite quick

    # List available eval categories
    python scripts/run_eval.py --list-categories

    # View results of the most recent eval run
    python scripts/run_eval.py --simulation-id <uuid> --view-last
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from core.repos.eval_repo import EvalRepo

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


def _score_color(score: float) -> str:
    """Return rich color tag for score value."""
    if score >= 70:
        return "green"
    elif score >= 40:
        return "yellow"
    return "red"


async def run_eval(args: argparse.Namespace) -> None:
    """Main async entry point."""
    verbose = getattr(args, "verbose", False)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from rich.console import Console

    from core.eval.prompt_loader import discover_categories

    console = Console()

    # --list-categories
    if args.list_categories:
        cats = discover_categories()
        if not cats:
            console.print("[dim]No eval prompts found in evals/prompts/[/dim]")
        else:
            console.print("[bold]Available eval categories:[/bold]")
            for cat in cats:
                console.print(f"  - {cat}")
        return

    if not args.simulation_id:
        console.print("[red]--simulation-id is required[/red]")
        sys.exit(1)

    sim_id = uuid.UUID(args.simulation_id)

    from core.bootstrap import bootstrap_services, shutdown_services
    from core.repos.eval_repo import EvalRepo

    svc = await bootstrap_services()

    try:
        eval_repo = EvalRepo(svc.db)

        # --view-last
        if args.view_last:
            await _view_last(console, eval_repo, sim_id)
            return

        # Run evals
        from core.eval.engine import EvalEngine

        engine = EvalEngine(
            db=svc.db,
            llm_client=svc.llm_client,
            eval_repo=eval_repo,
        )

        categories = (
            [c.strip() for c in args.categories.split(",")]
            if args.categories
            else None
        )

        console.print(f"\n[bold]Running eval suite '{args.suite}' on simulation {sim_id}[/bold]\n")

        run_id = await engine.run(
            sim_id,
            categories=categories,
            suite=args.suite,
        )

        # Display results
        await _view_results(console, eval_repo, run_id)

    finally:
        await shutdown_services(svc)


async def _view_last(
    console: Console,
    eval_repo: EvalRepo,
    sim_id: uuid.UUID,
) -> None:
    """Show the most recent eval results for a simulation."""
    run = await eval_repo.get_latest_eval_run(sim_id)
    if run is None:
        console.print("[dim]No eval runs found for this simulation.[/dim]")
        return
    await _view_results(console, eval_repo, run.id)


async def _view_results(
    console: Console,
    eval_repo: EvalRepo,
    run_id: uuid.UUID,
) -> None:
    """Display formatted eval results."""
    from rich.table import Table

    run = await eval_repo.get_eval_run(run_id)
    if run is None:
        console.print("[red]Eval run not found[/red]")
        return

    results = await eval_repo.get_eval_results(run_id)

    # Overall score
    overall = float(run.overall_score) if run.overall_score is not None else 0
    color = _score_color(overall)
    console.print(f"\n[bold {color}]Overall Score: {overall:.1f}/100[/bold {color}]")
    console.print(
        f"[dim]Suite: {run.eval_suite} | Status: {run.status}"
        f" | Cost: ${run.cost:.4f}[/dim]\n"
    )

    # Results table
    table = Table(title="Eval Results")
    table.add_column("Category", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Sub-scores", max_width=40)
    table.add_column("Top Finding", max_width=50)

    for r in results:
        score = float(r.score) if r.score is not None else 0
        color = _score_color(score)

        # Format sub-scores
        sub_str = ""
        if r.sub_scores:
            parts = []
            for k, v in r.sub_scores.items():
                parts.append(f"{k}={v}")
            sub_str = ", ".join(parts[:5])

        # Top finding from reasoning
        finding = (r.reasoning or "")[:50]
        if len(r.reasoning or "") > 50:
            finding += "..."

        table.add_row(
            r.category,
            f"[{color}]{score:.1f}[/{color}]",
            sub_str,
            finding,
        )

    console.print(table)

    # Cost summary
    total_tokens = sum(r.tokens_used for r in results)
    total_cost = sum(float(r.cost) for r in results)
    console.print(
        f"\n[dim]Total tokens: {total_tokens:,}"
        f" | Total eval cost: ${total_cost:.4f}[/dim]\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evaluations on simulation data"
    )
    parser.add_argument(
        "--simulation-id",
        type=str,
        default=None,
        help="UUID of the simulation to evaluate",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default=None,
        help="Comma-separated eval categories (e.g., entertainment,safety)",
    )
    parser.add_argument(
        "--suite",
        type=str,
        choices=["full", "quick", "autonomy", "economy", "creative", "narrative"],
        default="full",
        help="Eval suite to run (default: full)",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List all available eval categories",
    )
    parser.add_argument(
        "--view-last",
        action="store_true",
        help="View the most recent eval results for the simulation",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    asyncio.run(run_eval(args))


if __name__ == "__main__":
    main()
