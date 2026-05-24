"""Tests for structured Minecraft soak timeline export."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "minecraft"
BUILDER = SCRIPT_DIR / "build_timeline.py"
FIXTURE = REPO_ROOT / "tests" / "backend" / "fixtures" / "minecraft_timeline"
TIMELINE_EMITTER = SCRIPT_DIR / "fork-src" / "agent" / "bridge" / "timeline_emitter.js"
LMSTUDIO_USAGE = SCRIPT_DIR / "fork-src" / "agent" / "skills" / "lmstudio_usage.js"
HEARTBEAT = SCRIPT_DIR / "fork-src" / "agent" / "skills" / "heartbeat.js"
MEMORY_CONTEXT = SCRIPT_DIR / "fork-src" / "agent" / "skills" / "memory_context.js"


def _load_builder() -> ModuleType:
    sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location("build_timeline", BUILDER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_fixture(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE, run_dir)
    for artifact in ("timeline.ndjson", "timeline-totals.json", "monitor.html"):
        (run_dir / artifact).unlink(missing_ok=True)
    bots_dir = run_dir / "bots"
    bots_dir.mkdir(exist_ok=True)
    (bots_dir / "alpha.log").write_text(
        "\n".join(
            [
                "2026-05-20T22:00:04Z Alpha position x=0 y=64 z=0",
                "2026-05-20T22:00:10Z Alpha position x=1 y=64 z=0",
                "2026-05-20T22:00:35Z Alpha position x=2 y=64 z=0",
                "2026-05-20T22:01:00Z Alpha disconnected after local transport restart",
            ]
        ),
        encoding="utf-8",
    )
    return run_dir


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fixture_export_writes_ordered_timeline_and_totals(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = _copy_fixture(tmp_path)

    result = builder.build_timeline(run_dir, state_sample_interval_seconds=30)
    builder.write_artifacts(run_dir, result)

    events = _events(run_dir / "timeline.ndjson")
    event_types = [event["event_type"] for event in events]
    assert events == sorted(events, key=lambda event: event["seq"])
    assert [event["event_id"] for event in events] == [
        f"timeline-{index:06d}" for index in range(1, len(events) + 1)
    ]
    assert "llm.request" in event_types
    assert "llm.response" in event_types
    assert "action.intent" in event_types
    assert "action.start" in event_types
    assert "action.result" in event_types
    assert "chat.public" in event_types
    assert "state.sample" in event_types
    assert "error" in event_types

    totals = json.loads((run_dir / "timeline-totals.json").read_text(encoding="utf-8"))
    assert totals["counts_by_event_type"]["llm.response"] == 1
    assert totals["counts_by_agent"]["alpha"] >= 7
    assert totals["counts_by_model"]["local/test-chat"] == 2
    assert totals["token_totals"]["requests"] == 1
    assert totals["token_totals"]["provider_reported"]["requests"] == 1
    assert totals["token_totals"]["total_tokens"] == 17
    assert totals["tokens"]["total"] == 17
    assert totals["tokens"]["provider_reported"] == 17
    assert totals["tokens"]["estimated"] == 0


def test_director_v2_events_flow_through_timeline_and_totals(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = _copy_fixture(tmp_path)

    result = builder.build_timeline(run_dir, state_sample_interval_seconds=30)
    builder.write_artifacts(run_dir, result)

    exported = _events(run_dir / "timeline.ndjson")
    director_events = [event for event in exported if event["event_type"].startswith("director.")]
    assert [event["event_type"] for event in director_events] == [
        "director.scene.opened",
        "director.gate.decision",
        "director.gate.decision",
        "director.gate.decision",
        "director.tool.call",
        "director.memory.compaction",
        "director.scene.digest",
        "director.scene.closed",
    ]
    assert {event["trace_id"] for event in director_events} == {"trace-scene-1"}

    totals = json.loads((run_dir / "timeline-totals.json").read_text(encoding="utf-8"))
    director = totals["director"]
    assert director["scenes_opened"] == 1
    assert director["scenes_closed"] == 1
    assert director["selected_turns"] == 1
    assert director["suppressed_count"] == 2
    assert director["suppressed_by_reason"] == {"fanout_capped": 2}
    assert director["tool_calls_by_tool"] == {"recall_memory": 1}
    assert director["memory_compactions"] == 1
    assert director["build_plan_ids"] == ["build-plan-fixture-1"]
    assert director["llm_prompts_total"] == 1
    assert director["avoided_llm_prompts"] == 2
    assert director["ratio_prompts_per_scene_turn"] == 1.0


def test_cli_accepts_explicit_output_and_totals_paths(tmp_path: Path) -> None:
    run_dir = _copy_fixture(tmp_path)
    output_path = tmp_path / "exports" / "timeline.ndjson"
    totals_path = tmp_path / "exports" / "timeline-totals.json"

    proc = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--run-dir",
            str(run_dir),
            "--output",
            str(output_path),
            "--totals",
            str(totals_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert output_path.is_file()
    assert totals_path.is_file()
    assert "timeline exported" in proc.stdout
    assert str(output_path) in proc.stdout
    assert not (run_dir / "timeline.ndjson").exists()
    events = _events(output_path)
    totals = json.loads(totals_path.read_text(encoding="utf-8"))
    assert any(event["event_type"] == "llm.response" for event in events)
    assert totals["counts_by_event_type"]["llm.response"] == 1
    assert totals["tokens"]["total"] > 0
    assert "estimated" in totals["tokens"]
    assert "provider_reported" in totals["tokens"]


def test_missing_lmstudio_usage_is_estimated_and_marked(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (raw_dir / "vera.ndjson").write_text(
        json.dumps(
            {
                "ts": "2026-05-20T22:00:01Z",
                "event_type": "llm.response",
                "agent": "vera",
                "trace_id": "trace-llm-missing-usage",
                "payload": {
                    "model": "local/no-usage",
                    "messages": [{"role": "user", "content": "place a torch"}],
                    "completion": "I will place a torch.",
                    "outcome": "ok",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    event = result.events[0]
    assert event.event_type == "llm.response"
    assert event.payload["estimated"] is True
    assert event.payload["usage_source"] == "estimated"
    assert event.payload["prompt_tokens"] > 0
    assert event.payload["completion_tokens"] > 0
    assert result.totals["token_totals"]["estimated"]["requests"] == 1
    assert result.totals["tokens"]["estimated"] == result.totals["tokens"]["total"]


def test_lm_queue_events_are_counted_but_not_token_usage(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (raw_dir / "llm-queue.ndjson").write_text(
        "\n".join(
            json.dumps(event)
            for event in [
                {
                    "ts": "2026-05-20T22:00:01Z",
                    "event_type": "llm.queue.enqueued",
                    "trace_id": "queue-1",
                    "payload": {"model": "local/test", "queued": 1},
                },
                {
                    "ts": "2026-05-20T22:00:02Z",
                    "event_type": "llm.queue.completed",
                    "trace_id": "queue-1",
                    "payload": {
                        "model": "local/test",
                        "wait_ms": 50,
                        "latency_ms": 100,
                        "status": 200,
                        "tokens": {"total_tokens": 999},
                    },
                },
                {
                    "ts": "2026-05-20T22:00:03Z",
                    "event_type": "llm.response",
                    "agent": "vera",
                    "trace_id": "trace-response-1",
                    "payload": {
                        "model": "local/test",
                        "prompt_tokens": 4,
                        "completion_tokens": 6,
                        "total_tokens": 10,
                        "estimated": False,
                    },
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    assert result.totals["counts_by_event_type"]["llm.queue.enqueued"] == 1
    assert result.totals["counts_by_event_type"]["llm.queue.completed"] == 1
    assert result.totals["counts_by_model"]["local/test"] == 1
    assert result.totals["tokens"]["total"] == 10
    assert result.totals["token_totals"]["requests"] == 1


def test_bot_log_lmstudio_calls_are_inferred_without_raw_telemetry(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    (run_dir / "bots").mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (run_dir / "bots" / "vera.log").write_text(
        "\n".join(
            [
                "2026-05-20T22:00:01Z Awaiting LM Studio response from model local/test",
                '2026-05-20T22:00:03Z Generated response: I will mark the base. !placeHere("oak_log")',
                '2026-05-20T22:00:04Z Vera full response to Rex: ""I will mark the base. !placeHere("oak_log")""',
                "2026-05-20T22:00:05Z parsed command: { commandName: '!placeHere', args: [ 'oak_log' ] }",
                "2026-05-20T22:00:06Z Agent executed: !placeHere and got: Action output:",
                "2026-05-20T22:00:07Z Placed oak_log at (1, 64, 1).",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    llm_request = next(event for event in result.events if event.event_type == "llm.request")
    llm_response = next(event for event in result.events if event.event_type == "llm.response")
    intent = next(event for event in result.events if event.event_type == "action.intent")
    assert llm_request.trace_id == llm_response.trace_id == intent.trace_id
    assert llm_request.payload["usage_source"] == "bot_log_inferred"
    assert llm_response.payload["usage_source"] == "bot_log_inferred"
    assert llm_response.payload["response_text"] == 'I will mark the base. !placeHere("oak_log")'
    assert llm_response.payload["completion_tokens"] > 0
    assert llm_response.payload["outcome"] == "ok"
    assert llm_response.payload["accepted_commands"] == 1
    assert intent.payload["commands"][0]["text"] == '!placeHere("oak_log")'
    result_event = next(event for event in result.events if event.event_type == "action.result")
    assert result_event.payload["outcome"] == "success"
    assert result_event.payload["verified"] is True
    assert result.totals["counts_by_event_type"]["llm.response"] == 1
    assert result.totals["counts_by_event_type"]["action.result"] == 1
    assert result.totals["tokens"]["estimated"] == result.totals["tokens"]["total"]


def test_stale_generated_commands_do_not_become_action_intents(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    (run_dir / "bots").mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (run_dir / "bots" / "fork.log").write_text(
        "\n".join(
            [
                "2026-05-20T22:00:01Z Awaiting LM Studio response from model local/test",
                '2026-05-20T22:00:03Z Generated response: !move("stale", "east", 3)',
                "2026-05-20T22:00:04Z Fork received new message while generating, discarding old response.",
                '2026-05-20T22:00:05Z Fork full response to Vera: """"',
                "2026-05-20T22:00:06Z no response",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    responses = [event for event in result.events if event.event_type == "llm.response"]
    intents = [event for event in result.events if event.event_type == "action.intent"]
    assert len(responses) == 1
    assert responses[0].payload["outcome"] == "discarded_stale"
    assert responses[0].payload["discarded_commands"] == 1
    assert intents == []


