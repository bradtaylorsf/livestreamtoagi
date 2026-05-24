"""Tests for E12 unified run-spec starting-condition fields."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from core.minecraft.world_provisioner import WorldProvisionResult
from core.models import PersonaOverride, RunMode, RunSpec, WorldConfig
from core.run_spec import load_run_spec
from core.simulation.orchestrator import SimulationConfig, SimulationOrchestrator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "with_run_spec.yaml"


def test_run_spec_loader_validates_all_starting_condition_sections() -> None:
    spec = load_run_spec(FIXTURE)

    assert isinstance(spec, RunSpec)
    assert spec.run_mode == RunMode.persistent
    assert spec.agents == ["vera", "rex"]
    assert spec.persona_overrides[0].agent_id == "vera"
    assert "rain" in spec.persona_overrides[0].backstory
    assert spec.factions[0].name == "planners"
    assert spec.agent_goals["rex"] == ["Build a shared workshop."]
    assert spec.memory_seed is not None
    assert spec.memory_seed.mode == "none"
    assert spec.world is not None
    assert spec.world.seed == 601
    assert spec.world.world_type == "custom"
    assert spec.world.model_extra == {"biome_hint": "plains"}


def test_run_spec_missing_sections_default_to_empty_or_none() -> None:
    spec = RunSpec()

    assert spec.agents == []
    assert spec.persona_overrides == []
    assert spec.factions == []
    assert spec.agent_goals == {}
    assert spec.memory_seed is None
    assert spec.world is None
    assert spec.run_mode is None


def test_world_config_requires_path_for_custom_world() -> None:
    with pytest.raises(ValueError, match="world_config_path"):
        WorldConfig(world_type="custom")


def test_persona_override_requires_non_empty_agent_id() -> None:
    with pytest.raises(ValueError, match="agent_id"):
        PersonaOverride(agent_id=" ")


def test_simulation_config_load_seed_file_populates_run_spec_fields() -> None:
    cfg = SimulationConfig(
        name="run-spec-fixture",
        seed_file=str(FIXTURE),
        agents=["vera", "rex"],
        max_cost_rolling=1.0,
        rolling_window="1h",
        dry_run=True,
    )

    assert cfg.run_mode == RunMode.experimental
    cfg.load_seed_file(valid_agent_ids={"vera", "rex"})

    assert cfg.run_mode == RunMode.persistent
    assert cfg.persona_overrides[0].display_name == "Vera Prime"
    assert cfg.agent_goals["vera"] == ["Stabilize the settlement before nightfall."]
    assert cfg.memory_seed is not None
    assert cfg.memory_seed.mode == "none"
    assert len(cfg.factions) == 1
    assert cfg.world_config is not None
    assert cfg.world_config.world_config_path == "scripts/minecraft/world-flat-eval.config"


def test_simulation_config_to_dict_serializes_explicit_run_spec_fields() -> None:
    cfg = SimulationConfig(
        name="explicit-run-spec",
        seed_file="scenarios/awakening.yaml",
        agents=["vera", "rex"],
        persona_overrides=[
            {
                "agent_id": "vera",
                "backstory": "Vera keeps a field notebook for this run.",
            }
        ],
        agent_goals={"vera": ["Map the area."]},
        world_config={
            "seed": 123,
            "world_type": "flat",
            "persistent": False,
            "terrain_pack": "test",
        },
        run_mode="experimental",
        dry_run=True,
    )

    snapshot = cfg.to_dict()

    assert snapshot["persona_overrides"] == [
        {
            "agent_id": "vera",
            "backstory": "Vera keeps a field notebook for this run.",
        }
    ]
    assert snapshot["agent_goals"] == {"vera": ["Map the area."]}
    assert snapshot["world"] == {
        "seed": 123,
        "world_type": "flat",
        "persistent": False,
        "terrain_pack": "test",
    }
    assert snapshot["run_mode"] == "experimental"


def test_seed_yaml_does_not_override_explicit_run_config_fields(tmp_path: Path) -> None:
    seed_path = tmp_path / "scenario.yaml"
    seed_path.write_text(
        yaml.safe_dump(
            {
                "run_mode": "persistent",
                "persona_overrides": [
                    {"agent_id": "rex", "backstory": "Scenario Rex"},
                ],
                "agent_goals": {"rex": ["Scenario goal"]},
                "world": {"world_type": "flat", "seed": 1},
                "factions": [
                    {"name": "scenario", "members": ["rex"], "goal": "Scenario faction"},
                ],
                "phases": [],
            }
        )
    )
    cfg = SimulationConfig(
        name="precedence",
        seed_file=str(seed_path),
        agents=["vera", "rex"],
        persona_overrides=[{"agent_id": "vera", "backstory": "Run config Vera"}],
        agent_goals={"vera": ["Run config goal"]},
        world_config={"world_type": "default", "seed": 2},
        run_mode="experimental",
        factions=[{"name": "explicit", "members": ["vera"], "goal": "Explicit faction"}],
    )

    cfg.load_seed_file(valid_agent_ids={"vera", "rex"})

    assert cfg.run_mode == RunMode.experimental
    assert [override.agent_id for override in cfg.persona_overrides] == ["vera"]
    assert cfg.agent_goals == {"vera": ["Run config goal"]}
    assert cfg.world_config is not None
    assert cfg.world_config.seed == 2
    assert [f.name for f in cfg.factions] == ["explicit"]


def test_existing_scenario_loads_without_run_spec_snapshot_drift() -> None:
    cfg = SimulationConfig(
        name="awakening-regression",
        seed_file=str(SCENARIOS_DIR / "awakening.yaml"),
        agents=["vera", "rex", "aurora", "pixel", "grok"],
        dry_run=True,
    )
    cfg.load_seed_file(valid_agent_ids={"vera", "rex", "aurora", "pixel", "grok"})

    snapshot = cfg.to_dict()

    assert cfg.run_mode == RunMode.experimental
    assert "persona_overrides" not in snapshot
    assert "agent_goals" not in snapshot
    assert "world" not in snapshot
    assert "run_mode" not in snapshot


@pytest.mark.asyncio
async def test_orchestrator_records_world_provisioned_metadata(tmp_path: Path) -> None:
    cfg = SimulationConfig(
        name="world-provisioned",
        seed_file=str(SCENARIOS_DIR / "awakening.yaml"),
        agents=["vera"],
        world_config={"world_type": "default", "seed": 605},
        run_mode="experimental",
        dry_run=False,
    )
    sim_id = uuid.uuid4()
    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._config = cfg
    orchestrator._simulation_id = sim_id
    orchestrator._sim_repo = MagicMock(update_config=AsyncMock())
    orchestrator._llm = MagicMock()
    orchestrator.clock = MagicMock()
    orchestrator.clock.to_dict.return_value = {"speed_multiplier": 0}

    result = WorldProvisionResult(
        world_config_path=tmp_path / "run-world.config",
        level_name="world",
        run_mode=RunMode.experimental,
        persistent=False,
        action="reset_fresh",
    )
    with patch("core.minecraft.world_provisioner.provision_world", return_value=result):
        await orchestrator._provision_world_for_run()

    snapshot = cfg.to_dict()
    assert snapshot["world_provisioned"] == result.to_dict()
    orchestrator._sim_repo.update_config.assert_awaited_once_with(
        sim_id,
        {
            **snapshot,
            "clock_state": {"speed_multiplier": 0},
            "llm_provider": "openrouter",
        },
    )
