"""Shared service bootstrap for all entry points.

Eliminates duplicated initialization across core/main.py,
scripts/test_agent.py, and scripts/watch_conversations.py.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import httpx

from core.agent_economy import AgentEconomyManager
from core.agent_goals import AgentGoalManager
from core.agent_registry import AgentRegistry
from core.agent_state import AgentStateManager
from core.characters.departure import DepartureManager
from core.characters.spawner import CharacterSpawner
from core.characters.voting import VotingManager
from core.config_loader import ConfigLoader
from core.constants import LIVE_SIMULATION_ID
from core.context_assembly import ContextAssembler
from core.cost_governor import CostGovernor
from core.database import Database
from core.event_bus import EventBus
from core.events.event_generator import EventGenerator
from core.llm_client import (
    LOCAL_LLM_BASE_URL,
    OfflineTestLLMClient,
    OpenRouterClient,
    refresh_pricing,
)
from core.management import Management
from core.memory.archival_memory import ArchivalMemoryManager
from core.memory.backend import MemoryBackend, select_memory_backend
from core.memory.compaction import MemoryCompactor
from core.memory.core_memory import CoreMemoryManager
from core.memory.dreams import DreamManager
from core.memory.recall_memory import RecallMemoryManager
from core.memory.token_counter import TokenCounter
from core.redis_client import RedisClient
from core.redis_keys import ScopedRedis
from core.repos.alliance_repo import AllianceRepo
from core.repos.artifact_repo import ArtifactRepo
from core.repos.config_version_repo import ConfigVersionRepo
from core.repos.cost_repo import CostRepo
from core.repos.goal_repo import GoalRepo
from core.repos.memory_repo import MemoryRepo
from core.repos.relationship_repo import RelationshipRepo
from core.repos.transcript_repo import TranscriptRepo
from core.repos.world_repo import WorldRepo
from core.shared_state import SharedWorkingState
from core.social.alliances import AllianceManager

if TYPE_CHECKING:
    import uuid

logger = logging.getLogger(__name__)

EmbeddingFn = Callable[[str], Coroutine[Any, Any, list[float]]]
AGENT_HOURLY_CAP_ENV = "AGENT_HOURLY_CAP_USD"
DEFAULT_AGENT_HOURLY_CAP_USD = Decimal("2.00")


@dataclass
class MemoryServices:
    """Memory subsystem facade for ConversationEngine."""

    archival_memory: Any
    compactor: Any | None = None
    memory_repo: Any | None = None


@dataclass
class InfraServices:
    """Infrastructure facade for ConversationEngine."""

    config_loader: Any
    agent_registry: Any
    event_bus: Any
    llm_client: Any
    proximity: Any
    trigger_system: Any
    selection_logger: Any


@dataclass
class ConversationOptions:
    """Runtime options facade for ConversationEngine."""

    speed_multiplier: float = 1.0
    management_enabled: bool = True
    max_turns: int = 15
    debug_prompts: bool = False
    simulation_id: uuid.UUID | None = None
    recent_conversation_summaries: list[str] | None = None
    recent_outputs: list[str] | None = None
    required_agents: set[str] | None = None
    topic_history: dict[str, list[float]] | None = None
    prompt_log_repo: object | None = None
    factions: list[Any] | None = None


@dataclass
class Services:
    """All initialized subsystems returned by bootstrap_services()."""

    db: Database | None
    redis: RedisClient | None
    scoped_redis: ScopedRedis | None
    http_client: httpx.AsyncClient | None
    agent_registry: AgentRegistry
    llm_client: OpenRouterClient | None
    core_memory: CoreMemoryManager | None
    recall_memory: RecallMemoryManager | None
    archival_memory: ArchivalMemoryManager | None
    memory_backend: MemoryBackend | None
    compactor: MemoryCompactor | None
    context_assembler: ContextAssembler
    token_counter: TokenCounter
    memory_repo: MemoryRepo | None
    transcript_repo: TranscriptRepo | None
    event_bus: EventBus
    management: Management | None
    cost_repo: CostRepo | None
    cost_governor: CostGovernor | None
    artifact_repo: ArtifactRepo | None
    world_repo: WorldRepo | None
    relationship_repo: RelationshipRepo | None
    shared_working_state: SharedWorkingState | None
    goal_manager: AgentGoalManager | None
    agent_state_manager: AgentStateManager | None
    economy_manager: AgentEconomyManager | None
    alliance_manager: AllianceManager | None
    character_spawner: CharacterSpawner | None
    voting_manager: VotingManager | None
    departure_manager: DepartureManager | None
    dream_manager: DreamManager | None
    event_generator: EventGenerator | None
    config_loader: ConfigLoader
    config_version_repo: ConfigVersionRepo | None


def make_embedding_fn(
    http_client: httpx.AsyncClient,
    api_key: str,
) -> EmbeddingFn:
    """Create an embedding function from environment-backed provider config."""
    from core.memory.embeddings import (
        embedding_config_from_env,
        generate_deterministic_embedding,
        generate_embedding,
    )

    cfg = embedding_config_from_env(api_key)
    if cfg.provider == "deterministic":
        logger.warning(
            "Using deterministic local embeddings — recall persistence is testable, "
            "but semantic recall quality is not being verified",
        )
    elif not cfg.api_key:
        logger.warning(
            "%s embedding API key not set — recall memory embeddings may fail",
            cfg.provider,
        )

    async def embedding_fn(text: str) -> list[float]:
        if cfg.provider == "deterministic":
            return generate_deterministic_embedding(text, cfg.dimension)
        return await generate_embedding(
            text,
            http_client,
            cfg.api_key,
            url=cfg.url,
            model=cfg.model,
            expected_dimension=cfg.dimension,
        )

    return embedding_fn


def make_llm_client(
    *,
    cost_repo: CostRepo,
    http_client: httpx.AsyncClient | None = None,
    cost_governor: CostGovernor | None = None,
) -> OpenRouterClient:
    """Create the configured chat LLM client.

    Environment:
      LLM_PROVIDER=openrouter|lmstudio|openai-compatible
      LOCAL_LLM_BASE_URL=http://localhost:1234/v1
      LOCAL_LLM_MODEL=<loaded LM Studio model id>
    """
    provider = os.environ.get("LLM_PROVIDER", "openrouter")
    provider_key = provider.strip().lower()
    if provider_key == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key.strip() and _allow_offline_test_llm():
            logger.warning(
                "OPENROUTER_API_KEY is unset during integration tests; "
                "using deterministic offline LLM client"
            )
            return OfflineTestLLMClient(
                cost_repo=cost_repo,
                cost_governor=cost_governor,
            )
        return OpenRouterClient(
            api_key=api_key,
            cost_repo=cost_repo,
            http_client=http_client,
            provider="openrouter",
            cost_governor=cost_governor,
        )

    api_key = os.environ.get(
        "LOCAL_LLM_API_KEY",
        os.environ.get("LLM_API_KEY", "lm-studio"),
    )
    base_url = os.environ.get(
        "LOCAL_LLM_BASE_URL",
        os.environ.get("LLM_BASE_URL", LOCAL_LLM_BASE_URL),
    )
    local_model = os.environ.get("LOCAL_LLM_MODEL") or None
    local_model_building = os.environ.get("LOCAL_LLM_MODEL_BUILDING") or None
    passthrough = os.environ.get("LOCAL_LLM_PASSTHROUGH_MODEL", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return OpenRouterClient(
        api_key=api_key,
        cost_repo=cost_repo,
        http_client=http_client,
        provider=provider,
        base_url=base_url,
        local_model=local_model,
        local_model_building=local_model_building,
        passthrough_model=passthrough,
        cost_governor=cost_governor,
    )


def _allow_offline_test_llm() -> bool:
    if os.environ.get("ENV", "development").strip().lower() == "production":
        return False
    if os.environ.get("ALLOW_OFFLINE_TEST_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return True
    current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
    return "tests/integration/" in current_test or (
        "pytest" in sys.modules and os.environ.get("PYTEST_INTEGRATION_OFFLINE_LLM") == "1"
    )


def _parse_usd_cap_env(raw: str | None, *, key: str) -> Decimal | None:
    if raw is None:
        return None
    value = raw.strip()
    if value == "" or value.lower() in {"none", "off", "disabled"}:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{key} must be a decimal USD amount, got {raw!r}") from exc


def _agent_cap_env_key(agent_id: str) -> str:
    env_agent_id = re.sub(r"[^A-Z0-9]", "_", agent_id.upper())
    return f"{AGENT_HOURLY_CAP_ENV}_{env_agent_id}"


def _per_agent_caps_from_env(agent_ids: list[str]) -> dict[str, Decimal | None]:
    caps: dict[str, Decimal | None] = {}
    for agent_id in agent_ids:
        key = _agent_cap_env_key(agent_id)
        if key in os.environ:
            caps[agent_id] = _parse_usd_cap_env(os.environ.get(key), key=key)
    return caps


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

    # Create ScopedRedis for live simulation (prefix: "live:")
    scoped_redis = ScopedRedis(redis_client, LIVE_SIMULATION_ID)

    if auto_migrate:
        await _auto_migrate(db)

    config_version_repo = ConfigVersionRepo(db)

    agent_registry = AgentRegistry(
        redis_client=scoped_redis,
        config_version_repo=config_version_repo,
    )
    await agent_registry.load_all()

    # Populate per-agent conversation config from agent registry
    if load_config:
        config_loader.populate_from_registry(agent_registry)

    cost_repo = CostRepo(db)
    artifact_repo = ArtifactRepo(db)
    world_repo = WorldRepo(db)
    relationship_repo = RelationshipRepo(db)
    memory_repo = MemoryRepo(db)
    transcript_repo = TranscriptRepo(db)
    http_client = httpx.AsyncClient()

    provider = os.environ.get("LLM_PROVIDER", "openrouter").strip().lower()
    if provider == "openrouter" and (api_key.strip() or not _allow_offline_test_llm()):
        await refresh_pricing(http_client)

    from core.event_bus import event_bus as _module_event_bus

    all_agent_ids = [a.id for a in agent_registry.get_all_agents()]
    default_agent_cap = _parse_usd_cap_env(
        os.environ.get(AGENT_HOURLY_CAP_ENV, str(DEFAULT_AGENT_HOURLY_CAP_USD)),
        key=AGENT_HOURLY_CAP_ENV,
    )
    cost_governor = CostGovernor(
        cost_repo,
        redis_client,
        default_hourly_cap_usd=default_agent_cap,
        per_agent_caps_usd=_per_agent_caps_from_env(all_agent_ids),
        event_bus=_module_event_bus,
    )
    llm_client = make_llm_client(cost_repo=cost_repo, cost_governor=cost_governor)
    embedding_fn = make_embedding_fn(http_client, api_key)
    core_memory = CoreMemoryManager(memory_repo=memory_repo, token_counter=token_counter)
    recall_memory = RecallMemoryManager(
        memory_repo=memory_repo,
        embedding_fn=embedding_fn,
    )
    archival_memory = ArchivalMemoryManager(
        transcript_repo=transcript_repo,
        token_counter=token_counter,
    )
    memory_backend = select_memory_backend(recall_memory, archival_memory)
    compactor = MemoryCompactor(
        archival=archival_memory,
        recall=recall_memory,
        llm_client=llm_client,
        http_client=http_client,
        openrouter_api_key=api_key,
        embedding_fn=embedding_fn,
        simulation_id=LIVE_SIMULATION_ID,
    )

    management = Management(
        redis_client=scoped_redis,
        llm_client=llm_client,
        event_bus=_module_event_bus,
    )

    # Inject config_version_repo into config_loader for DB-backed config
    config_loader._config_repo = config_version_repo

    shared_working_state = SharedWorkingState(scoped_redis)
    goal_repo = GoalRepo(db)
    goal_manager = AgentGoalManager(redis=scoped_redis, goal_repo=goal_repo)

    from core.repos.agent_state_repo import AgentStateRepo

    agent_state_repo = AgentStateRepo(db)
    agent_state_manager = AgentStateManager(
        redis_client=scoped_redis,
        state_repo=agent_state_repo,
        simulation_id=LIVE_SIMULATION_ID,
    )

    economy_manager = AgentEconomyManager(db, simulation_id=LIVE_SIMULATION_ID)

    # Initialize economy accounts — exclude management and alpha (non-participant agents)
    economy_excluded = {"management", "alpha"}
    agent_ids = [agent_id for agent_id in all_agent_ids if agent_id not in economy_excluded]
    if agent_ids:
        try:
            await economy_manager.initialize_accounts(agent_ids)
        except Exception:
            logger.warning("Could not initialize economy accounts (table may not exist yet)")

    # Alliance system (#274)
    alliance_repo = AllianceRepo(db)
    alliance_manager = AllianceManager(
        alliance_repo=alliance_repo,
        economy_manager=economy_manager,
        simulation_id=LIVE_SIMULATION_ID,
    )

    # Character spawning (#275)
    character_spawner = CharacterSpawner(
        llm_client=llm_client,
        agent_registry=agent_registry,
        db=db,
        economy_manager=economy_manager,
    )
    voting_manager = VotingManager(
        db=db,
        event_bus=_module_event_bus,
    )
    departure_manager = DepartureManager(
        db=db,
        agent_state_manager=agent_state_manager,
        agent_registry=agent_registry,
        llm_client=llm_client,
        event_bus=_module_event_bus,
    )

    # Dream system (#272)
    dream_manager = DreamManager(
        memory_repo=memory_repo,
        llm_client=llm_client,
        core_memory_mgr=core_memory,
        goal_manager=goal_manager,
        agent_state_manager=agent_state_manager,
        agent_registry=agent_registry,
        token_counter=token_counter,
        embedding_fn=embedding_fn,
        simulation_id=LIVE_SIMULATION_ID,
    )

    # Event/novelty injection (#273)
    event_generator = EventGenerator(
        world_repo=world_repo,
        event_bus=_module_event_bus,
        agent_state_manager=agent_state_manager,
        simulation_id=LIVE_SIMULATION_ID,
    )

    context_assembler = ContextAssembler(
        agent_registry=agent_registry,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        token_counter=token_counter,
        redis_client=scoped_redis,
    )

    return Services(
        db=db,
        redis=redis_client,
        scoped_redis=scoped_redis,
        http_client=http_client,
        agent_registry=agent_registry,
        llm_client=llm_client,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        memory_backend=memory_backend,
        compactor=compactor,
        context_assembler=context_assembler,
        token_counter=token_counter,
        memory_repo=memory_repo,
        transcript_repo=transcript_repo,
        event_bus=_module_event_bus,
        management=management,
        cost_repo=cost_repo,
        cost_governor=cost_governor,
        artifact_repo=artifact_repo,
        world_repo=world_repo,
        relationship_repo=relationship_repo,
        shared_working_state=shared_working_state,
        goal_manager=goal_manager,
        agent_state_manager=agent_state_manager,
        economy_manager=economy_manager,
        alliance_manager=alliance_manager,
        character_spawner=character_spawner,
        voting_manager=voting_manager,
        departure_manager=departure_manager,
        dream_manager=dream_manager,
        event_generator=event_generator,
        config_loader=config_loader,
        config_version_repo=config_version_repo,
    )


async def _bootstrap_dry_run(
    token_counter: TokenCounter,
    config_loader: ConfigLoader,
) -> Services:
    """Lightweight bootstrap for --dry-run: no DB/Redis needed."""
    agent_registry = AgentRegistry(redis_client=None)
    await agent_registry.load_all()

    class _StubCoreMemory:
        async def get_core_memory(self, agent_id: str, **kwargs: object) -> None:
            return None

    class _StubRecallMemory:
        async def retrieve_recall_memories(
            self,
            agent_id: str,
            query: str,
            limit: int = 3,
            **kwargs: object,
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
        scoped_redis=None,
        http_client=None,
        agent_registry=agent_registry,
        llm_client=None,
        core_memory=None,
        recall_memory=None,
        archival_memory=None,
        memory_backend=None,
        compactor=None,
        context_assembler=context_assembler,
        token_counter=token_counter,
        memory_repo=None,
        transcript_repo=None,
        event_bus=EventBus(),
        management=None,
        cost_repo=None,
        cost_governor=None,
        artifact_repo=None,
        world_repo=None,
        relationship_repo=None,
        shared_working_state=None,
        goal_manager=None,
        agent_state_manager=AgentStateManager(),
        economy_manager=None,
        alliance_manager=None,
        character_spawner=None,
        voting_manager=None,
        departure_manager=None,
        dream_manager=None,
        event_generator=None,
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
    simulation_id: uuid.UUID | None = None,
) -> list[str]:
    """Ensure all agents have core memory initialized.

    Returns list of agent IDs that were newly initialized.
    """
    initialized: list[str] = []
    for agent in agent_registry.get_all_agents():
        existing = await core_memory.get_core_memory(agent.id, simulation_id=simulation_id)
        if existing is None:
            identity = (
                f"I am {agent.display_name}. My conversation model is {agent.model_conversation}."
            )
            await core_memory.initialize_agent_memory(
                agent.id,
                identity,
                simulation_id=simulation_id,
            )
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
