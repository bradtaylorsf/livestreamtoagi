"""Tests for SimulationClock."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from core.simulation.clock import SimulationClock


def test_clock_instant_mode_returns_start_time():
    """speed_multiplier=0 preserves instant/legacy behavior."""
    start = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(speed_multiplier=0, start_time=start)
    assert clock.now() == start
    assert clock.elapsed() == timedelta(0)
    assert clock.simulated_day() == 1
    assert clock.simulated_hour() == 9


def test_clock_advance_manual():
    """advance() moves clock forward in instant mode."""
    start = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(speed_multiplier=0, start_time=start)

    clock.advance(timedelta(hours=3))
    assert clock.now() == start + timedelta(hours=3)
    assert clock.simulated_hour() == 12

    clock.advance(timedelta(days=1))
    assert clock.simulated_day() == 2


def test_clock_speed_multiplier_advances_time():
    """speed_multiplier > 0 advances simulated time relative to real time."""
    start = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(speed_multiplier=42, start_time=start)

    # Wait a tiny bit of real time — simulated time should advance 42x faster
    time.sleep(0.05)  # 50ms real → ~2.1s simulated
    elapsed = clock.elapsed()
    assert elapsed.total_seconds() > 1.0  # at least 1 simulated second


def test_clock_monotonic_compatible():
    """monotonic() returns total elapsed simulated seconds."""
    start = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(speed_multiplier=0, start_time=start)
    assert clock.monotonic() == 0.0

    clock.advance(timedelta(seconds=30))
    assert clock.monotonic() == 30.0


def test_clock_to_dict():
    """to_dict() produces serializable state."""
    start = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(speed_multiplier=0, start_time=start)
    d = clock.to_dict()

    assert d["speed_multiplier"] == 0
    assert d["simulated_day"] == 1
    assert "start_time" in d
    assert "elapsed_seconds" in d


def test_clock_default_start_time():
    """Clock uses default Monday 9 AM UTC when no start_time given."""
    clock = SimulationClock(speed_multiplier=0)
    assert clock.now().hour == 9
    assert clock.now().weekday() == 0  # Monday


def test_clock_advance_accumulates():
    """Multiple advance() calls accumulate."""
    clock = SimulationClock(speed_multiplier=0)
    clock.advance(timedelta(hours=1))
    clock.advance(timedelta(hours=2))
    assert clock.elapsed() == timedelta(hours=3)


def test_clock_speed_multiplier_property():
    """speed_multiplier property returns configured value."""
    clock = SimulationClock(speed_multiplier=42)
    assert clock.speed_multiplier == 42
