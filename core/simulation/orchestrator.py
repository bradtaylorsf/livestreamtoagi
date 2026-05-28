"""SimulationOrchestrator — drives simulations in seeded or autonomous mode.

Seeded mode: loops through phases from a YAML seed file.
Autonomous mode: trigger system drives conversations continuously until
duration/cost/kill-switch limits are reached.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.event_bus import EventType
from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY, OpenRouterClient
from core.memory.reflection_scheduler import ReflectionScheduler
from core.model_config import resolve_internal_model
from core.models import (
    ExperimentalGoalConfig,
    FactionConfig,
    ManagementPolicy,
    MemorySeedConfig,
    PersonaOverride,
    RunMode,
    SimulationCreate,
    SimulationStatus,
    WorldConfig,
    resolve_management_policy,
)
from core.simulation.clock import SimulationClock
from core.simulation.embodiment import EmbodimentExecutor, select_executor
from core.simulation.phases import Phase, PhaseRunner, PhaseType

if TYPE_CHECKING:
    import uuid

    from core.agent_registry import AgentRegistry
    from core.bootstrap import Services
    from core.config_loader import ConfigLoader
    from core.context_assembly import ContextAssembler
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.database import Database
    from core.event_bus import EventBus
    from core.management import Management
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.compaction import MemoryCompactor
    from core.memory.reflection import ReflectionManager
    from core.redis_client import RedisClient
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.memory_repo import MemoryRepo
    from core.repos.relationship_repo import RelationshipRepo
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.display import SimulationDisplay

logger = logging.getLogger(__name__)


class CostLimitExceededError(Exception):
    """Raised when simulation spending exceeds a configured cost limit."""


def _normalize_agent_goals(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    """Return a stable agent_id -> goal text list mapping."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("agent_goals must be a mapping of agent_id to list of goals")

    normalized: dict[str, list[str]] = {}
    for agent_id, goals in raw.items():
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_goals keys must be non-empty agent ids")
        if isinstance(goals, str):
            normalized[agent_id] = [goals]
            continue
        if not isinstance(goals, list):
            raise ValueError(f"agent_goals for {agent_id!r} must be a list of strings")
        normalized[agent_id] = [str(goal) for goal in goals]
    return normalized


def parse_duration(value: str) -> timedelta:
    """Parse a human-readable duration string into a timedelta.

    Supported formats: '7d', '1d', '12h', '3d12h', '90m'.
    """
    pattern = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?")
    match = pattern.fullmatch(value.strip())
    if not match or not any(match.groups()):
        raise ValueError(
            f"Invalid duration '{value}'. Use format like '7d', '12h', '1d12h', '90m'."
        )
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    return timedelta(days=days, hours=hours, minutes=minutes)


def parse_experimental_goal(value: str) -> ExperimentalGoalConfig:
    """Parse an experimental goal string such as 'turns:20' or 'artifacts=2'."""
    raw = value.strip()
    separator = ":" if ":" in raw else "=" if "=" in raw else None
    if separator is None:
        raise ValueError("Invalid experimental goal. Use '<kind>:<target>', e.g. 'turns:20'.")
    kind, target = (part.strip() for part in raw.split(separator, 1))
    if not kind or not target:
        raise ValueError("Invalid experimental goal. Use '<kind>:<target>', e.g. 'turns:20'.")
    try:
        parsed_target = int(target)
    except ValueError as exc:
        raise ValueError("experimental goal target must be an integer") from exc
    return ExperimentalGoalConfig(kind=kind, target=parsed_target)


