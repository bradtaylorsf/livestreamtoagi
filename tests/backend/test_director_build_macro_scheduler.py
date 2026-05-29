"""Tests for Director V2 scene-scoped build macro scheduling."""

from __future__ import annotations

import pytest

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


def test_acquired_plan_remains_granted_for_owner_after_verdict_cache_expiry() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=10_000)
    objective = {
        "objective_id": "phase-storage",
        "phase_index": 1,
        "description": "shared storage depot",
        "owner_agent_id": "vera",
        "status": "pending",
    }
    first = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="vera",
        description="shared storage depot",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[_candidate("vera", "host facilitator"), _candidate("rex", "builder")],
        active_objective=objective,
        now_ms=1_000,
    )

    resumed = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="vera",
        description="shared storage depot",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[_candidate("vera", "host facilitator"), _candidate("rex", "builder")],
        active_objective=objective,
        now_ms=32_000,
    )

    assert first.granted is True
    assert resumed.granted is True
    assert resumed.reason == "already_owned"
    assert resumed.plan_id == first.plan_id
    assert resumed.objective_id == "phase-storage"


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


def test_settlement_objective_reassigns_stale_or_capped_owner() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=10_000)
    objective = {
        "objective_id": "phase-wall",
        "phase_index": 1,
        "description": "simple perimeter wall",
        "owner_agent_id": "rex",
        "status": "owner_cap_reached",
        "previous_owner_agent_ids": ["rex"],
    }
    owner, reason = scheduler.select_phase_owner(
        active_objective=objective,
        candidates=[
            _candidate("rex", "builder"),
            _candidate("fork", "architect engineer"),
            _candidate("vera", "host facilitator"),
        ],
        fallback_owner="rex",
        now_ms=2_000,
    )

    assert owner == "fork"
    assert reason == "settlement_phase_owner_reassigned"

    acquisition = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="fork",
        description="build a duplicate starter cabin",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[
            _candidate("rex", "builder"),
            _candidate("fork", "architect engineer"),
            _candidate("vera", "host facilitator"),
        ],
        active_objective=objective,
        now_ms=2_100,
    )

    assert acquisition.granted is True
    assert acquisition.owner == "fork"
    assert acquisition.objective_id == "phase-wall"
    assert acquisition.phase_index == 1
    assert acquisition.phase_owner == "fork"
    assert acquisition.support_assignments["rex"].phase_owner == "fork"


def test_pending_settlement_objective_owner_can_be_claimed_after_grace() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=10_000)
    objective = {
        "objective_id": "phase-square",
        "phase_index": 6,
        "description": "central town square",
        "owner_agent_id": "sentinel",
        "status": "pending",
    }

    owner, reason = scheduler.select_phase_owner(
        active_objective=objective,
        candidates=[
            _candidate("sentinel", "safety moderator"),
            _candidate("rex", "builder"),
            _candidate("vera", "host facilitator"),
        ],
        fallback_owner="rex",
        now_ms=2_000,
    )

    assert owner == "sentinel"
    assert reason == "settlement_phase_owner"

    acquisition = scheduler.try_acquire_plan(
        scene_id="mcscene-build-1",
        agent_id="rex",
        description="build the central town square",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[
            _candidate("sentinel", "safety moderator"),
            _candidate("rex", "builder"),
            _candidate("vera", "host facilitator"),
        ],
        active_objective=objective,
        now_ms=602_100,
    )

    assert acquisition.granted is True
    assert acquisition.owner == "rex"
    assert acquisition.objective_id == "phase-square"
    assert acquisition.phase_owner == "rex"
    assert acquisition.support_assignments["sentinel"].phase_owner == "rex"


# ─── E21-7h: emergent claim-based build authorization ──────────────────────


def test_select_emergent_build_owners_caps_concurrent_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_MAX_CONCURRENT_BUILDS", "2")
    scheduler = BuildMacroScheduler()

    granted = scheduler.select_emergent_build_owners(
        scene_id="scene-1",
        claim_holders=["rex", "vera", "fork", "aurora"],
        now_ms=1_000,
    )

    # Only the cap's worth of distinct claim-holders may build at once.
    assert len(granted) == 2
    assert granted <= {"rex", "vera", "fork", "aurora"}

    # A fresh claim-holder cannot exceed the cap while the slots are still held.
    blocked = scheduler.select_emergent_build_owners(
        scene_id="scene-2",
        claim_holders=["grok"],
        now_ms=1_500,
    )
    assert blocked == frozenset()


def test_select_emergent_build_owners_regrants_active_agent_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_MAX_CONCURRENT_BUILDS", "1")
    scheduler = BuildMacroScheduler()

    first = scheduler.select_emergent_build_owners(
        scene_id="scene-1", claim_holders=["rex"], now_ms=1_000
    )
    assert first == frozenset({"rex"})

    # Re-selecting the same active claim-holder re-grants the same slot — it must
    # not consume a second concurrency slot or get blocked by the cap.
    again = scheduler.select_emergent_build_owners(
        scene_id="scene-1", claim_holders=["rex"], now_ms=1_200
    )
    assert again == frozenset({"rex"})


def test_select_emergent_build_owners_expires_after_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("MC_SIM_BUILD_COOLDOWN_SEC", "300")
    scheduler = BuildMacroScheduler()

    assert scheduler.select_emergent_build_owners(
        scene_id="scene-1", claim_holders=["rex"], now_ms=1_000
    ) == frozenset({"rex"})

    # Within the cooldown window the only slot is still held by rex.
    assert (
        scheduler.select_emergent_build_owners(
            scene_id="scene-1", claim_holders=["vera"], now_ms=1_000 + 299_000
        )
        == frozenset()
    )

    # After the window rex's slot frees and the next claim-holder can build.
    assert scheduler.select_emergent_build_owners(
        scene_id="scene-1", claim_holders=["vera"], now_ms=1_000 + 301_000
    ) == frozenset({"vera"})


def test_settlement_objective_denies_non_phase_owner() -> None:
    scheduler = BuildMacroScheduler(cooldown_ms=10_000)

    denied = scheduler.try_acquire_plan(
        scene_id="mcscene-build-2",
        agent_id="vera",
        description="simple perimeter wall",
        origin={"x": 0, "y": 64, "z": 0},
        scene=_scene(),
        candidates=[_candidate("fork", "architect engineer"), _candidate("vera", "host")],
        active_objective={
            "objective_id": "phase-wall",
            "phase_index": 1,
            "description": "simple perimeter wall",
            "owner_agent_id": "fork",
            "status": "in_progress",
        },
        now_ms=1_000,
    )

    assert denied.granted is False
    assert denied.reason == "settlement_phase_owner"
    assert denied.owner == "fork"
    assert denied.objective_id == "phase-wall"
