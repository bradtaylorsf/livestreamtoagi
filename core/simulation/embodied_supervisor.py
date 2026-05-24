"""Embodied Minecraft simulation supervisor lifecycle."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.llm_client import OpenRouterClient
from core.models import FactionConfig, MemorySeedConfig, SimulationStatus
from core.simulation.clock import SimulationClock
from core.simulation.display import SimulationDisplay
from core.simulation.lifecycle import CostLimitExceededError, SimulationLifecycleBase
from core.simulation.orchestrator import SimulationConfig

if TYPE_CHECKING:
    import uuid

    from core.agent_registry import AgentRegistry
    from core.bootstrap import Services
    from core.config_loader import ConfigLoader
    from core.context_assembly import ContextAssembler
    from core.database import Database
    from core.event_bus import EventBus
    from core.management import Management
    from core.memory.compaction import MemoryCompactor
    from core.memory.reflection import ReflectionManager
    from core.redis_client import RedisClient
    from core.repos.memory_repo import MemoryRepo
    from core.repos.relationship_repo import RelationshipRepo
    from core.repos.simulation_repo import SimulationRepo

logger = logging.getLogger(__name__)

RunMode = Literal["persistent", "experimental"]
GoalPredicate = Callable[["EmbodiedSimulationSupervisor"], bool | Awaitable[bool]]


class EmbodiedSimulationConfig(SimulationConfig):
    """Run-spec-style config for embodied Minecraft runs."""

    def __init__(
        self,
        *,
        name: str,
        run_mode: RunMode,
        description: str | None = None,
        agents: list[str],
        max_cost: float = 10.0,
        max_cost_rolling: float | Decimal | None = None,
        rolling_window: timedelta | str | None = None,
        duration: timedelta | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        management_shadow: bool = True,
        existing_sim_id: str | None = None,
        hypothesis: str | None = None,
        auto_draft_learnings: bool = False,
        memory_seed: MemorySeedConfig | None = None,
        factions: list[dict[str, Any] | FactionConfig] | None = None,
        goal_predicate: str | GoalPredicate | None = None,
        world_config: dict[str, Any] | None = None,
        runtime_args: list[str] | None = None,
        tick_seconds: float = 5.0,
        end_eval_suite: str = "quick",
        run_end_hooks: bool = True,
        speed_multiplier: float = 1.0,
        submitted_params: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> None:
        if run_mode not in {"persistent", "experimental"}:
            raise ValueError("run_mode must be one of: persistent, experimental")
        if tick_seconds <= 0:
            raise ValueError("tick_seconds must be greater than zero")
        super().__init__(
            name=name,
            description=description,
            seed_file=None,
            agents=agents,
            max_cost=max_cost,
            max_cost_rolling=max_cost_rolling,
            rolling_window=rolling_window,
            speed="normal",
            speed_multiplier=speed_multiplier,
            duration=duration,
            dry_run=dry_run,
            verbose=verbose,
            management_shadow=management_shadow,
            existing_sim_id=existing_sim_id,
            hypothesis=hypothesis,
            auto_draft_learnings=auto_draft_learnings,
            memory_seed=memory_seed,
            factions=factions,
            conversation_mode="embodied",
            submitted_params=submitted_params,
            source=source,
        )
        self.run_mode = run_mode
        self.goal_predicate = goal_predicate
        self.world_config = dict(world_config or {})
        self.runtime_args = list(runtime_args or [])
        self.tick_seconds = float(tick_seconds)
        self.end_eval_suite = end_eval_suite
        self.run_end_hooks = run_end_hooks

    @property
    def mode(self) -> str:
        return "embodied"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "mode": "embodied",
                "run_mode": self.run_mode,
                "tick_seconds": self.tick_seconds,
                "end_eval_suite": self.end_eval_suite,
                "run_end_hooks": self.run_end_hooks,
            }
        )
        if self.goal_predicate is not None:
            data["goal_predicate"] = (
                self.goal_predicate
                if isinstance(self.goal_predicate, str)
                else getattr(self.goal_predicate, "__name__", "callable")
            )
        if self.world_config:
            data["world_config"] = self.world_config
        if self.runtime_args:
            data["runtime_args"] = self.runtime_args
        return data


@dataclass
class MinecraftRuntime:
    """Async wrapper around the existing low-level Minecraft soak harness."""

    script_path: Path | None = None
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    persistent_duration_hours: float = 87600.0
    process: asyncio.subprocess.Process | None = field(default=None, init=False)
    last_env: dict[str, str] = field(default_factory=dict, init=False)
    last_args: list[str] = field(default_factory=list, init=False)

    async def start(
        self,
        *,
        simulation_id: uuid.UUID,
        run_id: str,
        config: EmbodiedSimulationConfig,
    ) -> None:
        if self.process is not None and self.process.returncode is None:
            raise RuntimeError("MinecraftRuntime is already running")

        script = self.script_path or self.project_root / "scripts" / "minecraft" / "soak.sh"
        args = [str(script), *self._duration_args(config), *config.runtime_args]
        if config.dry_run and "--dry-run" not in args:
            args.append("--dry-run")

        env = os.environ.copy()
        env.update(self._run_env(simulation_id=simulation_id, run_id=run_id, config=config))
        self.last_env = env
        self.last_args = args

        self.process = await asyncio.create_subprocess_exec(
            "bash",
            *args,
            cwd=str(self.project_root),
            env=env,
            start_new_session=True,
        )

    @property
    def returncode(self) -> int | None:
        return None if self.process is None else self.process.returncode

    async def stop(self, *, timeout: float = 20.0) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except TimeoutError:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except PermissionError:
                self.process.kill()
            await self.process.wait()

    def _duration_args(self, config: EmbodiedSimulationConfig) -> list[str]:
        if config.duration is not None:
            hours = config.duration.total_seconds() / 3600.0
        elif config.run_mode == "persistent":
            hours = self.persistent_duration_hours
        else:
            hours = 2.0
        return ["--duration-hours", f"{hours:.6g}"]

    def _run_env(
        self,
        *,
        simulation_id: uuid.UUID,
        run_id: str,
        config: EmbodiedSimulationConfig,
    ) -> dict[str, str]:
        sim_text = str(simulation_id)
        env = {
            "MC_SIM_LOWLEVEL": "1",
            "MINECRAFT_SIMULATION_ID": sim_text,
            "MC_SIMULATION_ID": sim_text,
            "LTAG_SIMULATION_ID": sim_text,
            "EMBODIED_RUN_ID": run_id,
            "LTAG_RUN_ID": run_id,
        }
        world_env = config.world_config.get("env")
        if isinstance(world_env, dict):
            env.update({str(k): str(v) for k, v in world_env.items() if v is not None})
        world_config_path = config.world_config.get("world_config_path")
        if world_config_path:
            env["WORLD_CONFIG"] = str(world_config_path)
        server_dir = config.world_config.get("server_dir")
        if server_dir:
            env["SERVER_DIR"] = str(server_dir)
        return env


class EmbodiedSimulationSupervisor(SimulationLifecycleBase):
    """Coordinates a durable simulation lifecycle around Minecraft runtime."""

    def __init__(
        self,
        *,
        config: EmbodiedSimulationConfig,
        db: Database,
        redis_client: RedisClient,
        simulation_repo: SimulationRepo,
        config_loader: ConfigLoader,
        agent_registry: AgentRegistry,
        event_bus: EventBus,
        llm_client: OpenRouterClient,
        management: Management,
        context_assembler: ContextAssembler | None,
        reflection_manager: ReflectionManager,
        memory_repo: MemoryRepo | None = None,
        compactor: MemoryCompactor | None = None,
        display: SimulationDisplay | None = None,
        services: Services | None = None,
        clock: SimulationClock | None = None,
        relationship_repo: RelationshipRepo | None = None,
        runtime: MinecraftRuntime | None = None,
        eval_runner: Callable[[uuid.UUID], Any | Awaitable[Any]] | None = None,
        report_runner: Callable[[uuid.UUID], Any | Awaitable[Any]] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
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
        self._conversation_repo = None
        self._archival = None
        self._compactor = (
            compactor if compactor is not None else getattr(services, "compactor", None)
        )
        self._memory_repo = memory_repo
        self._proximity = None
        self._triggers = None
        self._selection_logger = None
        self._reflection = reflection_manager
        self._display = display or SimulationDisplay(
            verbose=config.verbose,
            agent_registry=agent_registry,
        )
        self._services = services
        self._relationship_repo = relationship_repo
        self._simulation_id: uuid.UUID | None = None
        self._start_time: float = 0.0
        self._started_at = None
        self._total_cost = Decimal("0")
        self._cancelled = False
        self._errors: list[dict[str, Any]] = []
        self.clock = clock or SimulationClock(speed_multiplier=config.speed_multiplier)
        self._runtime = runtime or MinecraftRuntime()
        self._eval_runner = eval_runner
        self._report_runner = report_runner
        self._sleep = sleep

    async def run(self) -> None:
        sim = await self._start_lifecycle(label="embodied")
        run_id = str(sim.id)
        reflection_scheduler = self._build_reflection_scheduler()
        stop_reason = "completed"

        try:
            await self._runtime.start(
                simulation_id=sim.id,
                run_id=run_id,
                config=self._config,
            )
            stop_reason = await self._monitor(reflection_scheduler)
            await self._runtime.stop()
            await self._run_eval_hook()
            status = (
                SimulationStatus.cancelled
                if stop_reason in {"cancelled", "kill_switch"}
                else SimulationStatus.completed
            )
            await self._finalize(status, error_log={"stop_reason": stop_reason})
            await self._run_report_hook()
        except CostLimitExceededError:
            await self._runtime.stop()
            logger.warning("Cost limit exceeded ($%s), stopping embodied run", self._total_cost)
            self._display.show_cost_exceeded(self._total_cost, self._config.max_cost)
            await self._finalize(
                SimulationStatus.cancelled,
                error_log={"reason": "cost_limit_exceeded", "total_cost": str(self._total_cost)},
            )
            await self._run_report_hook()
        except Exception as exc:
            await self._runtime.stop()
            logger.exception("Embodied simulation failed")
            await self._finalize(
                SimulationStatus.failed,
                error_log={"reason": str(exc)},
            )
            raise

    async def _monitor(self, reflection_scheduler: Any) -> str:
        while True:
            await self._sleep(self._config.tick_seconds)
            self._advance_clock()

            if not self._config.dry_run:
                reflection_results = await reflection_scheduler.check_and_run_all(
                    self._config.agents
                )
                for result in reflection_results:
                    if result.journal_entry:
                        self._display.show_reflection_triggered(
                            result.journal_entry.agent_id,
                            result.journal_entry.reflection_type,
                            self.clock.now(),
                        )
                await self._check_cost_limit()

            stop_reason = await self._stop_reason()
            if stop_reason is not None:
                return stop_reason

            runtime_returncode = self._runtime.returncode
            if runtime_returncode is not None:
                if runtime_returncode == 0:
                    return "runtime_completed"
                raise RuntimeError(f"Minecraft runtime exited with status {runtime_returncode}")

    def _advance_clock(self) -> None:
        multiplier = self._config.speed_multiplier if self._config.speed_multiplier > 0 else 1.0
        self.clock.advance(timedelta(seconds=self._config.tick_seconds * multiplier))

    async def _stop_reason(self) -> str | None:
        if self._cancelled:
            return "cancelled"
        if self._config.duration and self.clock.elapsed() >= self._config.duration:
            logger.info("Embodied duration limit reached (%s)", self._config.duration)
            return "duration"
        if await self._goal_reached():
            return "goal"
        if self._redis:
            kill = await self._redis.get(KILL_SWITCH_KEY)
            if kill in {KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_ACTIVE_VALUE.encode()}:
                logger.info("Kill switch activated; stopping embodied simulation")
                return "kill_switch"
        return None

    async def _goal_reached(self) -> bool:
        predicate = self._config.goal_predicate
        if predicate is None or isinstance(predicate, str):
            return False
        result = predicate(self)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    async def _run_eval_hook(self) -> None:
        if self._simulation_id is None or self._config.dry_run or not self._config.run_end_hooks:
            return
        if self._eval_runner is not None:
            await _maybe_await(self._eval_runner(self._simulation_id))
            return
        await self._run_hook_subprocess(
            [
                sys.executable,
                "scripts/run_eval.py",
                "--simulation-id",
                str(self._simulation_id),
                "--suite",
                self._config.end_eval_suite,
            ],
            "embodied end eval",
        )

    async def _run_report_hook(self) -> None:
        if self._simulation_id is None or self._config.dry_run or not self._config.run_end_hooks:
            return
        if self._report_runner is not None:
            await _maybe_await(self._report_runner(self._simulation_id))
            return
        report_dir = Path("logs") / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        output = report_dir / f"{self._simulation_id}.md"
        await self._run_hook_subprocess(
            [
                sys.executable,
                "scripts/report_simulation.py",
                "--simulation-id",
                str(self._simulation_id),
                "--format",
                "markdown",
                "--scorecard",
                "--output",
                str(output),
            ],
            "embodied end report",
        )

    async def _run_hook_subprocess(self, cmd: list[str], label: str) -> None:
        logger.info("Running %s: %s", label, " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(*cmd)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"{label} failed with status {rc}")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
