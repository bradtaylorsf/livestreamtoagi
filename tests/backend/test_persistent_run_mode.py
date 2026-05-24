"""Tests for persistent 24/7 run mode."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.models import SimulationStatus
from core.simulation.orchestrator import (
    CostLimitExceededError,
    SimulationConfig,
    SimulationOrchestrator,
)


def _persistent_config(**overrides) -> SimulationConfig:
    params = {
        "name": "persistent-test",
        "agents": ["vera"],
        "run_mode": "persistent",
        "max_cost": 10.0,
        "max_cost_rolling": 1.0,
        "rolling_window": timedelta(hours=1),
    }
    params.update(overrides)
    return SimulationConfig(**params)


def test_persistent_config_rejects_duration() -> None:
    with pytest.raises(ValueError, match="indefinite"):
        _persistent_config(duration=timedelta(hours=24))


def test_persistent_config_requires_rolling_cost_cap() -> None:
    with pytest.raises(ValueError, match="max_cost_rolling"):
        SimulationConfig(
            name="bad-persistent",
            agents=["vera"],
            run_mode="persistent",
        )


def test_persistent_config_forces_world_config_to_durable_branch() -> None:
    cfg = _persistent_config(world_config={"world_type": "default", "persistent": False})

    assert cfg.world_config is not None
    assert cfg.world_config.persistent is True


@pytest.mark.asyncio
async def test_persistent_terminated_ignores_duration_but_stops_on_cancel_and_kill() -> None:
    cfg = _persistent_config()
    cfg.duration = timedelta(seconds=1)

    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._cancelled = False
    orchestrator.clock = MagicMock()
    orchestrator.clock.elapsed.return_value = timedelta(days=365)
    orchestrator._redis = MagicMock()
    orchestrator._redis.get = AsyncMock(return_value=None)

    assert await orchestrator._terminated() is False
    orchestrator._redis.get.assert_awaited_once_with(KILL_SWITCH_KEY)

    orchestrator._cancelled = True
    assert await orchestrator._terminated() is True

    orchestrator._cancelled = False
    orchestrator._redis.get = AsyncMock(return_value=KILL_SWITCH_ACTIVE_VALUE)
    assert await orchestrator._terminated() is True


@pytest.mark.asyncio
async def test_persistent_cost_check_raises_on_rolling_spend() -> None:
    cfg = _persistent_config(max_cost=10.0, max_cost_rolling=1.0)
    sim_id = uuid.uuid4()
    repo = MagicMock()
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("2.50"))
    repo.get_rolling_cost_from_events = AsyncMock(return_value=Decimal("1.25"))
    repo.increment_stats = AsyncMock()

    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._sim_repo = repo
    orchestrator._simulation_id = sim_id
    orchestrator._total_cost = Decimal("0")

    with pytest.raises(CostLimitExceededError, match="Rolling spend"):
        await orchestrator._check_cost_limit()

    repo.get_rolling_cost_from_events.assert_awaited_once_with(sim_id, cfg.rolling_window)


@pytest.mark.asyncio
async def test_persistent_attach_existing_running_sim_resumes_cost_from_events() -> None:
    sim_id = uuid.uuid4()
    cfg = _persistent_config(existing_sim_id=str(sim_id))
    sim = SimpleNamespace(
        id=sim_id,
        status=SimulationStatus.running,
        started_at=datetime(2026, 5, 24, tzinfo=UTC),
    )
    repo = MagicMock()
    repo.get = AsyncMock(return_value=sim)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("4.25"))
    repo.update_config = AsyncMock(return_value=sim)
    repo.update_agents_participated = AsyncMock(return_value=sim)
    repo.update_status = AsyncMock(return_value=sim)

    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._sim_repo = repo
    orchestrator._total_cost = Decimal("0")

    attached = await orchestrator._create_or_attach_simulation({"run_mode": "persistent"}, {})

    assert attached is sim
    assert orchestrator._total_cost == Decimal("4.25")
    repo.get_total_cost_from_events.assert_awaited_once_with(sim_id)
    repo.update_status.assert_awaited_once_with(sim_id, SimulationStatus.running)


@pytest.mark.asyncio
async def test_persistent_heartbeat_writes_raw_live_keys() -> None:
    cfg = _persistent_config()
    sim_id = uuid.uuid4()
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)

    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._simulation_id = sim_id
    orchestrator._redis = redis
    orchestrator._last_persistent_heartbeat = 0.0

    await orchestrator._persistent_heartbeat(force=True)

    redis.set.assert_any_await("live:simulation_id", str(sim_id))
    heartbeat_call = redis.set.await_args_list[1]
    assert heartbeat_call.args[0] == "live:simulation_heartbeat"
    assert "T" in heartbeat_call.args[1]
