"""Integration tests for orchestrator ↔ world-event scheduler wiring (#854).

These tests don't bootstrap the full service graph — they construct a
``SimulationOrchestrator`` with mocked dependencies and exercise just the
``_build_world_event_runtime`` + ``_tick_world`` paths.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from core.simulation.decision_logger import DecisionLogReader, DecisionLogger
from core.simulation.orchestrator import SimulationConfig, SimulationOrchestrator


def _make_orchestrator(
    *,
    world_events: dict,
    sim_folder: Path,
    agents: list[str] | None = None,
    disable: bool = False,
) -> SimulationOrchestrator:
    """Build a minimal orchestrator wired with a DecisionLogger and mocks."""
    agents = agents or ["vera", "rex"]
    scenario = sim_folder / "scenario.yaml"
    block = dict(world_events)
    if disable:
        block["disable_world_event_scheduler"] = True
    scenario.write_text(
        yaml.safe_dump(
            {
                "meta": {"name": "wet", "description": "test", "agents": agents},
                "world_events": block,
                "phases": [{"name": "p", "type": "organic"}],
            }
        )
    )

    cfg = SimulationConfig(
        name="wet",
        seed_file=str(scenario),
        agents=agents,
        dry_run=True,
    )
    cfg.load_seed_file()

    trigger_system = MagicMock()
    trigger_system.queue_event = MagicMock()

    orchestrator = SimulationOrchestrator(
        config=cfg,
        db=MagicMock(),
        redis_client=MagicMock(),
        simulation_repo=MagicMock(),
        config_loader=MagicMock(),
        agent_registry=MagicMock(),
        event_bus=MagicMock(),
        llm_client=MagicMock(),
        management=MagicMock(),
        context_assembler=MagicMock(),
        conversation_repo=MagicMock(),
        archival_memory=MagicMock(),
        proximity=MagicMock(),
        trigger_system=trigger_system,
        selection_logger=MagicMock(),
        reflection_manager=MagicMock(),
        display=MagicMock(),
    )
    orchestrator._decision_logger = DecisionLogger(sim_folder)
    return orchestrator


def _read_log(sim_folder: Path) -> list[dict]:
    """Read the decision_log.jsonl as raw dicts."""
    path = sim_folder / "decision_log.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_orchestrator_disable_flag_skips_scheduler(tmp_path: Path) -> None:
    orch = _make_orchestrator(
        world_events={
            "schedule": [{"tick": 1, "event": "nightfall"}],
            "needs": {"hunger": {"tick_decay": 50.0, "critical_threshold": 25.0}},
        },
        sim_folder=tmp_path,
        disable=True,
    )

    orch._build_world_event_runtime(uuid.uuid4())
    assert orch._world_event_scheduler is None
    assert orch._needs_manager is None

    await orch._tick_world(["vera", "rex"])
    orch._decision_logger.close()
    rows = _read_log(tmp_path)
    assert rows == []


@pytest.mark.asyncio
async def test_scheduled_event_logged_to_decision_log(tmp_path: Path) -> None:
    orch = _make_orchestrator(
        world_events={"schedule": [{"tick": 1, "event": "nightfall"}]},
        sim_folder=tmp_path,
    )
    orch._build_world_event_runtime(uuid.uuid4())
    assert orch._world_event_scheduler is not None

    await orch._tick_world([])
    orch._decision_logger.close()

    reader = DecisionLogReader(tmp_path)
    rows = list(reader.replay())
    world_rows = [r for r in rows if r.event_type == "world_event"]
    assert len(world_rows) == 1
    assert world_rows[0].payload.event_type == "nightfall"


@pytest.mark.asyncio
async def test_needs_decay_emits_needs_state_row(tmp_path: Path) -> None:
    orch = _make_orchestrator(
        world_events={
            "needs": {
                "hunger": {
                    "tick_decay": 80.0,
                    "critical_threshold": 25.0,
                    "warning_threshold": 50.0,
                },
            },
        },
        sim_folder=tmp_path,
    )
    orch._build_world_event_runtime(uuid.uuid4())
    assert orch._needs_manager is not None

    # One tick is enough to drop hunger from 100 → 20, crossing critical.
    await orch._tick_world(["vera"])
    orch._decision_logger.close()

    reader = DecisionLogReader(tmp_path)
    rows = list(reader.replay())
    needs_rows = [r for r in rows if r.event_type == "needs_state"]
    crit_rows = [
        r for r in rows if r.event_type == "world_event"
        and r.payload.event_type == "hunger_critical"
    ]
    assert needs_rows, "expected a needs_state row after a critical crossing"
    assert crit_rows, "expected a hunger_critical world_event row"
    assert needs_rows[0].actor_id == "vera"


@pytest.mark.asyncio
async def test_world_event_queued_as_trigger(tmp_path: Path) -> None:
    orch = _make_orchestrator(
        world_events={"schedule": [{"tick": 1, "event": "nightfall"}]},
        sim_folder=tmp_path,
    )
    orch._build_world_event_runtime(uuid.uuid4())

    await orch._tick_world([])
    orch._decision_logger.close()

    orch._triggers.queue_event.assert_called()
    call_args = orch._triggers.queue_event.call_args_list[0]
    assert call_args.args[0] == "world_event"
    assert call_args.args[1]["event"] == "nightfall"


@pytest.mark.asyncio
async def test_survival_pressure_scenario_validates_and_arms(tmp_path: Path) -> None:
    """survival_pressure_test.yaml loads cleanly and arms the scheduler."""
    project_root = Path(__file__).resolve().parent.parent.parent
    scenario_path = project_root / "scenarios" / "survival_pressure_test.yaml"
    assert scenario_path.is_file()

    cfg = SimulationConfig(
        name="sp",
        seed_file=str(scenario_path),
        agents=["vera", "rex", "aurora", "sentinel"],
        dry_run=True,
    )
    cfg.load_seed_file()
    assert cfg.world_events is not None
    assert "schedule" in cfg.world_events
    assert "hunger" in cfg.world_events["needs"]
