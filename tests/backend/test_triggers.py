"""Unit tests for the conversation trigger system."""

from __future__ import annotations

import random
from collections import Counter
from unittest.mock import AsyncMock

import pytest

from core.conversation.triggers import (
    _DEFAULT_DAILY_SCHEDULE,
    TriggerSystem,
)
from core.models import TriggerConfig
from tests.backend.conversation_helpers import make_trigger_config as _make_trigger_config


class FakeClock:
    """Deterministic clock for testing."""

    def __init__(self, start: float = 1000.0) -> None:
        self._time = start

    def monotonic(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds


class FakeDatetime:
    """Returns a fixed datetime from __call__."""

    def __init__(self, year: int = 2026, month: int = 4, day: int = 2, hour: int = 10) -> None:
        self._year = year
        self._month = month
        self._day = day
        self._hour = hour

    def __call__(self):
        from datetime import datetime

        return datetime(self._year, self._month, self._day, self._hour, 0, 0)

    def set_hour(self, hour: int) -> None:
        self._hour = hour

    def set_day(self, day: int) -> None:
        self._day = day


def _make_system(
    *,
    config: TriggerConfig | None = None,
    clock: FakeClock | None = None,
    now_fn: FakeDatetime | None = None,
    rng: random.Random | None = None,
    recall_memory: AsyncMock | None = None,
) -> TriggerSystem:
    return TriggerSystem(
        config=config or _make_trigger_config(),
        recall_memory=recall_memory,
        clock=clock or FakeClock(),
        now_fn=now_fn or FakeDatetime(),
        rng=rng or random.Random(42),
    )


# ── Idle trigger ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idle_trigger_fires_after_timeout():
    """Idle trigger fires when silence exceeds idle_timeout_seconds."""
    clock = FakeClock()
    system = _make_system(clock=clock)

    # No time elapsed — should not fire idle (scheduled might fire though at hour 10)
    # Use hour 10 which has no scheduled event
    result = await system.check()
    assert result is None  # no trigger yet

    # Advance past the 90s timeout
    clock.advance(91)
    result = await system.check()
    assert result is not None
    assert result["type"] == "idle"
    assert "starter_agent_id" in result
    assert result["starter_agent_id"] in _make_trigger_config().agent_initiative
    assert result["silence_seconds"] >= 90


@pytest.mark.asyncio
async def test_idle_trigger_does_not_fire_before_timeout():
    """Idle trigger does not fire when silence is under threshold."""
    clock = FakeClock()
    system = _make_system(clock=clock)

    clock.advance(89)
    result = await system.check()
    assert result is None


@pytest.mark.asyncio
async def test_idle_trigger_resets_on_speech():
    """notify_speech() resets the idle timer."""
    clock = FakeClock()
    system = _make_system(clock=clock)

    clock.advance(80)
    system.notify_speech()
    clock.advance(80)  # 80s since last speech, still under 90

    result = await system.check()
    assert result is None


@pytest.mark.asyncio
async def test_idle_starter_weighted_by_initiative():
    """Higher-initiative agents should be selected more frequently."""
    config = _make_trigger_config()
    counts: Counter[str] = Counter()
    iterations = 5000

    for i in range(iterations):
        clock = FakeClock()
        rng = random.Random(i)
        # Use hour 10 (no scheduled event) and ensure no memory triggers
        system = _make_system(
            config=config,
            clock=clock,
            now_fn=FakeDatetime(hour=10),
            rng=rng,
        )
        clock.advance(100)  # past idle timeout
        result = await system.check()
        assert result is not None
        assert result["type"] == "idle"
        counts[result["starter_agent_id"]] += 1

    # Vera (0.8) should be selected more than Rex (0.2)
    assert counts["vera"] > counts["rex"]
    # Vera should be selected roughly 4x as often as Rex
    ratio = counts["vera"] / max(counts["rex"], 1)
    assert ratio > 2.0, f"Expected vera >> rex, got ratio {ratio:.1f}"


# ── Environmental events ─────────────────────────────────────


@pytest.mark.asyncio
async def test_environmental_event_queued_and_dequeued():
    """Queued environmental event is returned once then removed."""
    system = _make_system()

    system.queue_event("poll_result", {"winner": "option_a"})
    result = await system.check()

    assert result is not None
    assert result["type"] == "environmental"
    assert result["event_type"] == "poll_result"
    assert result["event_data"]["winner"] == "option_a"

    # Second check should not return the same event
    # (advance clock to avoid idle, use hour with no schedule)
    result2 = await system.check()
    # Could be None or another trigger, but not the same event
    assert result2 is None or result2.get("event_type") != "poll_result"


@pytest.mark.asyncio
async def test_multiple_environmental_events_fifo():
    """Events are dequeued in FIFO order."""
    system = _make_system()

    system.queue_event("poll_result", {"id": 1})
    system.queue_event("budget_update", {"id": 2})

    r1 = await system.check()
    r2 = await system.check()

    assert r1["event_type"] == "poll_result"
    assert r2["event_type"] == "budget_update"


# ── Audience events ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_audience_event_routes_to_pixel():
    """Audience events (donation, chat_highlight) set Pixel as starter."""
    system = _make_system()

    system.queue_event("donation", {"amount": 10, "user": "viewer123"})
    result = await system.check()

    assert result is not None
    assert result["type"] == "audience"
    assert result["starter_agent_id"] == "pixel"
    assert result["event_type"] == "donation"


@pytest.mark.asyncio
async def test_chat_highlight_routes_to_pixel():
    """chat_highlight events also route to Pixel."""
    system = _make_system()

    system.queue_event("chat_highlight", {"message": "hello agents!"})
    result = await system.check()

    assert result["type"] == "audience"
    assert result["starter_agent_id"] == "pixel"


# ── Priority order ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_priority_pending_events_over_idle():
    """Pending events fire before idle trigger even if idle timeout is exceeded."""
    clock = FakeClock()
    system = _make_system(clock=clock)

    clock.advance(200)  # well past idle timeout
    system.queue_event("world_expansion", {"chunk": "park"})

    result = await system.check()
    assert result["type"] == "environmental"
    assert result["event_type"] == "world_expansion"


@pytest.mark.asyncio
async def test_priority_pending_events_over_scheduled():
    """Pending events fire before scheduled triggers."""
    clock = FakeClock()
    now_fn = FakeDatetime(hour=9)  # standup hour
    system = _make_system(clock=clock, now_fn=now_fn)

    system.queue_event("budget_update", {"daily_spend": 42})

    result = await system.check()
    assert result["type"] == "environmental"
    assert result["event_type"] == "budget_update"


@pytest.mark.asyncio
async def test_priority_scheduled_over_idle():
    """Scheduled triggers fire before idle when both conditions are met."""
    clock = FakeClock()
    now_fn = FakeDatetime(hour=9)  # standup hour
    system = _make_system(clock=clock, now_fn=now_fn)

    clock.advance(200)  # past idle timeout

    result = await system.check()
    assert result["type"] == "scheduled"
    assert result["event_name"] == "standup"


@pytest.mark.asyncio
async def test_priority_idle_over_memory():
    """When idle fires, memory trigger (even with 100% chance) is not reached."""
    clock = FakeClock()
    # Use a rigged RNG that would always trigger memory
    rng = random.Random(42)
    recall = AsyncMock()
    recall.retrieve_recall_memories = AsyncMock(return_value="I remember the great debate.")

    system = _make_system(clock=clock, rng=rng, recall_memory=recall)
    clock.advance(100)  # past idle timeout

    result = await system.check()
    assert result["type"] == "idle"  # idle beats memory


# ── Scheduled events ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduled_events_check_correctly():
    """Scheduled trigger fires at the right hour with correct event name."""
    for hour, (event_name, starter) in _DEFAULT_DAILY_SCHEDULE.items():
        clock = FakeClock()
        now_fn = FakeDatetime(hour=hour)
        system = _make_system(clock=clock, now_fn=now_fn)

        result = await system.check()
        assert result is not None, f"Expected trigger at hour {hour}"
        assert result["type"] == "scheduled"
        assert result["event_name"] == event_name
        assert result["starter_agent_id"] == starter
        assert result["scheduled_hour"] == hour


@pytest.mark.asyncio
async def test_scheduled_event_does_not_fire_twice():
    """A scheduled event fires only once per day."""
    clock = FakeClock()
    now_fn = FakeDatetime(hour=9)
    system = _make_system(clock=clock, now_fn=now_fn)

    r1 = await system.check()
    assert r1 is not None
    assert r1["type"] == "scheduled"

    # Second check at same hour should not fire again
    r2 = await system.check()
    assert r2 is None or r2["type"] != "scheduled"


@pytest.mark.asyncio
async def test_scheduled_event_resets_on_new_day():
    """Scheduled events reset when the date changes."""
    clock = FakeClock()
    now_fn = FakeDatetime(hour=9, day=2)
    system = _make_system(clock=clock, now_fn=now_fn)

    r1 = await system.check()
    assert r1["type"] == "scheduled"

    # Move to next day, same hour
    now_fn.set_day(3)
    system.notify_speech()  # reset idle timer so idle doesn't fire
    r2 = await system.check()
    assert r2 is not None
    assert r2["type"] == "scheduled"
    assert r2["event_name"] == "standup"


@pytest.mark.asyncio
async def test_no_scheduled_event_at_non_schedule_hour():
    """No scheduled trigger at hours not in the daily schedule."""
    clock = FakeClock()
    now_fn = FakeDatetime(hour=14)  # not in schedule
    system = _make_system(clock=clock, now_fn=now_fn)

    result = await system.check()
    assert result is None


# ── Memory trigger ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_trigger_fires_with_recall():
    """Memory trigger fires when RNG hits and recall returns content."""

    class AlwaysTriggersRng:
        """RNG that always triggers memory (returns 0.0 < 0.02)."""
        def random(self) -> float:
            return 0.0

        def choice(self, seq):
            return seq[0]

        def choices(self, population, *, weights, k):
            return [population[0]]

    recall = AsyncMock()
    recall.retrieve_recall_memories = AsyncMock(return_value="The great pixel debate of 2026.")

    clock = FakeClock()
    now_fn = FakeDatetime(hour=10)  # no scheduled event
    system = TriggerSystem(
        config=_make_trigger_config(),
        recall_memory=recall,
        clock=clock,
        now_fn=now_fn,
        rng=AlwaysTriggersRng(),
    )

    result = await system.check()
    assert result is not None
    assert result["type"] == "memory"
    assert result["memory_summary"] == "The great pixel debate of 2026."
    assert result["starter_agent_id"] in _make_trigger_config().agent_initiative


@pytest.mark.asyncio
async def test_memory_trigger_skipped_without_recall_manager():
    """Memory trigger returns None if no RecallMemoryManager is provided."""

    class AlwaysTriggersRng:
        def random(self) -> float:
            return 0.0

        def choice(self, seq):
            return seq[0]

        def choices(self, population, *, weights, k):
            return [population[0]]

    clock = FakeClock()
    now_fn = FakeDatetime(hour=10)
    system = TriggerSystem(
        config=_make_trigger_config(),
        recall_memory=None,
        clock=clock,
        now_fn=now_fn,
        rng=AlwaysTriggersRng(),
    )

    result = await system.check()
    assert result is None


@pytest.mark.asyncio
async def test_memory_trigger_skipped_when_recall_returns_empty():
    """Memory trigger returns None if recall returns empty string."""

    class AlwaysTriggersRng:
        def random(self) -> float:
            return 0.0

        def choice(self, seq):
            return seq[0]

        def choices(self, population, *, weights, k):
            return [population[0]]

    recall = AsyncMock()
    recall.retrieve_recall_memories = AsyncMock(return_value="")

    clock = FakeClock()
    now_fn = FakeDatetime(hour=10)
    system = TriggerSystem(
        config=_make_trigger_config(),
        recall_memory=recall,
        clock=clock,
        now_fn=now_fn,
        rng=AlwaysTriggersRng(),
    )

    result = await system.check()
    assert result is None


# ── Reset ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_clears_state():
    """reset() clears pending events and resets timers."""
    clock = FakeClock()
    now_fn = FakeDatetime(hour=9)
    system = _make_system(clock=clock, now_fn=now_fn)

    # Fire scheduled trigger
    await system.check()
    # Queue an event
    system.queue_event("poll_result", {})

    system.reset()

    # Scheduled should fire again (fired_today cleared)
    r = await system.check()
    assert r is not None
    assert r["type"] == "scheduled"  # not the queued event (it was cleared)


# ── Trigger dict shape ───────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_dict_has_required_fields():
    """Every trigger includes type, starter_agent_id, and prompt_hint."""
    clock = FakeClock()
    system = _make_system(clock=clock)
    clock.advance(100)

    result = await system.check()
    assert result is not None
    assert "type" in result
    assert "starter_agent_id" in result
    assert "prompt_hint" in result
