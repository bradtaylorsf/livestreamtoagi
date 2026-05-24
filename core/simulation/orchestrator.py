"""SimulationOrchestrator — drives simulations in seeded or autonomous mode.

Seeded mode: loops through phases from a YAML seed file.
Autonomous mode: trigger system drives conversations continuously until
duration/cost/kill-switch limits are reached.
"""

from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import yaml

from core.llm_client import OpenRouterClient
from core.models import FactionConfig, MemorySeedConfig, SimulationStatus
from core.simulation.clock import SimulationClock
from core.simulation.lifecycle import CostLimitExceededError, SimulationLifecycleBase
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
        max_cost_rolling: float | Decimal | None = None,
        rolling_window: timedelta | str | None = None,
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
        memory_seed: MemorySeedConfig | None = None,
        scenario_id: str | None = None,
        scenario_meta: dict[str, Any] | None = None,
        scenario_agents: list[str] | None = None,
        excluded_agents: list[str] | None = None,
        factions: list[dict[str, Any] | FactionConfig] | None = None,
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
        self.management_shadow = management_shadow
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
        if normalized_conversation_mode not in {"director", "embodied"}:
            raise ValueError("conversation_mode must be one of: director, embodied")
        self.conversation_mode = normalized_conversation_mode
        self.submitted_params = dict(submitted_params or {})
        self.source = source

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

        # Parse memory_seed block if present (CLI overrides take precedence,
        # so only fill from YAML when the field is unset).
        raw_seed = data.get("memory_seed")
        if raw_seed and self.memory_seed is None:
            self.memory_seed = MemorySeedConfig(**raw_seed)

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
        return d


class SimulationOrchestrator(SimulationLifecycleBase):
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

    def _build_phase_runner(
        self,
        sim_id: uuid.UUID,
        relationship_tracker: Any | None = None,
    ) -> PhaseRunner:
        """Create a PhaseRunner with all dependencies wired."""
        # Keep sim isolation here: event_generator.simulation_id = sim_id and
        # agent_state_manager.simulation_id = sim_id are assigned in the shared
        # lifecycle helper before any phase emits events or writes state. That
        # helper also performs the historical _rescope_redis(sim_id) step.
        self._scope_services_to_simulation(sim_id)
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

    async def run(self) -> None:
        """Execute the seeded simulation — create record, run phases, finalize."""
        # _start_lifecycle creates/attaches the run and calls init_core_memories.
        sim = await self._start_lifecycle(label="seeded")

        # Create RelationshipTracker and AssertionEngine now that sim_id is known
        relationship_tracker = self._build_relationship_tracker(sim.id)
        assertion_engine = self._build_assertion_engine()

        # Wire relationship tracker into reflection manager
        if relationship_tracker:
            self._reflection.set_relationship_tracker(relationship_tracker)

        reflection_scheduler = self._build_reflection_scheduler()
        runner = self._build_phase_runner(sim.id, relationship_tracker)
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
        sim = await self._start_lifecycle(label="autonomous")

        # Create RelationshipTracker and AssertionEngine now that sim_id is known
        relationship_tracker = self._build_relationship_tracker(sim.id)
        assertion_engine = self._build_assertion_engine()

        if relationship_tracker:
            self._reflection.set_relationship_tracker(relationship_tracker)

        reflection_scheduler = self._build_reflection_scheduler()
        runner = self._build_phase_runner(sim.id, relationship_tracker)
        await self._apply_initial_agent_energy()

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
