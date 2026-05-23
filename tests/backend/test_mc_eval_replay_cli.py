"""Tests for the Minecraft dataset replay CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

from core.minecraft.eval.live_telemetry import OutcomeClass
from core.minecraft.eval.replay_cli import main


def test_replay_cli_dry_run_json_replays_dataset_commands(tmp_path: Path) -> None:
    dataset_path = _write_dataset(
        tmp_path,
        [
            _record("move-north", "!move", ["north", "2"]),
            _record("inventory-check", "!inventory", []),
        ],
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path), "--dry-run", "--json"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert data["command"] == "dataset-replay"
    assert data["resolved_command"] == "dataset-replay"
    assert data["dry_run"] is True
    assert data["cases"] == 2
    assert data["outcome_counts"][OutcomeClass.SUCCESS] == 2
    assert [case["command_text"] for case in data["case_results"]] == [
        "!move north 2",
        "!inventory",
    ]
    assert data["profile_detail"]["dataset_replay"]["total_prompts"] == 2
    assert data["profile_detail"]["dataset_replay"]["selected_prompts"] == 2
    assert stderr.getvalue() == ""


def test_replay_cli_command_filter_narrows_case_list(tmp_path: Path) -> None:
    dataset_path = _write_dataset(
        tmp_path,
        [
            _record("move-north", "!move", ["north", "2"]),
            _record("inventory-check", "!inventory", []),
            _record("move-south", "MOVE", ["south", "1"]),
        ],
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path), "--command", "move", "--dry-run", "--json"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert data["cases"] == 2
    assert [case["params"]["scenario_id"] for case in data["case_results"]] == [
        "move-north",
        "move-south",
    ]
    assert [case["command_text"] for case in data["case_results"]] == [
        "!move north 2",
        "!MOVE south 1",
    ]


def test_replay_cli_unknown_dataset_path_exits_nonzero(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(tmp_path / "missing.ndjson"), "--dry-run"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "dataset not found" in stderr.getvalue()


def test_replay_cli_enabled_live_mode_without_env_exits_nonzero(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path, [_record("move-north", "!move", ["north"])])
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path)],
        env={"MC_EVAL_LIVE_ENABLED": "1"},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "MC_EVAL_LIVE_ENABLED=1 requires" in stderr.getvalue()
    assert "MC_EVAL_LIVE_BRIDGE_URL" in stderr.getvalue()
    assert "MINECRAFT_BRIDGE_TOKEN" in stderr.getvalue()


def test_replay_cli_report_dir_writes_dataset_artifacts(tmp_path: Path) -> None:
    dataset_path = _write_dataset(
        tmp_path,
        [
            _record("move-north", "!move", ["north", "2"]),
            _record("inventory-check", "!inventory", []),
        ],
    )
    report_dir = tmp_path / "report"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "--dataset",
            str(dataset_path),
            "--dry-run",
            "--report-dir",
            str(report_dir),
        ],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    assert (report_dir / "summary.json").is_file()
    assert (report_dir / "cases.ndjson").is_file()
    assert (report_dir / "report.md").is_file()

    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["cases"] == 2
    assert summary["profile_detail"]["dataset_replay"]["command_counts"] == {
        "inventory": 1,
        "move": 1,
    }

    case_lines = (report_dir / "cases.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(case_lines) == 2
    assert json.loads(case_lines[0])["command_text"] == "!move north 2"

    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "## Dataset Replay" in report
    assert "## Categories" in report
    assert "## Pathfinding" in report
    assert "prompts_loaded: `2`" in report
    assert "`move`: success=1" in report
    assert "### Per-category Outcomes" in report


def test_replay_cli_verbose_prints_action_start_and_end_lines(tmp_path: Path) -> None:
    dataset_path = _write_dataset(
        tmp_path,
        [
            _record("move-north", "!move", ["north", "2"]),
            _record("move-south", "!move", ["south", "1"]),
        ],
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path), "--dry-run", "--verbose"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    text = stdout.getvalue()
    assert exit_code == 0, stderr.getvalue()
    assert text.count("command_input !move") == 2
    assert text.count("action_start action_id=") == 2
    assert text.count("action_end action_id=") == 2
    assert '"scenario_id":"move-north"' in text
    assert stderr.getvalue() == ""


def test_replay_cli_distinguishes_text_rejection_from_world_failure(
    tmp_path: Path,
) -> None:
    dataset_path = _write_dataset(
        tmp_path,
        [_record(f"move-{index}", "!move", ["north", str(index)]) for index in range(6)],
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path), "--dry-run", "--json"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert [case["outcome_class"] for case in data["case_results"]] == [
        OutcomeClass.SUCCESS,
        OutcomeClass.SUCCESS,
        OutcomeClass.WORLD_CONSTRAINT,
        OutcomeClass.REJECTED,
        OutcomeClass.TIMEOUT,
        OutcomeClass.MALFORMED,
    ]


def test_replay_cli_records_category_counts_and_pathfinding_signals(
    tmp_path: Path,
) -> None:
    dataset_path = _write_dataset(
        tmp_path,
        [_record(f"move-{index}", "!move", ["north", str(index)]) for index in range(5)],
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path), "--dry-run", "--json"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    detail = data["profile_detail"]["dataset_replay"]
    assert detail["per_category_outcome_counts"]["collision"][OutcomeClass.WORLD_CONSTRAINT] == 1
    assert detail["per_category_outcome_counts"]["pathfinding"][OutcomeClass.SUCCESS] == 2
    assert detail["per_category_outcome_counts"]["pathfinding"][OutcomeClass.TIMEOUT] == 1
    assert data["category_counts"]["collision"] == 1
    assert data["pathfinding_summary"]["collision"] == 1
    assert data["pathfinding_summary"]["blocked_path"] == 1
    assert data["pathfinding_summary"]["stuck"] == 1

    collision_case = data["case_results"][2]
    stuck_case = data["case_results"][4]
    assert collision_case["eval_category"] == "collision"
    assert collision_case["pathfinding"]["collision"] is True
    assert collision_case["pathfinding"]["blocked_path"] is True
    assert stuck_case["eval_category"] == "pathfinding"
    assert stuck_case["pathfinding"]["stuck"] is True


def test_replay_cli_empty_filter_exits_zero_with_clear_message(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path, [_record("move-north", "!move", ["north"])])
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--dataset", str(dataset_path), "--command", "inventory", "--dry-run"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    assert "No dataset prompts matched the selected filters." in stdout.getvalue()
    assert "cases: 0" in stdout.getvalue()
    assert stderr.getvalue() == ""


def _write_dataset(
    tmp_path: Path,
    records: list[dict[str, object]],
) -> Path:
    path = tmp_path / "passing-prompts.ndjson"
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _record(
    scenario_id: str,
    command_token: str,
    args: list[str],
) -> dict[str, object]:
    return {
        "args": args,
        "available_commands": ["!move", "!inventory"],
        "command_token": command_token,
        "expected_constraints": [
            {"kind": "requires_command", "command": f"!{command_token.lstrip('!')}"}
        ],
        "prompt_context": f"Prompt for {scenario_id}.",
        "raw_content": " ".join((command_token, *args)),
        "scenario_id": scenario_id,
        "seed": 23,
    }
