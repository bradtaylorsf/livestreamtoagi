"""Tests for the headless needs state machine (issue #854)."""

from __future__ import annotations

import pytest

from core.agent_needs import NEED_NAMES, NeedConfig, NeedsManager


def _hunger_only(decay: float = 25.0, warn: float = 50.0, crit: float = 25.0) -> dict:
    return {"hunger": NeedConfig(tick_decay=decay, warning_threshold=warn, critical_threshold=crit)}


def test_initial_state_is_full() -> None:
    mgr = NeedsManager(configs=_hunger_only())
    state = mgr.get_state("vera")
    for need in NEED_NAMES:
        assert state.get(need) == 100.0


def test_tick_applies_linear_decay() -> None:
    mgr = NeedsManager(configs=_hunger_only(decay=10.0))
    mgr.tick("vera", ticks=3)
    assert mgr.get_state("vera").hunger == pytest.approx(70.0)


def test_decay_is_deterministic_across_runs() -> None:
    a = NeedsManager(configs=_hunger_only(decay=2.5))
    b = NeedsManager(configs=_hunger_only(decay=2.5))
    for _ in range(20):
        a.tick("rex")
        b.tick("rex")
    assert a.get_state("rex").hunger == b.get_state("rex").hunger


def test_threshold_warning_emitted_once() -> None:
    mgr = NeedsManager(configs=_hunger_only(decay=15.0, warn=80.0, crit=20.0))

    first = mgr.tick("aurora", ticks=2)  # 100 → 70 → warning crossed
    assert len(first) == 1
    assert first[0].event_type == "hunger_warning"

    # Continuing to decay below the warning should not re-emit.
    again = mgr.tick("aurora", ticks=1)
    assert all(ev.event_type != "hunger_warning" for ev in again)


def test_threshold_critical_supersedes_warning() -> None:
    mgr = NeedsManager(
        configs={"hunger": NeedConfig(tick_decay=80.0, warning_threshold=50.0, critical_threshold=30.0)}
    )
    events = mgr.tick("rex", ticks=1)  # 100 → 20: crosses both
    # Only the critical event should be emitted (warning suppressed by critical).
    assert [ev.event_type for ev in events] == ["hunger_critical"]


def test_apply_effect_restores_and_clears_flag() -> None:
    mgr = NeedsManager(
        configs={"hunger": NeedConfig(tick_decay=80.0, critical_threshold=25.0, warning_threshold=50.0)}
    )
    crossing = mgr.tick("vera", ticks=1)  # 100 -> 20: critical
    assert crossing[0].event_type == "hunger_critical"

    mgr.apply_effect("vera", "hunger", +60.0)  # 20 -> 80
    state = mgr.get_state("vera")
    assert state.hunger == pytest.approx(80.0)
    assert not state.below_critical
    assert not state.below_warning

    # Now decay again — critical should re-fire on the next crossing.
    again = mgr.tick("vera", ticks=1)
    assert again and again[0].event_type == "hunger_critical"


def test_apply_effect_rejects_unknown_need() -> None:
    mgr = NeedsManager(configs=_hunger_only())
    with pytest.raises(ValueError):
        mgr.apply_effect("vera", "mana", 10.0)


def test_value_clamps_to_unit_range() -> None:
    mgr = NeedsManager(configs=_hunger_only(decay=200.0))
    mgr.tick("rex", ticks=1)
    assert mgr.get_state("rex").hunger == 0.0
    mgr.apply_effect("rex", "hunger", +500.0)
    assert mgr.get_state("rex").hunger == 100.0


def test_active_needs_returns_worst_first() -> None:
    mgr = NeedsManager(
        configs={
            "hunger": NeedConfig(tick_decay=0.0, warning_threshold=80.0, critical_threshold=25.0),
            "sleep": NeedConfig(tick_decay=0.0, warning_threshold=80.0, critical_threshold=25.0),
        }
    )
    state = mgr.get_state("vera")
    state.hunger = 30.0
    state.sleep = 10.0
    active = state.active_needs(mgr.configs)
    assert [item[0] for item in active] == ["sleep", "hunger"]
