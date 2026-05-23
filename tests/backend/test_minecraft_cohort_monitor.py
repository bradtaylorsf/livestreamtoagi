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
                "commands": [
                    {"name": "placeHere", "args": '"oak_log"', "text": '!placeHere("oak_log")'}
                ]
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
    assert "!placeHere(&quot;oak_log&quot;)" in html
    assert "placeHere: success placed oak_log" in html


def test_monitor_surfaces_runtime_queue_and_build_plan_events(tmp_path: Path) -> None:
    monitor = _load_monitor()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "ts": "2026-05-20T22:00:01Z",
            "event_type": "inbox.queued",
            "agent": "rex",
            "payload": {
                "source": "Vera",
                "message_preview": "Can you help with the cabin?",
                "queue_depth": 2,
                "running": True,
            },
        },
        {
            "ts": "2026-05-20T22:00:02Z",
            "event_type": "inbox.turn_completed",
            "agent": "rex",
            "payload": {"batch_size": 2, "remaining_depth": 1, "outcome": "ok"},
        },
        {
            "ts": "2026-05-20T22:00:03Z",
            "event_type": "llm.queue.enqueued",
            "trace_id": "queue-1",
            "payload": {"model": "local/test", "queued": 3, "running": 1},
        },
        {
            "ts": "2026-05-20T22:00:04Z",
            "event_type": "llm.queue.started",
            "trace_id": "queue-1",
            "payload": {"model": "local/test", "wait_ms": 420, "queued": 2, "running": 1},
        },
        {
            "ts": "2026-05-20T22:00:05Z",
            "event_type": "llm.queue.completed",
            "trace_id": "queue-1",
            "payload": {
                "model": "local/test",
                "wait_ms": 420,
                "latency_ms": 800,
                "status": 200,
                "running": 0,
                "tokens": {"total_tokens": 17},
            },
        },
        {
            "ts": "2026-05-20T22:00:06Z",
            "event_type": "action.queued",
            "agent": "rex",
            "payload": {"action": "action:placeHere", "queue_depth": 1},
        },
        {
            "ts": "2026-05-20T22:00:07Z",
            "event_type": "action.rejected_busy",
            "agent": "rex",
            "payload": {"action": "action:move", "queue_depth": 16, "reason": "queue_full"},
        },
        {
            "ts": "2026-05-20T22:00:08Z",
            "event_type": "build_plan.generation.completed",
            "agent": "rex",
            "payload": {
                "source": "builder_model",
                "provider": "openrouter",
                "builder_provider": "openrouter",
                "builder_model": "openrouter/test-frontier",
                "paid": True,
                "estimated_usd": 0.0042,
                "prompt_tokens": 50,
                "completion_tokens": 20,
                "total_tokens": 70,
                "plan": {"blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "oak_log"}]},
            },
        },
        {
            "ts": "2026-05-20T22:00:08.500Z",
            "event_type": "build_plan.generation.provider_failed",
            "agent": "rex",
            "payload": {
                "provider": "openrouter",
                "reason": "request_failed",
                "fallback_reason": "local",
            },
        },
        {
            "ts": "2026-05-20T22:00:08.750Z",
            "event_type": "build_plan.generation.skipped",
            "agent": "rex",
            "payload": {
                "reason": "cooldown",
                "cache_hit": True,
                "cooldown_remaining_sec": 240,
                "active_build": {"plan_id": "plan-build-1", "status": "executing"},
            },
        },
        {
            "ts": "2026-05-20T22:00:09Z",
            "event_type": "build_plan.execution.completed",
            "agent": "rex",
            "payload": {
                "action_id": "plan-build-1",
                "plan_id": "plan-build-1",
                "status": "completed",
                "cooldown_remaining_sec": 300,
                "result": "success: intended=1; present=1; missing=0; verified=1; completion=1.000",
            },
        },
    ]

    model = monitor.build_monitor_model(
        run_dir,
        events,
        metadata={"start_utc": "2026-05-20T22:00:00Z", "cost_agents": "rex"},
        now=monitor.parse_iso_ts("2026-05-20T22:00:09Z"),
    )
    html = monitor.render_monitor_html(model)

    assert model["pipeline"]["llm_queue_enqueued"] == 1
    assert model["pipeline"]["llm_queue_completed"] == 1
    assert model["pipeline"]["llm_queue_wait_ms_max"] == 420
    assert model["pipeline"]["inbox_queued_messages"] == 1
    assert model["pipeline"]["inbox_queue_depth_max"] == 2
    assert model["pipeline"]["actions_queued"] == 1
    assert model["pipeline"]["actions_rejected_busy"] == 1
    assert model["pipeline"]["action_queue_depth_max"] == 16
    assert model["pipeline"]["build_plans_generated"] == 1
    assert model["pipeline"]["build_plans_executed"] == 1
    assert model["pipeline"]["builder_plan_unique"] == 1
    assert model["pipeline"]["builder_plan_intended_blocks"] == 1
    assert model["pipeline"]["builder_plan_verified_blocks"] == 1
    assert model["pipeline"]["builder_plan_completion_rate"] == 1.0
    assert model["pipeline"]["builder_paid_calls"] == 1
    assert model["pipeline"]["builder_local_calls"] == 0
    assert model["pipeline"]["builder_estimated_usd"] == 0.0042
    assert model["pipeline"]["builder_provider_failures"] == 1
    assert model["pipeline"]["builder_plan_cache_hits"] == 1
    assert model["pipeline"]["builder_plan_skipped_cooldown"] == 1
    assert model["agents"][0]["inbox_queued_count"] == 1
    assert model["agents"][0]["action_rejected_count"] == 1
    assert model["agents"][0]["build_plan_count"] == 1
    assert model["agents"][0]["builder_paid_calls"] == 1
    assert model["agents"][0]["builder_failure_count"] == 1
    assert model["agents"][0]["builder_last_fallback_reason"] == "local"
    assert model["agents"][0]["builder_cache_hits"] == 1
    assert model["agents"][0]["builder_skipped_cooldown"] == 1
    assert model["agents"][0]["builder_cooldown_remaining_sec"] == 300
    assert model["agents"][0]["build_plan_intended_blocks"] == 1
    assert model["agents"][0]["build_plan_verified_blocks"] == 1
    assert "Queues" in html
    assert "Build Plans" in html
    assert "LLM queue done" in html
    assert "Max action depth" in html
    assert "openrouter/test-frontier" in html
    assert "Paid builder" in html
    assert "Active build" in html
    assert "Cache hits" in html
    assert "openrouter" in html
    assert "Intended blocks" in html
    assert "Verified blocks" in html


