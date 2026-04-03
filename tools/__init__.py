"""Agent tools package — core tools and tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .audience import GetAudienceStatusTool
from .base import BaseTool
from .memory_tools import RecallMemoryTool, RetrieveTranscriptTool, UpdateCoreMemoryTool
from .messaging import SendMessageTool
from .world_state import GetWorldStateTool

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.redis_client import RedisClient

__all__ = [
    "BaseTool",
    "GetAudienceStatusTool",
    "GetWorldStateTool",
    "RecallMemoryTool",
    "RetrieveTranscriptTool",
    "SendMessageTool",
    "ToolRegistry",
    "UpdateCoreMemoryTool",
    "get_core_tools",
    "get_memory_tools",
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


def get_memory_tools(
    recall_manager: RecallMemoryManager,
    archival_manager: ArchivalMemoryManager,
    core_manager: CoreMemoryManager,
    agent_id: str = "unknown",
) -> list[BaseTool]:
    """Create instances of all memory tools for an agent."""
    return [
        RecallMemoryTool(recall_manager=recall_manager, agent_id=agent_id),
        RetrieveTranscriptTool(archival_manager=archival_manager),
        UpdateCoreMemoryTool(core_manager=core_manager, agent_id=agent_id),
    ]
