"""Shared service bootstrap for all entry points.

Eliminates duplicated initialization across core/main.py,
scripts/test_agent.py, and scripts/watch_conversations.py.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import httpx

from core.agent_registry import AgentRegistry
from core.config_loader import ConfigLoader
from core.context_assembly import ContextAssembler
from core.database import Database
from core.event_bus import EventBus
from core.llm_client import OpenRouterClient, refresh_pricing
from core.memory.archival_memory import ArchivalMemoryManager
from core.memory.compaction import MemoryCompactor
from core.memory.core_memory import CoreMemoryManager
from core.memory.recall_memory import RecallMemoryManager
from core.memory.token_counter import TokenCounter
from core.management import Management
from core.redis_client import RedisClient
from core.repos.artifact_repo import ArtifactRepo
from core.repos.config_version_repo import ConfigVersionRepo
from core.repos.cost_repo import CostRepo
from core.repos.goal_repo import GoalRepo
from core.repos.memory_repo import MemoryRepo
from core.repos.relationship_repo import RelationshipRepo
from core.repos.transcript_repo import TranscriptRepo
from core.repos.world_repo import WorldRepo
from core.agent_goals import AgentGoalManager
from core.shared_state import SharedWorkingState

logger = logging.getLogger(__name__)

EmbeddingFn = Callable[[str], Coroutine[Any, Any, list[float]]]


@dataclass
class Services:
    """All initialized subsystems returned by bootstrap_services()."""

    db: Database | None
    redis: RedisClient | None
    http_client: httpx.AsyncClient | None
    agent_registry: AgentRegistry
    llm_client: OpenRouterClient | None
    core_memory: CoreMemoryManager | None
    recall_memory: RecallMemoryManager | None
    archival_memory: ArchivalMemoryManager | None
    compactor: MemoryCompactor | None
    context_assembler: ContextAssembler
    token_counter: TokenCounter
    memory_repo: MemoryRepo | None
    transcript_repo: TranscriptRepo | None
    event_bus: EventBus
    management: Management | None
    cost_repo: CostRepo | None
    artifact_repo: ArtifactRepo | None
    world_repo: WorldRepo | None
    relationship_repo: RelationshipRepo | None
    shared_working_state: SharedWorkingState | None
    goal_manager: AgentGoalManager | None
    config_loader: ConfigLoader
    config_version_repo: ConfigVersionRepo | None


def make_embedding_fn(
    http_client: httpx.AsyncClient, api_key: str,
) -> EmbeddingFn:
    """Create an embedding function using the real OpenRouter API."""
    if not api_key:
        logger.warning(
            "OPENROUTER_API_KEY not set — recall memory embeddings will fail",
        )

    from core.memory.embeddings import generate_embedding

    async def embedding_fn(text: str) -> list[float]:
        return await generate_embedding(text, http_client, api_key)

    return embedding_fn


async def bootstrap_services(
    *,
    dry_run: bool = False,
    auto_migrate: bool = False,
    load_config: bool = True,
) -> Services:
    """Wire up all subsystems and return a Services instance.

    Args:
        dry_run: If True, skip DB/Redis connections and return stub managers
            (for context-assembly-only modes like test_agent --dry-run).
        auto_migrate: If True, auto-run DB migrations when tables are missing.
        load_config: If True, load ConversationConfig from YAML.
    """
    token_counter = TokenCounter()
    config_loader = ConfigLoader()  # repo injected below after DB init

    if load_config:
        config_loader.load()

    if dry_run:
        return await _bootstrap_dry_run(token_counter, config_loader)

    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    db = Database()
    redis_client = RedisClient()

    await db.connect()
    await redis_client.connect()

    if auto_migrate:
        await _auto_migrate(db)

    config_version_repo = ConfigVersionRepo(db)

    agent_registry = AgentRegistry(
        redis_client=redis_client,
        config_version_repo=config_version_repo,
    )
    await agent_registry.load_all()

    cost_repo = CostRepo(db)
    artifact_repo = ArtifactRepo(db)
    world_repo = WorldRepo(db)
    relationship_repo = RelationshipRepo(db)
    memory_repo = MemoryRepo(db)
    transcript_repo = TranscriptRepo(db)
    http_client = httpx.AsyncClient()

    await refresh_pricing(http_client)
    llm_client = OpenRouterClient(api_key=api_key, cost_repo=cost_repo)
    core_memory = CoreMemoryManager(memory_repo=memory_repo, token_counter=token_counter)
    recall_memory = RecallMemoryManager(
        memory_repo=memory_repo,
        embedding_fn=make_embedding_fn(http_client, api_key),
    )
    archival_memory = ArchivalMemoryManager(
        transcript_repo=transcript_repo, token_counter=token_counter,
    )
    compactor = MemoryCompactor(
        archival=archival_memory,
        recall=recall_memory,
        llm_client=llm_client,
        http_client=http_client,
        openrouter_api_key=api_key,
    )

    from core.event_bus import event_bus as _module_event_bus

    management = Management(
        redis_client=redis_client,
        llm_client=llm_client,
        event_bus=_module_event_bus,
    )

    # Inject config_version_repo into config_loader for DB-backed config
    config_loader._config_repo = config_version_repo

    shared_working_state = SharedWorkingState(redis_client.client)
    goal_repo = GoalRepo(db)
    goal_manager = AgentGoalManager(redis=redis_client.client, goal_repo=goal_repo)

    context_assembler = ContextAssembler(
        agent_registry=agent_registry,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        token_counter=token_counter,
        redis_client=redis_client,
    )

    return Services(
        db=db,
        redis=redis_client,
        http_client=http_client,
        agent_registry=agent_registry,
        llm_client=llm_client,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        compactor=compactor,
        context_assembler=context_assembler,
        token_counter=token_counter,
        memory_repo=memory_repo,
        transcript_repo=transcript_repo,
        event_bus=_module_event_bus,
        management=management,
        cost_repo=cost_repo,
        artifact_repo=artifact_repo,
        world_repo=world_repo,
        relationship_repo=relationship_repo,
        shared_working_state=shared_working_state,
        goal_manager=goal_manager,
        config_loader=config_loader,
        config_version_repo=config_version_repo,
    )


async def _bootstrap_dry_run(
    token_counter: TokenCounter, config_loader: ConfigLoader,
) -> Services:
    """Lightweight bootstrap for --dry-run: no DB/Redis needed."""
    agent_registry = AgentRegistry(redis_client=None)
    await agent_registry.load_all()

    class _StubCoreMemory:
        async def get_core_memory(self, agent_id: str) -> None:
            return None

    class _StubRecallMemory:
        async def retrieve_recall_memories(
            self, agent_id: str, query: str, limit: int = 3,
        ) -> str:
            return ""

    class _StubArchivalMemory:
        async def retrieve_full_transcript(self, transcript_id: int) -> None:
            return None

    context_assembler = ContextAssembler(
        agent_registry=agent_registry,
        core_memory=_StubCoreMemory(),
        recall_memory=_StubRecallMemory(),
        archival_memory=_StubArchivalMemory(),
        token_counter=token_counter,
        redis_client=None,
    )

    return Services(
        db=None,
        redis=None,
        http_client=None,
        agent_registry=agent_registry,
        llm_client=None,
        core_memory=None,
        recall_memory=None,
        archival_memory=None,
        compactor=None,
        context_assembler=context_assembler,
        token_counter=token_counter,
        memory_repo=None,
        transcript_repo=None,
        event_bus=EventBus(),
        management=None,
        cost_repo=None,
        artifact_repo=None,
        world_repo=None,
        relationship_repo=None,
        shared_working_state=None,
        goal_manager=None,
        config_loader=config_loader,
        config_version_repo=None,
    )


async def shutdown_services(services: Services) -> None:
    """Gracefully shut down all connected services."""
    if services.llm_client:
        await services.llm_client.close()
    if services.http_client:
        await services.http_client.aclose()
    if services.redis:
        await services.redis.disconnect()
    if services.db:
        await services.db.disconnect()


async def init_core_memories(
    agent_registry: AgentRegistry,
    core_memory: CoreMemoryManager,
) -> list[str]:
    """Ensure all agents have core memory initialized.

    Returns list of agent IDs that were newly initialized.
    """
    initialized: list[str] = []
    for agent in agent_registry.get_all_agents():
        existing = await core_memory.get_core_memory(agent.id)
        if existing is None:
            identity = (
                f"I am {agent.display_name}. "
                f"My conversation model is {agent.model_conversation}."
            )
            await core_memory.initialize_agent_memory(agent.id, identity)
            initialized.append(agent.id)
    return initialized


async def _auto_migrate(db: Database) -> None:
    """Auto-run DB migrations if tables are missing."""
    try:
        await db.fetchval("SELECT 1 FROM core_memory LIMIT 0")
    except Exception:
        logger.info("Tables missing — running migrations...")
        import asyncpg

        conn = await asyncpg.connect(db.dsn, timeout=60)
        try:
            from db.migrate import up

            await up(conn)
            logger.info("Migrations applied")
        finally:
            await conn.close()
