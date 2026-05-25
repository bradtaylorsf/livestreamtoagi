"""Regression tests for public simulation run config plumbing."""

from __future__ import annotations

import argparse

from core.simulation.orchestrator import SimulationConfig
from core.simulation.phases import Phase, PhaseRunner, PhaseType
from scripts.run_simulation import (
    _agents_from_run_config,
    _memory_seed_from_run_config,
    _world_from_run_config,
)


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "agents": "aurora,fork,grok,pixel,rex,sentinel,vera",
        "memory_seed_mode": None,
        "memory_seed_file": None,
        "memory_seed_inherit_from": None,
        "world_config_file": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_run_config_agents_override_cli_default_roster() -> None:
    agents = _agents_from_run_config(
        _args(),
        {"agents": ["vera", "rex", "aurora", "pixel"]},
    )

    assert agents == ["vera", "rex", "aurora", "pixel"]


def test_run_config_memory_seed_translates_public_inherit_shape() -> None:
    seed = _memory_seed_from_run_config(
        _args(),
        {"memory_seed": {"mode": "inherit", "simulation_id": "sim-123"}},
    )

    assert seed is not None
    assert seed.mode == "inherit"
    assert seed.inherit_from == "sim-123"


def test_cli_world_config_file_overrides_run_config_world_block() -> None:
    world = _world_from_run_config(
        _args(world_config_file="scripts/minecraft/world-flat-eval.config"),
        {"world": {"world_type": "default", "seed": 123}},
    )

    assert world == {
        "world_type": "custom",
        "world_config_path": "scripts/minecraft/world-flat-eval.config",
    }


def test_simulation_config_snapshot_preserves_public_roster_fields() -> None:
    cfg = SimulationConfig(
        name="small-cast",
        seed_file="scenarios/awakening.yaml",
        agents=["vera", "rex", "aurora", "pixel"],
        max_cost=0.5,
        scenario_id="awakening.yaml",
        scenario_meta={"name": "Awakening"},
        scenario_agents=["vera", "rex", "aurora", "pixel", "grok"],
        excluded_agents=["grok"],
        initial_agent_energy={"vera": 85, "rex": 60, "aurora": 90, "pixel": 70},
        conversation_cadence=1.25,
        submitted_params={"agents": ["vera", "rex", "aurora", "pixel"]},
        source="public_submit",
    )

    snapshot = cfg.to_dict()

    assert snapshot["agents"] == ["vera", "rex", "aurora", "pixel"]
    assert snapshot["effective_agents"] == ["vera", "rex", "aurora", "pixel"]
    assert snapshot["scenario_agents"] == ["vera", "rex", "aurora", "pixel", "grok"]
    assert snapshot["excluded_agents"] == ["grok"]
    assert snapshot["energy"] == {"vera": 85, "rex": 60, "aurora": 90, "pixel": 70}
    assert snapshot["conversation_cadence"] == 1.25
    assert snapshot["source"] == "public_submit"


def test_phase_runner_constrains_required_agents_to_effective_roster() -> None:
    runner = object.__new__(PhaseRunner)
    runner._agent_ids = ["vera", "rex", "aurora", "pixel"]
    phase = Phase(
        name="requires-excluded",
        type=PhaseType.organic,
        required_agents=["grok", "rex"],
    )

    assert runner._active_required_agents(phase) == ["rex"]
    assert runner._starter_or_fallback("grok") == "vera"
