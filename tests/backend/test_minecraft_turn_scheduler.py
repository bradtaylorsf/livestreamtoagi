"""Tests for Minecraft Director V2 turn scheduling."""

from __future__ import annotations

from collections import Counter

import pytest

from core.minecraft.director import (
    DirectorTurnScheduler,
    Scene,
    SceneEventType,
    SchedulerCandidate,
    SchedulerConfig,
)


def _scene(
    *,
    scene_id: str = "mcscene-test",
    event_type: SceneEventType = SceneEventType.CHAT,
    participants: list[str] | None = None,
    observers: list[str] | None = None,
) -> Scene:
    return Scene(
        scene_id=scene_id,
        triggering_event_type=event_type,
        participants=participants or ["vera", "rex", "pixel"],
        observers=observers or [],
        event_ids=["event-1"],
        opened_at_ms=1_000,
        last_event_at_ms=1_000,
    )


def _candidate(agent_id: str, **overrides: object) -> SchedulerCandidate:
    values = {
        "agent_id": agent_id,
        "is_participant": True,
        "is_observer": False,
        "chattiness": 0.5,
        "role": None,
        "topic_relevance": 0.3,
        "seconds_since_spoke": 120.0,
        "turns_since_spoke": 1,
        "recent_turn_count": 0,
        "has_open_commitment": False,
        "active_task_match": False,
        "is_directly_addressed": False,
        "is_in_danger": False,
        "is_stuck": False,
        "role_fit": 0.3,
    }
    values.update(overrides)
    return SchedulerCandidate(**values)


@pytest.mark.parametrize("seed", [1, 17, 752])
def test_scheduler_output_is_deterministic_for_same_seed(seed: int) -> None:
    scheduler = DirectorTurnScheduler(SchedulerConfig(max_turns_per_scene=2))
    scene = _scene(participants=["vera", "rex", "pixel", "fork"])
    candidates = [
        _candidate("vera", chattiness=0.4, turns_since_spoke=2),
        _candidate("rex", chattiness=0.8, topic_relevance=0.6),
        _candidate("pixel", role_fit=0.7, has_open_commitment=True),
        _candidate("fork", active_task_match=True, role="builder"),
    ]

    first = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.CHAT,
        seed=seed,
    )
    second = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.CHAT,
        seed=seed,
    )

    assert first == second
    assert first.model_dump() == second.model_dump()


def test_direct_address_dominates_high_chattiness_non_addressee() -> None:
    scheduler = DirectorTurnScheduler()
    scene = _scene(participants=["rex", "fork"])
    candidates = [
        _candidate(
            "rex",
            chattiness=0.05,
            topic_relevance=0.05,
            seconds_since_spoke=0,
            turns_since_spoke=0,
            recent_turn_count=1,
            is_directly_addressed=True,
        ),
        _candidate(
            "fork",
            chattiness=1.0,
            topic_relevance=1.0,
            seconds_since_spoke=300,
            turns_since_spoke=4,
            role_fit=1.0,
        ),
    ]

    decision = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.CHAT,
        seed=4,
    )

    assert [turn.agent_id for turn in decision.selected] == ["rex"]
    assert decision.suppressed_agents == ["fork"]
    assert decision.suppression_reason == "direct_addressee_priority"


def test_health_danger_candidate_outranks_idle_chatter() -> None:
    scheduler = DirectorTurnScheduler()
    scene = _scene(event_type=SceneEventType.HEALTH_DANGER, participants=["vera", "pixel"])
    candidates = [
        _candidate(
            "vera",
            chattiness=0.05,
            topic_relevance=0.05,
            seconds_since_spoke=0,
            is_in_danger=True,
        ),
        _candidate(
            "pixel",
            chattiness=1.0,
            topic_relevance=1.0,
            seconds_since_spoke=300,
            turns_since_spoke=4,
            role_fit=1.0,
        ),
    ]

    decision = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.HEALTH_DANGER,
        seed=12,
    )

    assert [turn.agent_id for turn in decision.selected] == ["vera"]
    assert decision.selected[0].reason == "danger_priority"
    assert decision.suppression_reason == "urgent_priority"
    assert decision.was_urgent is True


def test_stuck_candidate_outranks_idle_chatter() -> None:
    scheduler = DirectorTurnScheduler()
    scene = _scene(event_type=SceneEventType.STUCK, participants=["fork", "pixel"])
    candidates = [
        _candidate(
            "fork",
            chattiness=0.05,
            topic_relevance=0.05,
            seconds_since_spoke=0,
            is_stuck=True,
        ),
        _candidate(
            "pixel",
            chattiness=1.0,
            topic_relevance=1.0,
            seconds_since_spoke=300,
            turns_since_spoke=4,
            role_fit=1.0,
        ),
    ]

    decision = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.STUCK,
        seed=15,
    )

    assert [turn.agent_id for turn in decision.selected] == ["fork"]
    assert decision.selected[0].reason == "stuck_priority"
    assert decision.suppression_reason == "urgent_priority"
    assert decision.was_urgent is True


