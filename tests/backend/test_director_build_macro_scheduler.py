"""Tests for Director V2 scene-scoped build macro scheduling."""

from __future__ import annotations

from core.minecraft.director.build_macro_scheduler import BuildMacroScheduler
from core.minecraft.director.scene_inbox import Scene, SceneEventType
from core.minecraft.director.turn_scheduler import SchedulerCandidate


def _scene() -> Scene:
    return Scene(
        scene_id="mcscene-build-1",
        triggering_event_type=SceneEventType.BUILD_ACTION,
        participants=["rex", "vera", "sentinel"],
        observers=["aurora"],
        event_ids=["event-build-1"],
        opened_at_ms=1_000,
        last_event_at_ms=1_000,
    )


def _candidate(agent_id: str, role: str) -> SchedulerCandidate:
    return SchedulerCandidate(
        agent_id=agent_id,
        is_participant=True,
        is_observer=False,
        chattiness=0.5,
        role=role,
        topic_relevance=0.8,
        seconds_since_spoke=60,
        turns_since_spoke=2,
        recent_turn_count=0,
        role_fit=0.8,
    )


def test_try_acquire_plan_suppresses_duplicate_scene_requests() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=10_000)
    first = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build a small cabin",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[_candidate("rex", "builder"), _candidate("vera", "host facilitator")],
        now_ms=1_000,
    )

    duplicate_owner = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build a small cabin",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[_candidate("rex", "builder"), _candidate("vera", "host facilitator")],
        now_ms=1_100,
    )
    duplicate_sibling = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="vera",
        description="build a small cabin",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[_candidate("rex", "builder"), _candidate("vera", "host facilitator")],
        now_ms=1_200,
    )

    assert first.granted is True
    assert first.owner == "rex"
    assert duplicate_owner.granted is False
    assert duplicate_owner.reason == "already_owned"
    assert duplicate_owner.plan_id == first.plan_id
    assert duplicate_sibling.granted is False
    assert duplicate_sibling.reason == "scene_locked"
    assert duplicate_sibling.owner == "rex"


def test_support_role_assignment_excludes_owner_and_names_support_tasks() -> None:
    scheduler = BuildMacroScheduler()
    result = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build a wall",
        origin={"x": 3, "y": 64, "z": 4},
        scene=_scene(),
        candidates=[
            _candidate("rex", "builder"),
            _candidate("vera", "host facilitator"),
            _candidate("sentinel", "safety moderator"),
            _candidate("aurora", "explorer"),
        ],
        now_ms=1_000,
    )

    assert result.granted is True
    assert set(result.support_assignments) == {"aurora", "sentinel", "vera"}
    assert result.support_assignments["sentinel"].support_role == "guard"
    assert result.support_assignments["aurora"].support_role == "gather"
    assert all(
        "rex" in assignment.support_task for assignment in result.support_assignments.values()
    )


def test_retryable_failure_releases_scene_lock_for_retry() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=10_000)
    first = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build a hut",
        origin={"x": 0, "y": 64, "z": 0},
        now_ms=1_000,
    )

    assert first.plan_id is not None
    assert scheduler.mark_failed(
        "mcscene-build-1",
        first.plan_id,
        reason="materials_missing",
        result="tool-missing: gather oak logs",
        retryable=True,
        now_ms=1_500,
    )
    retry = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build a hut",
        origin={"x": 0, "y": 64, "z": 0},
        now_ms=1_600,
    )

    assert retry.granted is True
    assert retry.plan_id == first.plan_id


def test_non_retryable_failure_holds_scene_lock_until_cooldown() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=1_000)
    first = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build protected wall",
        origin={"x": 0, "y": 64, "z": 0},
        now_ms=1_000,
    )

    assert first.plan_id is not None
    assert scheduler.mark_failed(
        "mcscene-build-1",
        first.plan_id,
        reason="protected",
        result="protected area",
        retryable=False,
        now_ms=1_100,
    )
    blocked = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="vera",
        description="build protected wall",
        origin={"x": 0, "y": 64, "z": 0},
        now_ms=1_500,
    )
    after_cooldown = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="vera",
        description="build protected wall",
        origin={"x": 0, "y": 64, "z": 0},
        now_ms=2_200,
    )

    assert blocked.granted is False
    assert blocked.reason == "scene_locked"
    assert after_cooldown.granted is True
