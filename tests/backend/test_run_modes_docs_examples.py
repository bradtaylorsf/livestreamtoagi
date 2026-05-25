"""Docs and examples for run modes stay loadable."""

from __future__ import annotations

from pathlib import Path

from core.models import RunMode
from core.run_spec import load_run_spec
from core.simulation.orchestrator import SimulationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_run_modes_index_references_example_specs() -> None:
    docs_path = PROJECT_ROOT / "docs" / "run-modes.md"
    text = docs_path.read_text()

    assert "scenarios/persistent_24x7.yaml" in text
    assert "scenarios/experimental_short_run.yaml" in text
    assert "run-modes/persistent.md" in text
    assert "run-modes/experimental.md" in text


def test_run_mode_example_specs_load_as_run_specs() -> None:
    persistent = load_run_spec(PROJECT_ROOT / "scenarios" / "persistent_24x7.yaml")
    experimental = load_run_spec(PROJECT_ROOT / "scenarios" / "experimental_short_run.yaml")

    assert persistent.run_mode == RunMode.persistent
    assert experimental.run_mode == RunMode.experimental
    assert experimental.experimental_goal is not None
    assert experimental.experimental_goal.kind == "phases_complete"


def test_run_mode_example_specs_build_simulation_configs() -> None:
    persistent_path = PROJECT_ROOT / "scenarios" / "persistent_24x7.yaml"
    experimental_path = PROJECT_ROOT / "scenarios" / "experimental_short_run.yaml"

    persistent = load_run_spec(persistent_path)
    persistent_cfg = SimulationConfig(
        name="persistent-doc-example",
        seed_file=str(persistent_path),
        agents=persistent.agents,
        run_mode=persistent.run_mode,
        max_cost_rolling=5,
        rolling_window="1h",
        dry_run=True,
    )
    persistent_cfg.load_seed_file(valid_agent_ids=set(persistent.agents))

    experimental = load_run_spec(experimental_path)
    experimental_cfg = SimulationConfig(
        name="experimental-doc-example",
        seed_file=str(experimental_path),
        agents=experimental.agents,
        run_mode=experimental.run_mode,
        dry_run=True,
    )
    experimental_cfg.load_seed_file(valid_agent_ids=set(experimental.agents))

    assert persistent_cfg.run_mode == RunMode.persistent
    assert persistent_cfg.world_config is not None
    assert persistent_cfg.world_config.persistent is True
    assert experimental_cfg.run_mode == RunMode.experimental
    assert experimental_cfg.world_config is not None
    assert experimental_cfg.world_config.persistent is False
