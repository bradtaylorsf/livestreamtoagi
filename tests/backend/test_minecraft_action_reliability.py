"""Tests for the Minecraft action-command reliability analyzer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYZER = REPO_ROOT / "scripts" / "minecraft" / "analyze_action_reliability.py"


def _load_analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analyze_action_reliability", ANALYZER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_bot_log(run_dir: Path, agent: str, lines: list[str]) -> Path:
    bots_dir = run_dir / "bots"
    bots_dir.mkdir(parents=True, exist_ok=True)
    path = bots_dir / f"{agent}.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_cli(run_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ANALYZER), "--run-dir", str(run_dir), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_good_run_computes_per_agent_metrics_and_verified_examples(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "good-run"
    _write_bot_log(
        run_dir,
        "alpha",
        [
            "[CHAT] Alpha: I will place the camp marker now.",
            'assistant command: !place("camp-marker", "oak_log", {"x": 0, "y": 64, "z": 0}, "up")',
            (
                "[place trace=trace-1] place camp-marker placed: position=0,64,0; "
                "expected=oak_log; before=air; after=oak_log; placed against grass_block"
            ),
            "[CHAT] Alpha: I will move two blocks east.",
            'assistant command: !move("scout-1", "east", 2)',
            "[move trace=trace-2] move scout-1 reached: distance_to_target=0.100 blocks; delta=2.000 blocks",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0.6,
            "min_parse_success": 0.8,
            "min_execution_rate": 0.7,
            "min_verified_success": 0.5,
            "min_intents": 1,
        },
    )

    alpha = data["agents"]["alpha"]
    assert data["acceptable"] is True
    assert alpha["counts"]["intent_utterances"] == 2
    assert alpha["counts"]["emitted_commands"] == 2
    assert alpha["counts"]["parse_successes"] == 2
    assert alpha["counts"]["command_executions"] == 2
    assert alpha["counts"]["verified_actions"] == 2
    assert alpha["metrics"]["intent_to_command_ratio"] == 1.0
    assert alpha["metrics"]["parse_success_rate"] == 1.0
    assert alpha["metrics"]["command_execution_rate"] == 1.0
    assert alpha["metrics"]["verified_success_rate"] == 1.0
    assert len(alpha["examples"]["verified_successes"]) == 2


def test_cli_writes_artifacts_and_fails_on_parser_failure_thresholds(tmp_path: Path) -> None:
    run_dir = tmp_path / "parse-failure-run"
    _write_bot_log(
        run_dir,
        "vera",
        [
            "[CHAT] Vera: I will place a visible block.",
            "empty parsed response from local model",
            "No commands found in response",
            "[CHAT] Vera: I will try a custom command.",
            "Command dance does not exist",
            'Could not parse command: !placeHere("oak_log"',
            "Error parsing command arguments: expected 2 arguments got 1",
        ],
    )

    proc = _run_cli(run_dir, "--min-intents", "1", "--top-n", "5")

    assert proc.returncode == 1
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "action-reliability.md").read_text(encoding="utf-8")
    assert data["acceptable"] is False
    assert data["agents"]["vera"]["counts"]["parse_failures"] == 5
    assert data["agents"]["vera"]["metrics"]["parse_success_rate"] == 0.0
    assert {item["class"] for item in data["aggregate"]["parser_failure_classes"]} >= {
        "empty_response",
        "no_commands_found",
        "unknown_command",
        "parse_error",
        "argument_error",
    }
    assert any(item["metric"] == "parse_success_rate" for item in data["threshold_violations"])
    assert "Failed Parse Examples" in markdown
    assert "Verified Success Examples" in markdown
    assert "NOT ACCEPTABLE" in markdown


def test_intent_without_command_fails_the_intent_to_command_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "intent-without-command-run"
    _write_bot_log(
        run_dir,
        "rex",
        [
            "[CHAT] Rex: I will build the first wall.",
            "[CHAT] Rex: I will place oak logs by spawn.",
            "[CHAT] Rex: I am going to move east.",
            "[CHAT] Rex: I will craft a tool.",
            "[CHAT] Rex: I will search for stone.",
        ],
    )

    proc = _run_cli(run_dir, "--min-intents", "5")

    assert proc.returncode == 1
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    rex = data["agents"]["rex"]
    assert rex["counts"]["intent_utterances"] == 5
    assert rex["counts"]["emitted_commands"] == 0
    assert rex["metrics"]["intent_to_command_ratio"] == 0.0
    assert rex["metrics"]["command_execution_rate"] == 0.0
    assert any(item["metric"] == "intent_to_command_ratio" for item in data["threshold_violations"])


def test_empty_llm_response_is_classified_as_parser_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty-response-run"
    _write_bot_log(
        run_dir,
        "pixel",
        [
            "[CHAT] Pixel: I will place a torch.",
            "blank LLM response",
            "No commands found",
        ],
    )

    proc = _run_cli(run_dir, "--min-intents", "1", "--top-n", "5")

    assert proc.returncode == 1
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    pixel_failures = data["agents"]["pixel"]["parser_failure_classes"]
    assert pixel_failures == [
        {"class": "empty_response", "count": 1},
        {"class": "no_commands_found", "count": 1},
    ]


def test_cli_threshold_flags_override_defaults(tmp_path: Path) -> None:
    run_dir = tmp_path / "threshold-override-run"
    _write_bot_log(
        run_dir,
        "fork",
        [
            "[CHAT] Fork: I will place a block.",
            "empty parsed response",
            "No commands found",
        ],
    )

    proc = _run_cli(
        run_dir,
        "--min-intents",
        "1",
        "--min-intent-to-command",
        "0",
        "--min-parse-success",
        "0",
        "--min-execution-rate",
        "0",
        "--min-verified-success",
        "0",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    assert data["acceptable"] is True
    assert data["thresholds"]["min_parse_success"] == 0.0
    assert data["threshold_violations"] == []
