"""Tests for structured Minecraft soak timeline export."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "minecraft"
BUILDER = SCRIPT_DIR / "build_timeline.py"
FIXTURE = REPO_ROOT / "tests" / "backend" / "fixtures" / "minecraft_timeline"
TIMELINE_EMITTER = SCRIPT_DIR / "fork-src" / "agent" / "bridge" / "timeline_emitter.js"
LMSTUDIO_USAGE = SCRIPT_DIR / "fork-src" / "agent" / "skills" / "lmstudio_usage.js"
HEARTBEAT = SCRIPT_DIR / "fork-src" / "agent" / "skills" / "heartbeat.js"


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
