"""Agent tools package — core tools and tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .audience import GetAudienceStatusTool
from .base import BaseTool
from .messaging import SendMessageTool
from .world_state import GetWorldStateTool

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.redis_client import RedisClient

__all__ = [
    "BaseTool",
    "GetAudienceStatusTool",
    "GetWorldStateTool",
    "SendMessageTool",
    "ToolRegistry",
    "get_core_tools",
]


class ToolRegistry:
    """Maps tool names to tool instances for per-agent assignment."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> dict[str, BaseTool]:
        return dict(self._tools)

    def names(self) -> list[str]:
        return list(self._tools.keys())


def get_core_tools(
    event_bus: EventBus,
    redis_client: RedisClient,
    agent_id: str = "unknown",
) -> list[BaseTool]:
    """Create instances of all core tools available to every agent."""
    return [
        SendMessageTool(event_bus=event_bus, agent_id=agent_id),
        GetWorldStateTool(redis_client=redis_client),
        GetAudienceStatusTool(redis_client=redis_client),
    ]