def test_bot_log_narration_without_accepted_command_is_not_action_intent(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    (run_dir / "bots").mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (run_dir / "bots" / "vera.log").write_text(
        "\n".join(
            [
                "2026-05-20T22:00:01Z Vera: I will build the west wall now.",
                "2026-05-20T22:00:02Z Memory updated to: Vera wants a wall.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    assert not any(event.event_type == "action.intent" for event in result.events)


def test_incoming_chat_command_examples_do_not_become_action_intents_or_errors(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    (run_dir / "bots").mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (run_dir / "bots" / "sentinel.log").write_text(
        "\n".join(
            [
                "2026-05-20T22:00:01Z Sentinel received message from Vera: "
                'please provide exact coordinates before using !place("act", "dirt", {"x":1,"y":64,"z":1})',
                "2026-05-20T22:00:02Z Memory updated to: Sentinel should ask for coordinates.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    assert not any(event.event_type == "action.intent" for event in result.events)
    assert not any(event.event_type == "error" for event in result.events)


def test_no_timestamp_bot_logs_interpolate_to_file_mtime(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    bots_dir = run_dir / "bots"
    bots_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    log_path = bots_dir / "vera.log"
    log_path.write_text(
        "\n".join(
            [
                "Awaiting LM Studio response from model local/test",
                'Generated response: !placeHere("oak_log")',
                'Vera full response to Rex: ""!placeHere("oak_log")""',
                "Agent executed: !placeHere and got: Action output: Placed oak_log at (1, 64, 1).",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(log_path, (1_779_315_000, 1_779_315_000))

    result = builder.build_timeline(run_dir)

    latest = max(event.ts for event in result.events if event.agent == "vera")
    assert latest.isoformat().startswith("2026-05-20T22:10:00")


def test_time_only_logs_use_local_timezone_before_z_export(monkeypatch) -> None:
    builder = _load_builder()
    monkeypatch.setenv("SOAK_LOCAL_TIMEZONE", "America/Los_Angeles")

    ts = builder.parse_line_ts(
        "[22:26:16 INFO]: <Aurora> Keep building out this strong stone wall!",
        base_date=datetime(2026, 5, 21, 4, 45, 19, tzinfo=UTC),
        fallback_seq=1,
    )

    assert ts.isoformat() == "2026-05-21T05:26:16+00:00"


def test_bridge_settle_and_behavior_status_are_telemetry_not_action_results(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    (run_dir / "bots").mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (run_dir / "bots" / "alpha.log").write_text(
        "\n".join(
            [
                "2026-05-20T22:00:01Z [behavior-status] Exiting.",
                "2026-05-20T22:00:02Z bridge_event trace_id=trace-1 request_id=bridge-1 "
                "direction=outbound service=action method=result phase=settle ok=true "
                "outcome=ok latency_ms=2",
                "2026-05-20T22:00:03Z Agent executed: !placeHere and got: Action output:",
                "2026-05-20T22:00:04Z Placed oak_log at (1, 64, 1).",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)

    event_types = [event.event_type for event in result.events]
    assert "behavior.event" in event_types
    assert "bridge.action.result" in event_types
    assert result.totals["counts_by_event_type"]["action.result"] == 1
    assert result.totals["counts_by_event_type"]["bridge.action.result"] == 1
    assert not any(event.event_type == "chat.public" for event in result.events)


def test_heartbeat_events_are_preserved_and_counted(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    events = [
        {
            "ts": "2026-05-20T22:00:01Z",
            "event_type": "heartbeat.fired",
            "agent": "vera",
            "trace_id": "trace-heartbeat-1",
            "payload": {"reason": "idle", "idle_ms": 91000, "in_action": False},
        },
        {
            "ts": "2026-05-20T22:00:02Z",
            "event_type": "heartbeat.outcome",
            "agent": "vera",
            "trace_id": "trace-heartbeat-1",
            "payload": {"had_command": True, "no_command_streak": 0},
        },
        {
            "ts": "2026-05-20T22:00:03Z",
            "event_type": "heartbeat.halted",
            "agent": "rex",
            "trace_id": "trace-heartbeat-2",
            "payload": {"reason": "max-no-command", "no_command_streak": 3},
        },
    ]
    (raw_dir / "vera.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)
    builder.write_artifacts(run_dir, result)

    exported = _events(run_dir / "timeline.ndjson")
    assert [event["event_type"] for event in exported] == [
        "heartbeat.fired",
        "heartbeat.outcome",
        "heartbeat.halted",
    ]
    assert exported[0]["payload"]["reason"] == "idle"
    totals = json.loads((run_dir / "timeline-totals.json").read_text(encoding="utf-8"))
    assert totals["counts_by_event_type"]["heartbeat.fired"] == 1
    assert totals["counts_by_event_type"]["heartbeat.outcome"] == 1
    assert totals["counts_by_event_type"]["heartbeat.halted"] == 1


def test_memory_context_events_are_preserved_and_counted(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    events = [
        {
            "ts": "2026-05-20T22:00:01Z",
            "event_type": "memory_context.startup",
            "agent": "vera",
            "trace_id": "trace-memory-1",
            "payload": {"fetched": True, "context_chars": 400},
        },
        {
            "ts": "2026-05-20T22:00:02Z",
            "event_type": "memory_context.fetched",
            "agent": "vera",
            "trace_id": "trace-memory-2",
            "payload": {
                "agent_id": "vera",
                "simulation_id": "sim-test",
                "core_chars": 120,
                "recall_chars": 80,
            },
        },
    ]
    (raw_dir / "vera.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    result = builder.build_timeline(run_dir)
    builder.write_artifacts(run_dir, result)

    exported = _events(run_dir / "timeline.ndjson")
    assert [event["event_type"] for event in exported] == [
        "memory_context.startup",
        "memory_context.fetched",
    ]
    totals = json.loads((run_dir / "timeline-totals.json").read_text(encoding="utf-8"))
    assert totals["counts_by_event_type"]["memory_context.startup"] == 1
    assert totals["counts_by_event_type"]["memory_context.fetched"] == 1


def test_trace_id_correlates_intent_start_and_result_chain(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = _copy_fixture(tmp_path)

    result = builder.build_timeline(run_dir)

    chain = [
        event
        for event in result.events
        if event.trace_id == "trace-action-1"
        and event.event_type in {"action.intent", "action.start", "action.result"}
    ]
    assert [event.event_type for event in chain] == [
        "action.intent",
        "action.start",
        "action.start",
        "action.result",
        "action.result",
    ]


def test_high_frequency_position_lines_are_interval_sampled(tmp_path: Path) -> None:
    builder = _load_builder()
    run_dir = _copy_fixture(tmp_path)

    result = builder.build_timeline(run_dir, state_sample_interval_seconds=30)

    samples = [
        event
        for event in result.events
        if event.event_type == "state.sample" and event.source == "bots/alpha.log"
    ]
    assert [event.payload["position"] for event in samples] == [
        {"x": 0.0, "y": 64.0, "z": 0.0},
        {"x": 2.0, "y": 64.0, "z": 0.0},
    ]


def test_malformed_lines_do_not_crash_cli(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "bots").mkdir(parents=True)
    (run_dir / "timeline-raw").mkdir()
    (run_dir / "metadata.env").write_text("start_utc=2026-05-20T22:00:00Z\n", encoding="utf-8")
    (run_dir / "bots" / "grok.log").write_text(
        "\x00\x01 this is not useful\n2026-05-20T22:00:01Z Grok: I will move north.\n",
        encoding="utf-8",
    )
    (run_dir / "timeline-raw" / "grok.ndjson").write_text("{bad json\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    events = _events(run_dir / "timeline.ndjson")
    assert any(event["event_type"] == "error" for event in events)
    assert (run_dir / "timeline-totals.json").is_file()


def test_node_timeline_shims_are_dependency_free_and_emit_expected_events() -> None:
    emitter = TIMELINE_EMITTER.read_text(encoding="utf-8")
    usage = LMSTUDIO_USAGE.read_text(encoding="utf-8")
    heartbeat = HEARTBEAT.read_text(encoding="utf-8")
    memory_context = MEMORY_CONTEXT.read_text(encoding="utf-8")

    assert "MC_TIMELINE_NDJSON" in emitter
    assert "MC_RUN_DIR" in emitter
    assert "appendFileSync" in emitter
    assert "throw" not in emitter
    assert "llm.request" in usage
    assert "llm.response" in usage
    assert "deterministicTokenEstimate" in usage
    assert "Math.ceil(text.length / 4)" in usage
    assert "from 'node:" in usage
    assert "from '../bridge/timeline_emitter.js'" in usage
    assert "heartbeat.fired" in heartbeat
    assert "heartbeat.outcome" in heartbeat
    assert "MC_HEARTBEAT_IDLE_MS" in heartbeat
    assert "from '../bridge/timeline_emitter.js'" in heartbeat
    assert "memory_context.fetched" in memory_context
    assert "MC_SIM_MEMORY_CONTEXT_ENABLED" in memory_context
    assert "from '../bridge/timeline_emitter.js'" in memory_context
