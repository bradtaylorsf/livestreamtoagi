"""Tests for the local Minecraft cohort monitor."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "minecraft"
MONITOR = SCRIPT_DIR / "build_monitor.py"
SOAK = SCRIPT_DIR / "soak.sh"
FIXTURE = REPO_ROOT / "tests" / "backend" / "fixtures" / "minecraft_timeline"
GITIGNORE = REPO_ROOT / ".gitignore"


def _load_monitor() -> ModuleType:
    sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location("build_monitor", MONITOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_fixture(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE, run_dir)
    return run_dir


def test_fixture_monitor_renders_self_contained_html(tmp_path: Path) -> None:
    monitor = _load_monitor()
    run_dir = _copy_fixture(tmp_path)

    output = monitor.build(
        run_dir,
        now=monitor.parse_iso_ts("2026-05-20T22:10:00Z"),
        thresholds=monitor.WarningThresholds(stall_seconds=120, llm_idle_seconds=120),
    )

    html = output.read_text(encoding="utf-8")
    assert output == run_dir / "monitor.html"
    assert 'class="cohort-monitor"' in html
    assert '<script id="data" type="application/json">' in html
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "Alpha" in html
    assert "Vera" in html
    assert "Stalled" in html
    assert "No recent LLM" in html
    assert "Blank responses" in html
    assert "Repeated command" in html
    assert "Stuck loop" in html
    assert "Public Chat" in html
    assert "LLM Requests" in html
    assert "Filtered Timeline" in html


def test_warning_rules_fire_on_representative_events(tmp_path: Path) -> None:
    monitor = _load_monitor()
    now = monitor.parse_iso_ts("2026-05-20T22:10:00Z")
    assert now is not None
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "ts": "2026-05-20T22:04:00Z",
            "event_type": "llm.response",
            "agent": "alpha",
            "trace_id": "blank-1",
            "payload": {"completion": "", "total_tokens": 5, "model": "local/test"},
        },
        {
            "ts": "2026-05-20T22:04:10Z",
            "event_type": "llm.response",
            "agent": "alpha",
            "trace_id": "blank-2",
            "payload": {"completion": "", "total_tokens": 5, "model": "local/test"},
        },
        {
            "ts": "2026-05-20T22:04:20Z",
            "event_type": "llm.response",
            "agent": "alpha",
            "trace_id": "blank-3",
            "payload": {"completion": "", "total_tokens": 5, "model": "local/test"},
        },
        {
            "ts": "2026-05-20T22:05:00Z",
            "event_type": "action.intent",
            "agent": "alpha",
            "payload": {"commands": ['!move("loop", "forward", 1)']},
        },
        {
            "ts": "2026-05-20T22:05:10Z",
            "event_type": "action.intent",
            "agent": "alpha",
            "payload": {"commands": ['!move("loop", "forward", 1)']},
        },
        {
            "ts": "2026-05-20T22:05:20Z",
            "event_type": "action.intent",
            "agent": "alpha",
            "payload": {"commands": ['!move("loop", "forward", 1)']},
        },
        {
            "ts": "2026-05-20T22:05:30Z",
            "event_type": "action.result",
            "agent": "alpha",
            "payload": {"outcome": "blocked", "detail": "blocked by terrain"},
        },
        {
            "ts": "2026-05-20T22:05:40Z",
            "event_type": "action.result",
            "agent": "alpha",
            "payload": {"outcome": "blocked", "detail": "blocked by terrain"},
        },
        {
            "ts": "2026-05-20T22:05:50Z",
            "event_type": "action.result",
            "agent": "alpha",
            "payload": {"outcome": "unreachable", "detail": "target unreachable"},
        },
        {
            "ts": "2026-05-20T22:09:50Z",
            "event_type": "lifecycle",
            "agent": "alpha",
            "payload": {"text": "disconnected after restart"},
        },
    ]

    model = monitor.build_monitor_model(
        run_dir,
        events,
        metadata={"start_utc": "2026-05-20T22:00:00Z", "cost_agents": "alpha"},
        now=now,
        thresholds=monitor.WarningThresholds(
            stall_seconds=120,
            repeated_blank_count=3,
            repeated_command_count=3,
            restart_recent_seconds=300,
            stuck_loop_count=3,
            llm_idle_seconds=120,
        ),
    )

    agent = model["agents"][0]
    codes = {item["code"] for item in agent["warnings"]}
    assert codes == {
        "stalled",
        "repeated_blank_response",
        "repeated_command",
        "crash_restart",
        "stuck_loop",
        "no_recent_llm",
    }
    assert agent["restart_count"] == 1
    assert agent["tokens"]["total_tokens"] == 15


def test_llm_feed_renders_response_output(tmp_path: Path) -> None:
    monitor = _load_monitor()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "ts": "2026-05-20T22:00:01Z",
            "event_type": "llm.request",
            "agent": "vera",
            "trace_id": "trace-llm-1",
            "payload": {
                "model": "local/test",
                "purpose": "mindcraft_chat",
                "prompt_tokens": 0,
                "total_tokens": 0,
            },
        },
        {
            "ts": "2026-05-20T22:00:03Z",
            "event_type": "llm.response",
            "agent": "vera",
            "trace_id": "trace-llm-1",
            "payload": {
                "model": "local/test",
                "latency_ms": 2000,
                "completion_tokens": 6,
                "total_tokens": 6,
                "outcome": "ok",
                "response_text": "I will scout the ridge.",
            },
        },
        {
            "ts": "2026-05-20T22:00:04Z",
            "event_type": "action.intent",
            "agent": "vera",
            "trace_id": "trace-llm-1",
            "payload": {
                "commands": [{"name": "placeHere", "args": '"oak_log"', "text": '!placeHere("oak_log")'}]
            },
        },
        {
            "ts": "2026-05-20T22:00:05Z",
            "event_type": "action.result",
            "agent": "vera",
            "trace_id": "trace-llm-1",
            "payload": {
                "action": "placeHere",
                "outcome": "success",
                "verified": True,
                "detail": "placed oak_log",
            },
        },
    ]

    model = monitor.build_monitor_model(
        run_dir,
        events,
        metadata={"start_utc": "2026-05-20T22:00:00Z", "cost_agents": "vera"},
        now=monitor.parse_iso_ts("2026-05-20T22:00:05Z"),
    )
    html = monitor.render_monitor_html(model)

    assert model["pipeline"]["llm_requests"] == 1
    assert model["pipeline"]["accepted_commands"] == 1
    assert model["pipeline"]["executed_actions"] == 1
    assert model["pipeline"]["verified_actions"] == 1
    assert "Action Pipeline" in html
    assert "Accepted commands" in html
    assert "<th>Output</th>" in html
    assert "<th>Game effect</th>" in html
    assert "I will scout the ridge." in html
    assert '!placeHere(&quot;oak_log&quot;)' in html
    assert "placeHere: success placed oak_log" in html


def test_monitor_separates_stale_discards_from_action_failures(tmp_path: Path) -> None:
    monitor = _load_monitor()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "ts": "2026-05-20T22:00:01Z",
            "event_type": "llm.response",
            "agent": "fork",
            "trace_id": "trace-stale-1",
            "payload": {
                "model": "local/test",
                "outcome": "discarded_stale",
                "response_text": '!move("stale", "east", 3)',
                "discarded_commands": 1,
                "total_tokens": 7,
            },
        },
        {
            "ts": "2026-05-20T22:00:02Z",
            "event_type": "action.result",
            "agent": "fork",
            "trace_id": "trace-action-1",
            "payload": {
                "action": "placeHere",
                "outcome": "failure",
                "outcome_class": "placement_blocked",
                "verified": False,
                "detail": "Failed to place cobblestone at (1, 65, 2).",
            },
        },
    ]

    model = monitor.build_monitor_model(
        run_dir,
        events,
        metadata={"start_utc": "2026-05-20T22:00:00Z", "cost_agents": "fork"},
        now=monitor.parse_iso_ts("2026-05-20T22:00:02Z"),
    )
    html = monitor.render_monitor_html(model)

    assert model["pipeline"]["discarded_stale_responses"] == 1
    assert model["pipeline"]["discarded_commands"] == 1
    assert model["pipeline"]["accepted_commands"] == 0
    assert model["pipeline"]["executed_actions"] == 1
    assert model["pipeline"]["outcome_classes"]["placement_blocked"] == 1
    assert "discarded_stale" in html
    assert "Discarded commands" in html


def test_cli_writes_monitor_html(tmp_path: Path) -> None:
    run_dir = _copy_fixture(tmp_path)

    proc = subprocess.run(
        [sys.executable, str(MONITOR), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (run_dir / "monitor.html").is_file()
    assert "monitor rendered" in proc.stdout


def test_cli_uses_temp_output_for_committed_fixture_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "tests" / "backend" / "fixtures" / "minecraft_timeline"
    shutil.copytree(FIXTURE, run_dir)

    proc = subprocess.run(
        [sys.executable, str(MONITOR), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (run_dir / "monitor.html").exists()
    assert "minecraft-cohort-monitor-fixtures" in proc.stdout


def test_fixture_monitor_html_is_ignored_generated_output() -> None:
    text = GITIGNORE.read_text(encoding="utf-8")
    assert "/tests/backend/fixtures/minecraft_timeline/monitor.html" in text


def test_soak_script_wires_monitor_as_nonfatal_artifact() -> None:
    text = SOAK.read_text(encoding="utf-8")
    assert "build_monitor.py" in text
    assert "serve_monitor.py" in text
    assert "run_monitor_render" in text
    assert "append_monitor_summary" in text
    assert "Monitor render failed; continuing" in text
