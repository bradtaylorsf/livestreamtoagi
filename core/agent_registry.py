"""Agent configuration loader and in-memory registry.

Loads agent configs from YAML files under agents/{id}/ and provides
typed access via AgentConfig models. Agent status is cached in Redis
for cross-process sharing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.llm_client import MODEL_REGISTRY
from core.models import AgentConfig, AgentStatus

if TYPE_CHECKING:
    from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

VALID_MODEL_NAMES = set(MODEL_REGISTRY.keys())
REDIS_STATUS_PREFIX = "agent:status:"


class AgentRegistry:
    """Loads and manages agent configurations with Redis-backed status."""

    def __init__(
        self,
        redis_client: RedisClient | None = None,
        agents_dir: str | Path = "agents",
    ) -> None:
        self._redis = redis_client
        self._agents_dir = Path(agents_dir)
        self._agents: dict[str, AgentConfig] = {}

    async def load_all(self) -> None:
        """Read YAML + md from disk, validate, and populate the registry."""
        new_agents: dict[str, AgentConfig] = {}

        if not self._agents_dir.is_dir():
            logger.warning("Agents directory not found: %s", self._agents_dir)
            self._agents = new_agents
            return

        for agent_dir in sorted(self._agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue

            config_path = agent_dir / "config.yaml"
            if not config_path.exists():
                logger.warning("Missing config.yaml in %s, skipping", agent_dir.name)
                continue

            try:
                config = self._load_agent(agent_dir)
            except Exception:
                logger.exception("Failed to load agent from %s", agent_dir.name)
                continue

            if config.id in new_agents:
                raise ValueError(f"Duplicate agent ID: {config.id}")

            new_agents[config.id] = config

        # Atomic swap
        self._agents = new_agents
        logger.info("Loaded %d agents: %s", len(self._agents), list(self._agents.keys()))

        # Sync statuses from Redis (best-effort)
        await self._sync_statuses_from_redis()

    def _load_agent(self, agent_dir: Path) -> AgentConfig:
        """Load and validate a single agent from its directory."""
        config_path = agent_dir / "config.yaml"
        with open(config_path) as f:
            raw: dict[str, Any] = yaml.safe_load(f)

        # Validate model names
        for field in ("model_conversation", "model_building"):
            model_name = raw.get(field, "")
            if model_name not in VALID_MODEL_NAMES:
                raise ValueError(
                    f"Agent '{raw.get('id', agent_dir.name)}' has invalid {field}: "
                    f"'{model_name}'. Valid models: {sorted(VALID_MODEL_NAMES)}"
                )

        # Load system prompt
        prompt_path = agent_dir / "system_prompt.md"
        system_prompt = ""
        if prompt_path.exists():
            system_prompt = prompt_path.read_text()

        # Load behaviors
        behaviors_path = agent_dir / "behaviors.yaml"
        behaviors: dict[str, Any] = {}
        if behaviors_path.exists():
            with open(behaviors_path) as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    behaviors = loaded

        # Handle YAML null for voice_id
        if raw.get("voice_id") is None:
            raw["voice_id"] = None

        raw["system_prompt"] = system_prompt
        raw["behaviors"] = behaviors

        return AgentConfig(**raw)

    def get_agent(self, agent_id: str) -> AgentConfig | None:
        """Return an agent config by ID, or None if not found."""
        return self._agents.get(agent_id)

    def get_all_agents(self) -> list[AgentConfig]:
        """Return all loaded agent configs."""
        return list(self._agents.values())

    def get_active_agents(self) -> list[AgentConfig]:
        """Return agents with status == active."""
        return [a for a in self._agents.values() if a.status == AgentStatus.active]

    async def set_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status in-memory and in Redis."""
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent not found: {agent_id}")

        agent.status = status

        if self._redis is not None:
            try:
                await self._redis.set(f"{REDIS_STATUS_PREFIX}{agent_id}", status.value)
            except Exception:
                logger.warning("Failed to write status to Redis for %s", agent_id)

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Read status from Redis, falling back to in-memory."""
        # Try Redis first
        if self._redis is not None:
            try:
                value = await self._redis.get(f"{REDIS_STATUS_PREFIX}{agent_id}")
                if value is not None:
                    return AgentStatus(value)
            except Exception:
                logger.warning("Failed to read status from Redis for %s", agent_id)

        # Fall back to in-memory
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent not found: {agent_id}")
        return agent.status

    async def reload(self) -> None:
        """Hot-reload configs from disk (atomic swap)."""
        await self.load_all()

    async def _sync_statuses_from_redis(self) -> None:
        """On startup, sync in-memory status from Redis if available."""
        if self._redis is None:
            return
        for agent_id, agent in self._agents.items():
            try:
                value = await self._redis.get(f"{REDIS_STATUS_PREFIX}{agent_id}")
                if value is not None:
                    agent.status = AgentStatus(value)
            except Exception:
                logger.warning("Failed to sync Redis status for %s", agent_id)
