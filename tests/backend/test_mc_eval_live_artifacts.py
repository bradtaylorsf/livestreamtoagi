"""Tests for Minecraft live eval artifact writers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from core.minecraft.eval.live_artifacts import write_live_eval_artifacts
from core.minecraft.eval.live_telemetry import ActionEvent, CaseResult, LiveRunSummary

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "minecraft"


def test_live_artifacts_write_expected_shapes_for_smoke_run(tmp_path: Path) -> None:
    summary = _smoke_summary()

    write_live_eval_artifacts(tmp_path, summary, traces="traces")

    for name in (
        "summary.json",
        "cases.ndjson",
        "report.md",
        "live-actions.ndjson",
        "live-scores.json",
        "live-generations.ndjson",
        "live-report.md",
        "timeline.ndjson",
    ):
        assert (tmp_path / name).is_file()

    action_lines = _read_ndjson(tmp_path / "live-actions.ndjson")
    assert len(action_lines) == sum(len(case.action_events) for case in summary.case_results)
    assert {
        "case_id",
        "agent_id",
        "action_id",
        "kind",
        "ts_ms",
        "payload",
    } <= set(action_lines[0])

    scores = json.loads((tmp_path / "live-scores.json").read_text(encoding="utf-8"))
    assert {
        "passed",
        "failed",
        "cases",
        "outcome_counts",
        "category_counts",
        "pathfinding_summary",
        "inventory_summary",
        "block_mutation_summary",
        "lifecycle_summary",
        "timing_summary",
        "case_results",
    } <= set(scores)
    assert scores["passed"] == 1
    assert scores["failed"] == 1
    assert scores["case_results"][0]["passed"] is True
    assert "final_state" not in scores["case_results"][0]

    generations = _read_ndjson(tmp_path / "live-generations.ndjson")
    assert [record["record_type"] for record in generations] == [
        "generated-command",
        "generated-command",
    ]
    assert generations[0]["command_text"].startswith("!move")
    assert generations[0]["params"]["direction"] == "north"

    report = (tmp_path / "live-report.md").read_text(encoding="utf-8")
    assert "[live-generations.ndjson](live-generations.ndjson)" in report
    assert "[live-actions.ndjson](live-actions.ndjson)" in report
    assert "[live-scores.json](live-scores.json)" in report
    assert "[timeline.ndjson](timeline.ndjson)" in report
    assert "[traces/live-move-0001.json](traces/live-move-0001.json)" in report

    trace = json.loads((tmp_path / "traces" / "live-move-0001.json").read_text())
    assert trace["case_id"] == "live-move-0001"
    assert trace["final_pose"] == {"x": 2, "y": 64, "z": 0}


def test_live_generations_references_replay_dataset(tmp_path: Path) -> None:
    summary = _replay_summary()
    dataset_path = tmp_path / "passing-prompts.ndjson"
    dataset_path.write_text("", encoding="utf-8")

    write_live_eval_artifacts(tmp_path / "report", summary, dataset_path=dataset_path)

    generations = _read_ndjson(tmp_path / "report" / "live-generations.ndjson")
    assert len(generations) == 1
    reference = generations[0]
    assert reference["record_type"] == "dataset-reference"
    assert reference["dataset_path"] == str(dataset_path)
    assert reference["filters"] == {"commands": ["move"], "limit": 1, "scenario_ids": []}
    assert reference["selected_scenario_ids"] == ["move-north"]
    assert reference["selected_command_tokens"] == ["!move"]
    assert reference["selected_cases"] == [
        {
            "case_id": "move-north",
            "command_text": "!move north 2",
            "command_token": "!move",
            "scenario_id": "move-north",
        }
    ]


def test_timeline_artifact_is_monitor_compatible_subset(tmp_path: Path) -> None:
    write_live_eval_artifacts(tmp_path, _smoke_summary())
    builder = _load_script("build_timeline")
    monitor = _load_script("build_monitor")

    timeline_path, totals_path = monitor.ensure_timeline_artifacts(tmp_path)
    assert timeline_path == tmp_path / "timeline.ndjson"
    assert totals_path == tmp_path / "timeline-totals.json"

    events = monitor.read_ndjson(timeline_path)
    assert events
    assert {event["event_type"] for event in events} <= builder.EVENT_TYPES
    assert {event["event_type"] for event in events} >= {
        "action.start",
        "action.completed",
        "action.result",
        "lifecycle",
    }
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["source"] == "live-eval" for event in events)
    assert all(monitor.parse_iso_ts(event["ts"]) is not None for event in events)
    assert events[0]["trace_id"] == "move-1"


def test_package_scripts_expose_live_artifact_workflow() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert scripts["mc:eval:live"] == ".venv/bin/python scripts/minecraft/eval_live.py"
    assert "--report-dir" in scripts["mc:eval:live:report"]
    assert "--traces-dir" in scripts["mc:eval:live:report"]
    assert (
        scripts["verify:mc-eval-live-artifacts"]
        == ".venv/bin/pytest tests/backend/test_mc_eval_live_artifacts.py -v"
    )


def _smoke_summary() -> LiveRunSummary:
    success = CaseResult(
        case_id="live-move-0001",
        command_text="!move move-1 north 2 10000",
        params={"action_id": "move-1", "direction": "north", "distance_blocks": 2},
        action_events=(
            ActionEvent(
                action_id="move-1",
                kind="start",
                ts_ms=1_800_000_000_000,
                payload={"command": "move", "case_id": "live-move-0001"},
            ),
            ActionEvent(
                action_id="move-1",
                kind="end",
                ts_ms=1_800_000_000_050,
                payload={"status": "ok", "case_id": "live-move-0001"},
            ),
        ),
        outcome_class="success",
        final_state={
            "pose": {"x": 2, "y": 64, "z": 0},
            "pathfinding": {"stuck": False, "collision": False, "blocked_path": False},
        },
        latency_ms=50,
    )
    death_loop = CaseResult(
        case_id="live-move-0002",
        command_text="!move move-2 west 4 10000",
        params={"action_id": "move-2", "direction": "west", "distance_blocks": 4},
        action_events=(
            ActionEvent(
                action_id="move-2",
                kind="start",
                ts_ms=1_800_000_000_100,
                payload={"command": "move", "case_id": "live-move-0002"},
            ),
            ActionEvent(
                action_id="move-2",
                kind="death",
                ts_ms=1_800_000_000_120,
                payload={"reason": "died in lava"},
            ),
            ActionEvent(
                action_id="move-2",
                kind="end",
                ts_ms=1_800_000_000_150,
                payload={"status": "failed", "reason": "death loop"},
            ),
        ),
        outcome_class="world_constraint",
        final_state={
            "death_count": 2,
            "death_loop": True,
            "pose": {"x": -1, "y": 63, "z": 0},
            "respawns": 2,
            "status_detail": "death loop after respawn",
        },
        latency_ms=50,
        error="death loop after respawn",
    )
    return LiveRunSummary(
        command="move",
        resolved_command="move",
        profile="flat-eval",
        seed=7,
        dry_run=True,
        verbose=False,
        case_results=(success, death_loop),
        profile_detail={"mc_port": 25568},
    )


def _replay_summary() -> LiveRunSummary:
    result = CaseResult(
        case_id="move-north",
        command_text="!move north 2",
        params={
            "args": ["north", "2"],
            "command_token": "!move",
            "scenario_id": "move-north",
        },
        action_events=(
            ActionEvent(
                action_id="move-north",
                kind="start",
                ts_ms=1_800_000_001_000,
                payload={"case_id": "move-north", "command": "move"},
            ),
            ActionEvent(
                action_id="move-north",
                kind="end",
                ts_ms=1_800_000_001_010,
                payload={"case_id": "move-north", "status": "ok"},
            ),
        ),
        outcome_class="success",
        final_state={"pose": {"x": 1, "y": 64, "z": 0}},
        latency_ms=10,
    )
    return LiveRunSummary(
        command="dataset-replay",
        resolved_command="dataset-replay",
        profile="flat-eval",
        seed=0,
        dry_run=True,
        verbose=False,
        case_results=(result,),
        profile_detail={
            "dataset_replay": {
                "dataset_path": "old-path.ndjson",
                "filters": {"commands": ["move"], "limit": 1, "scenario_ids": []},
                "selected_prompts": 1,
                "total_prompts": 3,
            }
        },
    )


def _read_ndjson(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _load_script(name: str) -> ModuleType:
    sys.path.insert(0, str(SCRIPT_DIR))
    script = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
