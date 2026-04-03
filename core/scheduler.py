"""Reflection scheduler — triggers 6-hour and weekly reflection cycles via APScheduler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry
    from core.memory.reflection import ReflectionManager

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_6hour_reflections(
    reflection_mgr: ReflectionManager,
    agent_registry: AgentRegistry,
) -> None:
    """Run 6-hour reflection for all active agents."""
    agents = agent_registry.get_active_agents()
    for agent in agents:
        try:
            result = await reflection_mgr.run_6hour_reflection(agent.id)
            logger.info(
                "6-hour reflection for %s: promoted=%d, importance_updates=%d",
                agent.id,
                result.promoted_count,
                result.importance_updates,
            )
        except Exception:
            logger.exception("6-hour reflection failed for %s", agent.id)


async def _run_weekly_reflections(
    reflection_mgr: ReflectionManager,
    agent_registry: AgentRegistry,
) -> None:
    """Run weekly reflection for all active agents."""
    agents = agent_registry.get_active_agents()
    for agent in agents:
        try:
            result = await reflection_mgr.run_weekly_reflection(agent.id)
            logger.info(
                "Weekly reflection for %s: promoted=%d, proposals=%d",
                agent.id,
                result.promoted_count,
                len(result.proposals),
            )
        except Exception:
            logger.exception("Weekly reflection failed for %s", agent.id)


def start_scheduler(
    reflection_mgr: ReflectionManager,
    agent_registry: AgentRegistry,
) -> AsyncIOScheduler:
    """Start the APScheduler with 6-hour and weekly reflection jobs."""
    global _scheduler  # noqa: PLW0603

    scheduler = AsyncIOScheduler()

    # 6-hour reflection at 2AM, 8AM, 2PM, 8PM UTC
    scheduler.add_job(
        _run_6hour_reflections,
        trigger=CronTrigger(hour="2,8,14,20", minute=0, timezone="UTC"),
        args=[reflection_mgr, agent_registry],
        id="reflection_6hour",
        name="6-hour reflection cycle",
        replace_existing=True,
    )

    # Weekly reflection at Sunday 8PM UTC
    scheduler.add_job(
        _run_weekly_reflections,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="UTC"),
        args=[reflection_mgr, agent_registry],
        id="reflection_weekly",
        name="Weekly reflection cycle",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Reflection scheduler started (6-hour: 2/8/14/20 UTC, weekly: Sun 20:00 UTC)")
    return scheduler


def stop_scheduler() -> None:
    """Stop the running scheduler."""
    global _scheduler  # noqa: PLW0603
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Reflection scheduler stopped")
        _scheduler = None
