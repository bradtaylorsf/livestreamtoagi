#!/usr/bin/env python3
"""Build the settlement-smoke report for a completed open-settlement run (#821).

Usage::

    python scripts/minecraft/build_settlement_smoke_report.py \
        --sim-folder snapshots/headless/<sim_uuid>

Writes ``smoke-report.json`` and ``smoke-report.md`` under the sim folder.
Exits with a non-zero code when the outcome class is one of ``idle_chat``,
``scattered``, or ``command_loop_churn`` so CI can gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.eval.settlement_smoke_signals import (  # noqa: E402
    SettlementSmokeOutcome,
    classify_sim_folder,
)

GATING_CLASSIFICATIONS = {"idle_chat", "scattered", "command_loop_churn"}


def _build_markdown(outcome: SettlementSmokeOutcome, sim_folder: Path) -> str:
    lines: list[str] = []
    lines.append(f"# Open Settlement Smoke Report — {sim_folder.name}")
    lines.append("")
    lines.append(f"**Classification:** `{outcome.classification}`")
    lines.append("")
    lines.append(f"- shared_objective_chosen: `{outcome.shared_objective_chosen}`")
    lines.append(f"- distinct_role_count: `{outcome.distinct_role_count}`")
    if outcome.distinct_role_actors:
        lines.append(f"- distinct_role_actors: {', '.join(outcome.distinct_role_actors)}")
    lines.append(f"- world_changing_action_count: `{outcome.world_changing_action_count}`")
    lines.append(f"- discussion_turns: `{outcome.discussion_turns}`")
    lines.append(f"- delegation_events: `{outcome.delegation_events}`")
    lines.append(f"- review_repair_events: `{outcome.review_repair_events}`")
    lines.append(f"- command_loop_signatures: `{len(outcome.command_loop_signatures)}`")
    lines.append("")

    lines.append("## Sub-counts")
    lines.append("")
    for key, value in outcome.sub_counts.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")

    if outcome.shared_objective_evidence is not None:
        ev = outcome.shared_objective_evidence
        lines.append("## Shared-objective evidence")
        lines.append("")
        lines.append(f"- tick `{ev.tick}` — {ev.actor_id}: {ev.note}")
        lines.append("")

    if outcome.world_changing_first_events:
        lines.append("## First world-changing actions")
        lines.append("")
        for ev in outcome.world_changing_first_events:
            lines.append(f"- tick `{ev.tick}` — {ev.actor_id} via `{ev.note}` ({ev.event_type})")
        lines.append("")

    if outcome.command_loop_signatures:
        lines.append("## Command-loop signatures (>= 4 blocked repeats)")
        lines.append("")
        for sig in outcome.command_loop_signatures:
            lines.append(f"- `{sig}`")
        lines.append("")

    lines.append("## Evidence files")
    lines.append("")
    lines.append(f"- `{sim_folder / 'decision_log.jsonl'}`")
    timeline = sim_folder / "timeline.ndjson"
    if timeline.exists():
        lines.append(f"- `{timeline}`")
    eval_scores = sim_folder / "eval_scores.json"
    if eval_scores.exists():
        lines.append(f"- `{eval_scores}`")
    lines.append("")

    if outcome.classification != "collaborative":
        lines.append("## Follow-up classification")
        lines.append("")
        lines.append(
            "Outcome was not `collaborative`. Use the failure class below as the "
            "lead label when filing a follow-up issue against epic #820 / #821."
        )
        lines.append("")
        lines.append(f"- failure_class: `{outcome.failure_class or 'unspecified'}`")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(outcome.summary)
    lines.append("")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the settlement-smoke report from a completed sim folder.",
    )
    parser.add_argument(
        "--sim-folder",
        required=True,
        help="Path to the headless sim folder containing decision_log.jsonl.",
    )
    parser.add_argument(
        "--no-exit-code",
        action="store_true",
        help="Always exit 0, even when classification is gating.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sim_folder = Path(args.sim_folder).resolve()
    if not sim_folder.is_dir():
        print(f"ERROR: sim folder not found: {sim_folder}", file=sys.stderr)
        return 2

    outcome = classify_sim_folder(sim_folder)

    (sim_folder / "smoke-report.json").write_text(
        json.dumps(outcome.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (sim_folder / "smoke-report.md").write_text(
        _build_markdown(outcome, sim_folder),
        encoding="utf-8",
    )

    print(f"settlement smoke: classification={outcome.classification}")
    print(outcome.summary)

    if args.no_exit_code:
        return 0
    if outcome.classification in GATING_CLASSIFICATIONS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
