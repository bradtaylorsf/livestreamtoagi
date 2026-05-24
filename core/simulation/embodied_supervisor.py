"""Lifecycle supervisor for embodied Minecraft simulation runs."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.models import RunMode, SimulationCreate, SimulationStatus
from core.simulation.clock import SimulationClock
from core.simulation.orchestrator import CostLimitExceededError, SimulationConfig

logger = logging.getLogger(__name__)

EmbodiedCommandRunner = Callable[
    [list[str], dict[str, str], Path, "EmbodiedSimulationSupervisor"],
    Awaitable[int],
]
EmbodiedHook = Callable[["EmbodiedSimulationSupervisor"], Awaitable[None]]


@dataclass
class EmbodiedSupervisorResult:
    """Summary of one embodied supervisor run."""

    simulation_id: uuid.UUID
    run_id: str
    status: SimulationStatus
    stop_reason: str
    run_dir: Path
    launcher_commands: list[list[str]] = field(default_factory=list)


def _duration_hours(duration: timedelta | None) -> str | None:
    if duration is None:
        return None
    hours = duration.total_seconds() / 3600
    return f"{hours:.6f}".rstrip("0").rstrip(".")


async def _default_command_runner(
    command: list[str],
    env: dict[str, str],
    cwd: Path,
    supervisor: EmbodiedSimulationSupervisor,
) -> int:
    """Run a child command while the supervisor polls kill/cost hooks."""
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=env,
    )
    try:
        while True:
            try:
                return await asyncio.wait_for(proc.wait(), timeout=supervisor.poll_interval_seconds)
            except TimeoutError:
                if await supervisor.should_stop():
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=10)
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                    return -15
                await supervisor.cadence_tick()
    finally:
        if proc.returncode is None:
            proc.terminate()


async def _default_subprocess_hook(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


class EmbodiedSimulationSupervisor:
    """Coordinate a Minecraft/Mindcraft run under one durable simulation id.

    The supervisor owns the DB simulation row and exports the run/simulation ids
    into the lower-level Minecraft harness. The harness still starts Paper,
    Mindcraft bots, and timeline capture; this class supplies lifecycle policy:
    cadence, kill/cost checks, stop reason, and end hooks.
    """

    def __init__(
        self,
        *,
        config: SimulationConfig,
        simulation_repo: Any,
        redis_client: Any | None = None,
        project_root: Path | None = None,
        clock: SimulationClock | None = None,
        command_runner: EmbodiedCommandRunner | None = None,
        reflection_hook: EmbodiedHook | None = None,
        eval_hook: EmbodiedHook | None = None,
        report_hook: EmbodiedHook | None = None,
        run_eval: bool = True,
        run_report: bool = True,
        poll_interval_seconds: float = 5.0,
        run_id: str | None = None,
        run_dir: Path | None = None,
        max_launcher_cycles: int | None = None,
    ) -> None:
        self.config = config
        self.simulation_repo = simulation_repo
        self.redis = redis_client
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.clock = clock or SimulationClock(speed_multiplier=config.speed_multiplier)
        self.command_runner = command_runner or _default_command_runner
        self.reflection_hook = reflection_hook
        self.eval_hook = eval_hook
        self.report_hook = report_hook
        self.run_eval = run_eval
        self.run_report = run_report
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.run_id = run_id or os.environ.get("LTAG_RUN_ID")
        self.run_dir = run_dir
        self.max_launcher_cycles = max_launcher_cycles
        self.simulation_id: uuid.UUID | None = None
        self.stop_reason: str | None = None
        self._cancelled = False
        self._started_at: datetime | None = None
        self._launcher_commands: list[list[str]] = []

    @property
    def is_persistent(self) -> bool:
        return self.config.run_mode == RunMode.persistent

    def cancel(self, reason: str = "cancelled") -> None:
        self._cancelled = True
        self._set_stop_reason(reason)

    async def run(self) -> EmbodiedSupervisorResult:
        sim = await self._create_or_attach_simulation()
        self.simulation_id = sim.id
        self._started_at = sim.started_at or datetime.now(UTC)
        self.run_id = self.run_id or f"run-{sim.id}"
        self.run_dir = self.run_dir or self._default_run_dir()

        await self._persist_supervisor_config("running")
        env = self._child_environment()

        status = SimulationStatus.completed
        launcher_cycles = 0
        if self.config.dry_run:
            self._set_stop_reason("dry_run")
            await self._finalize(status)
            return EmbodiedSupervisorResult(
                simulation_id=self.simulation_id,
                run_id=self.run_id,
                status=status,
                stop_reason=self.stop_reason,
                run_dir=self.run_dir,
                launcher_commands=[],
            )
        try:
            while True:
                if await self.should_stop():
                    status = SimulationStatus.cancelled
                    break
                command = self._minecraft_command()
                self._launcher_commands.append(command)
                return_code = await self.command_runner(command, env, self.project_root, self)
                launcher_cycles += 1
                if return_code != 0:
                    status = (
                        SimulationStatus.cancelled
                        if self.stop_reason in {"cancelled", "kill_switch", "cost_cap", "duration_reached", "goal_reached"}
                        else SimulationStatus.failed
                    )
                    if self.stop_reason is None:
                        self._set_stop_reason(f"minecraft_exit_{return_code}")
                    break
                if not self.is_persistent:
                    self._set_stop_reason(self.stop_reason or "completed")
                    break
                if self.max_launcher_cycles is not None and launcher_cycles >= self.max_launcher_cycles:
                    self._set_stop_reason("cycle_limit")
                    break

            if status == SimulationStatus.completed and self.stop_reason in {
                "cancelled",
                "kill_switch",
                "cost_cap",
                "duration_reached",
                "goal_reached",
            }:
                status = SimulationStatus.cancelled
        except CostLimitExceededError:
            self._set_stop_reason("cost_cap")
            status = SimulationStatus.cancelled
        except Exception as exc:
            self._set_stop_reason("supervisor_error")
            await self._finalize(SimulationStatus.failed, error_log={"reason": str(exc)})
            raise

        await self._finalize(status)
        if status in {SimulationStatus.completed, SimulationStatus.cancelled}:
            await self._run_end_hooks()
        return EmbodiedSupervisorResult(
            simulation_id=self.simulation_id,
            run_id=self.run_id,
            status=status,
            stop_reason=self.stop_reason or status.value,
            run_dir=self.run_dir,
            launcher_commands=list(self._launcher_commands),
        )

    async def cadence_tick(self) -> None:
        self.clock.advance(timedelta(seconds=self.poll_interval_seconds))
        if self.reflection_hook is not None:
            await self.reflection_hook(self)

    async def should_stop(self) -> bool:
        if self._cancelled:
            self._set_stop_reason("cancelled")
            return True
        if await self._kill_switch_active():
            self._set_stop_reason("kill_switch")
            return True
        await self._check_cost_limit()
        if not self.is_persistent and self.config.duration and self.clock.elapsed() >= self.config.duration:
            self._set_stop_reason("duration_reached")
            return True
        if not self.is_persistent and await self._experimental_goal_reached():
            self._set_stop_reason("goal_reached")
            return True
        return False

    async def _create_or_attach_simulation(self) -> Any:
        if self.config.existing_sim_id:
            sim_uuid = uuid.UUID(self.config.existing_sim_id)
            sim = await self.simulation_repo.get(sim_uuid)
            if sim is None:
                raise RuntimeError(f"existing embodied simulation {sim_uuid} not found")
            await self.simulation_repo.update_status(sim_uuid, SimulationStatus.running.value)
            return await self.simulation_repo.get(sim_uuid) or sim

        if self.is_persistent and hasattr(self.simulation_repo, "get_by_name"):
            sim = await self.simulation_repo.get_by_name(self.config.name)
            if sim is not None and sim.status == SimulationStatus.running:
                await self.simulation_repo.update_config(sim.id, self._config_snapshot("attached"))
                return sim

        return await self.simulation_repo.create(
            SimulationCreate(
                name=self.config.name,
                description=self.config.description,
                config=self._config_snapshot("created"),
                status=SimulationStatus.running,
                agents_participated=self.config.agents,
                model_versions={},
                hypothesis=self.config.hypothesis,
                factions=[f.model_dump() for f in self.config.factions],
            )
        )

    def _config_snapshot(self, lifecycle: str) -> dict[str, Any]:
        snapshot = self.config.to_dict()
        snapshot["embodied_supervisor"] = {
            "enabled": True,
            "lifecycle": lifecycle,
            "run_id": self.run_id,
            "simulation_id": str(self.simulation_id) if self.simulation_id else None,
            "run_dir": str(self.run_dir) if self.run_dir else None,
            "conversation_mode": self.config.conversation_mode,
            "poll_interval_seconds": self.poll_interval_seconds,
            "stop_reason": self.stop_reason,
        }
        return snapshot

    async def _persist_supervisor_config(self, lifecycle: str) -> None:
        if self.simulation_id is None:
            return
        await self.simulation_repo.update_config(self.simulation_id, self._config_snapshot(lifecycle))

    def _default_run_dir(self) -> Path:
        assert self.simulation_id is not None
        return self.project_root / "logs" / "embodied" / self.run_id_or_default()

    def run_id_or_default(self) -> str:
        if self.run_id:
            return self.run_id
        if self.simulation_id is not None:
            return f"run-{self.simulation_id}"
        return f"run-{uuid.uuid4()}"

    def _child_environment(self) -> dict[str, str]:
        assert self.simulation_id is not None
        assert self.run_id is not None
        assert self.run_dir is not None
        env = dict(os.environ)
        env.update(
            {
                "LTAG_RUN_ID": self.run_id,
                "LTAG_SIMULATION_ID": str(self.simulation_id),
                "MC_RUN_DIR": str(self.run_dir),
                "CONVERSATION_MODE": self.config.conversation_mode,
                "EMBODIED_SUPERVISOR": "1",
            }
        )
        if self.config.conversation_mode == "director_v2":
            env["DIRECTOR_V2_GATE"] = "1"
            env["SOAK_PROFILE"] = "director_v2"
        if self.config.agents:
            env["SOAK_BOTS"] = " ".join(self.config.agents)
            env["LTAG_SIM_AGENTS"] = " ".join(self.config.agents)
        duration_hours = _duration_hours(self.config.duration)
        if duration_hours is not None and not self.is_persistent:
            env["SOAK_DURATION_HOURS"] = duration_hours
        return env

    def _minecraft_command(self) -> list[str]:
        command = [str(self.project_root / "scripts" / "minecraft" / "soak.sh")]
        if self.config.conversation_mode == "director_v2":
            command.extend(["--profile", "director_v2"])
        duration_hours = _duration_hours(self.config.duration)
        if duration_hours is not None and not self.is_persistent:
            command.extend(["--duration-hours", duration_hours])
        if self.run_dir is not None:
            command.extend(["--log-dir", str(self.run_dir)])
        return command

    async def _kill_switch_active(self) -> bool:
        if self.redis is None:
            return False
        value = await self.redis.get(KILL_SWITCH_KEY)
        return value == KILL_SWITCH_ACTIVE_VALUE

    async def _check_cost_limit(self) -> None:
        if self.simulation_id is None:
            return
        total = Decimal("0")
        if hasattr(self.simulation_repo, "get_total_cost_from_events"):
            total = await self.simulation_repo.get_total_cost_from_events(self.simulation_id)
        if total > self.config.max_cost:
            raise CostLimitExceededError(
                f"Embodied run cost ${total} exceeds limit ${self.config.max_cost}"
            )
        if self.config.max_cost_rolling is not None and self.config.rolling_window is not None:
            rolling = await self.simulation_repo.get_rolling_cost_from_events(
                self.simulation_id,
                self.config.rolling_window,
            )
            if rolling > self.config.max_cost_rolling:
                raise CostLimitExceededError(
                    f"Embodied rolling cost ${rolling} exceeds limit ${self.config.max_cost_rolling}"
                )

    async def _experimental_goal_reached(self) -> bool:
        goal = self.config.experimental_goal
        if goal is None or self.simulation_id is None:
            return False
        sim = await self.simulation_repo.get(self.simulation_id)
        if sim is None:
            return False
        values = {
            "turns": int(getattr(sim, "total_turns", 0) or 0),
            "artifacts": int(getattr(sim, "total_artifacts", 0) or 0),
            "phases_complete": int((getattr(sim, "config", {}) or {}).get("phases_completed", 0)),
        }
        return values.get(goal.kind, 0) >= goal.target

    def _set_stop_reason(self, reason: str) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason

    async def _finalize(
        self,
        status: SimulationStatus,
        *,
        error_log: dict[str, Any] | None = None,
    ) -> None:
        if self.simulation_id is None:
            return
        completed_at = datetime.now(UTC)
        real_duration = (
            completed_at - self._started_at
            if self._started_at is not None
            else timedelta(seconds=0)
        )
        error_payload = error_log
        if error_payload is None and self.stop_reason not in {None, "completed"}:
            error_payload = {"reason": self.stop_reason}
        await self.simulation_repo.update_status(
            self.simulation_id,
            status.value,
            completed_at=completed_at,
            error_log=error_payload,
        )
        if hasattr(self.simulation_repo, "update_durations"):
            await self.simulation_repo.update_durations(
                self.simulation_id,
                simulated_duration=self.clock.elapsed(),
                real_duration=real_duration,
            )
        await self._persist_supervisor_config(status.value)

    async def _run_end_hooks(self) -> None:
        if self.run_eval:
            if self.eval_hook is not None:
                await self.eval_hook(self)
            else:
                await self._run_default_eval()
        if self.run_report:
            if self.report_hook is not None:
                await self.report_hook(self)
            else:
                await self._run_default_report()

    async def _run_default_eval(self) -> None:
        if self.simulation_id is None:
            return
        env = self._child_environment()
        command = [
            str(self.project_root / ".venv" / "bin" / "python"),
            str(self.project_root / "scripts" / "run_eval.py"),
            "--simulation-id",
            str(self.simulation_id),
            "--suite",
            os.environ.get("EMBODIED_SUPERVISOR_EVAL_SUITE", "quick"),
        ]
        try:
            await _default_subprocess_hook(command, cwd=self.project_root, env=env)
        except Exception:
            logger.warning("Embodied supervisor eval hook failed", exc_info=True)

    async def _run_default_report(self) -> None:
        if self.simulation_id is None or self.run_dir is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        env = self._child_environment()
        command = [
            str(self.project_root / ".venv" / "bin" / "python"),
            str(self.project_root / "scripts" / "report_simulation.py"),
            "--simulation-id",
            str(self.simulation_id),
            "--format",
            "markdown",
            "--output",
            str(self.run_dir / "simulation-report.md"),
        ]
        try:
            await _default_subprocess_hook(command, cwd=self.project_root, env=env)
        except Exception:
            logger.warning("Embodied supervisor report hook failed", exc_info=True)
