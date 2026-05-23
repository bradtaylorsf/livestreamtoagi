"""Tests for Director V2 batched scene memory compaction."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.bridge.consumers.scene_memory import (
    SceneMemoryConsumer,
    classify_compaction_error,
)
from core.bridge.contract import Vec3
from core.event_bus import EventBus, EventType
from core.minecraft.director.scene_inbox import SceneInbox, SceneInboxConfig
from core.minecraft.director.spatial_hearing import (
    AgentPose,
    SpatialHearingAdapter,
    SpatialHearingConfig,
)


class FakeCompactor:
    def __init__(self, *, raise_message: str | None = None) -> None:
        self.raise_message = raise_message
        self.compact_calls: list[dict[str, Any]] = []
        self.recall_calls: list[dict[str, Any]] = []

    async def compact_interaction(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        participants: list[str] | None = None,
        conversation_id: object | None = None,
        summary_style: str = "default",
    ) -> object:
        self.compact_calls.append(
            {
                "agent_id": agent_id,
                "interaction": interaction,
                "event_type": event_type,
                "participants": participants,
                "conversation_id": conversation_id,
                "summary_style": summary_style,
            }
        )
        if self.raise_message is not None:
            raise RuntimeError(self.raise_message)
        return SimpleNamespace(
            transcript=SimpleNamespace(id=101),
            recall_memory=SimpleNamespace(
                summary="Vera promised to build the bridge; Rex placed oak_planks; "
                "the inspect tool succeeded; Vera got stuck on a ravine."
            ),
        )

    async def compact_recall_only(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        transcript_id: int,
        participants: list[str] | None = None,
        summary_style: str = "default",
    ) -> object:
        self.recall_calls.append(
            {
                "agent_id": agent_id,
                "interaction": interaction,
                "event_type": event_type,
                "transcript_id": transcript_id,
                "participants": participants,
                "summary_style": summary_style,
            }
        )
        return SimpleNamespace(id=len(self.recall_calls) + 1)


def _pose(agent_id: str, x: float, z: float = 0) -> AgentPose:
    return AgentPose(
        agent_id=agent_id,
        position=Vec3(x=x, y=64, z=z),
        dimension="overworld",
        last_seen_ts=1_000,
    )


def _consumer(*, max_participants: int = 2) -> tuple[EventBus, FakeCompactor, SceneMemoryConsumer]:
    bus = EventBus()
    compactor = FakeCompactor()
    inbox = _inbox(bus=bus, max_participants=max_participants)
    return bus, compactor, SceneMemoryConsumer(bus, compactor, inbox=inbox)


def _inbox(*, bus: EventBus, max_participants: int = 2) -> SceneInbox:
    hearing = SpatialHearingAdapter(
        SpatialHearingConfig(
            default_hearing_radius_blocks=10,
            observer_radius_blocks=30,
            max_participants_per_scene=max_participants,
        )
    )
    inbox = SceneInbox(
        hearing=hearing,
        config=SceneInboxConfig(scene_window_ms=1_000),
        event_bus=bus,
    )
    for agent_id, x in [("vera", 0), ("rex", 2), ("pixel", 20)]:
        inbox.hearing.update_pose(agent_id, _pose(agent_id, x))
    return inbox


def _event(event_type: str, **overrides: Any) -> dict[str, Any]:
    event = {
        "event_id": f"{event_type}-1",
        "type": event_type,
        "source_agent_id": "vera",
        "origin": {"x": 0, "y": 64, "z": 0},
        "dimension": "overworld",
        "timestamp_ms": 1_000,
        "payload": {},
    }
    event.update(overrides)
    return event


async def test_high_frequency_movement_and_inventory_compacts_once() -> None:
    _bus, compactor, consumer = _consumer(max_participants=2)

    for idx in range(50):
        event_type = "movement_milestone" if idx % 2 == 0 else "inventory_change"
        await consumer.ingest_source_event(
            _event(
                event_type,
                event_id=f"noise-{idx}",
                timestamp_ms=1_000 + idx,
                payload={"milestone": False, "delta": 1, "item": "oak_planks"},
            )
        )

    await consumer.flush_due_scenes(now_ms=3_000)

    assert len(compactor.compact_calls) == 1
    assert compactor.compact_calls[0]["event_type"] == "minecraft_scene"
    assert compactor.compact_calls[0]["summary_style"] == "scene"


async def test_multi_turn_scene_compacts_digest_for_participants_and_observers() -> None:
    bus, compactor, consumer = _consumer(max_participants=2)
    digests: list[dict[str, Any]] = []
    agent_speaks: list[dict[str, Any]] = []

    async def on_digest(event: dict[str, Any]) -> None:
        digests.append(event["data"])

    async def on_agent_speak(event: dict[str, Any]) -> None:
        agent_speaks.append(event)

    bus.on(EventType.BRIDGE_SCENE_DIGEST, on_digest)
    bus.on(EventType.AGENT_SPEAK, on_agent_speak)
    try:
        await consumer.ingest_source_event(
            _event(
                "chat",
                event_id="chat-promise",
                payload={"message": "I'll build the bridge. @rex, inspect it after."},
            )
        )
        await consumer.ingest_source_event(
            _event(
                "build_action",
                event_id="build-1",
                timestamp_ms=1_100,
                payload={
                    "action_id": "build-bridge-1",
                    "status": "partial",
                    "detail": "placed oak_planks",
                },
            )
        )
        await consumer.ingest_source_event(
            _event(
                "tool_result",
                event_id="tool-1",
                timestamp_ms=1_200,
                payload={
                    "tool_name": "inspect_bridge",
                    "status": "success",
                    "result": "bridge has a two-block gap",
                },
            )
        )
        await consumer.ingest_source_event(
            _event(
                "stuck",
                event_id="stuck-1",
                timestamp_ms=1_300,
                payload={"detail": "pathfinder repeated the same ravine edge"},
            )
        )

        await consumer.flush_due_scenes(now_ms=1_300)
    finally:
        bus.off(EventType.BRIDGE_SCENE_DIGEST, on_digest)
        bus.off(EventType.AGENT_SPEAK, on_agent_speak)

    assert len(compactor.compact_calls) == 1
    compact_call = compactor.compact_calls[0]
    assert compact_call["agent_id"] == "vera"
    assert compact_call["participants"] == ["vera", "rex", "pixel"]
    assert compact_call["conversation_id"] is None

    interaction = compact_call["interaction"]
    assert "I'll build the bridge" in interaction
    assert "placed oak_planks" in interaction
    assert "inspect_bridge" in interaction
    assert "two-block gap" in interaction
    assert "repeated the same ravine edge" in interaction

    assert [call["agent_id"] for call in compactor.recall_calls] == ["rex", "pixel"]
    assert {call["transcript_id"] for call in compactor.recall_calls} == {101}
    assert {call["summary_style"] for call in compactor.recall_calls} == {"scene"}
    assert agent_speaks == []
    assert len(digests) == 1
    assert digests[0]["scene_id"].startswith("mcscene-")
    assert "Vera promised" in digests[0]["summary"]
    assert any("I'll build the bridge" in item for item in digests[0]["commitments"])


async def test_scene_memory_emits_director_timeline_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SOAK_RUN_DIR", str(tmp_path))
    _bus, _compactor, consumer = _consumer(max_participants=2)

    await consumer.ingest_source_event(
        _event(
            "chat",
            event_id="chat-digest-timeline",
            payload={"message": "I'll compact this scene for everyone."},
        )
    )
    await consumer.flush_due_scenes(now_ms=3_000)

    path = tmp_path / "timeline-raw" / "director_v2.ndjson"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    event_types = [record["event_type"] for record in records]
    assert "director.memory.compaction" in event_types
    assert "director.scene.digest" in event_types
    digest = next(record for record in records if record["event_type"] == "director.scene.digest")
    assert digest["payload"]["distributed_to"] == ["vera", "rex", "pixel"]
    assert digest["payload"]["tokens"] > 0


async def test_scene_memory_mirrors_external_scene_update_source_event() -> None:
    bus, compactor, consumer = _consumer(max_participants=2)
    external_inbox = _inbox(bus=bus, max_participants=2)

    consumer.start()
    try:
        await external_inbox.ingest(
            _event(
                "chat",
                event_id="external-gate-chat",
                payload={"message": "I'll mark the shared camp before we build."},
            )
        )
        await consumer.flush_due_scenes(now_ms=3_000)
    finally:
        consumer.stop()

    assert len(compactor.compact_calls) == 1
    interaction = compactor.compact_calls[0]["interaction"]
    assert "I'll mark the shared camp" in interaction
    assert compactor.compact_calls[0]["participants"] == ["vera", "rex", "pixel"]


async def test_scene_memory_keeps_system_evidence_but_excludes_it_as_memory_owner() -> None:
    bus, compactor, consumer = _consumer(max_participants=2)
    external_inbox = _inbox(bus=bus, max_participants=2)

    consumer.start()
    try:
        await external_inbox.ingest(
            _event(
                "chat",
                event_id="external-system-chat",
                source_agent_id="system",
                direct_addressees=["vera", "rex", "system"],
                payload={"message": "System heartbeat: Vera and Rex should place a block."},
            )
        )
        await consumer.flush_due_scenes(now_ms=3_000)
    finally:
        consumer.stop()

    assert len(compactor.compact_calls) == 1
    compact_call = compactor.compact_calls[0]
    assert compact_call["agent_id"] == "vera"
    assert compact_call["participants"] == ["vera", "rex", "pixel"]
    assert "system: System heartbeat" in compact_call["interaction"]
    assert all(call["agent_id"] != "system" for call in compactor.recall_calls)


async def test_model_unloaded_is_logged_as_memory_compaction_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    compactor = FakeCompactor(raise_message="Model unloaded by LM Studio")
    consumer = SceneMemoryConsumer(bus, compactor, inbox=_inbox(bus=bus))

    await consumer.ingest_source_event(
        _event(
            "stuck",
            event_id="stuck-model-unloaded",
            payload={"detail": "pathfinder stuck near bridge site"},
        )
    )

    with caplog.at_level(logging.ERROR, logger="core.bridge.consumers.scene_memory"):
        await consumer.flush_due_scenes(now_ms=1_000)

    assert compactor.compact_calls
    assert consumer.inbox.scenes == {}
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "memory_compaction_error"
    ]
    assert len(records) == 1
    assert records[0].error_class == "model_unloaded"
    assert classify_compaction_error(RuntimeError("model_not_loaded")) == "model_unloaded"
