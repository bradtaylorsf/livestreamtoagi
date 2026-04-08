"""Agent tools package — core tools and tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .alpha_dispatch import DispatchAlphaTool
from .audience import GetAudienceStatusTool
from .audience_tools import CreatePollTool, GetPollResultsTool, SendChatMessageTool
from .base import BaseTool
from .character_tools import ProposeCharacterTool, VoteCharacterTool
from .code_execution import ExecuteCodeTool
from .economy_tools import TransferBudgetTool, ViewAccountTool
from .memory_tools import RecallMemoryTool, RetrieveTranscriptTool, UpdateCoreMemoryTool
from .messaging import SendMessageTool
from .revenue_tools import (
    CheckEmailResponsesTool,
    CheckPostPerformanceTool,
    DraftEmailTool,
    DraftSocialPostTool,
    GetRevenueStatusTool,
)
from .self_modification import ProposeSelfModificationTool, ViewEvolutionLogTool
from .social_tools import (
    LeaveAllianceTool,
    ProposeAllianceTool,
    ViewAlliancesTool,
    VoteAllianceTool,
)
from .task_management import ManageTaskTool
from .tilemap_gen import GenerateTilemapTool
from .web_tools import FetchUrlTool, WebSearchTool
from .world_state import GetWorldStateTool

if TYPE_CHECKING:
    import docker
    from core.agent_economy import AgentEconomyManager
    from core.agent_registry import AgentRegistry
    from core.characters.spawner import CharacterSpawner
    from core.characters.voting import VotingManager
    from core.event_bus import EventBus
    from core.llm_client import LLMClient
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.management import Management
    from core.redis_client import RedisClient
    from core.repos.artifact_repo import ArtifactRepo
    from core.repos.cost_repo import CostRepo
    from core.repos.memory_repo import MemoryRepo
    from core.repos.world_repo import WorldRepo
    from core.shared_state import SharedWorkingState
    from core.social.alliances import AllianceManager

__all__ = [
    "BaseTool",
    "CreatePollTool",
    "ProposeAllianceTool",
    "ProposeCharacterTool",
    "VoteCharacterTool",
    "DispatchAlphaTool",
    "DraftEmailTool",
    "DraftSocialPostTool",
    "ExecuteCodeTool",
    "FetchUrlTool",
    "GenerateTilemapTool",
    "GetAudienceStatusTool",
    "GetPollResultsTool",
    "GetRevenueStatusTool",
    "GetWorldStateTool",
    "LeaveAllianceTool",
    "ManageTaskTool",
    "ProposeSelfModificationTool",
    "RecallMemoryTool",
    "RetrieveTranscriptTool",
    "SendChatMessageTool",
    "SendMessageTool",
    "ToolRegistry",
    "TransferBudgetTool",
    "UpdateCoreMemoryTool",
    "ViewAccountTool",
    "ViewAlliancesTool",
    "ViewEvolutionLogTool",
    "VoteAllianceTool",
    "WebSearchTool",
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
    management: Management | None = None,
    docker_client: docker.DockerClient | None = None,
    world_repo: WorldRepo | None = None,
    cost_repo: CostRepo | None = None,
    llm_client: LLMClient | None = None,
    memory_repo: MemoryRepo | None = None,
    artifact_repo: ArtifactRepo | None = None,
    simulation_mode: bool = False,
    shared_working_state: SharedWorkingState | None = None,
    agent_registry: AgentRegistry | None = None,
    economy_manager: AgentEconomyManager | None = None,
    alliance_manager: AllianceManager | None = None,
    character_spawner: CharacterSpawner | None = None,
    voting_manager: VotingManager | None = None,
) -> list[BaseTool]:
    """Create instances of all core tools available to every agent.

    When simulation_mode=True, Docker-dependent tools are replaced with
    stubs that return synthetic results (status="simulated").
    """
    tools: list[BaseTool] = [
        SendMessageTool(event_bus=event_bus, agent_id=agent_id),
        GetWorldStateTool(redis_client=redis_client),
        GetAudienceStatusTool(redis_client=redis_client),
        GetPollResultsTool(redis_client=redis_client, event_bus=event_bus),
    ]

    # Audience tools that require Management
    if management is not None:
        tools.append(
            SendChatMessageTool(
                management=management, event_bus=event_bus, redis_client=redis_client, agent_id=agent_id
            )
        )

    # Poll creation (no Management needed)
    tools.append(
        CreatePollTool(redis_client=redis_client, event_bus=event_bus, agent_id=agent_id)
    )

    # Code execution sandbox (or simulation stub)
    if simulation_mode:
        from .stubs import StubExecuteCodeTool, StubGenerateTilemapTool

        tools.append(StubExecuteCodeTool(event_bus=event_bus, agent_id=agent_id))
        tools.append(StubGenerateTilemapTool(event_bus=event_bus, agent_id=agent_id))
    else:
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
        tools.append(GetRevenueStatusTool(
            cost_repo=cost_repo, agent_id=agent_id,
            economy_manager=economy_manager,
        ))
    tools.append(DraftSocialPostTool(redis_client=redis_client, agent_id=agent_id))
    tools.append(DraftEmailTool(redis_client=redis_client, agent_id=agent_id))
    tools.append(CheckPostPerformanceTool(redis_client=redis_client, agent_id=agent_id))
    tools.append(CheckEmailResponsesTool(redis_client=redis_client, agent_id=agent_id))

    # Economy tools — available to all agents
    if economy_manager is not None:
        tools.append(TransferBudgetTool(economy_manager=economy_manager, agent_id=agent_id))
        tools.append(ViewAccountTool(economy_manager=economy_manager, agent_id=agent_id))

    # Character proposal/voting tools (#275)
    if character_spawner is not None:
        tools.append(ProposeCharacterTool(spawner=character_spawner, agent_id=agent_id))
    if voting_manager is not None:
        tools.append(VoteCharacterTool(voting_manager=voting_manager, agent_id=agent_id))

    # Alliance/social tools (#274)
    if alliance_manager is not None:
        tools.append(ProposeAllianceTool(alliance_manager=alliance_manager, agent_id=agent_id))
        tools.append(VoteAllianceTool(alliance_manager=alliance_manager, agent_id=agent_id))
        tools.append(LeaveAllianceTool(alliance_manager=alliance_manager, agent_id=agent_id))
        tools.append(ViewAlliancesTool(alliance_manager=alliance_manager, agent_id=agent_id))

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

    # Alpha dispatch (requires LLM client)
    if llm_client is not None:
        tools.append(
            DispatchAlphaTool(
                event_bus=event_bus,
                agent_id=agent_id,
                llm_client=llm_client,
                cost_repo=cost_repo,
            )
        )

    # Task management tool
    if shared_working_state is not None:
        tools.append(
            ManageTaskTool(shared_state=shared_working_state, agent_id=agent_id)
        )

    # Self-modification tools (available to all agents)
    if memory_repo is not None:
        tools.append(
            ProposeSelfModificationTool(agent_id=agent_id, memory_repo=memory_repo)
        )
        tools.append(
            ViewEvolutionLogTool(agent_id=agent_id, memory_repo=memory_repo)
        )

    if artifact_repo is not None:
        for tool in tools:
            tool.artifact_repo = artifact_repo

    # Set event_bus on all tools so BaseTool.run() can emit artifact_created
    for tool in tools:
        tool.event_bus = event_bus

    # Filter out tools the agent isn't authorized to use so they never
    # appear in the tool schema (prevents unauthorized call attempts).
    if agent_id != "unknown":
        if agent_registry is not None:
            # Use agent config's tools list as the source of truth
            agent_cfg = agent_registry.get_agent(agent_id)
            agent_tools = set(agent_cfg.tools) if agent_cfg else set()
            tools = [
                t for t in tools
                if not hasattr(t, "ALLOWED_AGENTS") or t.name in agent_tools
            ]
        else:
            # Fallback: use hardcoded ALLOWED_AGENTS on tool classes
            tools = [
                t for t in tools
                if not hasattr(t, "ALLOWED_AGENTS") or agent_id in t.ALLOWED_AGENTS
            ]

    return tools


def get_memory_tools(
    recall_manager: RecallMemoryManager,
    archival_manager: ArchivalMemoryManager,
    core_manager: CoreMemoryManager,
    agent_id: str = "unknown",
    artifact_repo: ArtifactRepo | None = None,
    agent_registry: AgentRegistry | None = None,
) -> list[BaseTool]:
    """Create instances of all memory tools for an agent."""
    update_tool = UpdateCoreMemoryTool(core_manager=core_manager, agent_id=agent_id)
    # Override CROSS_AGENT_WRITERS from agent registry if available
    if agent_registry is not None:
        update_tool.CROSS_AGENT_WRITERS = agent_registry.get_cross_agent_writers()

    tools: list[BaseTool] = [
        RecallMemoryTool(recall_manager=recall_manager, agent_id=agent_id),
        RetrieveTranscriptTool(archival_manager=archival_manager),
        update_tool,
    ]

    if artifact_repo is not None:
        for tool in tools:
            tool.artifact_repo = artifact_repo

    return tools
