"""SimulationOrchestrator — drives simulations in seeded or autonomous mode.

Seeded mode: loops through phases from a YAML seed file.
Autonomous mode: trigger system drives conversations continuously until
duration/cost/kill-switch limits are reached.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import yaml

from core.event_bus import EventType
from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY, OpenRouterClient
from core.memory.reflection_scheduler import ReflectionScheduler
from core.models import FactionConfig, SimulationCreate, SimulationStatus
from core.simulation.clock import SimulationClock
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
    """Raised when simulation spending exceeds --max-cost."""


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
        speed: str = "fast",
        speed_multiplier: float = 0,
        duration: timedelta | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        management_shadow: bool = True,
        debug_prompts: bool = False,
        existing_sim_id: str | None = None,
        hypothesis: str | None = None,
        auto_draft_learnings: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.seed_file = seed_file
        self.agents = agents
        self.max_cost = Decimal(str(max_cost))
        self.speed = speed
        self.speed_multiplier = speed_multiplier
        self.duration = duration
        self.dry_run = dry_run
        self.verbose = verbose
        self.management_shadow = management_shadow
        self.debug_prompts = debug_prompts
        self.world_sim: bool = False
        self.phases: list[Phase] = []
        self.audience_config: dict[str, Any] | None = None
        self.seed_tasks: bool = False
        self.seed_goals: bool = False
        self.factions: list[FactionConfig] = []
        # When provided, the orchestrator attaches to a pre-created
        # simulation row instead of inserting a new one. Used when the
        # admin dashboard pre-creates the row so it can immediately return
        # the simulation_id to the client for redirect.
        self.existing_sim_id = existing_sim_id
        self.hypothesis = hypothesis
        self.auto_draft_learnings = auto_draft_learnings

    @property
    def mode(self) -> str:
        """Return 'seeded' if a seed file is set, otherwise 'autonomous'."""
        return "seeded" if self.seed_file else "autonomous"

    def load_seed_file(self, valid_agent_ids: set[str] | None = None) -> None:
        """Parse the YAML seed file into Phase objects.

        ``valid_agent_ids`` is used to validate faction membership when
        provided; if None, faction membership is parsed but not checked.
        """
        if not self.seed_file:
            return

        with open(self.seed_file) as f:
            data = yaml.safe_load(f)

        self.audience_config = data.get("audience")
        self.seed_tasks = bool(data.get("seed_tasks", False))
        self.seed_goals = bool(data.get("seed_goals", False))

        # Parse factions if present
        raw_factions = data.get("factions") or []
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
                    raise ValueError(
                        f"faction '{faction.name}' has unknown members: {unknown}"
                    )
            self.factions.append(faction)

        raw_phases = data.get("phases", [])
        for entry in raw_phases:
            phase_type = entry.get("type", "organic")
            try:
                ptype = PhaseType(phase_type)
            except ValueError:
                logger.warning("Unknown phase type '%s', defaulting to organic", phase_type)
                ptype = PhaseType.organic

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
        if self.duration is not None:
            d["duration_seconds"] = self.duration.total_seconds()
        if self.phases:
            d["phase_count"] = len(self.phases)
            d["phase_names"] = [p.name for p in self.phases]
        if self.factions:
            d["factions"] = [f.model_dump() for f in self.factions]
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
        self.clock = clock or SimulationClock(speed_multiplier=config.speed_multiplier)

    @property
    def simulation_id(self) -> uuid.UUID | None:
        return self._simulation_id

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
        config_snapshot = {
            **self._config.to_dict(),
            "clock_state": self.clock.to_dict(),
            "llm_provider": (
                self._llm.provider if isinstance(self._llm, OpenRouterClient) else "openrouter"
            ),
        }
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
            "Created simulation %s (%s) with model versions: %s",
            sim.id,
            sim.name,
            model_versions,
        )

        self._display.show_simulation_start(sim, self._config)

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

        # Start world simulator if enabled
        world_sim = None
        if self._config.world_sim and not self._config.dry_run:
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
                self._display.show_phase_complete(result, phase.name)

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

            # Finalize
            if audience_sim:
                await audience_sim.stop()
            if world_sim:
                await world_sim.stop()
            status = SimulationStatus.cancelled if self._cancelled else SimulationStatus.completed
            await self._finalize(status)

        except CostLimitExceededError:
            if audience_sim:
                await audience_sim.stop()
            if world_sim:
                await world_sim.stop()
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

        config_snapshot = {
            **self._config.to_dict(),
            "clock_state": self.clock.to_dict(),
            "llm_provider": (
                self._llm.provider if isinstance(self._llm, OpenRouterClient) else "openrouter"
            ),
        }
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

        self._display.show_simulation_start(sim, self._config)

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

        # Start world simulator if enabled
        world_sim = None
        if self._config.world_sim and not self._config.dry_run:
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

        conversation_num = 0
        current_day = self.clock.simulated_day()
        day_stats: dict[str, Any] = {"conversations": 0, "cost": Decimal("0"), "tools": 0}

        self._display.show_day_boundary(current_day, {})

        try:
            while not await self._terminated():
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
                day_stats["conversations"] += 1
                day_stats["cost"] += result.cost
                day_stats["tools"] += result.artifacts

                self._display.show_phase_complete(result, phase.name)

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

            # Final day stats
            self._display.show_day_boundary(self.clock.simulated_day(), day_stats)
            if world_sim:
                await world_sim.stop()
            status = SimulationStatus.cancelled if self._cancelled else SimulationStatus.completed
            await self._finalize(status)

        except CostLimitExceededError:
            if world_sim:
                await world_sim.stop()
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
            return True
        # Duration limit
        if self._config.duration and self.clock.elapsed() >= self._config.duration:
            logger.info("Duration limit reached (%s)", self._config.duration)
            return True
        # Redis kill switch (accessible from Brad's phone)
        if self._redis:
            kill = await self._redis.get("kill_switch")
            if kill == "active":
                logger.info("Kill switch activated — stopping simulation")
                return True
        return False

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
        final_config = {**self._config.to_dict(), "clock_state": self.clock.to_dict()}
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
            },
            "evals": evals,
            "surprises": [],
            "failures": list(self._errors),
        }

        await self._sim_repo.update_research_fields(
            self._simulation_id, outcomes=outcomes
        )

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
                model="claude-haiku-4-5",
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
