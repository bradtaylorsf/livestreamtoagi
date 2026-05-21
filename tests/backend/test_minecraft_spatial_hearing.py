"""Tests for deterministic Minecraft spatial hearing."""

from __future__ import annotations

from core.bridge.contract import Vec3
from core.minecraft.director.spatial_hearing import (
    AgentPose,
    SpatialHearingAdapter,
    SpatialHearingConfig,
)


def _pose(agent_id: str, x: float, *, dimension: str = "overworld") -> AgentPose:
    return AgentPose(
        agent_id=agent_id,
        position=Vec3(x=x, y=64, z=0),
        dimension=dimension,
        last_seen_ts=1_000,
    )


def test_agents_within_returns_same_dimension_agents_by_distance_then_id() -> None:
    hearing = SpatialHearingAdapter(
        SpatialHearingConfig(default_hearing_radius_blocks=10, observer_radius_blocks=20)
    )
    for agent_id, x in (("pixel", 4), ("rex", 2), ("aurora", 2), ("grok", 12)):
        hearing.update_pose(agent_id, _pose(agent_id, x))
    hearing.update_pose("nether-rex", _pose("nether-rex", 1, dimension="minecraft:nether"))

    nearby = hearing.agents_within(Vec3(x=0, y=64, z=0), "overworld", 10)

    assert nearby == ["aurora", "rex", "pixel"]


def test_direct_addressees_are_participants_even_outside_hearing_radius() -> None:
    hearing = SpatialHearingAdapter(
        SpatialHearingConfig(
            default_hearing_radius_blocks=10,
            observer_radius_blocks=30,
            max_participants_per_scene=3,
        )
    )
    for agent_id, x in (
        ("vera", 0),
        ("rex", 1),
        ("pixel", 2),
        ("fork", 3),
        ("grok", 80),
        ("aurora", 20),
    ):
        hearing.update_pose(agent_id, _pose(agent_id, x))

    participants, observers = hearing.classify_listeners(
        Vec3(x=0, y=64, z=0),
        "overworld",
        direct_addressees={"vera", "grok"},
    )

    assert participants == ["vera", "rex", "grok"]
    assert observers == ["pixel", "fork", "aurora"]


def test_unknown_direct_addressee_is_still_required_participant() -> None:
    hearing = SpatialHearingAdapter(
        SpatialHearingConfig(default_hearing_radius_blocks=5, max_participants_per_scene=1)
    )

    participants, observers = hearing.classify_listeners(
        Vec3(x=0, y=64, z=0),
        "overworld",
        direct_addressees={"sentinel"},
    )

    assert participants == ["sentinel"]
    assert observers == []
