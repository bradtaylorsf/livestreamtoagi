"""get_world_state tool — current world snapshot from Redis."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BaseTool, parse_json

if TYPE_CHECKING:
    from core.redis_client import RedisClient


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
            "agents": parse_json(agents_raw, []),
            "active_tasks": parse_json(tasks_raw, []),
            "recent_events": parse_json(events_raw, []),
            "budget": parse_json(budget_raw, {"spent": 0.0, "remaining": 0.0}),
        }