def test_monitor_surfaces_director_v2_panels_and_warnings(tmp_path: Path) -> None:
    monitor = _load_monitor()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "ts": "2026-05-20T22:00:01Z",
            "event_type": "director.scene.opened",
            "agent": "beta",
            "trace_id": "trace-scene-1",
            "payload": {
                "scene_id": "scene-1",
                "participants": ["alpha", "beta"],
                "observers": [],
                "triggering_event_type": "chat",
                "queue_depth": 1,
            },
        },
        {
            "ts": "2026-05-20T22:00:02Z",
            "event_type": "director.gate.decision",
            "agent": "beta",
            "trace_id": "trace-scene-1",
            "payload": {
                "scene_id": "scene-1",
                "agent_id": "beta",
                "selected": True,
                "turn_kind": "speaker",
                "reason": "direct_address",
                "suppressed_agents": ["alpha"],
                "queue_depth": 1,
                "scene_event_type": "chat",
                "llm_prompt_count": 1,
            },
        },
        {
            "ts": "2026-05-20T22:00:02.100Z",
            "event_type": "director.gate.decision",
            "agent": "alpha",
            "trace_id": "trace-scene-1",
            "payload": {
                "scene_id": "scene-1",
                "agent_id": "alpha",
                "selected": False,
                "reason": "suppressed",
                "suppression_reason": "fanout_capped",
                "queue_depth": 20,
                "scene_event_type": "chat",
                "avoided_prompt_count": 1,
            },
        },
        {
            "ts": "2026-05-20T22:00:03Z",
            "event_type": "director.gate.decision",
            "agent": "alpha",
            "trace_id": "trace-scene-2",
            "payload": {
                "scene_id": "scene-2",
                "agent_id": "alpha",
                "selected": False,
                "reason": "suppressed",
                "suppression_reason": "cooldown",
                "queue_depth": 2,
                "scene_event_type": "chat",
            },
        },
        {
            "ts": "2026-05-20T22:00:04Z",
            "event_type": "director.gate.decision",
            "agent": "alpha",
            "trace_id": "trace-scene-3",
            "payload": {
                "scene_id": "scene-3",
                "agent_id": "alpha",
                "selected": False,
                "reason": "suppressed",
                "suppression_reason": "cooldown",
                "queue_depth": 2,
                "scene_event_type": "chat",
            },
        },
        {
            "ts": "2026-05-20T22:00:05Z",
            "event_type": "director.tool.call",
            "agent": "alpha",
            "payload": {
                "agent_id": "alpha",
                "scene_id": "scene-1",
                "tool_name": "fetch_url",
                "status": "error",
                "ok": False,
                "error_class": "TimeoutError",
                "latency_ms": 100,
            },
        },
        {
            "ts": "2026-05-20T22:00:06Z",
            "event_type": "director.tool.call",
            "agent": "alpha",
            "payload": {
                "agent_id": "alpha",
                "scene_id": "scene-1",
                "tool_name": "fetch_url",
                "status": "error",
                "ok": False,
                "error_class": "TimeoutError",
                "latency_ms": 100,
            },
        },
        {
            "ts": "2026-05-20T22:00:07Z",
            "event_type": "director.tool.call",
            "agent": "alpha",
            "payload": {
                "agent_id": "alpha",
                "scene_id": "scene-1",
                "tool_name": "fetch_url",
                "status": "error",
                "ok": False,
                "error_class": "TimeoutError",
                "latency_ms": 100,
            },
        },
        {
            "ts": "2026-05-20T22:00:08Z",
            "event_type": "director.scene.digest",
            "agent": "beta",
            "payload": {
                "scene_id": "scene-1",
                "participants": ["alpha", "beta"],
                "distributed_to": ["alpha", "beta"],
                "entries_count": 3,
                "tokens": 33,
                "latency_ms": 50,
                "summary": "Beta spoke while Alpha was suppressed.",
            },
        },
        {
            "ts": "2026-05-20T22:00:09Z",
            "event_type": "build_plan.generation.completed",
            "agent": "beta",
            "payload": {
                "scene_id": "scene-1",
                "owner": "beta",
                "plan_id": "plan-scene-1",
                "provider": "local",
                "estimated_usd": 0,
                "plan": {"blocks": []},
            },
        },
    ]

    model = monitor.build_monitor_model(
        run_dir,
        events,
        metadata={"start_utc": "2026-05-20T22:00:00Z", "cost_agents": "alpha beta"},
        now=monitor.parse_iso_ts("2026-05-20T22:00:09Z"),
        thresholds=monitor.WarningThresholds(
            director_queue_depth=10,
            director_starvation_scenes=3,
            director_failure_loop_count=3,
        ),
    )
    html = monitor.render_monitor_html(model)

    codes = {item["code"] for item in model["director"]["warnings"]}
    assert {
        "director_queue_depth",
        "director_starvation",
        "director_tool_failure_loop",
    }.issubset(codes)
    alpha = next(agent for agent in model["agents"] if agent["agent"] == "alpha")
    assert {"director_queue_depth", "director_starvation", "director_tool_failure_loop"}.issubset(
        {item["code"] for item in alpha["warnings"]}
    )
    assert model["director"]["summary"]["selected_turns"] == 1
    assert model["director"]["summary"]["suppressed_turns"] == 3
    assert model["director"]["summary"]["queue_depth_max"] == 20
    assert "Director V2 Evidence" in html
    assert "Selected vs Suppressed" in html
    assert "Scene Digests &amp; Compactions" in html
    assert "Builder Macros &amp; Tools" in html
    assert "Fairness" in html
    assert "Director Events" in html
    assert "fanout_capped" in html
    assert "TimeoutError" in html


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