class SimulationConfig:
    """Parsed CLI arguments and seed file contents."""

    def __init__(
        self,
        *,
        name: str,
        description: str | None = None,
        seed_file: str | None = None,
        agents: list[str],
        max_cost: float = 10.0,
        max_cost_rolling: float | Decimal | None = None,
        rolling_window: timedelta | str | None = None,
        speed: str = "fast",
        speed_multiplier: float = 0,
        duration: timedelta | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        management_shadow: bool | None = None,
        management_policy: str | ManagementPolicy | None = None,
        debug_prompts: bool = False,
        existing_sim_id: str | None = None,
        hypothesis: str | None = None,
        auto_draft_learnings: bool = False,
        memory_seed: MemorySeedConfig | None = None,
        scenario_id: str | None = None,
        scenario_meta: dict[str, Any] | None = None,
        scenario_agents: list[str] | None = None,
        excluded_agents: list[str] | None = None,
        factions: list[dict[str, Any] | FactionConfig] | None = None,
        persona_overrides: list[dict[str, Any] | PersonaOverride] | None = None,
        agent_goals: dict[str, list[str]] | None = None,
        world_config: dict[str, Any] | WorldConfig | None = None,
        run_mode: str | RunMode | None = None,
        experimental_goal: dict[str, Any] | ExperimentalGoalConfig | None = None,
        initial_agent_energy: dict[str, float] | None = None,
        conversation_cadence: float = 1.0,
        conversation_mode: str = "director",
        submitted_params: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.seed_file = seed_file
        self.agents = agents
        self.max_cost = Decimal(str(max_cost))
        self.max_cost_rolling = (
            Decimal(str(max_cost_rolling)) if max_cost_rolling is not None else None
        )
        if self.max_cost_rolling is not None and self.max_cost_rolling < 0:
            raise ValueError("max_cost_rolling cannot be negative")
        self.rolling_window = (
            parse_duration(rolling_window) if isinstance(rolling_window, str) else rolling_window
        )
        if (self.max_cost_rolling is None) != (self.rolling_window is None):
            raise ValueError("max_cost_rolling and rolling_window must be set together")
        if self.rolling_window is not None and self.rolling_window.total_seconds() <= 0:
            raise ValueError("rolling_window must be greater than zero")
        self.speed = speed
        self.speed_multiplier = speed_multiplier
        self.duration = duration
        self.dry_run = dry_run
        self.verbose = verbose
        self._management_policy_override = management_policy is not None
        self.debug_prompts = debug_prompts
        self.world_sim: bool = False
        self.phases: list[Phase] = []
        self.audience_config: dict[str, Any] | None = None
        self.seed_tasks: bool = False
        self.seed_goals: bool = False
        self.factions: list[FactionConfig] = [
            f if isinstance(f, FactionConfig) else FactionConfig(**f) for f in (factions or [])
        ]
        self._factions_override = factions is not None
        self.persona_overrides: list[PersonaOverride] = [
            p if isinstance(p, PersonaOverride) else PersonaOverride(**p)
            for p in (persona_overrides or [])
        ]
        self._persona_overrides_override = persona_overrides is not None
        self.agent_goals = _normalize_agent_goals(agent_goals)
        self._agent_goals_override = agent_goals is not None
        self.world_config = (
            world_config
            if isinstance(world_config, WorldConfig)
            else WorldConfig(**world_config)
            if world_config is not None
            else None
        )
        self.world_provisioned: dict[str, Any] | None = None
        self._world_config_override = world_config is not None
        self.run_mode: RunMode | None = (
            RunMode(run_mode)
            if run_mode is not None
            else RunMode.experimental
            if seed_file or experimental_goal is not None
            else None
        )
        self._run_mode_explicit = run_mode is not None
        if management_policy is None and management_shadow is not None:
            management_policy = (
                ManagementPolicy.shadow if management_shadow else ManagementPolicy.enforce
            )
            self._management_policy_override = True
        self.management_policy = resolve_management_policy(management_policy, self.run_mode)
        self.management_shadow = self.management_policy == ManagementPolicy.shadow
        self.experimental_goal = (
            experimental_goal
            if isinstance(experimental_goal, ExperimentalGoalConfig)
            else ExperimentalGoalConfig(**experimental_goal)
            if experimental_goal is not None
            else None
        )
        self._experimental_goal_override = experimental_goal is not None
        self._validate_run_mode_constraints()
        # When provided, the orchestrator attaches to a pre-created
        # simulation row instead of inserting a new one. Used when the
        # admin dashboard pre-creates the row so it can immediately return
        # the simulation_id to the client for redirect.
        self.existing_sim_id = existing_sim_id
        self.hypothesis = hypothesis
        self.auto_draft_learnings = auto_draft_learnings
        self.memory_seed: MemorySeedConfig | None = memory_seed
        self.scenario_id = scenario_id
        self.scenario_meta = scenario_meta or None
        self.scenario_agents = list(scenario_agents or [])
        self.excluded_agents = list(excluded_agents or [])
        self.initial_agent_energy = dict(initial_agent_energy or {})
        self.conversation_cadence = max(0.1, float(conversation_cadence or 1.0))
        normalized_conversation_mode = conversation_mode.strip().lower()
        if normalized_conversation_mode not in {"director", "embodied", "director_v2"}:
            raise ValueError("conversation_mode must be one of: director, embodied, director_v2")
        self.conversation_mode = normalized_conversation_mode
        self.submitted_params = dict(submitted_params or {})
        self.source = source
        # ``eval_targets`` is populated when a scenario YAML declares one.
        # The dashboard (E22-10) and headless eval scorer (E22-9) read it
        # to filter scenarios and apply category-specific rubrics.
        self.eval_targets: dict[str, Any] | None = None
        # ``world_events`` block (E22-4) parsed from the scenario YAML. The
        # orchestrator builds a WorldEventScheduler + NeedsManager from
        # this block at runtime.
        self.world_events: dict[str, Any] | None = None

    @property
    def mode(self) -> str:
        """Return 'seeded' if a seed file is set, otherwise 'autonomous'."""
        if self.run_mode == RunMode.persistent:
            return "autonomous"
        return "seeded" if self.seed_file else "autonomous"

    def _validate_run_mode_constraints(self) -> None:
        """Apply run-mode invariants after CLI and seed-file fields merge."""
        if self.run_mode == RunMode.persistent:
            if self.duration is not None:
                raise ValueError("persistent mode is indefinite; do not set duration")
            if self.experimental_goal is not None:
                raise ValueError("persistent mode is indefinite; do not set experimental_goal")
            if self.max_cost_rolling is None or self.rolling_window is None:
                raise ValueError(
                    "persistent mode requires max_cost_rolling and rolling_window "
                    "so it is bounded by a rolling cap"
                )
            if self.world_config is None:
                self.world_config = WorldConfig(persistent=True)
            else:
                self.world_config.persistent = True
            return

        if self.run_mode == RunMode.headless:
            if self.seed_file is None and self.duration is None and self.experimental_goal is None:
                raise ValueError(
                    "headless mode requires a seed_file, duration, or experimental_goal"
                )
            if self.world_config is not None and self.world_config.durable_world_id:
                raise ValueError("headless mode cannot use durable_world_id")
            if self.world_config is not None:
                self.world_config.persistent = False
            return

        if self.run_mode != RunMode.experimental:
            return

        if self.seed_file is None and self.duration is None and self.experimental_goal is None:
            raise ValueError(
                "experimental mode requires a seed_file, duration, or experimental_goal"
            )
        if self.world_config is not None:
            if self.world_config.durable_world_id:
                raise ValueError("experimental mode cannot use durable_world_id")
            self.world_config.persistent = False

    def load_seed_file(self, valid_agent_ids: set[str] | None = None) -> None:
        """Parse the YAML seed file into Phase objects.

        ``valid_agent_ids`` is used to validate faction membership when
        provided; if None, faction membership is parsed but not checked.
        """
        if not self.seed_file:
            return

        with open(self.seed_file) as f:
            data = yaml.safe_load(f)

        # Validate the YAML against the canonical scenario schema (E22-3).
        # Pydantic raises ValidationError with field-level messages on bad
        # input — propagate as-is so authors see exactly what's wrong.
        from core.simulation.scenario_schema import validate_scenario_dict

        parsed_scenario = validate_scenario_dict(data)
        if parsed_scenario.eval_targets is not None:
            self.eval_targets = parsed_scenario.eval_targets.model_dump()
        if parsed_scenario.world_events is not None:
            self.world_events = parsed_scenario.world_events.model_dump()

        self.audience_config = data.get("audience")
        self.seed_tasks = bool(data.get("seed_tasks", False))
        self.seed_goals = bool(data.get("seed_goals", False))

        # Parse memory_seed block if present (CLI overrides take precedence,
        # so only fill from YAML when the field is unset).
        raw_seed = data.get("memory_seed")
        if raw_seed and self.memory_seed is None:
            self.memory_seed = MemorySeedConfig(**raw_seed)

        raw_persona_overrides = data.get("persona_overrides")
        if raw_persona_overrides is not None and not self._persona_overrides_override:
            if not isinstance(raw_persona_overrides, list):
                raise ValueError("persona_overrides must be a list")
            self.persona_overrides = [
                entry if isinstance(entry, PersonaOverride) else PersonaOverride(**entry)
                for entry in raw_persona_overrides
            ]

        raw_agent_goals = data.get("agent_goals")
        if raw_agent_goals is not None and not self._agent_goals_override:
            self.agent_goals = _normalize_agent_goals(raw_agent_goals)

        raw_world = data.get("world")
        if raw_world is not None and not self._world_config_override:
            if not isinstance(raw_world, dict):
                raise ValueError("world must be a mapping")
            self.world_config = WorldConfig(**raw_world)

        raw_run_mode = data.get("run_mode")
        if raw_run_mode is not None and not self._run_mode_explicit:
            self.run_mode = RunMode(raw_run_mode)
            self._run_mode_explicit = True

        raw_management_policy = data.get("management_policy")
        if raw_management_policy is not None and not self._management_policy_override:
            self.management_policy = ManagementPolicy(raw_management_policy)
            self._management_policy_override = True
        elif not self._management_policy_override:
            self.management_policy = resolve_management_policy(None, self.run_mode)
        self.management_shadow = self.management_policy == ManagementPolicy.shadow

        raw_experimental_goal = data.get("experimental_goal")
        if raw_experimental_goal is not None and not self._experimental_goal_override:
            if not isinstance(raw_experimental_goal, dict):
                raise ValueError("experimental_goal must be a mapping")
            self.experimental_goal = ExperimentalGoalConfig(**raw_experimental_goal)

        self._validate_run_mode_constraints()

        # Parse factions if present. Public submissions pass an explicit
        # normalized list, which intentionally overrides the scenario YAML.
        raw_factions = (
            [f.model_dump() for f in self.factions]
            if self._factions_override
            else data.get("factions") or []
        )
        seen_names: set[str] = set()
        self.factions = []
        for entry in raw_factions:
            faction = FactionConfig(**entry)
            if faction.name in seen_names:
                raise ValueError(f"duplicate faction name: {faction.name}")
            seen_names.add(faction.name)
            if valid_agent_ids is not None:
                unknown = [m for m in faction.members if m not in valid_agent_ids]
                if unknown:
                    raise ValueError(f"faction '{faction.name}' has unknown members: {unknown}")
            self.factions.append(faction)

        raw_phases = data.get("phases", [])
        for entry in raw_phases:
            # Phase type is validated by the scenario schema above, so this
            # PhaseType(...) call always succeeds.
            ptype = PhaseType(entry.get("type", "organic"))

            # Extract config: everything except name and type
            config = {k: v for k, v in entry.items() if k not in ("name", "type")}
            required = config.pop("required_agents", [])

            self.phases.append(
                Phase(
                    name=entry.get("name", f"phase_{len(self.phases)}"),
                    type=ptype,
                    config=config,
                    required_agents=required,
                )
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize config for DB snapshot."""
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "seed_file": self.seed_file,
            "agents": self.agents,
            "max_cost": str(self.max_cost),
            "speed": self.speed,
            "speed_multiplier": self.speed_multiplier,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "management_shadow": self.management_shadow,
            "world_sim": self.world_sim,
        }
        if self.management_policy is not None and (
            self._management_policy_override
            or self._run_mode_explicit
            or self.run_mode == RunMode.persistent
            or self.experimental_goal is not None
        ):
            d["management_policy"] = self.management_policy.value
        if self.duration is not None:
            d["duration_seconds"] = self.duration.total_seconds()
        if self.max_cost_rolling is not None:
            d["max_cost_rolling"] = str(self.max_cost_rolling)
        if self.rolling_window is not None:
            d["rolling_window_seconds"] = self.rolling_window.total_seconds()
        if self.phases:
            d["phase_count"] = len(self.phases)
            d["phase_names"] = [p.name for p in self.phases]
        if self.factions or self._factions_override or self.source == "public_submit":
            d["factions"] = [f.model_dump() for f in self.factions]
        if self.scenario_id:
            d["scenario_id"] = self.scenario_id
        if self.scenario_meta:
            d["scenario_meta"] = self.scenario_meta
        if self.scenario_agents:
            d["scenario_agents"] = self.scenario_agents
        if self.excluded_agents or self.source == "public_submit":
            d["excluded_agents"] = self.excluded_agents
        if self.agents:
            d["effective_agents"] = self.agents
        if self.initial_agent_energy:
            d["energy"] = self.initial_agent_energy
        if self.conversation_cadence != 1.0 or self.source == "public_submit":
            d["conversation_cadence"] = self.conversation_cadence
        if self.submitted_params:
            d["params"] = self.submitted_params
        if self.source:
            d["source"] = self.source
        if self.memory_seed is not None:
            d["memory_seed"] = self.memory_seed.model_dump(exclude_none=True)
        if self.persona_overrides:
            d["persona_overrides"] = [
                p.model_dump(exclude_none=True) for p in self.persona_overrides
            ]
        if self.agent_goals:
            d["agent_goals"] = self.agent_goals
        if self.world_config is not None:
            d["world"] = self.world_config.model_dump(exclude_none=True)
        if self.world_provisioned is not None:
            d["world_provisioned"] = self.world_provisioned
        if self.run_mode is not None and (
            self._run_mode_explicit
            or self.run_mode == RunMode.persistent
            or self.experimental_goal is not None
        ):
            d["run_mode"] = self.run_mode.value
        if self.experimental_goal is not None:
            d["experimental_goal"] = self.experimental_goal.model_dump()
        if self.eval_targets is not None:
            d["eval_targets"] = self.eval_targets
        if self.world_events is not None:
            d["world_events"] = self.world_events
        return d


class SimulationOrchestrator:
    """Drives a full-day simulation through sequential phases."""

    def __init__(
        self,
        *,
        config: SimulationConfig,
        db: Database,
        redis_client: RedisClient,
        simulation_repo: SimulationRepo,
        config_loader: ConfigLoader,
        agent_registry: AgentRegistry,
        event_bus: EventBus,
        llm_client: OpenRouterClient,
        management: Management,
        context_assembler: ContextAssembler,
        conversation_repo: ConversationRepo,
        archival_memory: ArchivalMemoryManager,
        proximity: ProximityManager,
        trigger_system: TriggerSystem,
        selection_logger: SelectionLogger,
        reflection_manager: ReflectionManager,
        compactor: MemoryCompactor | None = None,
        memory_repo: MemoryRepo | None = None,
        display: SimulationDisplay,
        services: Services | None = None,
        clock: SimulationClock | None = None,
        relationship_repo: RelationshipRepo | None = None,
        build_plan_compiler: Any | None = None,
        build_plan_resolver: Any | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._redis = redis_client
        self._sim_repo = simulation_repo
        self._config_loader = config_loader
        self._agents = agent_registry
        self._event_bus = event_bus
        self._llm = llm_client
        self._management = management
        self._context = context_assembler
        self._conversation_repo = conversation_repo
        self._archival = archival_memory
        self._compactor = compactor
        self._memory_repo = memory_repo
        self._proximity = proximity
        self._triggers = trigger_system
        self._selection_logger = selection_logger
        self._reflection = reflection_manager
        self._display = display
        self._services = services
        self._relationship_repo = relationship_repo

        # Instantiate prompt log repo when debug_prompts is enabled
        self._prompt_log_repo: object | None = None
        if self._config.debug_prompts:
            from core.repos.prompt_log_repo import PromptLogRepo

            self._prompt_log_repo = PromptLogRepo(db)
        self._simulation_id: uuid.UUID | None = None
        self._start_time: float = 0.0
        self._started_at: datetime | None = None
        self._total_cost = Decimal("0")
        self._cancelled = False
        self._errors: list[dict[str, Any]] = []
        self._last_persistent_heartbeat = 0.0
        self._experimental_stop_reason: str | None = None
        self._experimental_progress: dict[str, int] = {
            "phases_completed": 0,
            "turns": 0,
            "artifacts": 0,
        }
        self.clock = clock or SimulationClock(speed_multiplier=config.speed_multiplier)

        # Single switch point for embodiment behavior — everything else in the
        # orchestrator (and the conversation engine, dreams, relationships,
        # alliances, blackboard) is shared across modes.
        self._executor: EmbodimentExecutor = select_executor(
            self._config.run_mode,
            build_plan_compiler=build_plan_compiler,
            build_plan_resolver=build_plan_resolver,
        )
        self._decision_logger: Any | None = None
        # Per-sim ownership ledger (#891). Instantiated in ``run`` once the
        # sim_folder is known so tools can persist to
        # <sim>/ownership_log.jsonl and mirror events into the decision log.
        self._ownership_ledger: Any | None = None
        # Per-sim trade ledger (#892) — same pattern, persists to
        # <sim>/trade_log.jsonl via the trade tools.
        self._trade_ledger: Any | None = None
        # Event-bus callbacks the orchestrator registers to mirror live
        # events into the decision log (issue #859). Stored so _finalize can
        # unsubscribe cleanly.
        self._decision_log_callbacks: list[tuple[str, Any]] = []
        # World-event scheduler + needs manager (E22-4). Built lazily in
        # ``run``/``run_autonomous`` so tests that only construct the
        # orchestrator don't pay the import cost.
        self._world_event_scheduler: Any | None = None
        self._needs_manager: Any | None = None
        # Counter used to derive a monotonic "world tick" from phase
        # completions. The world-event scheduler operates on this counter
        # rather than wall-time so headless and embodied runs share the
        # same advancement semantics.
        self._world_tick: int = 0

    @property
    def simulation_id(self) -> uuid.UUID | None:
        return self._simulation_id

    def _attach_decision_logger_listeners(self) -> None:
        """Mirror AGENT_SPEAK / TOOL_EXECUTED events into the decision log.

        Without this, the headless scorer's LLM-judge categories (which read
        utterance excerpts) and the deterministic productivity/errors signals
        get an empty log on real runs because nothing else writes utterance
        or non-propose_build tool rows. propose_build still goes through the
        embodiment executor so we skip it here to avoid double-logging.
        """
        if self._decision_logger is None:
            return

        async def on_agent_speak(event: dict[str, Any]) -> None:
            data = event.get("data") or {}
            try:
                self._decision_logger.log_utterance(
                    actor_id=str(data.get("agent_id") or "unknown"),
                    text=str(data.get("content") or ""),
                    channel=str(data.get("channel") or "chat"),
                    model=data.get("model"),
                    runtime_model=data.get("runtime_model"),
                    tokens=data.get("tokens"),
                    cost=str(data["cost"]) if data.get("cost") is not None else None,
                )
            except Exception:  # pragma: no cover - logging must never break the sim
                logger.debug("decision_logger.log_utterance failed", exc_info=True)

        async def on_tool_executed(event: dict[str, Any]) -> None:
            data = event.get("data") or {}
            tool_name = str(data.get("tool_name") or data.get("tool") or "")
            # propose_build is already written via HeadlessExecutor /
            # EmbodiedExecutor execute_tool_intent — skip to avoid dupes.
            if not tool_name or tool_name == "propose_build":
                return
            try:
                self._decision_logger.log_tool_intent(
                    actor_id=str(data.get("agent_id") or "unknown"),
                    tool_name=tool_name,
                    args=data.get("args") or data.get("inputs") or {},
                    status=str(data.get("status") or "executed"),
                    block_reason=data.get("block_reason"),
                    outcome=data.get("result") or data.get("outcome"),
                )
            except Exception:  # pragma: no cover
                logger.debug("decision_logger.log_tool_intent failed", exc_info=True)

        async def on_management_intervention(event: dict[str, Any]) -> None:
            data = event.get("data") or {}
            try:
                self._decision_logger.log_utterance(
                    actor_id="management",
                    text=str(data.get("reason") or data.get("message") or ""),
                    channel="management",
                )
            except Exception:  # pragma: no cover
                logger.debug("decision_logger.log_utterance(management) failed", exc_info=True)

        self._event_bus.on(EventType.AGENT_SPEAK.value, on_agent_speak)
        self._decision_log_callbacks.append((EventType.AGENT_SPEAK.value, on_agent_speak))
        self._event_bus.on(EventType.TOOL_EXECUTED.value, on_tool_executed)
        self._decision_log_callbacks.append((EventType.TOOL_EXECUTED.value, on_tool_executed))
        # BaseTool.run emits ARTIFACT_CREATED (not TOOL_EXECUTED) when any tool
        # invocation completes. Mirror it into the decision log so the headless
        # classifier's tool_intent count reflects real tool activity.
        self._event_bus.on(EventType.ARTIFACT_CREATED.value, on_tool_executed)
        self._decision_log_callbacks.append((EventType.ARTIFACT_CREATED.value, on_tool_executed))
        self._event_bus.on(EventType.MANAGEMENT_INTERVENTION.value, on_management_intervention)
        self._decision_log_callbacks.append(
            (EventType.MANAGEMENT_INTERVENTION.value, on_management_intervention)
        )

    def _detach_decision_logger_listeners(self) -> None:
        for event_type, cb in self._decision_log_callbacks:
            try:
                self._event_bus.off(event_type, cb)
            except Exception:  # pragma: no cover
                logger.debug("decision_logger callback unsubscribe failed", exc_info=True)
        self._decision_log_callbacks.clear()

    def _build_world_event_runtime(self, sim_id: uuid.UUID) -> None:
        """Instantiate the world-event scheduler + needs manager for the run.

        No-op when the scenario doesn't declare a ``world_events:`` block
        or when it sets ``disable_world_event_scheduler: true`` (used in
        embodied runs to defer to real Minecraft events).
        """
        block = self._config.world_events or {}
        if block.get("disable_world_event_scheduler"):
            logger.info("world_events: scheduler disabled by scenario")
            return

        from core.agent_needs import NeedConfig, NeedsManager
        from core.simulation.world_events import WorldEventScheduler

        seed = int(hashlib.sha256(str(sim_id).encode()).hexdigest()[:8], 16)
        self._world_event_scheduler = WorldEventScheduler.from_config(block, seed=seed)
        need_configs = {name: NeedConfig(**raw) for name, raw in (block.get("needs") or {}).items()}
        self._needs_manager = NeedsManager(
            configs=need_configs,
            simulation_id=str(sim_id),
        )
        if need_configs or block.get("schedule") or block.get("probabilistic"):
            logger.info(
                "world_events: scheduler armed with %d scheduled, %d probabilistic, %d needs",
                len(block.get("schedule") or []),
                len(block.get("probabilistic") or []),
                len(need_configs),
            )

    async def _tick_world(self, agent_ids: list[str]) -> None:
        """Advance the world-event scheduler + needs manager by one tick.

        Called once per phase. Emits events to the shared blackboard and
        the decision logger, and queues conversation triggers so the next
        phase can react to a hunger spike or nightfall.
        """
        if self._world_event_scheduler is None and self._needs_manager is None:
            return
        self._world_tick += 1
        tick = self._world_tick

        events: list[Any] = []
        if self._world_event_scheduler is not None:
            events.extend(self._world_event_scheduler.tick(tick))

        needs_events: list[Any] = []
        if self._needs_manager is not None and agent_ids:
            needs_events = self._needs_manager.tick_all(agent_ids, ticks=1)
            # Mirror snapshots to sim-scoped Redis so prompt assembly can
            # surface active needs without re-reading the manager.
            for agent_id in agent_ids:
                await self._snapshot_needs_to_redis(agent_id)

        if events or needs_events:
            await self._publish_world_events(events, needs_events, tick)

    async def _snapshot_needs_to_redis(self, agent_id: str) -> None:
        """Mirror one agent's needs into Redis via the scoped client."""
        if self._needs_manager is None or self._services is None:
            return
        scoped = getattr(self._services, "scoped_redis", None)
        if scoped is None:
            return
        try:
            import json as _json

            state = self._needs_manager.get_state(agent_id)
            await scoped.set(
                f"agent:needs:{agent_id}",
                _json.dumps(state.model_dump()),
            )
        except Exception:
            logger.debug("needs snapshot to redis failed", exc_info=True)

    async def _publish_world_events(
        self,
        events: list[Any],
        needs_events: list[Any],
        tick: int,
    ) -> None:
        """Log world events to decision log and push them on the blackboard."""
        shared = self._services.shared_working_state if self._services is not None else None

        for event in events:
            if self._decision_logger is not None:
                try:
                    self._decision_logger.log_world_event(
                        event_type=event.event_type,
                        trigger=event.trigger,
                        details=event.details,
                        sim_time=float(tick),
                    )
                except Exception:
                    logger.warning("decision log: world_event write failed", exc_info=True)
            if shared is not None and shared._redis is not None:
                try:
                    import json as _json

                    await shared._redis.rpush(
                        "shared:world_events",
                        _json.dumps(
                            {
                                "event": event.event_type,
                                "tick": tick,
                                "trigger": event.trigger,
                            }
                        ),
                    )
                except Exception:
                    logger.debug("blackboard: world_event push failed", exc_info=True)
            try:
                self._triggers.queue_event(
                    "world_event",
                    {"event": event.event_type, "tick": tick},
                )
            except Exception:
                logger.debug("trigger queue: world_event push failed", exc_info=True)

        for event in needs_events:
            if self._decision_logger is not None:
                state = self._needs_manager.get_state(event.agent_id)
                try:
                    self._decision_logger.log_needs_state(
                        actor_id=event.agent_id,
                        hunger=state.hunger,
                        sleep=state.sleep,
                        energy=state.energy,
                        other={"safety": state.safety, "social": state.social},
                        sim_time=float(tick),
                    )
                    self._decision_logger.log_world_event(
                        event_type=event.event_type,
                        trigger="needs",
                        details={
                            "agent_id": event.agent_id,
                            "need": event.need,
                            "value": event.value,
                            "threshold": event.threshold,
                        },
                        sim_time=float(tick),
                    )
                except Exception:
                    logger.warning("decision log: needs_state write failed", exc_info=True)

    def _build_reflection_scheduler(self) -> ReflectionScheduler:
        """Create a ReflectionScheduler from config, falling back to defaults."""
        kwargs: dict[str, int] = {}
        try:
            rc = self._config_loader.config.reflection
            if hasattr(rc, "six_hour_interval_hours") and isinstance(
                rc.six_hour_interval_hours, int
            ):
                kwargs = {
                    "six_hour_interval_hours": rc.six_hour_interval_hours,
                    "daily_hour": rc.daily_hour,
                    "weekly_day": rc.weekly_day,
                }
        except (AttributeError, TypeError):
            pass
        return ReflectionScheduler(self.clock, self._reflection, **kwargs)

    def _rescope_redis(self, sim_id: uuid.UUID) -> None:
        """Create a simulation-scoped Redis and re-wire all services.

        Every service created at bootstrap holds a reference to a ScopedRedis
        with the ``live:`` prefix.  When running a non-live simulation we must
        swap that reference so Redis keys are namespaced under
        ``sim:<uuid>:`` — giving true isolation between live and simulated
        runs.
        """
        from core.redis_keys import ScopedRedis

        scoped = ScopedRedis(self._redis, sim_id)

        # Services that hold a direct _redis reference
        if self._services:
            if self._services.agent_state_manager is not None:
                self._services.agent_state_manager._redis = scoped
                self._services.agent_state_manager._cache.clear()
            if self._services.shared_working_state is not None:
                self._services.shared_working_state._redis = scoped
            if self._services.goal_manager is not None:
                self._services.goal_manager._redis = scoped
            if self._services.agent_registry is not None:
                self._services.agent_registry._redis = scoped
            if self._services.scoped_redis is not None:
                # Update the canonical reference so anything that reads it later
                # picks up the sim-scoped instance.
                self._services.scoped_redis = scoped

        # Services held directly by the orchestrator
        if self._proximity is not None:
            self._proximity._redis = scoped
        if self._context is not None:
            self._context._redis = scoped
        if self._management is not None:
            self._management._redis = scoped

        logger.info(
            "Re-scoped Redis for simulation %s (prefix: %s)",
            sim_id,
            scoped._prefix,
        )

    def _build_phase_runner(
        self,
        sim_id: uuid.UUID,
        relationship_tracker: Any | None = None,
    ) -> PhaseRunner:
        """Create a PhaseRunner with all dependencies wired."""
        # Re-scope Redis so all services use sim:<uuid>: key prefix
        self._rescope_redis(sim_id)

        # Override simulation_id on all shared service objects to match this simulation.
        # These are created once at bootstrap with LIVE_SIMULATION_ID and must be
        # repointed when running a non-live simulation.
        if self._compactor is not None:
            self._compactor._simulation_id = sim_id
        if self._reflection is not None:
            self._reflection._simulation_id = sim_id
        if self._management is not None:
            self._management._simulation_id = sim_id
        if self._services:
            if self._services.economy_manager is not None:
                self._services.economy_manager.simulation_id = sim_id
            if self._services.alliance_manager is not None:
                self._services.alliance_manager.simulation_id = sim_id
            if self._services.dream_manager is not None:
                self._services.dream_manager._simulation_id = sim_id
            if self._services.event_generator is not None:
                self._services.event_generator.simulation_id = sim_id
            if self._services.agent_state_manager is not None:
                self._services.agent_state_manager.simulation_id = sim_id
        return PhaseRunner(
            config_loader=self._config_loader,
            agent_registry=self._agents,
            event_bus=self._event_bus,
            llm_client=self._llm,
            management=self._management,
            context_assembler=self._context,
            conversation_repo=self._conversation_repo,
            archival_memory=self._archival,
            proximity=self._proximity,
            trigger_system=self._triggers,
            selection_logger=self._selection_logger,
            reflection_manager=self._reflection,
            compactor=self._compactor,
            memory_repo=self._memory_repo,
            simulation_id=sim_id,
            agents=self._config.agents,
            dry_run=self._config.dry_run,
            services=self._services,
            clock=self.clock,
            relationship_tracker=relationship_tracker,
            debug_prompts=self._config.debug_prompts,
            prompt_log_repo=self._prompt_log_repo,
            factions=list(self._config.factions),
            conversation_mode=self._config.conversation_mode,
            embodiment_executor=self._executor,
            sim_folder=getattr(self, "_sim_folder", None),
            ownership_ledger=getattr(self, "_ownership_ledger", None),
            trade_ledger=getattr(self, "_trade_ledger", None),
            decision_logger=self._decision_logger,
        )

    def _idle_gap(self) -> timedelta:
        """Return a randomized idle gap duration between conversations.

        Uses idle_timeout_seconds from trigger config as the mean,
        with +/-30% jitter for natural variation.
        """
        try:
            mean = self._config_loader.config.triggers.idle_timeout_seconds
            if not isinstance(mean, (int, float)):
                mean = 90
        except (AttributeError, TypeError):
            mean = 90
        jitter = 0.3
        gap = random.uniform(mean * (1 - jitter), mean * (1 + jitter))
        gap = gap / self._config.conversation_cadence
        return timedelta(seconds=gap)

    def _build_model_versions(self) -> dict[str, dict[str, str]]:
        """Build a map of agent_id → {conversation, building} resolved model IDs."""
        versions: dict[str, dict[str, str]] = {}
        for agent_id in self._config.agents:
            agent = self._agents.get_agent(agent_id)
            if agent is None:
                continue
            conv_model = agent.model_conversation
            build_model = agent.model_building
            if isinstance(self._llm, OpenRouterClient):
                versions[agent_id] = {
                    "conversation": self._llm.model_provenance(conv_model),
                    "building": self._llm.model_provenance(build_model),
                }
                continue
            # Fallback for non-OpenRouterClient mocks/stubs in tests: resolve
            # to OpenRouter IDs from the local registry.
            conv_canonical = MODEL_NAME_ALIASES.get(conv_model, conv_model)
            build_canonical = MODEL_NAME_ALIASES.get(build_model, build_model)
            conv_openrouter = (
                MODEL_REGISTRY[conv_canonical].openrouter_id
                if conv_canonical in MODEL_REGISTRY
                else conv_model
            )
            build_openrouter = (
                MODEL_REGISTRY[build_canonical].openrouter_id
                if build_canonical in MODEL_REGISTRY
                else build_model
            )
            versions[agent_id] = {
                "conversation": conv_openrouter,
                "building": build_openrouter,
            }
        return versions

    def _seed_rng(self, simulation_id: uuid.UUID) -> None:
        """Seed the global RNG from the simulation ID for reproducibility."""
        seed = int(hashlib.sha256(str(simulation_id).encode()).hexdigest()[:8], 16)
        random.seed(seed)
        logger.info("RNG seeded with %d (from simulation %s)", seed, simulation_id)

    async def _apply_memory_seed(self, sim_id: uuid.UUID) -> None:
        """If the config carries a ``memory_seed`` block, apply it to ``sim_id``.

        Called immediately after the simulation row exists, before the
        regular ``init_core_memories`` pass. Any seeded core memory satisfies
        the existence check there, so default identity prompts are skipped.
        """
        if (
            self._config.memory_seed is None
            or self._config.dry_run
            or self._services is None
            or self._services.core_memory is None
            or self._services.recall_memory is None
            or self._memory_repo is None
        ):
            return

        from core.memory.memory_seed import MemorySeedApplier

        applier = MemorySeedApplier(
            db=self._db,
            memory_repo=self._memory_repo,
            core_memory_mgr=self._services.core_memory,
            recall_memory_mgr=self._services.recall_memory,
            agent_registry=self._agents,
            token_counter=self._services.token_counter,
            relationship_repo=self._relationship_repo,
        )
        seed_result = await applier.apply(self._config.memory_seed, sim_id)
        logger.info(
            "Applied memory_seed mode=%s: %d core, %d recall, %d journal for agents %s",
            self._config.memory_seed.mode,
            seed_result.core_memories_restored,
            seed_result.recall_memories_restored,
            seed_result.journal_entries_restored,
            seed_result.agents_restored,
        )
        for w in seed_result.warnings:
            logger.warning("memory_seed: %s", w)

    async def _apply_initial_agent_energy(self) -> None:
        """Apply public-submission initial energy to active agent states."""
        if (
            not self._config.initial_agent_energy
            or self._config.dry_run
            or self._services is None
            or self._services.agent_state_manager is None
        ):
            return

        manager = self._services.agent_state_manager
        active = set(self._config.agents)
        for agent_id, raw_value in self._config.initial_agent_energy.items():
            if agent_id not in active:
                continue
            value = float(raw_value)
            normalized = value / 100.0 if value > 1.0 else value
            state = await manager.get_state(agent_id)
            state.energy = max(0.0, min(1.0, normalized))
            await manager.save_state(state)

    async def _seed_configured_agent_goals(self) -> None:
        """Seed run-spec agent goals after the simulation id is known."""
        if (
            not self._config.agent_goals
            or self._config.dry_run
            or self._services is None
            or self._services.goal_manager is None
        ):
            return
        await self._services.goal_manager.seed_agent_goals(
            self._config.agent_goals,
            simulation_id=self._simulation_id,
        )
        logger.info("Seeded run-spec goals for %d agents", len(self._config.agent_goals))

    async def _persist_config_snapshot(self) -> None:
        """Persist the current config snapshot after runtime setup mutates it."""
        if self._simulation_id is None or self._config.dry_run:
            return
        await self._sim_repo.update_config(self._simulation_id, self._current_config_snapshot())

    def _current_config_snapshot(self) -> dict[str, Any]:
        """Build the DB config snapshot with runtime fields included."""
        snapshot = {
            **self._config.to_dict(),
            "clock_state": self.clock.to_dict(),
            "llm_provider": (
                self._llm.provider if isinstance(self._llm, OpenRouterClient) else "openrouter"
            ),
        }
        if self._config.run_mode == RunMode.experimental:
            progress = dict(
                getattr(
                    self,
                    "_experimental_progress",
                    {"phases_completed": 0, "turns": 0, "artifacts": 0},
                )
            )
            stop_reason = getattr(self, "_experimental_stop_reason", None)
            if any(progress.values()) or stop_reason is not None:
                snapshot["experimental_progress"] = progress
            if stop_reason is not None:
                snapshot["experimental_stop_reason"] = stop_reason
        return snapshot

    async def _provision_world_for_run(self) -> None:
        """Apply RunSpec.world to the Minecraft server world config."""
        if not self._executor.requires_minecraft_world:
            return
        if self._config.world_config is None or self._config.dry_run or self._simulation_id is None:
            return

        from core.minecraft.world_provisioner import provision_world

        run_mode = self._config.run_mode or RunMode.experimental
        project_root = Path(__file__).resolve().parents[2]
        server_dir = Path(os.environ.get("SERVER_DIR", project_root / "minecraft-server"))
        script_dir = project_root / "scripts" / "minecraft"
        persistent = self._config.world_config.persistent or run_mode == RunMode.persistent

        try:
            result = provision_world(
                self._config.world_config,
                run_mode,
                server_dir=server_dir,
                script_dir=script_dir,
                dry_run=self._config.dry_run,
            )
        except FileNotFoundError as exc:
            if persistent:
                logger.warning("Persistent Minecraft world is not present yet: %s", exc)
                self._config.world_provisioned = {
                    "run_mode": run_mode.value,
                    "persistent": True,
                    "action": "missing_existing_world",
                    "error": str(exc),
                }
                await self._persist_config_snapshot()
                return
            raise

        self._config.world_provisioned = result.to_dict()
        logger.info(
            "Provisioned Minecraft world for run_mode=%s: action=%s level_name=%s config=%s",
            run_mode.value,
            result.action,
            result.level_name,
            result.world_config_path,
        )
        await self._persist_config_snapshot()

    async def _create_or_attach_simulation(
        self,
        config_snapshot: dict[str, Any],
        model_versions: dict[str, dict[str, str]],
    ) -> Any:
        """Create a new simulation row, or attach to one pre-created by the API.

        When ``config.existing_sim_id`` is set the row was inserted by the
        admin dashboard so the client could be redirected immediately;
        we fetch it, refresh its config / agents / status, and reuse it.
        """
        import uuid as _uuid

        if self._config.existing_sim_id:
            sim_uuid = _uuid.UUID(self._config.existing_sim_id)
            sim = await self._sim_repo.get(sim_uuid)
            if sim is None:
                raise RuntimeError(f"existing_sim_id {sim_uuid} not found in simulations table")
            if (
                self._config.run_mode == RunMode.persistent
                and sim.status == SimulationStatus.running
            ):
                self._total_cost = await self._sim_repo.get_total_cost_from_events(sim_uuid)
            await self._sim_repo.update_config(sim_uuid, config_snapshot)
            await self._sim_repo.update_agents_participated(sim_uuid, self._config.agents)
            await self._sim_repo.update_status(sim_uuid, SimulationStatus.running)
            if self._config.factions:
                await self._sim_repo.update_factions(
                    sim_uuid, [f.model_dump() for f in self._config.factions]
                )
            # Re-read so we have fresh config/agents/status fields
            sim = await self._sim_repo.get(sim_uuid)
            return sim

        return await self._sim_repo.create(
            SimulationCreate(
                name=self._config.name,
                description=self._config.description,
                config=config_snapshot,
                status=SimulationStatus.running,
                agents_participated=self._config.agents,
                model_versions=model_versions,
                hypothesis=self._config.hypothesis,
                factions=[f.model_dump() for f in self._config.factions],
            )
        )

    async def run(self) -> None:
        """Execute the seeded simulation — create record, run phases, finalize."""
        self._start_time = time.monotonic()

        # Create simulation record (include clock state in config snapshot)
        config_snapshot = self._current_config_snapshot()
        model_versions = self._build_model_versions()
        sim = await self._create_or_attach_simulation(config_snapshot, model_versions)
        self._simulation_id = sim.id
        self._started_at = sim.started_at or datetime.now(UTC)
        self._llm._simulation_id = sim.id  # All LLM calls now tracked to this simulation
        self._selection_logger.simulation_id = sim.id
        self._seed_rng(sim.id)
        if self._config.run_mode == RunMode.persistent:
            await self._persistent_heartbeat(force=True)

        # Collect runtime errors for error_log persistence
        self._errors.clear()
        self._event_bus.on(
            EventType.SIMULATION_ERROR,
            self._on_simulation_error,
        )

        logger.info(
            "Created simulation %s (%s) with model versions: %s",
            sim.id,
            sim.name,
            model_versions,
        )

        try:
            await self._provision_world_for_run()
        except Exception as exc:
            await self._finalize(SimulationStatus.failed, error_log={"reason": str(exc)})
            raise

        await self._executor.setup(
            simulation_id=sim.id,
            sim_folder=getattr(self, "_sim_folder", None),
            decision_logger=self._decision_logger,
        )
        self._attach_decision_logger_listeners()

        self._display.show_simulation_start(sim, self._config)

        # Apply memory seed BEFORE init_core_memories so seeded values win.
        await self._apply_memory_seed(sim.id)

        # Initialize core memory for all agents in this simulation
        if self._services and self._services.core_memory:
            from core.bootstrap import init_core_memories

            initialized = await init_core_memories(
                self._agents,
                self._services.core_memory,
                simulation_id=sim.id,
            )
            if initialized:
                logger.info(
                    "Initialized core memory for %d agents: %s",
                    len(initialized),
                    initialized,
                )

        # Create RelationshipTracker and AssertionEngine now that sim_id is known
        relationship_tracker = self._build_relationship_tracker(sim.id)
        assertion_engine = self._build_assertion_engine()

        # Wire relationship tracker into reflection manager
        if relationship_tracker:
            self._reflection.set_relationship_tracker(relationship_tracker)

        reflection_scheduler = self._build_reflection_scheduler()
        runner = self._build_phase_runner(sim.id, relationship_tracker)
        self._build_world_event_runtime(sim.id)
        await self._apply_initial_agent_energy()

        # Initialize economy accounts for this simulation scope
        # (bootstrap creates live-scoped accounts; we need sim-scoped ones)
        if self._services and self._services.economy_manager and not self._config.dry_run:
            try:
                economy_excluded = {"management", "alpha"}
                agent_ids = [a for a in self._config.agents if a not in economy_excluded]
                await self._services.economy_manager.initialize_accounts(agent_ids)
                logger.info(
                    "Initialized economy accounts for %d agents in simulation", len(agent_ids)
                )
            except Exception:
                logger.warning(
                    "Failed to initialize economy accounts for simulation", exc_info=True
                )

        # Start audience simulator if configured
        audience_sim = None
        if self._config.audience_config and not self._config.dry_run:
            from core.simulation.audience_sim import AudienceSimulator

            audience_sim = AudienceSimulator(self._redis, self._config.audience_config)
            await audience_sim.seed_initial_state()
            audience_sim.start()

        persistent_mode = self._config.run_mode == RunMode.persistent

        # Start world simulator if enabled
        world_sim = None
        if self._config.world_sim and not self._config.dry_run and not persistent_mode:
            from core.simulation.recurring_personas import PersonaManager
            from core.simulation.world_simulator import WorldSimulator

            persona_mgr = PersonaManager(llm_client=self._llm, clock=self.clock)
            persona_mgr.load_personas()
            world_sim = WorldSimulator(
                redis_client=self._redis,
                llm_client=self._llm,
                clock=self.clock,
                event_bus=self._event_bus,
                persona_manager=persona_mgr,
            )
            world_sim.start()

        # Seed shared task board and agent goals if configured
        if not self._config.dry_run:
            if self._config.seed_tasks and self._services and self._services.shared_working_state:
                await self._services.shared_working_state.seed_initial_tasks()
                logger.info("Seeded initial tasks on shared task board")
            if self._config.seed_goals and self._services and self._services.goal_manager:
                await self._services.goal_manager.seed_story_goals(
                    simulation_id=self._simulation_id,
                )
                logger.info("Seeded story goals for agents")
            await self._seed_configured_agent_goals()

        phases = self._config.phases
        total_phases = len(phases)

        try:
            for idx, phase in enumerate(phases):
                if self._cancelled:
                    break

                self._display.show_phase_start(phase.name, idx, total_phases)

                result = await runner.run_phase(phase)

                # Evaluate phase assertions
                if assertion_engine and not self._config.dry_run:
                    try:
                        # Phase-defined assertions from the seed file (may be empty)
                        assertion_results = await assertion_engine.evaluate_phase(
                            phase,
                            result,
                            sim.id,
                        )
                        # Always emit baseline conversation assertions so the
                        # Assertions tab is populated even when the seed
                        # scenario omits an `assertions:` block.
                        baseline_results = await assertion_engine.evaluate_conversation_defaults(
                            result,
                            sim.id,
                            config={},
                            phase_name=phase.name,
                        )
                        result.assertions = assertion_results + baseline_results
                    except Exception:
                        logger.warning(
                            "Assertion evaluation failed for phase %s",
                            phase.name,
                            exc_info=True,
                        )

                # Update DB stats
                if not self._config.dry_run:
                    await self._sim_repo.increment_stats(
                        sim.id,
                        conversations=result.conversations or (1 if result.turns > 0 else 0),
                        turns=result.turns,
                        tokens=result.tokens,
                        cost=result.cost,
                        artifacts=result.artifacts,
                        management_flags=result.management_flags,
                    )
                    if result.agents_participated:
                        await self._sim_repo.update_agents_participated(
                            sim.id, result.agents_participated
                        )

                self._total_cost += result.cost
                self._record_experimental_progress(result)
                self._display.show_phase_complete(result, phase.name)

                # Advance world-event scheduler + needs by one tick per phase.
                # Headless runs rely on this for hunger/nightfall pressure;
                # embodied runs can opt out via the scenario block.
                await self._tick_world(list(self._config.agents))

                # Advance simulated clock so reflection scheduler can track time
                if result.duration_seconds > 0:
                    if self._config.speed_multiplier > 0:
                        advance = timedelta(
                            seconds=result.duration_seconds * self._config.speed_multiplier
                        )
                    else:
                        # In instant mode, treat each phase as ~30 simulated minutes
                        # so time-based reflections can fire during seeded runs
                        advance = timedelta(minutes=30)
                    self.clock.advance(advance)

                # Mark explicit reflection phases to prevent scheduler duplicates
                if phase.type == PhaseType.reflection:
                    for agent_id in self._config.agents:
                        reflection_scheduler.mark_recently_reflected(agent_id)

                # Run auto-scheduled reflections after each phase
                if not self._config.dry_run:
                    reflection_results = await reflection_scheduler.check_and_run_all(
                        self._config.agents
                    )
                    for rr in reflection_results:
                        if rr.journal_entry:
                            self._display.show_reflection_triggered(
                                rr.journal_entry.agent_id,
                                rr.journal_entry.reflection_type,
                                self.clock.now(),
                            )

                # Check cost limit
                if not self._config.dry_run:
                    await self._check_cost_limit()
                if self._experimental_goal_reached():
                    self._mark_experimental_stop_reason("goal_reached")
                    break

            # Finalize
            if audience_sim:
                await audience_sim.stop()
            if world_sim:
                await world_sim.stop()
            status = SimulationStatus.cancelled if self._cancelled else SimulationStatus.completed
            if self._cancelled:
                self._mark_experimental_stop_reason("cancelled")
            elif self._config.run_mode == RunMode.experimental:
                if self._experimental_goal_reached():
                    self._mark_experimental_stop_reason("goal_reached")
                else:
                    self._mark_experimental_stop_reason("phases_complete")
            await self._finalize(status)

        except CostLimitExceededError:
            if audience_sim:
                await audience_sim.stop()
            if world_sim:
                await world_sim.stop()
            self._mark_experimental_stop_reason("cost_cap")
            logger.warning("Cost limit exceeded ($%s), stopping simulation", self._total_cost)
            self._display.show_cost_exceeded(self._total_cost, self._config.max_cost)
            await self._finalize(
                SimulationStatus.cancelled,
                error_log={"reason": "cost_limit_exceeded", "total_cost": str(self._total_cost)},
            )

        except Exception as exc:
            if audience_sim:
                await audience_sim.stop()
            if world_sim:
                await world_sim.stop()
            logger.exception("Simulation failed")
            await self._finalize(
                SimulationStatus.failed,
                error_log={"reason": str(exc)},
            )
            raise

    async def run_autonomous(self) -> None:
        """Run in autonomous mode — trigger system drives all conversations."""
        self._start_time = time.monotonic()

        config_snapshot = self._current_config_snapshot()
        model_versions = self._build_model_versions()
        sim = await self._create_or_attach_simulation(config_snapshot, model_versions)
        self._simulation_id = sim.id
        self._started_at = sim.started_at or datetime.now(UTC)
        self._llm._simulation_id = sim.id  # All LLM calls now tracked to this simulation
        self._selection_logger.simulation_id = sim.id
        self._seed_rng(sim.id)

        # Collect runtime errors for error_log persistence
        self._errors.clear()
        self._event_bus.on(
            EventType.SIMULATION_ERROR,
            self._on_simulation_error,
        )

        logger.info(
            "Created autonomous simulation %s (%s) with model versions: %s",
            sim.id,
            sim.name,
            model_versions,
        )

        try:
            await self._provision_world_for_run()
        except Exception as exc:
            await self._finalize(SimulationStatus.failed, error_log={"reason": str(exc)})
            raise

        await self._executor.setup(
            simulation_id=sim.id,
            sim_folder=getattr(self, "_sim_folder", None),
            decision_logger=self._decision_logger,
        )
        self._attach_decision_logger_listeners()

        self._display.show_simulation_start(sim, self._config)

        # Apply memory seed BEFORE init_core_memories so seeded values win.
        await self._apply_memory_seed(sim.id)

        # Initialize core memory for all agents in this simulation
        if self._services and self._services.core_memory:
            from core.bootstrap import init_core_memories

            initialized = await init_core_memories(
                self._agents,
                self._services.core_memory,
                simulation_id=sim.id,
            )
            if initialized:
                logger.info(
                    "Initialized core memory for %d agents: %s",
                    len(initialized),
                    initialized,
                )

        # Create RelationshipTracker and AssertionEngine now that sim_id is known
        relationship_tracker = self._build_relationship_tracker(sim.id)
        assertion_engine = self._build_assertion_engine()

        if relationship_tracker:
            self._reflection.set_relationship_tracker(relationship_tracker)

        reflection_scheduler = self._build_reflection_scheduler()
        runner = self._build_phase_runner(sim.id, relationship_tracker)
        self._build_world_event_runtime(sim.id)
        await self._apply_initial_agent_energy()

        persistent_mode = self._config.run_mode == RunMode.persistent

        # Start world simulator if enabled
        world_sim = None
        if self._config.world_sim and not self._config.dry_run and not persistent_mode:
            from core.simulation.recurring_personas import PersonaManager
            from core.simulation.world_simulator import WorldSimulator

            persona_mgr = PersonaManager(llm_client=self._llm, clock=self.clock)
            persona_mgr.load_personas()
            world_sim = WorldSimulator(
                redis_client=self._redis,
                llm_client=self._llm,
                clock=self.clock,
                event_bus=self._event_bus,
                persona_manager=persona_mgr,
            )
            world_sim.start()

        await self._seed_configured_agent_goals()

        conversation_num = 0
        current_day = self.clock.simulated_day()
        day_stats: dict[str, Any] = {"conversations": 0, "cost": Decimal("0"), "tools": 0}

        self._display.show_day_boundary(current_day, {})

        try:
            while not await self._terminated():
                if persistent_mode and not self._config.dry_run:
                    await self._persistent_heartbeat()
                    await self._check_cost_limit()

                # Check for day boundary
                new_day = self.clock.simulated_day()
                if new_day != current_day:
                    self._display.show_day_boundary(new_day, day_stats)
                    # Store per-day stats in metadata
                    if not self._config.dry_run:
                        await self._sim_repo.update_durations(
                            sim.id,
                            simulated_duration=self.clock.elapsed(),
                        )
                    current_day = new_day
                    day_stats = {"conversations": 0, "cost": Decimal("0"), "tools": 0}

                # Get next trigger from trigger system
                trigger = await self._triggers.check()
                if trigger is None:
                    # No trigger fired — advance clock by idle gap and retry
                    gap = self._idle_gap()
                    self.clock.advance(gap)
                    self._triggers.notify_speech()  # Reset idle timer
                    continue

                if not self._config.agents:
                    raise RuntimeError("autonomous simulation has no active agents")
                if trigger.get("starter_agent_id") not in self._config.agents:
                    trigger["starter_agent_id"] = self._config.agents[0]

                conversation_num += 1
                trigger_type = trigger.get("type", "idle")
                self._display.show_autonomous_status(trigger_type, conversation_num)

                # Map trigger to a phase and run it
                phase = Phase(
                    name=f"auto_{trigger_type}_{conversation_num}",
                    type=self._trigger_to_phase_type(trigger_type),
                    config={
                        "location": trigger.get("location", "town_square"),
                        "topic": trigger.get("prompt_hint"),
                    },
                    required_agents=[trigger.get("starter_agent_id", "vera")],
                )
                result = await runner.run_phase(phase)

                # Update stats
                if not self._config.dry_run:
                    await self._sim_repo.increment_stats(
                        sim.id,
                        conversations=result.conversations or (1 if result.turns > 0 else 0),
                        turns=result.turns,
                        tokens=result.tokens,
                        cost=result.cost,
                        artifacts=result.artifacts,
                        management_flags=result.management_flags,
                    )
                    if result.agents_participated:
                        await self._sim_repo.update_agents_participated(
                            sim.id, result.agents_participated
                        )

                # Evaluate assertions for autonomous conversations
                if assertion_engine and not self._config.dry_run:
                    try:
                        conv_config = self._config_loader.config.conversation_config
                    except AttributeError:
                        conv_config = {}
                    assertion_results = await assertion_engine.evaluate_conversation_defaults(
                        result,
                        sim.id,
                        conv_config if isinstance(conv_config, dict) else {},
                    )
                    result.assertions = assertion_results

                self._total_cost += result.cost
                self._record_experimental_progress(result)
                day_stats["conversations"] += 1
                day_stats["cost"] += result.cost
                day_stats["tools"] += result.artifacts

                self._display.show_phase_complete(result, phase.name)

                # Advance the headless world-event scheduler one tick per
                # autonomous conversation. Skipped when the scenario opts
                # out (embodied runs fed by real Minecraft events).
                await self._tick_world(list(self._config.agents))

                # Advance clock by conversation duration + idle gap
                multiplier = self._config.speed_multiplier
                if multiplier > 0:
                    conv_duration = timedelta(seconds=result.duration_seconds * multiplier)
                else:
                    conv_duration = timedelta(seconds=result.duration_seconds)
                self.clock.advance(conv_duration + self._idle_gap())
                self._triggers.notify_speech()

                # Run auto-scheduled reflections
                if not self._config.dry_run:
                    reflection_results = await reflection_scheduler.check_and_run_all(
                        self._config.agents
                    )
                    for rr in reflection_results:
                        if rr.journal_entry:
                            self._display.show_reflection_triggered(
                                rr.journal_entry.agent_id,
                                rr.journal_entry.reflection_type,
                                self.clock.now(),
                            )

                # Check cost limit
                if not self._config.dry_run:
                    await self._check_cost_limit()
                if self._experimental_goal_reached():
                    self._mark_experimental_stop_reason("goal_reached")

            # Final day stats
            self._display.show_day_boundary(self.clock.simulated_day(), day_stats)
            if world_sim:
                await world_sim.stop()
            status = SimulationStatus.cancelled if self._cancelled else SimulationStatus.completed
            if self._cancelled:
                self._mark_experimental_stop_reason("cancelled")
            await self._finalize(status)

        except CostLimitExceededError:
            if world_sim:
                await world_sim.stop()
            self._mark_experimental_stop_reason("cost_cap")
            logger.warning(
                "Cost limit exceeded ($%s), stopping simulation",
                self._total_cost,
            )
            self._display.show_cost_exceeded(self._total_cost, self._config.max_cost)
            await self._finalize(
                SimulationStatus.cancelled,
                error_log={
                    "reason": "cost_limit_exceeded",
                    "total_cost": str(self._total_cost),
                },
            )

        except Exception as exc:
            if world_sim:
                await world_sim.stop()
            logger.exception("Autonomous simulation failed")
            await self._finalize(
                SimulationStatus.failed,
                error_log={"reason": str(exc)},
            )
            raise

    async def _terminated(self) -> bool:
        """Check all termination conditions for autonomous mode."""
        if self._cancelled:
            self._mark_experimental_stop_reason("cancelled")
            return True
        if self._experimental_goal_reached():
            logger.info("Experimental goal reached (%s)", self._config.experimental_goal)
            self._mark_experimental_stop_reason("goal_reached")
            return True
        # Duration limit
        if (
            getattr(self._config, "run_mode", None) != RunMode.persistent
            and self._config.duration
            and self.clock.elapsed() >= self._config.duration
        ):
            logger.info("Duration limit reached (%s)", self._config.duration)
            self._mark_experimental_stop_reason("duration_reached")
            return True
        # Redis kill switch (accessible from Brad's phone)
        if self._redis:
            kill = await self._redis.get(KILL_SWITCH_KEY)
            if kill == KILL_SWITCH_ACTIVE_VALUE:
                logger.info("Kill switch activated — stopping simulation")
                self._mark_experimental_stop_reason("kill_switch")
                return True
        return False

    def _mark_experimental_stop_reason(self, reason: str) -> None:
        """Record why an experimental run stopped, preserving the first terminal cause."""
        if getattr(self._config, "run_mode", None) != RunMode.experimental:
            return
        if getattr(self, "_experimental_stop_reason", None) is None:
            self._experimental_stop_reason = reason

    def _record_experimental_progress(self, result: Any) -> None:
        """Update bounded-run progress counters from a completed phase result."""
        if getattr(self._config, "run_mode", None) != RunMode.experimental:
            return
        if not hasattr(self, "_experimental_progress"):
            self._experimental_progress = {
                "phases_completed": 0,
                "turns": 0,
                "artifacts": 0,
            }
        self._experimental_progress["phases_completed"] += 1
        self._experimental_progress["turns"] += int(getattr(result, "turns", 0) or 0)
        self._experimental_progress["artifacts"] += int(getattr(result, "artifacts", 0) or 0)

    _GOAL_KIND_TO_PROGRESS_KEY = {
        "phases_complete": "phases_completed",
        "turns": "turns",
        "artifacts": "artifacts",
    }

    def _experimental_goal_reached(self) -> bool:
        """Return whether the configured experimental goal has been satisfied."""
        goal = getattr(self._config, "experimental_goal", None)
        if getattr(self._config, "run_mode", None) != RunMode.experimental or goal is None:
            return False
        progress = getattr(
            self,
            "_experimental_progress",
            {"phases_completed": 0, "turns": 0, "artifacts": 0},
        )
        progress_key = self._GOAL_KIND_TO_PROGRESS_KEY.get(goal.kind, goal.kind)
        return progress.get(progress_key, 0) >= goal.target

    async def _persistent_heartbeat(self, *, force: bool = False) -> None:
        """Publish the active persistent simulation id on raw Redis."""
        if self._simulation_id is None or self._config.run_mode != RunMode.persistent:
            return
        now = time.monotonic()
        if not force and now - self._last_persistent_heartbeat < 30:
            return
        await self._redis.set("live:simulation_id", str(self._simulation_id))
        await self._redis.set("live:simulation_heartbeat", datetime.now(UTC).isoformat())
        self._last_persistent_heartbeat = now

    @staticmethod
    def _trigger_to_phase_type(trigger_type: str) -> PhaseType:
        """Map a trigger type string to a PhaseType for autonomous conversations."""
        mapping = {
            "idle": PhaseType.organic,
            "scheduled": PhaseType.scheduled,
            "environmental": PhaseType.organic,
            "memory": PhaseType.organic,
            "audience": PhaseType.audience_sim,
        }
        return mapping.get(trigger_type, PhaseType.organic)

    def _build_relationship_tracker(self, sim_id: uuid.UUID) -> Any | None:
        """Create a RelationshipTracker if relationship_repo is available."""
        if self._relationship_repo is None:
            return None
        from core.social.relationship_tracker import RelationshipTracker

        return RelationshipTracker(
            llm_client=self._llm,
            relationship_repo=self._relationship_repo,
            simulation_id=sim_id,
            clock=self.clock,
        )

    def _build_assertion_engine(self) -> Any | None:
        """Create an AssertionEngine with repo for persisting results."""
        from core.repos.assertion_repo import AssertionRepo
        from core.simulation.assertions import AssertionEngine

        repo = AssertionRepo(self._db) if self._db else None
        return AssertionEngine(assertion_repo=repo)

    def cancel(self) -> None:
        """Signal the orchestrator to stop after the current phase."""
        self._cancelled = True

    async def _check_cost_limit(self) -> None:
        """Reconcile cost from cost_events and raise if over limit.

        Queries the authoritative cost_events table so the limit check
        accounts for ALL LLM calls (management, compaction, reflections, etc.),
        not just conversation turns from agent_speak events.  Also persists
        the reconciled total to the simulation record so it stays accurate
        even if the process crashes before _finalize().
        """
        if self._simulation_id is None:
            return
        try:
            actual_cost = await self._sim_repo.get_total_cost_from_events(self._simulation_id)
            if actual_cost > 0 and actual_cost != self._total_cost:
                # Sync the in-memory total and persist to DB
                await self._sim_repo.increment_stats(
                    self._simulation_id,
                    cost=actual_cost - self._total_cost,
                )
                self._total_cost = actual_cost
        except Exception:
            logger.warning(
                "Cost reconciliation failed for %s, using in-memory total $%s",
                self._simulation_id,
                self._total_cost,
                exc_info=True,
            )
        if self._total_cost > self._config.max_cost:
            raise CostLimitExceededError(
                f"Total cost ${self._total_cost} exceeds limit ${self._config.max_cost}"
            )
        if self._config.max_cost_rolling is not None and self._config.rolling_window is not None:
            rolling_cost = await self._sim_repo.get_rolling_cost_from_events(
                self._simulation_id,
                self._config.rolling_window,
            )
            if rolling_cost > self._config.max_cost_rolling:
                raise CostLimitExceededError(
                    f"Rolling spend ${rolling_cost} over {self._config.rolling_window} "
                    f"exceeds limit ${self._config.max_cost_rolling}"
                )

    async def _on_simulation_error(self, event: dict[str, Any]) -> None:
        """Collect runtime errors emitted via SIMULATION_ERROR events."""
        self._errors.append(event)

    async def _finalize(
        self,
        status: SimulationStatus,
        *,
        error_log: dict[str, Any] | None = None,
    ) -> None:
        """Update the simulation record with final status and durations."""
        if self._simulation_id is None:
            return

        # Merge explicit error_log with accumulated runtime errors
        combined_log: dict[str, Any] | list[Any] | None = None
        if error_log and self._errors:
            combined_log = {**error_log, "runtime_errors": self._errors}
        elif error_log:
            combined_log = error_log
        elif self._errors:
            combined_log = {"runtime_errors": self._errors}

        # Unsubscribe error listener
        self._event_bus.off(
            EventType.SIMULATION_ERROR,
            self._on_simulation_error,
        )
        self._detach_decision_logger_listeners()

        try:
            await self._executor.teardown()
        except Exception:  # pragma: no cover
            logger.warning("Executor teardown raised", exc_info=True)

        completed_at = datetime.now(UTC)
        # Wall-clock duration between start and completion. Falls back to
        # monotonic delta only if started_at was never captured (defensive).
        if self._started_at is not None:
            real_duration = completed_at - self._started_at
        else:
            real_duration = timedelta(seconds=time.monotonic() - self._start_time)
        # Use clock elapsed time if speed_multiplier > 0, else fallback to phase count
        if self._config.speed_multiplier > 0 or self._config.mode == "autonomous":
            simulated_duration = self.clock.elapsed()
        else:
            simulated_duration = timedelta(hours=len(self._config.phases))

        await self._sim_repo.update_status(
            self._simulation_id,
            status.value,
            completed_at=completed_at,
            error_log=combined_log,
        )
        await self._sim_repo.update_durations(
            self._simulation_id,
            simulated_duration=simulated_duration,
            real_duration=real_duration,
        )

        # Reconcile total_cost from cost_events (authoritative source)
        try:
            actual_cost = await self._sim_repo.get_total_cost_from_events(self._simulation_id)
            if actual_cost > 0:
                await self._sim_repo.increment_stats(
                    self._simulation_id,
                    cost=actual_cost - self._total_cost,
                )
                self._total_cost = actual_cost
        except Exception:
            logger.warning(
                "Failed to reconcile cost from cost_events for %s",
                self._simulation_id,
                exc_info=True,
            )

        # Persist final clock state into config
        final_config = self._current_config_snapshot()
        await self._sim_repo.update_config(self._simulation_id, final_config)

        # Build a baseline outcomes object (research artifact) so the
        # simulation is comparable post-run without requiring manual edits.
        try:
            await self._write_baseline_outcomes(real_duration, simulated_duration)
        except Exception:
            logger.warning(
                "Failed to persist baseline outcomes for %s",
                self._simulation_id,
                exc_info=True,
            )

        # Fetch final record for summary
        sim = await self._sim_repo.get(self._simulation_id)
        if sim:
            self._display.show_summary(sim, real_duration)

        # Kick off MP4 rendering for completed/failed runs. Best-effort:
        # never block finalize on a video render, and gracefully skip when
        # there's nothing to render (no transcripts, no events).
        if sim is not None and sim.status in {"completed", "failed"}:
            try:
                await self._enqueue_video_render(sim)
            except Exception:
                logger.warning(
                    "Failed to enqueue video render for %s",
                    self._simulation_id,
                    exc_info=True,
                )

        # Notify the public submitter (if any) that their run finished.
        # Wrapped: notification failures must never block finalize.
        if sim is not None and sim.submitted_by_user_id is not None:
            try:
                await self._notify_submitter(sim)
            except Exception:
                logger.warning(
                    "Failed to send completion notification for %s",
                    self._simulation_id,
                    exc_info=True,
                )

    async def _enqueue_video_render(self, sim: Any) -> None:
        """Enqueue the headless video render for ``sim``."""
        from core.video.worker import enqueue_render, mark_unrenderable

        if sim.total_turns <= 0 or sim.total_conversations <= 0:
            await mark_unrenderable(
                sim.id,
                sim_repo=self._sim_repo,
                reason="no transcript turns",
            )
            return
        await enqueue_render(sim.id, sim_repo=self._sim_repo)

    async def _notify_submitter(self, sim: Any) -> None:
        """Email the public submitter that their simulation finished."""
        from core.notifications import send_completion_email
        from core.repos.user_repo import UserRepo

        user_repo = UserRepo(self._db)
        user = await user_repo.get_by_id(sim.submitted_by_user_id)
        if user is None:
            logger.info(
                "[notify] submitter %s no longer exists; skipping email",
                sim.submitted_by_user_id,
            )
            return

        video_url = getattr(sim, "video_url", None)
        await send_completion_email(
            sim,
            user,
            user_repo=user_repo,
            video_url=video_url,
        )

    async def _write_baseline_outcomes(
        self,
        real_duration: timedelta,
        simulated_duration: timedelta,
    ) -> None:
        """Populate a baseline outcomes JSONB and (optionally) draft a learning."""
        if self._simulation_id is None:
            return
        sim = await self._sim_repo.get(self._simulation_id)
        if sim is None:
            return

        # Pull eval scores if any exist for this run.
        evals: dict[str, Any] = {}
        try:
            from core.repos.eval_repo import EvalRepo

            eval_repo = EvalRepo(self._db)
            latest = await eval_repo.get_latest_eval_run(self._simulation_id)
            if latest is not None:
                evals["eval_run_id"] = str(latest.id)
                evals["eval_suite"] = latest.eval_suite
                evals["overall_score"] = (
                    str(latest.overall_score) if latest.overall_score is not None else None
                )
                results = await eval_repo.get_eval_results(latest.id)
                evals["category_scores"] = {
                    r.category: (str(r.score) if r.score is not None else None) for r in results
                }
        except Exception:
            logger.debug("No eval data attached to simulation", exc_info=True)

        outcomes: dict[str, Any] = {
            "key_metrics": {
                "total_conversations": sim.total_conversations,
                "total_turns": sim.total_turns,
                "total_tokens": sim.total_tokens,
                "total_cost": str(sim.total_cost),
                "total_artifacts": sim.total_artifacts,
                "total_management_flags": sim.total_management_flags,
                "simulated_duration_seconds": simulated_duration.total_seconds(),
                "real_duration_seconds": real_duration.total_seconds(),
                "phases_completed": getattr(
                    self,
                    "_experimental_progress",
                    {"phases_completed": len(self._config.phases)},
                ).get("phases_completed", len(self._config.phases)),
                "stop_reason": getattr(self, "_experimental_stop_reason", None),
            },
            "evals": evals,
            "surprises": [],
            "failures": list(self._errors),
        }

        await self._sim_repo.update_research_fields(self._simulation_id, outcomes=outcomes)

        if self._config.auto_draft_learnings and not self._config.dry_run:
            try:
                draft = await self._draft_learning_summary(sim, outcomes)
                if draft:
                    await self._sim_repo.append_learning(
                        self._simulation_id, author="system", text=draft
                    )
            except Exception:
                logger.warning(
                    "Auto-draft learnings failed for %s",
                    self._simulation_id,
                    exc_info=True,
                )

    async def _draft_learning_summary(
        self,
        sim: Any,
        outcomes: dict[str, Any],
    ) -> str | None:
        """Ask the LLM to summarize the run in 2-3 sentences."""
        prompt = (
            "Summarize this simulation run in 2-3 sentences as a research learning. "
            f"Hypothesis: {sim.hypothesis or '(none provided)'}. "
            f"Key metrics: {outcomes['key_metrics']}. "
            f"Eval data: {outcomes['evals']}. "
            f"Failures: {len(outcomes['failures'])}."
        )
        try:
            resp = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=resolve_internal_model("simulation_learning_summary"),
                max_tokens=200,
            )
        except Exception:
            logger.debug("LLM draft learnings call failed", exc_info=True)
            return None
        content = getattr(resp, "content", None)
        if content is None and isinstance(resp, dict):
            content = resp.get("content")
        if content is None:
            return None
        text = str(content).strip()
        return text or None
