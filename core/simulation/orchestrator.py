"""SimulationOrchestrator — drives simulations in seeded or autonomous mode.

Seeded mode: loops through phases from a YAML seed file.
Autonomous mode: trigger system drives conversations continuously until
duration/cost/kill-switch limits are reached.
"""

from __future__ import annotations

import logging
import random
import re
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
        overseer_shadow: bool = True,
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
        self.overseer_shadow = overseer_shadow
        self.phases: list[Phase] = []

    @property
    def mode(self) -> str:
        """Return 'seeded' if a seed file is set, otherwise 'autonomous'."""
        return "seeded" if self.seed_file else "autonomous"

    def load_seed_file(self) -> None:
        """Parse the YAML seed file into Phase objects."""
        if not self.seed_file:
            return

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
            "overseer_shadow": self.overseer_shadow,
        }
        if self.duration is not None:
            d["duration_seconds"] = self.duration.total_seconds()
        if self.phases:
            d["phase_count"] = len(self.phases)
            d["phase_names"] = [p.name for p in self.phases]
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
        clock: SimulationClock | None = None,
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

    def _build_phase_runner(self, sim_id: uuid.UUID) -> PhaseRunner:
        """Create a PhaseRunner with all dependencies wired."""
        return PhaseRunner(
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
            simulation_id=sim_id,
            agents=self._config.agents,
            dry_run=self._config.dry_run,
            services=self._services,
            clock=self.clock,
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

    async def run(self) -> None:
        """Execute the seeded simulation — create record, run phases, finalize."""
        self._start_time = time.monotonic()

        # Create simulation record (include clock state in config snapshot)
        config_snapshot = {**self._config.to_dict(), "clock_state": self.clock.to_dict()}
        sim = await self._sim_repo.create(SimulationCreate(
            name=self._config.name,
            description=self._config.description,
            config=config_snapshot,
            status=SimulationStatus.running,
            agents_participated=self._config.agents,
        ))
        self._simulation_id = sim.id
        logger.info("Created simulation %s (%s)", sim.id, sim.name)

        self._display.show_simulation_start(sim, self._config)

        reflection_scheduler = self._build_reflection_scheduler()
        runner = self._build_phase_runner(sim.id)

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

    async def run_autonomous(self) -> None:
        """Run in autonomous mode — trigger system drives all conversations."""
        self._start_time = time.monotonic()

        config_snapshot = {**self._config.to_dict(), "clock_state": self.clock.to_dict()}
        sim = await self._sim_repo.create(SimulationCreate(
            name=self._config.name,
            description=self._config.description,
            config=config_snapshot,
            status=SimulationStatus.running,
            agents_participated=self._config.agents,
        ))
        self._simulation_id = sim.id
        logger.info(
            "Created autonomous simulation %s (%s)", sim.id, sim.name
        )

        self._display.show_simulation_start(sim, self._config)

        reflection_scheduler = self._build_reflection_scheduler()
        runner = self._build_phase_runner(sim.id)

        conversation_num = 0
        current_day = self.clock.simulated_day()
        day_stats: dict[str, Any] = {"conversations": 0, "cost": Decimal("0"), "tools": 0}

        self._display.show_day_boundary(current_day, {})

        try:
            while not self._terminated():
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
                        conversations=result.conversations or (
                            1 if result.turns > 0 else 0
                        ),
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
                    reflection_results = (
                        await reflection_scheduler.check_and_run_all(
                            self._config.agents
                        )
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

            # Final day stats
            self._display.show_day_boundary(
                self.clock.simulated_day(), day_stats
            )
            status = (
                SimulationStatus.cancelled
                if self._cancelled
                else SimulationStatus.completed
            )
            await self._finalize(status)

        except CostLimitExceededError:
            logger.warning(
                "Cost limit exceeded ($%s), stopping simulation",
                self._total_cost,
            )
            self._display.show_cost_exceeded(
                self._total_cost, self._config.max_cost
            )
            await self._finalize(
                SimulationStatus.cancelled,
                error_log={
                    "reason": "cost_limit_exceeded",
                    "total_cost": str(self._total_cost),
                },
            )

        except Exception as exc:
            logger.exception("Autonomous simulation failed")
            await self._finalize(
                SimulationStatus.failed,
                error_log={"reason": str(exc)},
            )
            raise

    def _terminated(self) -> bool:
        """Check all termination conditions for autonomous mode."""
        if self._cancelled:
            return True
        # Duration limit
        if self._config.duration and self.clock.elapsed() >= self._config.duration:
            logger.info("Duration limit reached (%s)", self._config.duration)
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
        if self._config.speed_multiplier > 0 or self._config.mode == "autonomous":
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

        # Persist final clock state into config
        final_config = {**self._config.to_dict(), "clock_state": self.clock.to_dict()}
        await self._sim_repo.update_config(self._simulation_id, final_config)

        # Fetch final record for summary
        sim = await self._sim_repo.get(self._simulation_id)
        if sim:
            self._display.show_summary(sim, real_duration)
