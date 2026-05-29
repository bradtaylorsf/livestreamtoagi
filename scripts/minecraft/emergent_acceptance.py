#!/usr/bin/env python3
"""Emergent-mode acceptance gate for the overnight Minecraft soak (E21-7e, #909).

Emergent mode boots the bots with an EMPTY shared task board and lets them
self-organize via ``manage_task`` and the civilization ledgers, instead of
marching through a seeded settlement objective list. The settlement acceptance
report (``build_director_acceptance_report.py``) only rewards build-ish,
phase-ordered macros, so it is blind to the task lifecycle that defines emergent
collaboration. This module is the missing gate: it reuses the Director V2
acceptance report (for the multi-turn-scene + zero-objective evidence) and the
settlement smoke classifier (for the task-lifecycle + civilization evidence) and
turns the Part-3 acceptance criteria into pass/fail ``Criterion`` checks.

It is a pure module — no LLM, no DB writes beyond the evidence files the report
builder already emits — so the soak and tests can call it in seconds.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Make ``core`` importable when this module is run as a script
# (``python build_director_acceptance_report.py --mode emergent``), where only
# the script's directory is on sys.path. Mirrors seed_settlement_objectives.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build_director_acceptance_report import (  # noqa: E402
    DEFAULT_MAX_SELECTED_AGENT_RATIO,
    DEFAULT_QUEUE_DEPTH_THRESHOLD,
    DEFAULT_WARMUP_SECONDS,
    Criterion,
    build_report,
)

from core.eval.settlement_smoke_signals import (  # noqa: E402
    SettlementSmokeOutcome,
    classify_sim_folder,
)

# Part-3 acceptance thresholds. Encoded as data so the soak / tests can tune them
# without editing the criteria logic.
DEFAULT_EMERGENT_THRESHOLDS: dict[str, int] = {
    "min_task_creators": 3,
    "min_task_claimers": 2,
    "min_completed_tasks": 1,
    "min_claim_then_build": 1,
    "min_civilization_events": 1,
    "min_multi_turn_scenes": 1,
    "min_distinct_world_changers": 2,
    "min_world_changing_intents": 2,
}

_SETTLEMENT_OBJECTIVE_CRITERION = "settlement_objectives_have_structured_results"


@dataclass
class EmergentAcceptanceResult:
    """Pass/fail verdict over an emergent-mode run."""

    overall_status: str
    classification: str
    criteria: list[Criterion]
    metrics: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.overall_status == "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "profile": "emergent",
            "overall_status": self.overall_status,
            "classification": self.classification,
            "criteria": [criterion.to_json() for criterion in self.criteria],
            "metrics": self.metrics,
        }


def evaluate_emergent_acceptance(
    run_dir: Path,
    sim_folder: Path,
    *,
    thresholds: dict[str, int] | None = None,
    queue_threshold: int = DEFAULT_QUEUE_DEPTH_THRESHOLD,
    warmup_seconds: int = DEFAULT_WARMUP_SECONDS,
    max_selected_agent_ratio: float = DEFAULT_MAX_SELECTED_AGENT_RATIO,
    report: dict[str, Any] | None = None,
    outcome: SettlementSmokeOutcome | None = None,
) -> EmergentAcceptanceResult:
    """Evaluate the Part-3 emergent acceptance criteria.

    ``run_dir`` holds the Director V2 ``timeline.ndjson`` (multi-turn scenes,
    settlement-objective macros). ``sim_folder`` holds ``decision_log.jsonl``
    (the task-board + civilization tool lifecycle). ``report`` / ``outcome`` may
    be injected to avoid recomputation in tests.
    """
    th = {**DEFAULT_EMERGENT_THRESHOLDS, **(thresholds or {})}
    run_dir = Path(run_dir)
    sim_folder = Path(sim_folder)

    if report is None:
        report = build_report(
            run_dir,
            queue_threshold=max(1, queue_threshold),
            warmup_seconds=max(0, warmup_seconds),
            max_selected_agent_ratio=max(0.01, max_selected_agent_ratio),
        )
    if outcome is None:
        outcome = classify_sim_folder(sim_folder)

    report_metrics = report["metrics"]
    sub = outcome.sub_counts
    settlement_objective_count = int(report_metrics.get("settlement_objective_count", 0))
    multi_turn_scene_ids = report_metrics.get("multi_turn_collaboration_scene_ids") or []
    settlement_objective_criterion_engaged = any(
        criterion.get("id") == _SETTLEMENT_OBJECTIVE_CRITERION
        for criterion in report.get("criteria", [])
    )

    creators = int(sub.get("distinct_task_creators", 0))
    claimers = int(sub.get("distinct_task_claimers", 0))
    completed = int(sub.get("completed_task_count", 0))
    claim_then_build = int(sub.get("claim_then_build", 0))
    ownership_events = int(sub.get("ownership_events", 0))
    trade_events = int(sub.get("trade_events", 0))
    world_changing_intents = int(sub.get("world_changing_intents", 0))
    distinct_world_changers = int(sub.get("distinct_world_changing_actors", 0))

    criteria: list[Criterion] = []

    def add(criterion_id: str, ok: bool, summary: str, evidence: list[str], gap: str) -> None:
        criteria.append(
            Criterion(
                criterion_id,
                "pass" if ok else "fail",
                summary,
                evidence,
                None if ok else gap,
            )
        )

    add(
        "emergent_empty_task_board_at_start",
        settlement_objective_count == 0,
        f"settlement_objective_count={settlement_objective_count}; expected 0 (no seed)",
        ["settlement-objectives.ndjson", "timeline.ndjson"],
        "Emergent runs must boot with an empty task board; a settlement seed leaked in.",
    )
    add(
        "emergent_distinct_task_creators",
        creators >= th["min_task_creators"],
        f"distinct_task_creators={creators}; threshold>={th['min_task_creators']}",
        ["decision_log.jsonl"],
        "Fewer than the required distinct agents posted work via manage_task create_task.",
    )
    add(
        "emergent_tasks_claimed_by_distinct_agents",
        claimers >= th["min_task_claimers"],
        f"distinct_task_claimers={claimers}; threshold>={th['min_task_claimers']}",
        ["decision_log.jsonl"],
        "Fewer than the required distinct agents claimed work via manage_task claim_task.",
    )
    add(
        "emergent_task_completed_with_evidence",
        completed >= th["min_completed_tasks"],
        f"completed_task_count={completed}; threshold>={th['min_completed_tasks']}",
        ["decision_log.jsonl"],
        "No task reached done (manage_task update_status -> done).",
    )
    add(
        "emergent_build_fired_from_claim",
        claim_then_build >= th["min_claim_then_build"],
        f"claim_then_build={claim_then_build}; threshold>={th['min_claim_then_build']}",
        ["decision_log.jsonl"],
        "No world-changing build followed a claim_task; builds may be first-shouter races.",
    )
    add(
        "emergent_civilization_tool_fired",
        (ownership_events >= th["min_civilization_events"])
        or (trade_events >= th["min_civilization_events"]),
        f"ownership_events={ownership_events}; trade_events={trade_events}; "
        f"threshold>={th['min_civilization_events']}",
        ["decision_log.jsonl"],
        "No civilization tool (claim_ownership/propose_trade) fired organically.",
    )
    add(
        "emergent_no_phase_rotation_stall",
        settlement_objective_count == 0 and not settlement_objective_criterion_engaged,
        f"settlement_objective_count={settlement_objective_count}; "
        f"settlement_objective_criterion_engaged={settlement_objective_criterion_engaged}",
        ["settlement-objectives.ndjson", "acceptance-report.json"],
        "A phase-ordered settlement objective path engaged; the phase machine must be "
        "bypassed in emergent mode.",
    )
    add(
        "multi_turn_collaboration_scene",
        len(multi_turn_scene_ids) >= th["min_multi_turn_scenes"],
        f"multi_turn_scenes={len(multi_turn_scene_ids)}; threshold>={th['min_multi_turn_scenes']}",
        ["director-decisions.ndjson", "timeline.ndjson"],
        "No scene proved multi-turn collaboration (>=2 distinct selected turns).",
    )
    add(
        "emergent_distinct_world_change_proxy",
        world_changing_intents >= th["min_world_changing_intents"]
        and distinct_world_changers >= th["min_distinct_world_changers"],
        f"world_changing_intents={world_changing_intents}; "
        f"distinct_world_changing_actors={distinct_world_changers}; "
        f"thresholds>={th['min_world_changing_intents']}/{th['min_distinct_world_changers']}",
        ["decision_log.jsonl"],
        "Fewer than 2 distinct agents made world-changing intents (proxy for >=2 structures).",
    )
    add(
        "emergent_collaborative_classification",
        outcome.classification == "collaborative",
        f"classification={outcome.classification}",
        ["decision_log.jsonl", "smoke-report.json"],
        "The settlement smoke classifier did not read this run as collaborative.",
    )

    overall_status = "pass" if all(c.status == "pass" for c in criteria) else "fail"
    metrics = {
        "settlement_objective_count": settlement_objective_count,
        "multi_turn_collaboration_scene_ids": list(multi_turn_scene_ids),
        "settlement_objective_criterion_engaged": settlement_objective_criterion_engaged,
        "distinct_task_creators": creators,
        "distinct_task_claimers": claimers,
        "completed_task_count": completed,
        "claim_then_build": claim_then_build,
        "ownership_events": ownership_events,
        "trade_events": trade_events,
        "world_changing_intents": world_changing_intents,
        "distinct_world_changing_actors": distinct_world_changers,
        "classification": outcome.classification,
    }
    return EmergentAcceptanceResult(
        overall_status=overall_status,
        classification=outcome.classification,
        criteria=criteria,
        metrics=metrics,
    )


def result_markdown(result: EmergentAcceptanceResult, *, run_dir: Path, sim_folder: Path) -> str:
    lines = [
        "# Emergent Mode Acceptance Report",
        "",
        f"Run directory: `{run_dir}`",
        f"Sim folder: `{sim_folder}`",
        f"Classification: **{result.classification}**",
        f"Overall status: **{result.overall_status.upper()}**",
        "",
        "## Criteria",
        "",
        "| Criterion | Status | Summary |",
        "| --- | --- | --- |",
    ]
    for criterion in result.criteria:
        lines.append(f"| `{criterion.criterion_id}` | {criterion.status} | {criterion.summary} |")
    lines.extend(["", "## Metrics", ""])
    for key, value in result.metrics.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def write_artifacts(
    result: EmergentAcceptanceResult, *, run_dir: Path, sim_folder: Path
) -> tuple[Path, Path]:
    """Write ``emergent-acceptance.json`` + ``.md`` into ``run_dir``."""
    run_dir = Path(run_dir)
    json_path = run_dir / "emergent-acceptance.json"
    md_path = run_dir / "emergent-acceptance.md"
    json_path.write_text(json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n", "utf-8")
    md_path.write_text(
        result_markdown(result, run_dir=run_dir, sim_folder=sim_folder), encoding="utf-8"
    )
    return json_path, md_path


__all__ = [
    "DEFAULT_EMERGENT_THRESHOLDS",
    "EmergentAcceptanceResult",
    "evaluate_emergent_acceptance",
    "result_markdown",
    "write_artifacts",
]
