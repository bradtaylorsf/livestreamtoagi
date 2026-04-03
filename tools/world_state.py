"""get_world_state tool — current world snapshot from Redis."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .base import BaseTool

if TYPE_CHECKING:
    from core.redis_client import RedisClient

logger = logging.getLogger(__name__)


class GetWorldStateTool(BaseTool):
    """Get current state of the world — agent locations, active tasks, recent events."""

    name = "get_world_state"
    description = (
        "Get current state of the world — agent locations, active tasks, "
        "recent events, budget status"
    )
    parameters = {}

    def __init__(self, redis_client: RedisClient) -> None:
        self._redis = redis_client

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        agents_raw = await self._redis.get("world:agents")
        tasks_raw = await self._redis.get("world:active_tasks")
        events_raw = await self._redis.get("world:recent_events")
        budget_raw = await self._redis.get("world:budget")

        return {
            "agents": _parse_json(agents_raw, []),
            "active_tasks": _parse_json(tasks_raw, []),
            "recent_events": _parse_json(events_raw, []),
            "budget": _parse_json(budget_raw, {"spent": 0.0, "remaining": 0.0}),
        }


def _parse_json(raw: str | None, default: Any) -> Any:
    """Parse a JSON string, returning default on failure."""
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse Redis value as JSON: %s", raw[:100] if raw else raw)
        return default
