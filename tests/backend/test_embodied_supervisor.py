"""Tests for the embodied simulation supervisor lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE
from core.models import Simulation, SimulationStatus
from core.simulation.clock import SimulationClock
from core.simulation.embodied_supervisor import (
    EmbodiedSimulationConfig,
    EmbodiedSimulationSupervisor,
    MinecraftRuntime,
)


class FakeMinecraftRuntime:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.simulation_id: uuid.UUID | None = None
        self.run_id: str | None = None
        self.config: EmbodiedSimulationConfig | None = None
        self.returncode: int | None = None

    async def start(
        self,
        *,
        simulation_id: uuid.UUID,
        run_id: str,
        config: EmbodiedSimulationConfig,
    ) -> None:
        self.started = True
        self.simulation_id = simulation_id
        self.run_id = run_id
        self.config = config

    async def stop(self) -> None:
        self.stopped = True


def _simulation(sim_id: uuid.UUID, *, status: str = "running") -> Simulation:
    return Simulation(
        id=sim_id,
        name="embodied-test",
        description="test",
        config={"mode": "embodied"},
        status=status,
        started_at=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        agents_participated=["alpha", "vera"],
    )


def _agent_registry() -> MagicMock:
    registry = MagicMock()
    agent = SimpleNamespace(
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
    )
    registry.get_agent.return_value = agent
    return registry


def _repo(sim: Simulation) -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock(return_value=sim)
    repo.get = AsyncMock(return_value=sim)
    repo.update_status = AsyncMock(return_value=sim)
    repo.update_durations = AsyncMock(return_value=sim)
    repo.update_config = AsyncMock(return_value=sim)
    repo.update_agents_participated = AsyncMock(return_value=sim)
    repo.update_research_fields = AsyncMock(return_value=sim)
    repo.increment_stats = AsyncMock(return_value=sim)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("0"))
    repo.get_rolling_cost_from_events = AsyncMock(return_value=Decimal("0"))
    return repo


def _supervisor(
    *,
    config: EmbodiedSimulationConfig,
    sim: Simulation,
    runtime: FakeMinecraftRuntime,
    redis_get: Any = None,
    eval_runner: Any = None,
    report_runner: Any = None,
) -> tuple[EmbodiedSimulationSupervisor, MagicMock]:
    repo = _repo(sim)
    redis = MagicMock()
    redis.get = (
        AsyncMock(side_effect=redis_get) if redis_get is not None else AsyncMock(return_value=None)
    )
    reflection = MagicMock()
    reflection.run_6hour_reflection = AsyncMock()
    reflection.run_weekly_reflection = AsyncMock()
    display = MagicMock()

    supervisor = EmbodiedSimulationSupervisor(
        config=config,
        db=MagicMock(),
        redis_client=redis,
        simulation_repo=repo,
        config_loader=SimpleNamespace(config=SimpleNamespace()),
        agent_registry=_agent_registry(),
        event_bus=MagicMock(on=MagicMock(), off=MagicMock()),
        llm_client=MagicMock(),
        management=MagicMock(),
        context_assembler=MagicMock(),
        reflection_manager=reflection,
        display=display,
        runtime=runtime,
        eval_runner=eval_runner,
        report_runner=report_runner,
        clock=SimulationClock(speed_multiplier=config.speed_multiplier),
        sleep=AsyncMock(return_value=None),
    )
    return supervisor, repo


@pytest.mark.asyncio
async def test_experimental_run_uses_one_simulation_id_for_runtime_and_end_hooks() -> None:
    sim_id = uuid.uuid4()
    sim = _simulation(sim_id)
    runtime = FakeMinecraftRuntime()
    eval_runner = AsyncMock()
    report_runner = AsyncMock()
    config = EmbodiedSimulationConfig(
        name="experimental",
        run_mode="experimental",
        agents=["alpha", "vera"],
        duration=timedelta(seconds=2),
        tick_seconds=1,
    )
    supervisor, repo = _supervisor(
        config=config,
        sim=sim,
        runtime=runtime,
        eval_runner=eval_runner,
        report_runner=report_runner,
    )

    await supervisor.run()

    assert runtime.started is True
    assert runtime.stopped is True
    assert runtime.simulation_id == sim_id
    assert runtime.run_id == str(sim_id)
    eval_runner.assert_awaited_once_with(sim_id)
    report_runner.assert_awaited_once_with(sim_id)
    repo.update_status.assert_awaited()
    assert repo.update_status.call_args.args[1] == SimulationStatus.completed.value


@pytest.mark.asyncio
async def test_persistent_run_has_no_duration_stop_and_stops_on_kill_switch() -> None:
    sim_id = uuid.uuid4()
    sim = _simulation(sim_id)
    runtime = FakeMinecraftRuntime()
    config = EmbodiedSimulationConfig(
        name="persistent",
        run_mode="persistent",
        agents=["alpha", "vera"],
        duration=None,
        tick_seconds=1,
        run_end_hooks=False,
    )
    supervisor, repo = _supervisor(
        config=config,
        sim=sim,
        runtime=runtime,
        redis_get=[None, KILL_SWITCH_ACTIVE_VALUE],
    )

    await supervisor.run()

    assert runtime.started is True
    assert runtime.stopped is True
    assert supervisor.clock.elapsed() > timedelta(seconds=1)
    assert repo.update_status.call_args.args[1] == SimulationStatus.cancelled.value
    assert repo.update_status.call_args.kwargs["error_log"]["stop_reason"] == "kill_switch"


@pytest.mark.asyncio
async def test_cost_limit_cancels_embodied_run_and_stops_runtime() -> None:
    sim_id = uuid.uuid4()
    sim = _simulation(sim_id)
    runtime = FakeMinecraftRuntime()
    config = EmbodiedSimulationConfig(
        name="cost",
        run_mode="persistent",
        agents=["alpha", "vera"],
        max_cost=0.01,
        tick_seconds=1,
        run_end_hooks=False,
    )
    supervisor, repo = _supervisor(config=config, sim=sim, runtime=runtime)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("1.00"))

    await supervisor.run()

    assert runtime.stopped is True
    assert repo.update_status.call_args.args[1] == SimulationStatus.cancelled.value
    assert repo.update_status.call_args.kwargs["error_log"]["reason"] == "cost_limit_exceeded"


def test_minecraft_runtime_env_contains_all_run_id_aliases() -> None:
    sim_id = uuid.uuid4()
    runtime = MinecraftRuntime()
    config = EmbodiedSimulationConfig(
        name="env",
        run_mode="experimental",
        agents=["alpha"],
        duration=timedelta(minutes=1),
    )

    env = runtime._run_env(simulation_id=sim_id, run_id=str(sim_id), config=config)

    assert env["MINECRAFT_SIMULATION_ID"] == str(sim_id)
    assert env["MC_SIMULATION_ID"] == str(sim_id)
    assert env["LTAG_SIMULATION_ID"] == str(sim_id)
    assert env["EMBODIED_RUN_ID"] == str(sim_id)
    assert env["LTAG_RUN_ID"] == str(sim_id)
    assert env["MC_SIM_LOWLEVEL"] == "1"
