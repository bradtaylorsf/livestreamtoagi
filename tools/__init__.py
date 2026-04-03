"""Agent tools package — core tools and tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .audience import GetAudienceStatusTool
from .audience_tools import CreatePollTool, GetPollResultsTool, SendChatMessageTool
from .base import BaseTool
from .code_execution import ExecuteCodeTool
from .messaging import SendMessageTool
from .revenue_tools import DraftEmailTool, DraftSocialPostTool, GetRevenueStatusTool
from .tilemap_gen import GenerateTilemapTool
from .web_tools import FetchUrlTool, WebSearchTool
from .world_state import GetWorldStateTool

if TYPE_CHECKING:
    import docker
    from core.event_bus import EventBus
    from core.overseer import Overseer
    from core.redis_client import RedisClient
    from core.repos.cost_repo import CostRepo
    from core.repos.world_repo import WorldRepo

__all__ = [
    "BaseTool",
    "CreatePollTool",
    "DraftEmailTool",
    "DraftSocialPostTool",
    "ExecuteCodeTool",
    "FetchUrlTool",
    "GenerateTilemapTool",
    "GetAudienceStatusTool",
    "GetPollResultsTool",
    "GetRevenueStatusTool",
    "GetWorldStateTool",
    "SendChatMessageTool",
    "SendMessageTool",
    "ToolRegistry",
    "WebSearchTool",
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
    overseer: Overseer | None = None,
    docker_client: docker.DockerClient | None = None,
    world_repo: WorldRepo | None = None,
    cost_repo: CostRepo | None = None,
) -> list[BaseTool]:
    """Create instances of all core tools available to every agent."""
    tools: list[BaseTool] = [
        SendMessageTool(event_bus=event_bus, agent_id=agent_id),
        GetWorldStateTool(redis_client=redis_client),
        GetAudienceStatusTool(redis_client=redis_client),
        GetPollResultsTool(redis_client=redis_client, event_bus=event_bus),
    ]

    # Audience tools that require Overseer
    if overseer is not None:
        tools.append(
            SendChatMessageTool(
                overseer=overseer, event_bus=event_bus, redis_client=redis_client, agent_id=agent_id
            )
        )

    # Poll creation (no Overseer needed)
    tools.append(
        CreatePollTool(redis_client=redis_client, event_bus=event_bus, agent_id=agent_id)
    )

    # Code execution sandbox
    exec_tool = ExecuteCodeTool(event_bus=event_bus, agent_id=agent_id, docker_client=docker_client)
    tools.append(exec_tool)

    # Tilemap generation (requires world_repo for chunk storage)
    if world_repo is not None:
        tools.append(
            GenerateTilemapTool(
                event_bus=event_bus,
                agent_id=agent_id,
                execute_code_tool=exec_tool,
                world_repo=world_repo,
            )
        )

    # Revenue and marketing tools
    if cost_repo is not None:
        tools.append(GetRevenueStatusTool(cost_repo=cost_repo, agent_id=agent_id))
    tools.append(DraftSocialPostTool(redis_client=redis_client, agent_id=agent_id))
    tools.append(DraftEmailTool(redis_client=redis_client, agent_id=agent_id))

    # Web search and URL fetch tools
    tools.append(
        WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id=agent_id,
            cost_repo=cost_repo,
        )
    )
    tools.append(
        FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id=agent_id,
            cost_repo=cost_repo,
        )
    )

    return tools
