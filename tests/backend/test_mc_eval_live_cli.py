"""Tests for the focused Minecraft live command smoke CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

from core.minecraft.eval.live_cli import main


def test_live_cli_dry_run_json_emits_case_count_and_outcomes() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--command", "move", "--cases", "3", "--dry-run", "--json"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert data["command"] == "move"
    assert data["resolved_command"] == "move"
    assert data["dry_run"] is True
    assert data["cases"] == 3
    assert len(data["case_results"]) == 3
    assert data["outcome_counts"]["success"] == 2
    assert data["outcome_counts"]["world_constraint"] == 1
    assert stderr.getvalue() == ""


def test_live_cli_verbose_prints_action_start_and_end_lines() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--command", "inventory", "--cases", "2", "--dry-run", "--verbose"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    text = stdout.getvalue()
    assert exit_code == 0, stderr.getvalue()
    assert text.count("command_input !inventory") == 2
    assert text.count("action_start action_id=") == 2
    assert text.count("action_end action_id=") == 2
    assert "final_state" in text
    assert stderr.getvalue() == ""


def test_live_cli_unknown_command_exits_nonzero_with_helpful_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--command", "teleport", "--cases", "1", "--dry-run"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "unknown Minecraft live eval command" in stderr.getvalue()
    assert "move" in stderr.getvalue()


def test_live_cli_enabled_live_mode_without_env_exits_nonzero() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--command", "move", "--cases", "1"],
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


def test_live_cli_writes_output_and_report_artifacts(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    output_path = tmp_path / "summary.json"
    report_dir = tmp_path / "report"

    exit_code = main(
        [
            "--command",
            "build",
            "--cases",
            "2",
            "--dry-run",
            "--output",
            str(output_path),
            "--report-dir",
            str(report_dir),
        ],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    assert output_path.is_file()
    assert (report_dir / "summary.json").is_file()
    assert (report_dir / "cases.ndjson").is_file()
    assert (report_dir / "report.md").is_file()

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["command"] == "build"
    assert output["resolved_command"] == "planAndBuild"
    assert output["cases"] == 2

    case_lines = (report_dir / "cases.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(case_lines) == 2
    assert json.loads(case_lines[0])["command_text"].startswith("!planAndBuild")
    assert "planAndBuild" in (report_dir / "report.md").read_text(encoding="utf-8")
