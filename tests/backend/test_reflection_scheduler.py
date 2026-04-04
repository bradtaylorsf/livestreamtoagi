"""Tests for ReflectionScheduler — auto-scheduled reflections tied to simulation clock."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.memory.reflection_scheduler import ReflectionScheduler
from core.simulation.clock import SimulationClock


def _make_reflection_result(**overrides):
    result = MagicMock()
    result.promoted_count = overrides.get("promoted_count", 0)
    result.importance_updates = overrides.get("importance_updates", 0)
    result.journal_entry = overrides.get("journal_entry", None)
    result.proposals = overrides.get("proposals", [])
    return result


class TestReflectionScheduler:
    def _make_scheduler(
        self,
        *,
        speed_multiplier: float = 0,
        six_hour_interval_hours: int = 6,
        daily_hour: int = 23,
        weekly_day: int = 7,
    ) -> tuple[ReflectionScheduler, SimulationClock, MagicMock]:
        clock = SimulationClock(speed_multiplier=speed_multiplier)
        reflection_manager = MagicMock()
        reflection_manager.run_6hour_reflection = AsyncMock(
            return_value=_make_reflection_result()
        )
        reflection_manager.run_weekly_reflection = AsyncMock(
            return_value=_make_reflection_result()
        )
        scheduler = ReflectionScheduler(
            clock,
            reflection_manager,
            six_hour_interval_hours=six_hour_interval_hours,
            daily_hour=daily_hour,
            weekly_day=weekly_day,
        )
        return scheduler, clock, reflection_manager

    @pytest.mark.asyncio
    async def test_no_reflection_before_interval(self):
        scheduler, clock, mgr = self._make_scheduler()
        # Only advance 3 hours — not enough for 6-hour reflection
        clock.advance(timedelta(hours=3))
        results = await scheduler.check_and_run("vera")
        assert results == []
        mgr.run_6hour_reflection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_6hour_reflection_fires_after_interval(self):
        scheduler, clock, mgr = self._make_scheduler()
        # Advance past 6 hours (using 80% threshold = 4.8h)
        clock.advance(timedelta(hours=5))
        results = await scheduler.check_and_run("vera")
        assert len(results) == 1
        mgr.run_6hour_reflection.assert_awaited_once_with("vera")

    @pytest.mark.asyncio
    async def test_no_duplicate_6hour_reflection(self):
        scheduler, clock, mgr = self._make_scheduler()
        clock.advance(timedelta(hours=7))
        await scheduler.check_and_run("vera")
        mgr.run_6hour_reflection.reset_mock()

        # Only 1 more hour — not enough for another 6-hour reflection
        clock.advance(timedelta(hours=1))
        results = await scheduler.check_and_run("vera")
        assert results == []
        mgr.run_6hour_reflection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_daily_reflection_fires_at_configured_hour(self):
        scheduler, clock, mgr = self._make_scheduler(daily_hour=23)
        # Default start is 9:00 AM — advance 14 hours to 11 PM
        clock.advance(timedelta(hours=14))
        results = await scheduler.check_and_run("vera")
        assert len(results) == 1
        mgr.run_6hour_reflection.assert_awaited_once_with("vera")

    @pytest.mark.asyncio
    async def test_daily_reflection_only_fires_once_per_day(self):
        scheduler, clock, mgr = self._make_scheduler(daily_hour=23)
        clock.advance(timedelta(hours=14))  # 11 PM
        await scheduler.check_and_run("vera")
        mgr.run_6hour_reflection.reset_mock()

        # Still same day, later hour
        clock.advance(timedelta(minutes=30))
        results = await scheduler.check_and_run("vera")
        assert results == []

    @pytest.mark.asyncio
    async def test_weekly_reflection_fires_on_weekly_day(self):
        scheduler, clock, mgr = self._make_scheduler(weekly_day=7)
        # Advance to day 7 (6 full days from day 1)
        clock.advance(timedelta(days=6))
        results = await scheduler.check_and_run("rex")
        assert len(results) == 1
        mgr.run_weekly_reflection.assert_awaited_once_with("rex")

    @pytest.mark.asyncio
    async def test_weekly_reflection_only_fires_once_on_day(self):
        scheduler, clock, mgr = self._make_scheduler(weekly_day=7)
        clock.advance(timedelta(days=6))
        await scheduler.check_and_run("rex")
        mgr.run_weekly_reflection.reset_mock()

        # Still day 7
        clock.advance(timedelta(hours=2))
        results = await scheduler.check_and_run("rex")
        assert results == []
        mgr.run_weekly_reflection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mark_recently_reflected_prevents_duplicate(self):
        scheduler, clock, mgr = self._make_scheduler()
        # Mark as recently reflected
        scheduler.mark_recently_reflected("vera")
        # Advance 5 hours — would normally trigger
        clock.advance(timedelta(hours=5))
        results = await scheduler.check_and_run("vera")
        # Should still trigger since 5h > 4.8h (80% of 6h)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_mark_recently_reflected_resets_timer(self):
        scheduler, clock, mgr = self._make_scheduler()
        clock.advance(timedelta(hours=3))
        scheduler.mark_recently_reflected("vera")
        # Only 2 more hours from the mark — not enough
        clock.advance(timedelta(hours=2))
        results = await scheduler.check_and_run("vera")
        assert results == []

    @pytest.mark.asyncio
    async def test_check_and_run_all_parallel(self):
        scheduler, clock, mgr = self._make_scheduler()
        clock.advance(timedelta(hours=7))
        results = await scheduler.check_and_run_all(["vera", "rex", "aurora"])
        assert len(results) == 3
        assert mgr.run_6hour_reflection.await_count == 3

    @pytest.mark.asyncio
    async def test_check_and_run_all_handles_exceptions(self):
        scheduler, clock, mgr = self._make_scheduler()
        clock.advance(timedelta(hours=7))
        mgr.run_6hour_reflection = AsyncMock(side_effect=RuntimeError("LLM down"))
        # Should not raise — errors are caught
        results = await scheduler.check_and_run_all(["vera", "rex"])
        assert results == []

    @pytest.mark.asyncio
    async def test_independent_tracking_per_agent(self):
        scheduler, clock, mgr = self._make_scheduler()
        clock.advance(timedelta(hours=7))
        await scheduler.check_and_run("vera")
        mgr.run_6hour_reflection.reset_mock()

        # Rex hasn't reflected yet, but vera just did
        results = await scheduler.check_and_run("rex")
        assert len(results) == 1
        mgr.run_6hour_reflection.assert_awaited_once_with("rex")

        # Vera should not reflect again
        results = await scheduler.check_and_run("vera")
        assert results == []
