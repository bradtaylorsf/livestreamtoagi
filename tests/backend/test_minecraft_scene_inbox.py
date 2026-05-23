"""Tests for the Minecraft Director V2 scene inbox."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from core.bridge.contract import Vec3
from core.event_bus import EventBus, EventType
from core.minecraft.director.scene_inbox import (
    SceneEventType,
    SceneInbox,
    register,
)
from core.minecraft.director.spatial_hearing import (
    AgentPose,
    SpatialHearingAdapter,
    SpatialHearingConfig,
)


def _pose(agent_id: str, x: float, z: float = 0) -> AgentPose:
    return AgentPose(
        agent_id=agent_id,
        position=Vec3(x=x, y=64, z=z),
        dimension="overworld",
        last_seen_ts=1_000,
    )


def _inbox(
    *,
    hearing_radius: float = 10,
    observer_radius: float = 30,
    max_participants: int = 5,
    bus: EventBus | None = None,
) -> SceneInbox:
    hearing = SpatialHearingAdapter(
        SpatialHearingConfig(
            default_hearing_radius_blocks=hearing_radius,
            observer_radius_blocks=observer_radius,
            max_participants_per_scene=max_participants,
        )
    )
    return SceneInbox(hearing=hearing, event_bus=bus or EventBus())


def _seed_poses(inbox: SceneInbox, poses: list[tuple[str, float]]) -> None:
    for agent_id, x in poses:
        inbox.hearing.update_pose(agent_id, _pose(agent_id, x))


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


@pytest.fixture
def captured_scene_updates() -> Iterator[tuple[EventBus, list[dict[str, Any]]]]:
    bus = EventBus()
    seen: list[dict[str, Any]] = []

    async def on_scene_update(event: dict[str, Any]) -> None:
        seen.append(event["data"])

    bus.on(EventType.BRIDGE_SCENE_UPDATE, on_scene_update)
    try:
        yield bus, seen
    finally:
        bus.off(EventType.BRIDGE_SCENE_UPDATE, on_scene_update)


async def test_multi_agent_chat_groups_nearby_agents_and_direct_distant_addressee(
    captured_scene_updates: tuple[EventBus, list[dict[str, Any]]],
) -> None:
    bus, emitted = captured_scene_updates
    inbox = _inbox(bus=bus, max_participants=5)
    _seed_poses(inbox, [("vera", 0), ("rex", 2), ("pixel", 4), ("grok", 50)])

    update = await inbox.ingest(
        _event(
            "chat",
            event_id="chat-hello",
            payload={"message": "Rex, help me wire this. @grok can audit later."},
        )
    )

    assert update.scene_id is not None
    assert update.is_new_scene is True
    assert update.scene is not None
    assert update.scene.participants == ["vera", "rex", "pixel", "grok"]
    assert update.scene.observers == []
    assert len(emitted) == 1
    assert "source_event" in emitted[0]
    assert "source_inbox_id" in emitted[0]
    assert emitted[0]["source_event"]["dedupe_key"] == "chat:vera:overworld:0:4:0:"
    assert {
        key: emitted[0][key]
        for key in (
            "scene_id",
            "participants",
            "observers",
            "triggering_event_type",
            "event_id",
            "source_agent_id",
            "participants_added",
            "observers_added",
            "suppression_reason",
        )
    } == {
        "scene_id": update.scene_id,
        "participants": ["vera", "rex", "pixel", "grok"],
        "observers": [],
        "triggering_event_type": "chat",
        "event_id": "chat-hello",
        "source_agent_id": "vera",
        "participants_added": ["vera", "rex", "pixel", "grok"],
        "observers_added": [],
        "suppression_reason": None,
    }


async def test_nearby_build_action_caps_participants_and_records_observers() -> None:
    inbox = _inbox(max_participants=3)
    _seed_poses(
        inbox,
        [
            ("vera", 0),
            ("rex", 2),
            ("pixel", 3),
            ("fork", 4),
            ("aurora", 20),
        ],
    )

    update = await inbox.ingest(_event("build_action", event_id="build-wall"))

    assert update.suppression_reason == "participant_cap"
    assert update.scene is not None
    assert update.scene.participants == ["vera", "rex", "pixel"]
    assert update.scene.observers == ["fork", "aurora"]


async def test_distant_observer_is_recorded_without_becoming_participant() -> None:
    inbox = _inbox(max_participants=5)
    _seed_poses(inbox, [("vera", 0), ("rex", 5), ("aurora", 20)])

    update = await inbox.ingest(_event("block_interaction", event_id="place-door"))

    assert update.scene is not None
    assert update.scene.participants == ["vera", "rex"]
    assert update.scene.observers == ["aurora"]
    assert "aurora" not in update.participants_added


async def test_health_danger_always_opens_new_scene_inside_existing_window() -> None:
    inbox = _inbox(max_participants=5)
    _seed_poses(inbox, [("vera", 0), ("rex", 3), ("aurora", 20)])

    first = await inbox.ingest(_event("build_action", event_id="build-start", timestamp_ms=1_000))
    danger = await inbox.ingest(_event("health_danger", event_id="lava-hit", timestamp_ms=2_000))

    assert first.scene_id != danger.scene_id
    assert danger.is_new_scene is True
    assert danger.scene is not None
    assert danger.scene.triggering_event_type == SceneEventType.HEALTH_DANGER
    assert danger.scene.participants == ["vera", "rex"]
    assert danger.scene.observers == ["aurora"]


async def test_repeated_low_level_movement_events_dedupe_to_one_debug_update(
    captured_scene_updates: tuple[EventBus, list[dict[str, Any]]],
) -> None:
    bus, emitted = captured_scene_updates
    inbox = _inbox(bus=bus)
    _seed_poses(inbox, [("vera", 0), ("rex", 3), ("aurora", 20)])

    updates = [
        await inbox.ingest(
            _event(
                "movement_milestone",
                event_id=f"move-{idx}",
                timestamp_ms=1_000 + idx,
                payload={"milestone": False},
            )
        )
        for idx in range(10)
    ]

    assert updates[0].suppression_reason == "telemetry_only"
    assert [update.suppression_reason for update in updates[1:]] == ["duplicate_event"] * 9
    assert len(inbox.scenes) == 1
    scene = updates[0].scene
    assert scene is not None
    assert scene.participants == []
    assert scene.observers == ["rex", "aurora"]
    assert scene.event_ids == ["move-0"]
    assert len(emitted) == 1
    assert emitted[0]["suppression_reason"] == "telemetry_only"
    assert emitted[0]["participants"] == []
    assert emitted[0]["observers"] == ["rex", "aurora"]


async def test_scene_ids_are_deterministic_for_identical_inputs() -> None:
    first = _inbox()
    second = _inbox()
    for inbox in (first, second):
        _seed_poses(inbox, [("vera", 0), ("rex", 3)])

    event = _event("chat", event_id="same-chat", timestamp_ms=12_345)

    first_update = await first.ingest(event)
    second_update = await second.ingest(event)

    assert first_update.scene_id == second_update.scene_id
    assert first_update.scene is not None
    assert second_update.scene is not None
    assert first_update.scene.participants == second_update.scene.participants


async def test_register_groups_bridge_perception_and_action_result_events(
    captured_scene_updates: tuple[EventBus, list[dict[str, Any]]],
) -> None:
    bus, emitted = captured_scene_updates
    inbox = register(bus, _inbox(bus=bus, max_participants=4))
    _seed_poses(inbox, [("rex", 3), ("pixel", 20)])

    await bus.emit(
        EventType.BRIDGE_PERCEPTION,
        {
            "agent_id": "vera",
            "request_id": "perception-1",
            "run_id": "run-1",
            "simulation_id": "sim-1",
            "observations": [
                {
                    "type": "pose",
                    "after": {"x": 0, "y": 64, "z": 0},
                    "dimension": "overworld",
                    "class": "reached",
                }
            ],
        },
    )
    await bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {
            "agent_id": "vera",
            "request_id": "action-1",
            "run_id": "run-1",
            "simulation_id": "sim-1",
            "action_id": "build-step-1",
            "status": "success",
            "detail": "placed support block",
        },
    )

    scene_updates = [record for record in emitted if record["triggering_event_type"] != "chat"]
    assert len(scene_updates) == 2
    assert scene_updates[0]["triggering_event_type"] == "movement_milestone"
    assert scene_updates[0]["suppression_reason"] is None
    assert scene_updates[1]["triggering_event_type"] == "build_action"
    assert scene_updates[1]["participants"] == ["vera", "rex"]
    assert scene_updates[1]["observers"] == ["pixel"]
