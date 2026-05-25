"""Tests for bounded experimental short-run mode."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import RunMode
from core.simulation.orchestrator import (
    SimulationConfig,
    SimulationOrchestrator,
    parse_experimental_goal,
)
from core.simulation.phases import PhaseResult


def test_experimental_config_requires_defined_end_without_seed_file() -> None:
    with pytest.raises(ValueError, match="requires a seed_file, duration, or experimental_goal"):
        SimulationConfig(
            name="unbounded-experiment",
            agents=["vera"],
            run_mode="experimental",
        )


def test_experimental_config_forces_fresh_world() -> None:
    cfg = SimulationConfig(
        name="fresh-world",
        agents=["vera"],
        run_mode="experimental",
        duration=timedelta(minutes=10),
        world_config={"world_type": "default", "persistent": True},
    )

    assert cfg.world_config is not None
    assert cfg.world_config.persistent is False


def test_experimental_config_rejects_durable_world_id() -> None:
    with pytest.raises(ValueError, match="durable_world_id"):
        SimulationConfig(
            name="durable-experiment",
            agents=["vera"],
            run_mode="experimental",
            duration=timedelta(minutes=10),
            world_config={
                "world_type": "default",
                "persistent": False,
                "durable_world_id": "world",
            },
        )


def test_parse_experimental_goal_accepts_colon_and_equals() -> None:
    assert parse_experimental_goal("turns:12").kind == "turns"
    assert parse_experimental_goal("artifacts=2").target == 2


@pytest.mark.asyncio
async def test_experimental_goal_records_goal_reached_stop_reason() -> None:
    cfg = SimulationConfig(
        name="goal-experiment",
        agents=["vera"],
        experimental_goal={"kind": "turns", "target": 3},
        dry_run=True,
    )
    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._cancelled = False
    orchestrator._experimental_stop_reason = None
    orchestrator._experimental_progress = {
        "phases_completed": 0,
        "turns": 0,
        "artifacts": 0,
    }
    orchestrator._redis = MagicMock()
    orchestrator._redis.get = AsyncMock(return_value=None)
    orchestrator.clock = MagicMock()
    orchestrator.clock.elapsed.return_value = timedelta(minutes=1)

    orchestrator._record_experimental_progress(PhaseResult(turns=3))

    assert cfg.run_mode == RunMode.experimental
    assert await orchestrator._terminated() is True
    assert orchestrator._experimental_stop_reason == "goal_reached"
    orchestrator._redis.get.assert_not_awaited()


def test_phases_complete_goal_matches_progress_counter() -> None:
    """`phases_complete` goal kind reads the `phases_completed` progress counter."""
    cfg = SimulationConfig(
        name="phases-complete-goal",
        agents=["vera"],
        experimental_goal={"kind": "phases_complete", "target": 3},
        dry_run=True,
    )
    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._experimental_stop_reason = None
    orchestrator._experimental_progress = {
        "phases_completed": 0,
        "turns": 0,
        "artifacts": 0,
    }

    for _ in range(2):
        orchestrator._record_experimental_progress(PhaseResult(turns=1))
    assert orchestrator._experimental_goal_reached() is False

    orchestrator._record_experimental_progress(PhaseResult(turns=1))
    assert orchestrator._experimental_goal_reached() is True
