"""Tests for the focused Minecraft live command smoke CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

from core.minecraft.eval.live_cli import main
from core.minecraft.eval.live_runner import FakeBridgeClient


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
    assert data["category_counts"]["pathfinding"] == 2
    assert data["category_counts"]["collision"] == 1
    assert data["pathfinding_summary"]["success"] == 2
    assert data["pathfinding_summary"]["collision"] == 1
    assert data["pathfinding_summary"]["blocked_path"] == 1
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
    assert "inventory: " in text
    assert "block_mutation: " in text
    assert text.count("  inventory ") == 2
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
    assert "category_counts" in output
    assert "pathfinding_summary" in output

    case_lines = (report_dir / "cases.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(case_lines) == 2
    assert json.loads(case_lines[0])["command_text"].startswith("!planAndBuild")
    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "planAndBuild" in report
    assert "## Categories" in report
    assert "## Pathfinding" in report
    assert "## Inventory" in report
    assert "## Block Mutation" in report


def test_live_cli_place_here_report_includes_inventory_and_block_mutation_sections(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    report_dir = tmp_path / "report"

    exit_code = main(
        [
            "--command",
            "placeHere",
            "--cases",
            "2",
            "--dry-run",
            "--report-dir",
            str(report_dir),
        ],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    text = stdout.getvalue()
    assert exit_code == 0, stderr.getvalue()
    assert "inventory: " in text
    assert "block_mutation: " in text

    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "## Inventory" in report
    assert "## Block Mutation" in report
    assert "matches_expected=true" in report
    assert "matches_expected=false" in report


def test_live_cli_outputs_lifecycle_summary_and_report_section(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    output_path = tmp_path / "summary.json"
    report_dir = tmp_path / "report"
    bridge = FakeBridgeClient(
        {
            "move": (
                {
                    "status": "failed",
                    "reason": "death loop: died in lava after respawn",
                    "action_events": (
                        {
                            "kind": "death",
                            "ts_ms": 1,
                            "payload": {"reason": "died in lava"},
                        },
                        {
                            "kind": "death",
                            "ts_ms": 2,
                            "payload": {"reason": "died in lava again"},
                        },
                    ),
                    "final_state": {
                        "death_count": 2,
                        "death_loop": True,
                        "respawns": 2,
                        "spawn": {"safe": False, "reason": "spawn in lava"},
                    },
                },
            )
        }
    )

    exit_code = main(
        [
            "--command",
            "move",
            "--cases",
            "1",
            "--verbose",
            "--output",
            str(output_path),
            "--report-dir",
            str(report_dir),
        ],
        env={},
        bridge=bridge,
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    text = stdout.getvalue()
    assert exit_code == 0, stderr.getvalue()
    assert "lifecycle: " in text
    assert "death_loops=1" in text
    assert "  lifecycle " in text

    summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["lifecycle_summary"]["death_loops"] == 1
    assert summary["case_results"][0]["eval_category"] == "death_loop"
    assert summary["case_results"][0]["lifecycle"]["death_count"] == 2

    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "## Lifecycle" in report
    assert "death_count=2" in report
    assert "death_loop=true" in report


def test_live_cli_multi_agent_json_emits_timing_fields() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "--multi-agent",
            "--agents",
            "vera:move:2,rex:placeHere:2",
            "--tick-ms",
            "200",
            "--stagger-ms",
            "50",
            "--director-fanout",
            "2",
            "--dry-run",
            "--json",
        ],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert data["command"] == "multi-agent-timing"
    assert data["resolved_command"] == "multi-agent-timing"
    assert data["category_counts"]["multi_agent_timing"] == 4
    assert data["timing_summary"]["cases"] == 4
    assert data["timing_summary"]["agents"] == 2
    assert data["timing_summary"]["per_agent"]["vera"]["cases"] == 2
    assert data["profile_detail"]["multi_agent"]["tick_ms"] == 200
    assert data["case_results"][0]["agent_id"] == "vera"
    assert data["case_results"][0]["timing"]["agent_id"] == "vera"
    assert stderr.getvalue() == ""


def test_live_cli_multi_agent_invalid_agent_spec_exits_nonzero() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["--multi-agent", "--agents", "vera:move", "--dry-run"],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "invalid --agents spec" in stderr.getvalue()


def test_live_cli_multi_agent_report_contains_timing_section(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    report_dir = tmp_path / "report"

    exit_code = main(
        [
            "--multi-agent",
            "--agents",
            "vera:move:3,rex:placeHere:3",
            "--dry-run",
            "--report-dir",
            str(report_dir),
        ],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    text = stdout.getvalue()
    assert exit_code == 0, stderr.getvalue()
    assert "Minecraft multi-agent timing" in text
    assert "timing: " in text
    assert "timing_agent vera:" in text

    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "# Minecraft Multi-agent Timing" in report
    assert "## Multi-agent timing" in report
    assert "failure_classes=" in report
    assert "failure_class=queue_contention" in report
