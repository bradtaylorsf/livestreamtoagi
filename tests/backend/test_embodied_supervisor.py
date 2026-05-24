"""Embodied simulation supervisor lifecycle coverage (#710)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.models import RunMode, SimulationStatus
from core.simulation.embodied_supervisor import EmbodiedSimulationSupervisor
from core.simulation.orchestrator import SimulationConfig


def _sim(sim_id: uuid.UUID, **overrides: Any) -> SimpleNamespace:
    base = {
        "id": sim_id,
        "name": "embodied-test",
        "status": SimulationStatus.running.value,
        "started_at": datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        "total_turns": 0,
        "total_artifacts": 0,
        "config": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _repo(sim: SimpleNamespace) -> SimpleNamespace:
    repo = SimpleNamespace()
    repo.create = AsyncMock(return_value=sim)
    repo.get = AsyncMock(return_value=sim)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.update_config = AsyncMock()
    repo.update_status = AsyncMock(return_value=sim)
    repo.update_durations = AsyncMock(return_value=sim)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("0"))
    repo.get_rolling_cost_from_events = AsyncMock(return_value=Decimal("0"))
    return repo


def _experimental_config(**overrides: Any) -> SimulationConfig:
    kwargs: dict[str, Any] = {
        "name": "embodied-test",
        "agents": ["vera", "rex"],
        "run_mode": RunMode.experimental,
        "duration": timedelta(minutes=15),
        "conversation_mode": "embodied",
        "max_cost": 1,
    }
    kwargs.update(overrides)
    return SimulationConfig(**kwargs)


@pytest.mark.asyncio
async def test_experimental_run_propagates_one_id_to_minecraft_and_end_hooks(
    tmp_path: Path,
) -> None:
    sim_id = uuid.uuid4()
    sim = _sim(sim_id)
    repo = _repo(sim)
    captured: dict[str, Any] = {}
    hooks: list[str] = []

    async def runner(command, env, cwd, supervisor):
        captured["command"] = command
        captured["env"] = env
        captured["cwd"] = cwd
        assert supervisor.simulation_id == sim_id
        return 0

    async def eval_hook(supervisor):
        hooks.append(f"eval:{supervisor.simulation_id}")

    async def report_hook(supervisor):
        hooks.append(f"report:{supervisor.run_id}")

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        eval_hook=eval_hook,
        report_hook=report_hook,
        run_id="run-embodied-test",
        run_dir=tmp_path / "evidence",
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.completed
    assert result.simulation_id == sim_id
    assert result.run_id == "run-embodied-test"
    assert captured["env"]["LTAG_RUN_ID"] == "run-embodied-test"
    assert captured["env"]["LTAG_SIMULATION_ID"] == str(sim_id)
    assert captured["env"]["MC_RUN_DIR"] == str(tmp_path / "evidence")
    assert captured["env"]["SOAK_BOTS"] == "vera rex"
    assert captured["command"][:1] == [str(tmp_path / "scripts" / "minecraft" / "soak.sh")]
    assert "--duration-hours" in captured["command"]
    assert hooks == [f"eval:{sim_id}", "report:run-embodied-test"]
    repo.create.assert_awaited_once()
    repo.update_status.assert_awaited()


@pytest.mark.asyncio
async def test_experimental_run_stops_cleanly_on_duration(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)

    async def runner(command, env, cwd, supervisor):
        supervisor.clock.advance(timedelta(minutes=20))
        assert await supervisor.should_stop() is True
        return -15

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(duration=timedelta(minutes=15)),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "duration_reached"
    repo.update_status.assert_awaited()
    assert repo.update_status.await_args.args[1] == SimulationStatus.cancelled.value


@pytest.mark.asyncio
async def test_persistent_run_has_no_duration_and_honors_kill_switch(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    redis = SimpleNamespace(get=AsyncMock(return_value=KILL_SWITCH_ACTIVE_VALUE))

    async def runner(command, env, cwd, supervisor):
        raise AssertionError("kill switch should stop before launching Minecraft")

    config = SimulationConfig(
        name="live-embodied",
        agents=["vera"],
        run_mode=RunMode.persistent,
        conversation_mode="embodied",
        max_cost_rolling=Decimal("5"),
        rolling_window=timedelta(hours=1),
    )
    supervisor = EmbodiedSimulationSupervisor(
        config=config,
        simulation_repo=repo,
        redis_client=redis,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "kill_switch"
    redis.get.assert_awaited_with(KILL_SWITCH_KEY)


@pytest.mark.asyncio
async def test_cost_cap_stops_before_launch(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("2"))

    async def runner(command, env, cwd, supervisor):
        raise AssertionError("cost cap should stop before launching Minecraft")

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(max_cost=Decimal("1")),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "cost_cap"


@pytest.mark.asyncio
async def test_cadence_tick_invokes_reflection_hook(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    reflected: list[str] = []

    async def runner(command, env, cwd, supervisor):
        await supervisor.cadence_tick()
        await supervisor.cadence_tick()
        supervisor.cancel()
        return -15

    async def reflection_hook(supervisor):
        reflected.append(str(supervisor.simulation_id))

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        reflection_hook=reflection_hook,
        run_eval=False,
        run_report=False,
        poll_interval_seconds=1,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "cancelled"
    assert reflected == [str(sim.id), str(sim.id)]
