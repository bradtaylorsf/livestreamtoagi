"""ReflectionScheduler — auto-scheduled reflections tied to simulation clock.

Fires 6-hour, daily, and weekly reflections automatically based on simulated
clock intervals. Tracks last reflection time per agent to prevent duplicates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent_state import AgentStateManager
    from core.memory.dreams import DreamManager
    from core.memory.reflection import ReflectionManager
    from core.models import ReflectionResult
    from core.simulation.clock import SimulationClock

logger = logging.getLogger(__name__)


class ReflectionScheduler:
    """Checks and runs reflections based on simulated clock intervals."""

    def __init__(
        self,
        clock: SimulationClock,
        reflection_manager: ReflectionManager,
        *,
        six_hour_interval_hours: int = 6,
        daily_hour: int = 23,
        weekly_day: int = 7,
        dream_interval_hours: int = 14,
        dream_manager: DreamManager | None = None,
        agent_state_manager: AgentStateManager | None = None,
    ) -> None:
        self._clock = clock
        self._reflection = reflection_manager
        self._six_hour_interval = timedelta(hours=six_hour_interval_hours)
        self._daily_hour = daily_hour
        self._weekly_day = weekly_day

        # Dream system integration (#272)
        self._dream_manager = dream_manager
        self._dream_interval = timedelta(hours=dream_interval_hours)
        self._agent_state_manager = agent_state_manager

        # Per-agent tracking: last reflection simulated time
        # Initialize to clock start so first reflection fires after the interval
        self._init_time = clock.now()
        self._last_6hour: dict[str, datetime] = {}
        self._last_daily: dict[str, str] = {}  # agent_id -> "YYYY-MM-DD"
        self._last_weekly: dict[str, int] = {}  # agent_id -> simulated_day
        self._last_dream: dict[str, datetime] = {}  # agent_id -> simulated_time

    def _ensure_tracking(self, agent_id: str) -> None:
        """Initialize tracking for an agent on first encounter."""
        if agent_id not in self._last_6hour:
            self._last_6hour[agent_id] = self._init_time
        if agent_id not in self._last_dream:
            self._last_dream[agent_id] = self._init_time

    async def check_and_run(self, agent_id: str) -> list[ReflectionResult]:
        """Check if any reflection is due for this agent and run if so."""
        self._ensure_tracking(agent_id)
        now = self._clock.now()
        results: list[ReflectionResult] = []

        # Weekly reflection (check first — it's the rarest)
        current_day = self._clock.simulated_day()
        if (
            current_day >= self._weekly_day
            and current_day % self._weekly_day == 0
            and self._last_weekly.get(agent_id) != current_day
        ):
            logger.info(
                "Weekly reflection due for %s (day %d, simulated %s)",
                agent_id,
                current_day,
                now.isoformat(),
            )
            try:
                result = await self._reflection.run_weekly_reflection(agent_id)
                results.append(result)
                self._last_weekly[agent_id] = current_day
                # Weekly reflection also counts as a 6-hour and daily reflection
                self._last_6hour[agent_id] = now
                self._last_daily[agent_id] = now.strftime("%Y-%m-%d")
            except Exception:
                logger.exception("Weekly reflection failed for %s", agent_id)
            return results

        # Daily reflection (at configured hour, once per simulated day)
        today_str = now.strftime("%Y-%m-%d")
        if now.hour >= self._daily_hour and self._last_daily.get(agent_id) != today_str:
            logger.info(
                "Daily reflection due for %s (hour %d, simulated %s)",
                agent_id,
                now.hour,
                now.isoformat(),
            )
            try:
                result = await self._reflection.run_6hour_reflection(agent_id)
                results.append(result)
                self._last_daily[agent_id] = today_str
                self._last_6hour[agent_id] = now
            except Exception:
                logger.exception("Daily reflection failed for %s", agent_id)
            return results

        # 6-hour reflection
        elapsed = now - self._last_6hour[agent_id]
        # Use 80% threshold to avoid near-duplicate reflections
        if elapsed >= self._six_hour_interval * 0.8:
            logger.info(
                "6-hour reflection due for %s (%.1fh elapsed, simulated %s)",
                agent_id,
                elapsed.total_seconds() / 3600,
                now.isoformat(),
            )
            try:
                result = await self._reflection.run_6hour_reflection(agent_id)
                results.append(result)
                self._last_6hour[agent_id] = now
            except Exception:
                logger.exception("6-hour reflection failed for %s", agent_id)

        # Dream cycle (#272): check if dream is due
        await self._check_and_run_dream(agent_id, now)

        return results

    async def check_and_run_all(self, agent_ids: list[str]) -> list[ReflectionResult]:
        """Run check_and_run for all agents in parallel."""
        tasks = [self.check_and_run(agent_id) for agent_id in agent_ids]
        nested = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[ReflectionResult] = []
        for item in nested:
            if isinstance(item, BaseException):
                logger.exception("Reflection check failed: %s", item)
            else:
                results.extend(item)
        return results

    async def _check_and_run_dream(
        self,
        agent_id: str,
        now: datetime,
    ) -> None:
        """Check if a dream cycle is due and run it.

        Dreams trigger every dream_interval_hours (default 14h), or when
        boredom is very high (>0.8) as an override.
        """
        if self._dream_manager is None:
            return

        dream_elapsed = now - self._last_dream.get(agent_id, self._init_time)
        should_dream = dream_elapsed >= self._dream_interval

        # Boredom override: dream when very bored (>0.8)
        if not should_dream and self._agent_state_manager is not None:
            try:
                state = await self._agent_state_manager.get_state(agent_id)
                if state.boredom > 0.8:
                    should_dream = True
                    logger.info(
                        "Boredom-triggered dream for %s (boredom=%.2f)", agent_id, state.boredom
                    )
            except Exception:
                pass

        if should_dream:
            logger.info(
                "Dream cycle due for %s (%.1fh since last dream)",
                agent_id,
                dream_elapsed.total_seconds() / 3600,
            )
            try:
                await self._dream_manager.run_dream(agent_id)
                self._last_dream[agent_id] = now
            except Exception:
                logger.exception("Dream cycle failed for %s", agent_id)

    def mark_recently_reflected(self, agent_id: str) -> None:
        """Mark an agent as having just reflected (prevents duplicate from scheduler).

        Called when a seed-file explicit reflection phase runs.
        """
        now = self._clock.now()
        self._last_6hour[agent_id] = now
        self._last_daily[agent_id] = now.strftime("%Y-%m-%d")
        self._last_weekly[agent_id] = self._clock.simulated_day()
