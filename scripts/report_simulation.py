#!/usr/bin/env python3
"""CLI for generating post-simulation timeline reports.

Usage:
    # Generate full report
    python scripts/report_simulation.py --simulation-id <uuid>

    # Generate report for specific days
    python scripts/report_simulation.py --simulation-id <uuid> --days 1,3,7

    # Output as JSON
    python scripts/report_simulation.py --simulation-id <uuid> --format json

    # Compare two simulations
    python scripts/report_simulation.py --compare <uuid1> <uuid2>

    # Export as markdown
    python scripts/report_simulation.py --simulation-id <uuid> --format markdown --output report.md
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


async def run_report(args: argparse.Namespace) -> None:
    """Main async entry point."""
    from core.bootstrap import bootstrap_services, shutdown_services
    from core.reporting.formatters import (
        format_comparison_terminal,
        format_json,
        format_markdown,
        format_terminal,
    )
    from core.reporting.timeline_reporter import TimelineReporter

    svc = await bootstrap_services(auto_migrate=True)

    try:
        if args.compare:
            reporter = TimelineReporter(
                db=svc.db,
                simulation_id=args.compare[0],
                relationship_repo=svc.relationship_repo,
            )
            comparison = await reporter.compare(args.compare[1])

            if args.format == "json":
                output = format_json_comparison(comparison)
            else:
                output = format_comparison_terminal(comparison)

            print(output)
            return

        if not args.simulation_id:
            print("Error: --simulation-id is required (unless using --compare)")
            sys.exit(1)

        days = None
        if args.days:
            days = [int(d.strip()) for d in args.days.split(",")]

        reporter = TimelineReporter(
            db=svc.db,
            simulation_id=args.simulation_id,
            relationship_repo=svc.relationship_repo,
        )
        report = await reporter.generate(days=days, format=args.format)

        # Append scorecard if requested
        if args.scorecard:
            from core.repos.assertion_repo import AssertionRepo
            from core.reporting.scorecard import LaunchScorecard

            assertion_repo = AssertionRepo(svc.db) if svc.db else None
            scorecard = LaunchScorecard(
                db=svc.db,
                simulation_id=args.simulation_id,
                assertion_repo=assertion_repo,
                relationship_repo=svc.relationship_repo,
            )
            scorecard_result = await scorecard.evaluate()
            from core.reporting.timeline_reporter import ReportSection

            report.sections.append(ReportSection(
                title="Launch Readiness Scorecard",
                data=scorecard_result.to_dict(),
            ))

        if args.format == "json":
            output = format_json(report)
        elif args.format == "markdown":
            output = format_markdown(report)
        else:
            output = format_terminal(report)

        if args.output:
            Path(args.output).write_text(output)
            print(f"Report written to {args.output}")
        else:
            print(output)

    finally:
        await shutdown_services(svc)


def format_json_comparison(comparison):
    """Format comparison report as JSON."""
    import json

    return json.dumps(comparison.to_dict(), indent=2, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate post-simulation timeline reports"
    )
    parser.add_argument(
        "--simulation-id",
        type=str,
        default=None,
        help="UUID of the simulation to report on",
    )
    parser.add_argument(
        "--days",
        type=str,
        default=None,
        help="Comma-separated day numbers to include (e.g. 1,3,7)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["terminal", "json", "markdown"],
        default="terminal",
        help="Output format (default: terminal)",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("UUID1", "UUID2"),
        help="Compare two simulation runs side-by-side",
    )
    parser.add_argument(
        "--scorecard",
        action="store_true",
        help="Include launch-readiness scorecard in the report",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (for markdown/json export)",
    )

    args = parser.parse_args()
    if not args.simulation_id and not args.compare:
        parser.error("Either --simulation-id or --compare must be provided")

    asyncio.run(run_report(args))


if __name__ == "__main__":
    main()
