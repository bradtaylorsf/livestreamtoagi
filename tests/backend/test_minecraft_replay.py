"""Tests for the Minecraft replay scheduler + CLI (issue #858)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.minecraft.replay import (
    ChatEvent,
    ExecuteBuildScriptEvent,
    ReplayManifest,
    ReplayScheduler,
    ScreenshotEvent,
    capture_screenshot,
)
from core.simulation.decision_log_schema import SCHEMA_VERSION

# ─── Bridge fakes ────────────────────────────────────────────────


class _RecordingBridge:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        self.commands.append(command_text)
        # Mimic the FakeBridgeClient contract used by the live eval.
        return {"status": "ok", "reason": "completed"}


class _NoScreenshotBridge:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        self.commands.append(command_text)
        if command_text.startswith("!screenshot"):
            return {"status": "rejected", "reason": "screenshot endpoint unavailable"}
        return {"status": "ok"}


# ─── Fixture helpers ─────────────────────────────────────────────


def _write_decision_log(sim_folder: Path, rows: list[dict[str, Any]]) -> Path:
    log_path = sim_folder / "decision_log.jsonl"
    with log_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return log_path


def _utterance(actor: str, text: str, *, tick: int, sim_time: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "utterance",
        "tick": tick,
        "wall_time": datetime.now(UTC).isoformat(),
        "sim_time": sim_time,
        "actor_id": actor,
        "payload": {"text": text, "channel": "chat"},
    }


def _propose_build(
    actor: str, intent_id: str, *, tick: int, sim_time: float
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "tool_intent",
        "tick": tick,
        "wall_time": datetime.now(UTC).isoformat(),
        "sim_time": sim_time,
        "actor_id": actor,
        "payload": {
            "tool_name": "propose_build",
            "args": {
                "intent_id": intent_id,
                "structure_type": "cabin",
                "proposer_id": actor,
            },
            "status": "simulated",
        },
    }


def _relationship_delta(
    a: str, b: str, *, tick: int, sim_time: float, before: float, after: float
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "relationship_delta",
        "tick": tick,
        "wall_time": datetime.now(UTC).isoformat(),
        "sim_time": sim_time,
        "actor_id": a,
        "payload": {
            "a": a,
            "b": b,
            "before": {"sentiment": before},
            "after": {"sentiment": after},
        },
    }


def _alliance_delta(
    alliance_id: str, members: list[str], *, tick: int, sim_time: float
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "alliance_delta",
        "tick": tick,
        "wall_time": datetime.now(UTC).isoformat(),
        "sim_time": sim_time,
        "actor_id": None,
        "payload": {
            "alliance_id": alliance_id,
            "members": members,
            "before": {"members": []},
            "after": {"members": members},
        },
    }


def _write_build_intents(sim_folder: Path, rows: list[dict[str, Any]]) -> Path:
    path = sim_folder / "build_intents.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def _write_build_script(sim_folder: Path, intent_id: str) -> Path:
    target_dir = sim_folder / "build_scripts"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{intent_id}.script.json"
    payload = {
        "intent_id": intent_id,
        "structure_type": "cabin",
        "size_class": "small",
        "origin": {"x": 0, "y": 64, "z": 0},
        "commands": [
            {
                "kind": "setblock",
                "position": {"x": 1, "y": 64, "z": 1},
                "block_type": "oak_planks",
                "region_to": None,
                "state": None,
                "structure_id": None,
                "wait_seconds": None,
            }
        ],
        "materials_manifest": {"oak_planks": 1},
        "total_blocks": 1,
        "estimated_seconds": 0.125,
        "source_plan_hash": "fakehash",
        "compiler_version": 1,
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


# ─── Scheduler tests ─────────────────────────────────────────────


def test_scheduler_orders_events_by_sim_time(tmp_path: Path) -> None:
    rows = [
        _utterance("rex", "hello", tick=1, sim_time=1.0),
        _propose_build("rex", "build-001", tick=2, sim_time=2.0),
        _utterance("vera", "ack", tick=3, sim_time=3.0),
    ]
    _write_decision_log(tmp_path, rows)
    _write_build_intents(
        tmp_path,
        [
            {
                "intent_id": "build-001",
                "actor_id": "rex",
                "submitted_at": 2.0,
                "args": {"intent_id": "build-001"},
            }
        ],
    )
    _write_build_script(tmp_path, "build-001")

    scheduler = ReplayScheduler(sim_folder=tmp_path)
    events = scheduler.events()

    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    build_events = [e for e in events if isinstance(e, ExecuteBuildScriptEvent)]
    screenshots = [e for e in events if isinstance(e, ScreenshotEvent)]

    assert [e.text for e in chat_events] == ["hello", "ack"]
    assert len(build_events) == 1
    assert build_events[0].intent_id == "build-001"
    # build_start + build_complete by default
    milestones = sorted({s.milestone for s in screenshots})
    assert "build_start" in milestones
    assert "build_complete" in milestones


def test_scheduler_emits_conflict_milestone_on_sentiment_drop(tmp_path: Path) -> None:
    rows = [
        _relationship_delta("rex", "vera", tick=1, sim_time=1.0, before=0.5, after=0.3),
    ]
    _write_decision_log(tmp_path, rows)

    events = ReplayScheduler(sim_folder=tmp_path).events()
    assert any(
        isinstance(e, ScreenshotEvent) and e.milestone == "conflict" for e in events
    )


def test_scheduler_ignores_small_sentiment_changes(tmp_path: Path) -> None:
    rows = [
        _relationship_delta("rex", "vera", tick=1, sim_time=1.0, before=0.5, after=0.45),
    ]
    _write_decision_log(tmp_path, rows)
    events = ReplayScheduler(sim_folder=tmp_path).events()
    assert not any(
        isinstance(e, ScreenshotEvent) and e.milestone == "conflict" for e in events
    )


def test_scheduler_emits_alliance_form_when_alliance_appears(tmp_path: Path) -> None:
    rows = [
        _alliance_delta("alliance-001", ["rex", "vera"], tick=1, sim_time=1.0),
    ]
    _write_decision_log(tmp_path, rows)
    events = ReplayScheduler(sim_folder=tmp_path).events()
    assert any(
        isinstance(e, ScreenshotEvent) and e.milestone == "alliance_form" for e in events
    )


def test_scheduler_respects_enabled_milestones(tmp_path: Path) -> None:
    rows = [
        _propose_build("rex", "build-002", tick=1, sim_time=1.0),
        _alliance_delta("alliance-002", ["rex"], tick=2, sim_time=2.0),
    ]
    _write_decision_log(tmp_path, rows)
    _write_build_intents(
        tmp_path,
        [
            {
                "intent_id": "build-002",
                "actor_id": "rex",
                "submitted_at": 1.0,
                "args": {"intent_id": "build-002"},
            }
        ],
    )
    _write_build_script(tmp_path, "build-002")

    events = ReplayScheduler(
        sim_folder=tmp_path,
        enabled_milestones=("build_start",),
    ).events()
    milestones = {e.milestone for e in events if isinstance(e, ScreenshotEvent)}
    assert milestones == {"build_start"}


def test_scheduler_executes_orphan_build_intent_rows(tmp_path: Path) -> None:
    """A build intent without a matching tool_intent row is still replayed."""
    # No decision log — only build_intents.jsonl
    _write_decision_log(tmp_path, [])
    _write_build_intents(
        tmp_path,
        [
            {
                "intent_id": "build-orphan",
                "actor_id": "rex",
                "submitted_at": 5.0,
                "args": {"intent_id": "build-orphan"},
            }
        ],
    )
    _write_build_script(tmp_path, "build-orphan")

    events = ReplayScheduler(sim_folder=tmp_path).events()
    build_events = [e for e in events if isinstance(e, ExecuteBuildScriptEvent)]
    assert len(build_events) == 1
    assert build_events[0].intent_id == "build-orphan"


# ─── Screenshot helper ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_screenshot_writes_placeholder_when_bridge_unsupported(
    tmp_path: Path,
) -> None:
    bridge = _NoScreenshotBridge()
    out = tmp_path / "shots" / "x.png"
    result = await capture_screenshot(bridge, label="hello", output_path=out)
    assert out.is_file()
    assert out.stat().st_size > 0
    assert result.status == "unsupported"


@pytest.mark.asyncio
async def test_capture_screenshot_stores_ok_bytes_when_bridge_supports_it(
    tmp_path: Path,
) -> None:
    class _SupportingBridge:
        async def send_command(self, command_text: str) -> Mapping[str, Any]:
            assert command_text.startswith("!screenshot")
            return {"status": "ok", "image_bytes": b"\x89PNG-FAKE"}

    out = tmp_path / "shots" / "ok.png"
    result = await capture_screenshot(_SupportingBridge(), label="x", output_path=out)
    assert out.read_bytes() == b"\x89PNG-FAKE"
    assert result.status == "ok"


# ─── Manifest ─────────────────────────────────────────────────


def test_manifest_round_trips(tmp_path: Path) -> None:
    manifest = ReplayManifest(
        sim_folder=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        started_at=datetime.now(UTC),
        world_profile="default",
        bridge_kind="FakeBridge",
    )
    path = tmp_path / "manifest.json"
    manifest.write(path)
    loaded = ReplayManifest.from_path(path)
    assert loaded.sim_folder == manifest.sim_folder
    assert loaded.world_profile == "default"


# ─── CLI end-to-end (fake bridge) ───────────────────────────────


def test_cli_runs_with_fake_bridge_and_emits_manifest(tmp_path: Path) -> None:
    from scripts.replay_in_minecraft import main

    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    rows = [
        _utterance("rex", "hi", tick=1, sim_time=1.0),
        _propose_build("rex", "build-cli", tick=2, sim_time=2.0),
    ]
    _write_decision_log(sim_folder, rows)
    _write_build_intents(
        sim_folder,
        [
            {
                "intent_id": "build-cli",
                "actor_id": "rex",
                "submitted_at": 2.0,
                "args": {"intent_id": "build-cli"},
            }
        ],
    )
    _write_build_script(sim_folder, "build-cli")

    output_dir = tmp_path / "out"
    rc = main(
        [
            "--sim-folder",
            str(sim_folder),
            "--dry-run",
            "--output-dir",
            str(output_dir),
            "--speed-multiplier",
            "100.0",
        ],
        env={},
        load_env=False,
    )
    assert rc == 0
    manifest_path = output_dir / "replay_manifest.json"
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text())
    assert payload["events_replayed_count"] > 0
    assert payload["build_scripts_executed"] == ["build-cli"]
    # build_start + build_complete screenshots written
    screenshots_dir = output_dir / "screenshots"
    pngs = sorted(p.name for p in screenshots_dir.glob("*.png"))
    assert any(name.startswith("build_start") for name in pngs)
    assert any(name.startswith("build_complete") for name in pngs)


def test_cli_replay_is_idempotent(tmp_path: Path) -> None:
    """Re-running against the same sim folder writes the same screenshot names."""
    from scripts.replay_in_minecraft import main

    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    _write_decision_log(
        sim_folder,
        [_propose_build("rex", "build-idem", tick=1, sim_time=1.0)],
    )
    _write_build_intents(
        sim_folder,
        [
            {
                "intent_id": "build-idem",
                "actor_id": "rex",
                "submitted_at": 1.0,
                "args": {"intent_id": "build-idem"},
            }
        ],
    )
    _write_build_script(sim_folder, "build-idem")

    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for output_dir in (out_a, out_b):
        rc = main(
            [
                "--sim-folder",
                str(sim_folder),
                "--dry-run",
                "--output-dir",
                str(output_dir),
                "--speed-multiplier",
                "100.0",
            ],
            env={},
            load_env=False,
        )
        assert rc == 0
    names_a = sorted(p.name for p in (out_a / "screenshots").glob("*.png"))
    names_b = sorted(p.name for p in (out_b / "screenshots").glob("*.png"))
    assert names_a == names_b


def test_cli_rejects_invalid_milestone(tmp_path: Path) -> None:
    from scripts.replay_in_minecraft import main

    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    _write_decision_log(sim_folder, [])

    import io

    stderr = io.StringIO()
    rc = main(
        [
            "--sim-folder",
            str(sim_folder),
            "--dry-run",
            "--screenshot-milestones",
            "not_a_real_milestone",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        env={},
        load_env=False,
        stderr=stderr,
    )
    assert rc == 1
    assert "unknown screenshot milestone" in stderr.getvalue()
