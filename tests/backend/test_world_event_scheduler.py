"""Tests for the headless world-event scheduler (issue #854)."""

from __future__ import annotations

from core.simulation.world_events import WorldEventScheduler


def test_scheduled_event_fires_on_target_tick() -> None:
    sched = WorldEventScheduler(schedule=[{"tick": 5, "event": "nightfall"}])

    # Earlier ticks emit nothing.
    for t in range(1, 5):
        assert sched.tick(t) == []
    fired = sched.tick(5)
    assert len(fired) == 1
    assert fired[0].event_type == "nightfall"
    assert fired[0].trigger == "scheduled"
    # And it does not fire again on subsequent ticks.
    assert sched.tick(6) == []


def test_late_scheduled_event_fires_when_overshot() -> None:
    sched = WorldEventScheduler(schedule=[{"tick": 5, "event": "dawn"}])
    fired = sched.tick(7)  # we passed tick 5 already; still emit once.
    assert len(fired) == 1
    assert fired[0].event_type == "dawn"


def test_probabilistic_event_is_seed_deterministic() -> None:
    a = WorldEventScheduler(
        probabilistic=[{"event": "enemy_nearby", "prob_per_tick": 0.5}],
        seed=42,
    )
    b = WorldEventScheduler(
        probabilistic=[{"event": "enemy_nearby", "prob_per_tick": 0.5}],
        seed=42,
    )
    a_emitted = [len(a.tick(t)) for t in range(1, 11)]
    b_emitted = [len(b.tick(t)) for t in range(1, 11)]
    assert a_emitted == b_emitted


def test_probabilistic_requires_gates_until_gate_activates() -> None:
    sched = WorldEventScheduler(
        schedule=[{"tick": 5, "event": "nightfall"}],
        probabilistic=[
            {"event": "enemy_nearby", "prob_per_tick": 1.0, "requires": "nightfall"}
        ],
        seed=0,
    )
    # Before nightfall, enemy_nearby never fires regardless of probability.
    for t in range(1, 5):
        assert sched.tick(t) == []

    # On tick 5, scheduled nightfall fires *and* the gated event becomes
    # eligible immediately.
    fired_at_5 = sched.tick(5)
    types = [ev.event_type for ev in fired_at_5]
    assert "nightfall" in types
    assert "enemy_nearby" in types

    # Subsequent ticks continue to roll for the gated event.
    fired_at_6 = sched.tick(6)
    assert any(ev.event_type == "enemy_nearby" for ev in fired_at_6)


def test_dawn_clears_nightfall_gate() -> None:
    sched = WorldEventScheduler(
        schedule=[
            {"tick": 5, "event": "nightfall"},
            {"tick": 10, "event": "dawn"},
        ],
        probabilistic=[
            {"event": "enemy_nearby", "prob_per_tick": 1.0, "requires": "nightfall"}
        ],
        seed=0,
    )
    sched.tick(5)  # activates nightfall
    sched.tick(10)  # activates dawn, should clear nightfall
    fired = sched.tick(11)
    assert all(ev.event_type != "enemy_nearby" for ev in fired)


def test_from_config_handles_missing_block() -> None:
    sched = WorldEventScheduler.from_config(None)
    assert sched.tick(1) == []


def test_force_event_activates_gate() -> None:
    sched = WorldEventScheduler(
        probabilistic=[
            {"event": "enemy_nearby", "prob_per_tick": 1.0, "requires": "nightfall"}
        ],
        seed=0,
    )
    assert sched.tick(1) == []
    sched.force("nightfall", sim_tick=1)
    fired = sched.tick(2)
    assert any(ev.event_type == "enemy_nearby" for ev in fired)
