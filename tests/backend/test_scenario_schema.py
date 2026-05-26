"""Tests for the canonical scenario YAML schema (E22-3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.simulation.scenario_schema import (
    EvalTargetsBlock,
    ScenarioSchema,
    validate_scenario_dict,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"


def _all_scenarios() -> list[Path]:
    return sorted(p for p in SCENARIOS_DIR.glob("*.yaml") if p.is_file())


def _minimal_scenario(**overrides) -> dict:
    base: dict = {
        "meta": {
            "name": "Test",
            "description": "desc",
            "agents": ["vera"],
        },
        "phases": [{"name": "p1", "type": "organic"}],
    }
    base.update(overrides)
    return base


def test_every_committed_scenario_validates() -> None:
    """Fixture roundtrip: every scenarios/*.yaml passes the schema.

    The Scenario Library test (``test_every_scenario_yaml_has_a_meta_block``)
    enforces that committed YAMLs include a meta block — this test just
    confirms they all parse cleanly through the new schema.
    """
    for path in _all_scenarios():
        with path.open() as f:
            data = yaml.safe_load(f)
        validate_scenario_dict(data)


def test_minimal_scenario_is_valid() -> None:
    scenario = validate_scenario_dict(_minimal_scenario())
    assert scenario.meta.name == "Test"
    assert scenario.phases[0].type == "organic"
    assert scenario.eval_targets is None


def test_eval_targets_unknown_category_rejected() -> None:
    data = _minimal_scenario(
        eval_targets={"primary": ["this_is_not_a_real_category"]}
    )
    with pytest.raises(ValidationError) as excinfo:
        validate_scenario_dict(data)
    assert "unknown eval categories" in str(excinfo.value)


def test_eval_targets_unknown_success_criteria_rejected() -> None:
    data = _minimal_scenario(
        eval_targets={
            "primary": ["social_dynamics"],
            "success_criteria": {"bogus_category": "min_score >= 50"},
        }
    )
    with pytest.raises(ValidationError) as excinfo:
        validate_scenario_dict(data)
    assert "success_criteria" in str(excinfo.value)


def test_eval_targets_known_categories_accepted() -> None:
    targets = EvalTargetsBlock(
        primary=["social_dynamics", "world_evolution"],
        secondary=["dialogue_quality"],
        success_criteria={"social_dynamics": "min_score >= 60"},
    )
    assert targets.primary == ["social_dynamics", "world_evolution"]


def test_unknown_phase_type_rejected() -> None:
    data = _minimal_scenario(phases=[{"name": "p1", "type": "not_a_real_type"}])
    with pytest.raises(ValidationError) as excinfo:
        validate_scenario_dict(data)
    assert "unknown phase type" in str(excinfo.value)


def test_duplicate_faction_names_rejected() -> None:
    data = _minimal_scenario(
        factions=[
            {"name": "alpha", "members": ["vera"], "goal": "x"},
            {"name": "alpha", "members": ["rex"], "goal": "y"},
        ]
    )
    with pytest.raises(ValidationError) as excinfo:
        validate_scenario_dict(data)
    assert "duplicate faction name" in str(excinfo.value)


def test_unknown_top_level_key_rejected() -> None:
    data = _minimal_scenario(this_key_does_not_exist={})
    with pytest.raises(ValidationError):
        validate_scenario_dict(data)


def test_phase_extra_keys_allowed() -> None:
    """Phase specs allow extras — they flow into Phase.config."""
    data = _minimal_scenario(
        phases=[
            {
                "name": "p1",
                "type": "organic",
                "count": 3,
                "topics": ["hello"],
                "location": "town_square",
            }
        ]
    )
    scenario = validate_scenario_dict(data)
    assert scenario.phases[0].name == "p1"


def test_eval_targets_present_on_backfilled_scenarios() -> None:
    """Acceptance: the six scenarios listed in #853 carry eval_targets."""
    backfilled = {
        "faction_emergence_test.yaml",
        "dream_smoke_test.yaml",
        "goal_generation_test.yaml",
        "full_evolution_7d.yaml",
        "awakening.yaml",
        "open_settlement_90m.yaml",
    }
    for path in _all_scenarios():
        if path.name not in backfilled:
            continue
        with path.open() as f:
            data = yaml.safe_load(f)
        scenario = validate_scenario_dict(data)
        assert (
            scenario.eval_targets is not None
        ), f"{path.name} expected an eval_targets block"
        assert scenario.eval_targets.primary, f"{path.name} primary is empty"


def test_orchestrator_load_seed_populates_eval_targets(tmp_path: Path) -> None:
    """SimulationConfig.load_seed_file exposes eval_targets after parsing."""
    from core.simulation.orchestrator import SimulationConfig

    seed = tmp_path / "scenario.yaml"
    seed.write_text(
        yaml.safe_dump(
            _minimal_scenario(
                eval_targets={
                    "primary": ["social_dynamics"],
                    "secondary": ["dialogue_quality"],
                    "success_criteria": {"social_dynamics": "min_score >= 60"},
                }
            )
        )
    )

    cfg = SimulationConfig(name="t", seed_file=str(seed), agents=["vera"])
    cfg.load_seed_file()
    assert cfg.eval_targets is not None
    assert cfg.eval_targets["primary"] == ["social_dynamics"]
    snapshot = cfg.to_dict()
    assert snapshot["eval_targets"]["primary"] == ["social_dynamics"]


def test_validator_cli_passes_on_valid_files(tmp_path: Path) -> None:
    seed = tmp_path / "ok.yaml"
    seed.write_text(yaml.safe_dump(_minimal_scenario()))
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_scenario.py"), str(seed)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_validator_cli_fails_on_invalid_files(tmp_path: Path) -> None:
    seed = tmp_path / "bad.yaml"
    seed.write_text(
        yaml.safe_dump(
            _minimal_scenario(eval_targets={"primary": ["nope_not_real"]})
        )
    )
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_scenario.py"), str(seed)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr


def test_validator_cli_strict_flag_requires_eval_targets(tmp_path: Path) -> None:
    seed = tmp_path / "no-targets.yaml"
    seed.write_text(yaml.safe_dump(_minimal_scenario()))
    relaxed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_scenario.py"), str(seed)],
        capture_output=True,
        text=True,
    )
    assert relaxed.returncode == 0
    strict = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "validate_scenario.py"),
            "--strict",
            str(seed),
        ],
        capture_output=True,
        text=True,
    )
    assert strict.returncode == 1
    assert "eval_targets" in strict.stderr


def test_scenario_meta_public_endpoint_exposes_eval_targets() -> None:
    from core.public_routes import _build_scenario_meta

    awakening = SCENARIOS_DIR / "awakening.yaml"
    meta = _build_scenario_meta(awakening)
    assert meta.eval_targets is not None
    assert "primary" in meta.eval_targets
    assert "dialogue_quality" in meta.eval_targets["primary"]


def test_schema_round_trip_preserves_phase_count() -> None:
    """A scenario can be serialized back to a dict and re-validated."""
    data = _minimal_scenario(
        phases=[
            {"name": f"p{i}", "type": "organic", "count": 1}
            for i in range(5)
        ]
    )
    scenario = validate_scenario_dict(data)
    again = ScenarioSchema.model_validate(scenario.model_dump())
    assert len(again.phases) == 5
