"""SimulationOrchestrator — drives a full-day simulation through sequential phases.

Creates a simulation record, loops through phases from the seed file,
tracks stats incrementally, and handles graceful shutdown on Ctrl+C.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import yaml

from core.memory.reflection_scheduler import ReflectionScheduler
from core.models import SimulationCreate, SimulationStatus
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
    from core.llm_client import OpenRouterClient
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.compaction import MemoryCompactor
    from core.memory.reflection import ReflectionManager
    from core.overseer import Overseer
    from core.redis_client import RedisClient
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.memory_repo import MemoryRepo
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.display import SimulationDisplay

logger = logging.getLogger(__name__)


class CostLimitExceededError(Exception):
    """Raised when simulation spending exceeds --max-cost."""


class SimulationConfig:
    """Parsed CLI arguments and seed file contents."""

    def __init__(
        self,
        *,
        name: str,
        description: str | None = None,
        seed_file: str,
        agents: list[str],
        max_cost: float = 10.0,
        speed: str = "fast",
        speed_multiplier: float = 0,
        dry_run: bool = False,
        verbose: bool = False,
        overseer_shadow: bool = True,
    ) -> None:
        self.name = name
        self.description = description
        self.seed_file = seed_file
        self.agents = agents
        self.max_cost = Decimal(str(max_cost))
        self.speed = speed
        self.speed_multiplier = speed_multiplier
        self.dry_run = dry_run
        self.verbose = verbose
        self.overseer_shadow = overseer_shadow
        self.phases: list[Phase] = []

    def load_seed_file(self) -> None:
        """Parse the YAML seed file into Phase objects."""
        with open(self.seed_file) as f:
            data = yaml.safe_load(f)

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

            self.phases.append(Phase(
                name=entry.get("name", f"phase_{len(self.phases)}"),
                type=ptype,
                config=config,
                required_agents=required,
            ))

    def to_dict(self) -> dict[str, Any]:
        """Serialize config for DB snapshot."""
        return {
            "name": self.name,
            "description": self.description,
            "seed_file": self.seed_file,
            "agents": self.agents,
            "max_cost": str(self.max_cost),
            "speed": self.speed,
            "speed_multiplier": self.speed_multiplier,
            "dry_run": self.dry_run,
            "overseer_shadow": self.overseer_shadow,
            "phase_count": len(self.phases),
            "phase_names": [p.name for p in self.phases],
        }


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
        overseer: Overseer,
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
    ) -> None:
        self._config = config
        self._db = db
        self._redis = redis_client
        self._sim_repo = simulation_repo
        self._config_loader = config_loader
        self._agents = agent_registry
        self._event_bus = event_bus
        self._llm = llm_client
        self._overseer = overseer
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

        self._simulation_id: uuid.UUID | None = None
        self._start_time: float = 0.0
        self._total_cost = Decimal("0")
        self._cancelled = False
        self.clock = SimulationClock(speed_multiplier=config.speed_multiplier)

    @property
    def simulation_id(self) -> uuid.UUID | None:
        return self._simulation_id

    async def run(self) -> None:
        """Execute the full simulation — create record, run phases, finalize."""
        self._start_time = time.monotonic()

        # Create simulation record
        sim = await self._sim_repo.create(SimulationCreate(
            name=self._config.name,
            description=self._config.description,
            config=self._config.to_dict(),
            status=SimulationStatus.running,
            agents_participated=self._config.agents,
        ))
        self._simulation_id = sim.id
        logger.info("Created simulation %s (%s)", sim.id, sim.name)

        self._display.show_simulation_start(sim, self._config)

        # Build reflection scheduler from config (if available)
        reflection_kwargs: dict[str, int] = {}
        try:
            rc = self._config_loader.config.reflection
            if hasattr(rc, "six_hour_interval_hours") and isinstance(
                rc.six_hour_interval_hours, int
            ):
                reflection_kwargs = {
                    "six_hour_interval_hours": rc.six_hour_interval_hours,
                    "daily_hour": rc.daily_hour,
                    "weekly_day": rc.weekly_day,
                }
        except (AttributeError, TypeError):
            pass  # Use defaults
        reflection_scheduler = ReflectionScheduler(
            self.clock, self._reflection, **reflection_kwargs
        )

        # Build phase runner
        runner = PhaseRunner(
            config_loader=self._config_loader,
            agent_registry=self._agents,
            event_bus=self._event_bus,
            llm_client=self._llm,
            overseer=self._overseer,
            context_assembler=self._context,
            conversation_repo=self._conversation_repo,
            archival_memory=self._archival,
            proximity=self._proximity,
            trigger_system=self._triggers,
            selection_logger=self._selection_logger,
            reflection_manager=self._reflection,
            compactor=self._compactor,
            memory_repo=self._memory_repo,
            simulation_id=sim.id,
            agents=self._config.agents,
            dry_run=self._config.dry_run,
            services=self._services,
            clock=self.clock,
        )

        phases = self._config.phases
        total_phases = len(phases)

        try:
            for idx, phase in enumerate(phases):
                if self._cancelled:
                    break

                self._display.show_phase_start(phase.name, idx, total_phases)

                result = await runner.run_phase(phase)

                # Update DB stats
                if not self._config.dry_run:
                    await self._sim_repo.increment_stats(
                        sim.id,
                        conversations=result.conversations or (1 if result.turns > 0 else 0),
                        turns=result.turns,
                        tokens=result.tokens,
                        cost=result.cost,
                        artifacts=result.artifacts,
                        overseer_flags=result.overseer_flags,
                    )
                    if result.agents_participated:
                        await self._sim_repo.update_agents_participated(
                            sim.id, result.agents_participated
                        )

                self._total_cost += result.cost
                self._display.show_phase_complete(result, phase.name)

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
                    self._check_cost_limit()

            # Finalize
            status = SimulationStatus.cancelled if self._cancelled else SimulationStatus.completed
            await self._finalize(status)

        except CostLimitExceededError:
            logger.warning("Cost limit exceeded ($%s), stopping simulation", self._total_cost)
            self._display.show_cost_exceeded(self._total_cost, self._config.max_cost)
            await self._finalize(
                SimulationStatus.cancelled,
                error_log={"reason": "cost_limit_exceeded", "total_cost": str(self._total_cost)},
            )

        except Exception as exc:
            logger.exception("Simulation failed")
            await self._finalize(
                SimulationStatus.failed,
                error_log={"reason": str(exc)},
            )
            raise

    def cancel(self) -> None:
        """Signal the orchestrator to stop after the current phase."""
        self._cancelled = True

    def _check_cost_limit(self) -> None:
        """Raise CostLimitExceededError if spending exceeds max_cost."""
        if self._total_cost > self._config.max_cost:
            raise CostLimitExceededError(
                f"Total cost ${self._total_cost} exceeds limit ${self._config.max_cost}"
            )

    async def _finalize(
        self,
        status: SimulationStatus,
        *,
        error_log: dict[str, Any] | None = None,
    ) -> None:
        """Update the simulation record with final status and durations."""
        if self._simulation_id is None:
            return

        real_duration = timedelta(seconds=time.monotonic() - self._start_time)
        # Use clock elapsed time if speed_multiplier > 0, else fallback to phase count
        if self._config.speed_multiplier > 0:
            simulated_duration = self.clock.elapsed()
        else:
            simulated_duration = timedelta(hours=len(self._config.phases))

        await self._sim_repo.update_status(
            self._simulation_id,
            status.value,
            completed_at=datetime.now(UTC),
            error_log=error_log,
        )
        await self._sim_repo.update_durations(
            self._simulation_id,
            simulated_duration=simulated_duration,
            real_duration=real_duration,
        )

        # Fetch final record for summary
        sim = await self._sim_repo.get(self._simulation_id)
        if sim:
            self._display.show_summary(sim, real_duration)