def test_build_site_coordination_favors_task_and_role_matches() -> None:
    scheduler = DirectorTurnScheduler(SchedulerConfig(max_turns_per_scene=2, random_jitter=0.0))
    scene = _scene(
        event_type=SceneEventType.BUILD_ACTION,
        participants=["rex", "fork", "vera"],
        observers=["pixel"],
    )
    candidates = [
        _candidate(
            "rex",
            role="builder",
            topic_relevance=0.9,
            active_task_match=True,
            role_fit=0.9,
        ),
        _candidate(
            "fork",
            role="architect",
            topic_relevance=0.9,
            active_task_match=True,
            role_fit=0.95,
        ),
        _candidate(
            "vera",
            chattiness=0.0,
            topic_relevance=0.0,
            seconds_since_spoke=0,
            role_fit=0.0,
            recent_turn_count=10,
        ),
        _candidate(
            "pixel",
            is_participant=False,
            is_observer=True,
            chattiness=1.0,
            topic_relevance=1.0,
            seconds_since_spoke=300,
            role_fit=1.0,
        ),
    ]

    decision = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.BUILD_ACTION,
        seed=22,
    )

    assert {turn.agent_id for turn in decision.selected} == {"rex", "fork"}
    assert {turn.kind for turn in decision.selected} == {"planner"}
    assert "pixel" not in decision.suppressed_agents


def test_fanout_cap_selects_only_configured_turn_count() -> None:
    scheduler = DirectorTurnScheduler(SchedulerConfig(max_turns_per_scene=2))
    scene = _scene(participants=["vera", "rex", "aurora", "pixel", "fork", "sentinel"])
    candidates = [_candidate(agent_id) for agent_id in scene.participants]

    decision = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.CHAT,
        seed=35,
    )

    assert len(decision.selected) == 2
    assert len(decision.suppressed_agents) == 4
    assert decision.suppression_reason == "fanout_capped"


def test_idle_scene_fairness_prevents_monopoly_and_force_selects_silent_agent() -> None:
    scheduler = DirectorTurnScheduler()
    agent_ids = ["vera", "rex", "aurora", "pixel", "fork"]
    turns_since_spoke = {agent_id: 1 for agent_id in agent_ids}
    turns_since_spoke["fork"] = 5
    recent_window: list[str] = []
    counts: Counter[str] = Counter()
    force_selected_seen = False

    for idx in range(200):
        candidates = [
            _candidate(
                agent_id,
                seconds_since_spoke=min(turns_since_spoke[agent_id] * 60.0, 300.0),
                turns_since_spoke=turns_since_spoke[agent_id],
                recent_turn_count=recent_window[-10:].count(agent_id),
            )
            for agent_id in agent_ids
        ]
        decision = scheduler.select(
            scene=_scene(participants=agent_ids),
            candidates=candidates,
            scene_event_type=SceneEventType.CHAT,
            recent_speakers=recent_window,
            seed=1_000 + idx,
        )
        selected = decision.selected[0].agent_id
        force_selected_seen = force_selected_seen or turns_since_spoke[selected] >= 5
        counts[selected] += 1
        recent_window = [*recent_window, selected][-10:]
        for agent_id in agent_ids:
            if agent_id == selected:
                turns_since_spoke[agent_id] = 0
            else:
                turns_since_spoke[agent_id] += 1

    assert force_selected_seen is True
    assert max(counts.values()) <= 80


def test_consecutive_turn_block_prevents_same_agent_third_turn() -> None:
    scheduler = DirectorTurnScheduler()
    scene = _scene(participants=["rex", "vera", "pixel"])
    candidates = [
        _candidate("rex", chattiness=1.0, topic_relevance=1.0, seconds_since_spoke=300),
        _candidate("vera"),
        _candidate("pixel"),
    ]

    decision = scheduler.select(
        scene=scene,
        candidates=candidates,
        scene_event_type=SceneEventType.CHAT,
        recent_speakers=["rex", "rex"],
        seed=44,
    )

    assert "rex" not in {turn.agent_id for turn in decision.selected}
    assert "rex" in decision.suppressed_agents
    assert decision.suppression_reason == "consecutive_turn_block"


def test_observer_excluded_unless_directly_addressed() -> None:
    scheduler = DirectorTurnScheduler()
    scene = _scene(participants=["vera"], observers=["pixel"])
    observer = _candidate(
        "pixel",
        is_participant=False,
        is_observer=True,
        chattiness=1.0,
        topic_relevance=1.0,
        seconds_since_spoke=300,
        role_fit=1.0,
    )

    ordinary = scheduler.select(
        scene=scene,
        candidates=[_candidate("vera"), observer],
        scene_event_type=SceneEventType.CHAT,
        seed=55,
    )
    addressed = scheduler.select(
        scene=scene,
        candidates=[
            _candidate("vera"),
            observer.model_copy(update={"is_directly_addressed": True}),
        ],
        scene_event_type=SceneEventType.CHAT,
        seed=55,
    )

    assert [turn.agent_id for turn in ordinary.selected] == ["vera"]
    assert "pixel" not in ordinary.suppressed_agents
    assert [turn.agent_id for turn in addressed.selected] == ["pixel"]
    assert addressed.suppression_reason == "direct_addressee_priority"
