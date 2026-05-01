"""Agent configuration loader and in-memory registry.

Loads agent configs from the database (versioned config tables) with
fallback to YAML files under agents/{id}/. Agent status is cached in
Redis for cross-process sharing.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.constants import LIVE_SIMULATION_ID
from core.llm_client import MODEL_REGISTRY
from core.models import AgentConfig, AgentStatus

if TYPE_CHECKING:
    from core.redis_client import RedisClient
    from core.redis_keys import ScopedRedis
    from core.repos.config_version_repo import ConfigVersionRepo

logger = logging.getLogger(__name__)

VALID_MODEL_NAMES = set(MODEL_REGISTRY.keys())
MODEL_NAME_ALIASES = {
    "anthropic/claude-haiku-4.5": "claude-haiku-4-5",
    "anthropic/claude-sonnet-4.6": "claude-sonnet-4-6",
    "google/gemini-flash": "gemini-flash",
    "google/gemini-2.5-pro": "gemini-2.5-pro",
    "openai/gpt-4o-mini": "gpt-4o-mini",
    "openai/gpt-5.2": "gpt-5.2",
    "deepseek/deepseek-v3.2": "deepseek-v3.2",
    "x-ai/grok-3-mini": "grok-3-mini",
    "x-ai/grok-3": "grok-3",
}
REDIS_STATUS_PREFIX = "agent:status:"


class AgentRegistry:
    """Loads and manages agent configurations with Redis-backed status."""

    def __init__(
        self,
        redis_client: RedisClient | ScopedRedis | None = None,
        agents_dir: str | Path = "agents",
        config_version_repo: ConfigVersionRepo | None = None,
        simulation_id: _uuid.UUID | None = None,
    ) -> None:
        self._redis = redis_client
        self._agents_dir = Path(agents_dir)
        self._agents: dict[str, AgentConfig] = {}
        self._config_repo = config_version_repo
        self._simulation_id = simulation_id if simulation_id is not None else LIVE_SIMULATION_ID

    async def load_all(self) -> None:
        """Load agent configs from DB (if available), falling back to YAML."""
        new_agents: dict[str, AgentConfig] = {}

        # Try loading from DB first
        if self._config_repo is not None:
            db_agents = await self._load_from_db()
            if db_agents:
                new_agents = db_agents

        # Fall back to or supplement with YAML for agents not in DB
        yaml_agents = self._load_all_from_yaml()
        for agent_id, config in yaml_agents.items():
            if agent_id not in new_agents:
                new_agents[agent_id] = config

        # Atomic swap
        self._agents = new_agents
        logger.info("Loaded %d agents: %s", len(self._agents), list(self._agents.keys()))

        # Sync statuses from Redis (best-effort)
        await self._sync_statuses_from_redis()

    async def _load_from_db(self) -> dict[str, AgentConfig]:
        """Load all agents from versioned DB config."""
        assert self._config_repo is not None
        agents: dict[str, AgentConfig] = {}

        try:
            active_configs = await self._config_repo.get_all_active_configs(
                simulation_id=self._simulation_id
            )
        except Exception:
            logger.warning("Failed to load active configs from DB, will fall back to YAML")
            return agents

        for ac in active_configs:
            try:
                prompt_ver = await self._config_repo.get_prompt_version(
                    ac.agent_id,
                    ac.prompt_version,
                    simulation_id=self._simulation_id,
                )
                if prompt_ver is None:
                    continue

                params = prompt_ver.config_params
                agents[ac.agent_id] = AgentConfig(
                    id=ac.agent_id,
                    display_name=params.get("display_name", ac.agent_id),
                    role=params.get("role", ""),
                    model_conversation=params.get("model_conversation", "claude-haiku-4-5"),
                    model_building=params.get("model_building", "claude-sonnet-4-6"),
                    voice_id=params.get("voice_id"),
                    color_hex=params.get("color_hex", "#888888"),
                    color_rich=params.get("color_rich", "white"),
                    audio_effects=params.get("audio_effects"),
                    chattiness=float(params.get("chattiness", 0.5)),
                    initiative=float(params.get("initiative", 0.5)),
                    interrupt_tendency=float(params.get("interrupt_tendency", 0.0)),
                    eavesdrop_tendency=float(params.get("eavesdrop_tendency", 0.0)),
                    closing_weight=float(params.get("closing_weight", 0.0)),
                    role_priority_bonus=float(params.get("role_priority_bonus", 0.0)),
                    cross_agent_writer=bool(params.get("cross_agent_writer", False)),
                    tools=params.get("tools", []),
                    topic_relevance=params.get("topic_relevance", {}),
                    adjacency=params.get("adjacency", {}),
                    system_prompt=prompt_ver.system_prompt,
                    behaviors=prompt_ver.behaviors,
                )
            except Exception:
                logger.exception("Failed to load agent %s from DB", ac.agent_id)

        return agents

    def _load_all_from_yaml(self) -> dict[str, AgentConfig]:
        """Load all agents from YAML files on disk."""
        agents: dict[str, AgentConfig] = {}

        if not self._agents_dir.is_dir():
            logger.warning("Agents directory not found: %s", self._agents_dir)
            return agents

        for agent_dir in sorted(self._agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            if agent_dir.name == "template":
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
            if config.id in agents:
                raise ValueError(f"Duplicate agent ID: {config.id}")
            agents[config.id] = config

        self._validate_agents(agents)
        return agents

    def _validate_agents(self, agents: dict[str, AgentConfig]) -> None:
        """Startup validation: warn about misconfigured agents."""
        agent_ids = set(agents.keys())
        for agent_id, config in agents.items():
            # Warn if adjacency references unknown agents
            for adj_id in config.adjacency:
                if adj_id not in agent_ids:
                    logger.warning(
                        "Agent %s adjacency references unknown agent %s",
                        agent_id,
                        adj_id,
                    )
        tool_counts = {aid: len(cfg.tools) for aid, cfg in agents.items()}
        logger.info(
            "Agent roster: %s (tool counts: %s)",
            sorted(agent_ids),
            tool_counts,
        )

    async def reload_agent(self, agent_id: str) -> None:
        """Hot-swap a single agent's config from DB after eval loop writes a new version."""
        if self._config_repo is None:
            logger.warning("No config repo available, cannot reload agent %s from DB", agent_id)
            return

        try:
            ac = await self._config_repo.get_active_config(
                agent_id, simulation_id=self._simulation_id
            )
            if ac is None:
                return

            prompt_ver = await self._config_repo.get_prompt_version(
                agent_id,
                ac.prompt_version,
                simulation_id=self._simulation_id,
            )
            if prompt_ver is None:
                return

            params = prompt_ver.config_params
            new_config = AgentConfig(
                id=agent_id,
                display_name=params.get("display_name", agent_id),
                role=params.get("role", ""),
                model_conversation=params.get("model_conversation", "claude-haiku-4-5"),
                model_building=params.get("model_building", "claude-sonnet-4-6"),
                voice_id=params.get("voice_id"),
                color_hex=params.get("color_hex", "#888888"),
                color_rich=params.get("color_rich", "white"),
                audio_effects=params.get("audio_effects"),
                chattiness=float(params.get("chattiness", 0.5)),
                initiative=float(params.get("initiative", 0.5)),
                interrupt_tendency=float(params.get("interrupt_tendency", 0.0)),
                eavesdrop_tendency=float(params.get("eavesdrop_tendency", 0.0)),
                closing_weight=float(params.get("closing_weight", 0.0)),
                role_priority_bonus=float(params.get("role_priority_bonus", 0.0)),
                cross_agent_writer=bool(params.get("cross_agent_writer", False)),
                tools=params.get("tools", []),
                topic_relevance=params.get("topic_relevance", {}),
                adjacency=params.get("adjacency", {}),
                system_prompt=prompt_ver.system_prompt,
                behaviors=prompt_ver.behaviors,
            )

            # Preserve current status
            old = self._agents.get(agent_id)
            if old is not None:
                new_config = new_config.model_copy(update={"status": old.status})

            self._agents[agent_id] = new_config
            logger.info("Hot-swapped agent %s to prompt v%d", agent_id, ac.prompt_version)
        except Exception:
            logger.exception("Failed to reload agent %s from DB", agent_id)

    # Files that are loaded into dedicated config fields (not merged into behaviors)
    _RESERVED_FILES = {"config.yaml", "behaviors.yaml", "system_prompt.md"}

    def _load_agent(self, agent_dir: Path) -> AgentConfig:
        """Load and validate a single agent from its directory."""
        config_path = agent_dir / "config.yaml"
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # Validate raw YAML structure
        if not isinstance(raw, dict):
            raise ValueError(
                f"config.yaml in {agent_dir.name} must be a YAML mapping, got {type(raw).__name__}"
            )
        required_keys = {"id", "display_name", "model_conversation", "model_building"}
        missing = required_keys - set(raw.keys())
        if missing:
            raise ValueError(
                f"config.yaml in {agent_dir.name} missing required keys: {sorted(missing)}"
            )

        # Validate model names
        for field in ("model_conversation", "model_building"):
            model_name = raw.get(field, "")
            canonical_model_name = MODEL_NAME_ALIASES.get(model_name, model_name)
            if canonical_model_name not in VALID_MODEL_NAMES:
                raise ValueError(
                    f"Agent '{raw.get('id', agent_dir.name)}' has invalid {field}: "
                    f"'{model_name}'. Valid models: {sorted(VALID_MODEL_NAMES)}"
                )

        # Load system prompt
        prompt_path = agent_dir / "system_prompt.md"
        system_prompt = ""
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")

        # Load behaviors
        behaviors_path = agent_dir / "behaviors.yaml"
        behaviors: dict[str, Any] = {}
        if behaviors_path.exists():
            with open(behaviors_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    behaviors = loaded

        # Load additional YAML files (e.g. content_rules.yaml, intervention_levels.yaml)
        # Only adds keys not already present in behaviors.yaml to avoid overwrites.
        for extra_path in sorted(agent_dir.glob("*.yaml")):
            if extra_path.name in self._RESERVED_FILES:
                continue
            key = extra_path.stem  # "content_rules.yaml" → "content_rules"
            if key in behaviors:
                continue  # behaviors.yaml already defines this key
            with open(extra_path, encoding="utf-8") as f:
                extra = yaml.safe_load(f)
            if isinstance(extra, dict):
                behaviors[key] = extra
            else:
                logger.warning(
                    "Extra YAML %s in %s is not a dict (got %s), skipping",
                    extra_path.name,
                    agent_dir.name,
                    type(extra).__name__,
                )

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

    # ── Derived lookups (replace hardcoded dicts) ────────────────

    def get_voice_map(self) -> dict[str, str]:
        """Build VOICE_MAP from agent configs (agent_id -> voice_id)."""
        return {a.id: a.voice_id for a in self._agents.values() if a.voice_id}

    def get_agent_roles(self) -> dict[str, str]:
        """Build AGENT_ROLES from agent configs (agent_id -> role)."""
        return {a.id: a.role for a in self._agents.values()}

    def get_agent_colors(self) -> dict[str, str]:
        """Build AGENT_COLORS hex map from agent configs."""
        return {a.id: a.color_hex for a in self._agents.values()}

    def get_rich_colors(self) -> dict[str, str]:
        """Build AGENT_COLORS rich-terminal map from agent configs."""
        return {a.id: a.color_rich for a in self._agents.values()}

    def get_role_bonuses(self) -> dict[str, float]:
        """Build role priority bonus map from agent configs."""
        return {
            a.id: a.role_priority_bonus for a in self._agents.values() if a.role_priority_bonus > 0
        }

    def get_cross_agent_writers(self) -> frozenset[str]:
        """Build set of agents allowed to write other agents' core memory."""
        return frozenset(a.id for a in self._agents.values() if a.cross_agent_writer)

    def get_allowed_agents_for_tool(self, tool_name: str) -> frozenset[str]:
        """Build ALLOWED_AGENTS set for a given tool name."""
        return frozenset(a.id for a in self._agents.values() if tool_name in a.tools)

    def get_conversation_participants(self) -> list[AgentConfig]:
        """Return agents that participate in conversations (non-zero chattiness or initiative)."""
        return [a for a in self._agents.values() if a.chattiness > 0 or a.initiative > 0]

    def build_closer_weights(self) -> dict[str, float]:
        """Build closer_weights dict from agent configs."""
        return {a.id: a.closing_weight for a in self._agents.values() if a.closing_weight > 0}

    def build_interrupt_tendency(self) -> dict[str, float]:
        """Build agent_interrupt_tendency dict from agent configs."""
        return {a.id: a.interrupt_tendency for a in self._agents.values()}

    def build_eavesdrop_tendency(self) -> dict[str, float]:
        """Build eavesdrop_tendency dict from agent configs."""
        return {
            a.id: a.eavesdrop_tendency for a in self._agents.values() if a.eavesdrop_tendency > 0
        }

    def build_initiative(self) -> dict[str, float]:
        """Build agent_initiative dict from agent configs."""
        return {a.id: a.initiative for a in self._agents.values() if a.initiative > 0}

    def build_relevance_map(self) -> dict[str, dict[str, float]]:
        """Build topic relevance_map from agent configs."""
        result: dict[str, dict[str, float]] = {}
        for agent in self._agents.values():
            for topic, score in agent.topic_relevance.items():
                if topic not in result:
                    result[topic] = {}
                result[topic][agent.id] = score
        return result

    def build_adjacency(self) -> dict[str, dict[str, float]]:
        """Build adjacency map from agent configs."""
        return {a.id: dict(a.adjacency) for a in self._agents.values() if a.adjacency}

    async def set_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status in Redis (if available) then in-memory."""
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent not found: {agent_id}")

        # Write Redis first so persistent state leads in-memory
        if self._redis is not None:
            try:
                await self._redis.set(f"{REDIS_STATUS_PREFIX}{agent_id}", status.value)
            except Exception:
                logger.warning("Failed to write status to Redis for %s", agent_id)

        self._agents[agent_id] = agent.model_copy(update={"status": status})

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Read status from Redis, falling back to in-memory."""
        # Try Redis first
        if self._redis is not None:
            try:
                value = await self._redis.get(f"{REDIS_STATUS_PREFIX}{agent_id}")
                if value is not None:
                    try:
                        return AgentStatus(value)
                    except ValueError:
                        logger.warning("Invalid status value in Redis for %s: %r", agent_id, value)
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
        for agent_id in list(self._agents):
            try:
                value = await self._redis.get(f"{REDIS_STATUS_PREFIX}{agent_id}")
                if value is not None:
                    try:
                        status = AgentStatus(value)
                        agent = self._agents[agent_id]
                        self._agents[agent_id] = agent.model_copy(update={"status": status})
                    except ValueError:
                        logger.warning("Invalid status in Redis for %s: %r", agent_id, value)
            except Exception:
                logger.warning("Failed to sync Redis status for %s", agent_id)
