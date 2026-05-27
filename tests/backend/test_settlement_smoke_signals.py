"""Tests for the settlement-smoke classifier and report builder (#821)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from core.eval.settlement_smoke_signals import (
    SettlementSmokeOutcome,
    classify_rows,
    classify_sim_folder,
)
from core.simulation.decision_logger import DecisionLogger
from core.simulation.scenario_schema import validate_scenario_dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "open_settlement_smoke.yaml"
REPORT_SCRIPT = PROJECT_ROOT / "scripts" / "minecraft" / "build_settlement_smoke_report.py"


# ─── Scenario YAML ────────────────────────────────────────────────────────


def test_scenario_yaml_validates() -> None:
    with SCENARIO_PATH.open() as f:
        data = yaml.safe_load(f)
    scenario = validate_scenario_dict(data)
    phase_names = [p.name for p in scenario.phases]
    assert phase_names == ["discussion", "delegation", "review_repair"]
    assert scenario.run_mode == "experimental"
    assert scenario.management_policy == "shadow"
    assert scenario.eval_targets is not None
    assert "social_dynamics" in scenario.eval_targets.primary
    assert "world_evolution" in scenario.eval_targets.primary
    assert "agency" in scenario.eval_targets.primary


def test_scenario_does_not_name_a_blueprint() -> None:
    """The smoke profile must not pre-name a specific structure type."""
    text = SCENARIO_PATH.read_text().lower()
    forbidden = ("cabin", "watchtower", "coliseum")
    for token in forbidden:
        assert token not in text, f"scenario must not name {token!r}"


# ─── Classifier fixtures ──────────────────────────────────────────────────


def _build_log(tmp_path: Path, events: list[tuple[str, dict]]) -> Path:
    """Drive the real DecisionLogger to write a fixture decision_log.jsonl."""
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    logger = DecisionLogger(sim_folder)
    try:
        for kind, payload in events:
            if kind == "utterance":
                logger.log_utterance(**payload)
            elif kind == "tool_intent":
                logger.log_tool_intent(**payload)
            elif kind == "world_event":
                logger.log_world_event(**payload)
            else:
                raise AssertionError(f"unsupported kind {kind!r}")
    finally:
        logger.close()
    return sim_folder


def _collaborative_events() -> list[tuple[str, dict]]:
    return [
        ("utterance", {"actor_id": "alpha", "text": "Let's build a starter farm together."}),
        ("utterance", {"actor_id": "rex", "text": "I'll build the perimeter wall."}),
        ("utterance", {"actor_id": "vera", "text": "I'll gather logs for Rex."}),
        (
            "tool_intent",
            {
                "actor_id": "rex",
                "tool_name": "buildFromPlan",
                "args": {"name": "wall"},
                "status": "executed",
            },
        ),
        ("utterance", {"actor_id": "fork", "text": "Looks off — let's fix the corner."}),
    ]


def _partial_events() -> list[tuple[str, dict]]:
    return [
        ("utterance", {"actor_id": "alpha", "text": "Let's build a small camp."}),
        ("utterance", {"actor_id": "rex", "text": "I'll build the foundation."}),
        ("utterance", {"actor_id": "vera", "text": "I'll gather supplies for Rex."}),
        # No executed world-changing intent.
        (
            "tool_intent",
            {
                "actor_id": "rex",
                "tool_name": "buildFromPlan",
                "args": {},
                "status": "blocked",
                "block_reason": "policy",
            },
        ),
    ]


def _idle_chat_events() -> list[tuple[str, dict]]:
    return [
        ("utterance", {"actor_id": "alpha", "text": "Hi everyone."}),
        ("utterance", {"actor_id": "rex", "text": "Hello."}),
        ("utterance", {"actor_id": "vera", "text": "How is everyone."}),
    ]


def _scattered_events() -> list[tuple[str, dict]]:
    return [
        ("utterance", {"actor_id": "grok", "text": "Just doing something random."}),
        (
            "tool_intent",
            {
                "actor_id": "grok",
                "tool_name": "placeHere",
                "args": {"block": "dirt"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "grok",
                "tool_name": "collectBlock",
                "args": {"name": "dirt"},
                "status": "executed",
            },
        ),
    ]


def _command_loop_events() -> list[tuple[str, dict]]:
    base = [
        ("utterance", {"actor_id": "alpha", "text": "Let's build something."}),
    ]
    repeats = [
        (
            "tool_intent",
            {
                "actor_id": "rex",
                "tool_name": "buildFromPlan",
                "args": {"name": "wall"},
                "status": "blocked",
                "block_reason": "missing_inventory",
            },
        )
    ] * 5
    return base + repeats


# ─── Classifier behavior ──────────────────────────────────────────────────


def test_classify_collaborative(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _collaborative_events())
    outcome = classify_sim_folder(folder)
    assert isinstance(outcome, SettlementSmokeOutcome)
    assert outcome.classification == "collaborative"
    assert outcome.shared_objective_chosen is True
    assert outcome.distinct_role_count >= 2
    assert outcome.world_changing_action_count >= 1
    assert outcome.review_repair_events >= 1
    assert outcome.failure_class is None


def test_classify_partial(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _partial_events())
    outcome = classify_sim_folder(folder)
    assert outcome.classification == "partial"
    assert outcome.shared_objective_chosen is True
    assert outcome.distinct_role_count >= 2
    assert outcome.world_changing_action_count == 0
    assert outcome.failure_class == "no_world_changing_action"


def test_classify_idle_chat(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _idle_chat_events())
    outcome = classify_sim_folder(folder)
    assert outcome.classification == "idle_chat"
    assert outcome.shared_objective_chosen is False
    assert outcome.world_changing_action_count == 0
    assert outcome.failure_class == "zero_successful_tool_intents"


def test_classify_scattered(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _scattered_events())
    outcome = classify_sim_folder(folder)
    assert outcome.classification == "scattered"
    assert outcome.world_changing_action_count >= 1
    assert outcome.shared_objective_chosen is False
    assert outcome.failure_class == "world_change_without_consensus"


def test_classify_command_loop_churn(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _command_loop_events())
    outcome = classify_sim_folder(folder)
    assert outcome.classification == "command_loop_churn"
    assert outcome.command_loop_signatures
    assert outcome.failure_class == "repeated_blocked_tool_intents"


def test_classify_rows_pure() -> None:
    """classify_rows works on an in-memory iterable too."""
    from datetime import UTC, datetime

    from core.simulation.decision_log_schema import (
        ToolIntentPayload,
        ToolIntentRow,
        UtterancePayload,
        UtteranceRow,
    )

    now = datetime.now(UTC)
    rows = [
        UtteranceRow(
            tick=1,
            wall_time=now,
            sim_time=0.0,
            actor_id="alpha",
            payload=UtterancePayload(text="Let's build a small camp."),
        ),
        UtteranceRow(
            tick=2,
            wall_time=now,
            sim_time=0.0,
            actor_id="rex",
            payload=UtterancePayload(text="I'll build the wall."),
        ),
        UtteranceRow(
            tick=3,
            wall_time=now,
            sim_time=0.0,
            actor_id="vera",
            payload=UtterancePayload(text="I'll gather supplies."),
        ),
        ToolIntentRow(
            tick=4,
            wall_time=now,
            sim_time=0.0,
            actor_id="rex",
            payload=ToolIntentPayload(
                tool_name="buildFromPlan",
                args={},
                status="executed",
            ),
        ),
        UtteranceRow(
            tick=5,
            wall_time=now,
            sim_time=0.0,
            actor_id="fork",
            payload=UtterancePayload(text="Looks off, let's fix it."),
        ),
    ]
    outcome = classify_rows(rows)
    assert outcome.classification == "collaborative"


# ─── Report-builder CLI ───────────────────────────────────────────────────


def test_report_builder_writes_json_and_md(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _collaborative_events())
    result = subprocess.run(
        [sys.executable, str(REPORT_SCRIPT), "--sim-folder", str(folder)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    json_path = folder / "smoke-report.json"
    md_path = folder / "smoke-report.md"
    assert json_path.is_file()
    assert md_path.is_file()
    payload = json.loads(json_path.read_text())
    assert payload["classification"] == "collaborative"
    assert payload["shared_objective_chosen"] is True


def test_report_builder_nonzero_on_idle_chat(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _idle_chat_events())
    result = subprocess.run(
        [sys.executable, str(REPORT_SCRIPT), "--sim-folder", str(folder)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 1, result.stdout
    payload = json.loads((folder / "smoke-report.json").read_text())
    assert payload["classification"] == "idle_chat"


def test_report_builder_missing_folder(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    result = subprocess.run(
        [sys.executable, str(REPORT_SCRIPT), "--sim-folder", str(missing)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 2
    assert "sim folder not found" in result.stderr


def test_report_builder_no_exit_code_flag(tmp_path: Path) -> None:
    folder = _build_log(tmp_path, _idle_chat_events())
    result = subprocess.run(
        [
            sys.executable,
            str(REPORT_SCRIPT),
            "--sim-folder",
            str(folder),
            "--no-exit-code",
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr


# ─── Smoke-script surface ─────────────────────────────────────────────────


def test_smoke_script_exists_and_is_executable() -> None:
    script = PROJECT_ROOT / "scripts" / "minecraft" / "run_open_settlement_smoke.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111, "smoke wrapper must be executable"
    body = script.read_text()
    assert "scripts/minecraft/eval_commands.py" in body  # preflight wiring
    assert "scripts/run_headless_sim.py" in body
    assert "build_settlement_smoke_report.py" in body
    assert "open_settlement_smoke.yaml" in body
