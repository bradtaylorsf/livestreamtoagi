"""CLI defaulting tests for scripts/run_simulation.py."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SIMULATION = REPO_ROOT / "scripts" / "run_simulation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_simulation_cli", RUN_SIMULATION)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    original_environ = os.environ.copy()
    try:
        spec.loader.exec_module(module)
    finally:
        os.environ.clear()
        os.environ.update(original_environ)
    return module


run_simulation = _load_module()


def test_default_agents_include_alpha_and_exclude_management() -> None:
    agents = run_simulation._default_agents().split(",")

    assert agents[0] == "alpha"
    assert "alpha" in agents
    assert "management" not in agents


def test_seed_file_agents_are_default_roster_when_cli_agents_omitted() -> None:
    args = argparse.Namespace(
        agents=None,
        seed_file="scenarios/two_team_civilization_75m.yaml",
    )

    agents = run_simulation._agents_from_run_config(args, {})

    assert agents == ["alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"]


def test_explicit_cli_agents_override_seed_file_agents() -> None:
    args = argparse.Namespace(
        agents="vera,rex",
        seed_file="scenarios/two_team_civilization_75m.yaml",
    )

    assert run_simulation._agents_from_run_config(args, {}) == ["vera", "rex"]


def test_env_management_disable_overrides_env_policy(monkeypatch) -> None:
    monkeypatch.setenv("MC_SIM_DISABLE_MANAGEMENT", "1")
    monkeypatch.setenv("MC_SIM_MANAGEMENT_POLICY", "shadow")

    assert run_simulation._management_policy_from_env() == "off"


def test_env_management_policy_supports_review_mode_alias(monkeypatch) -> None:
    monkeypatch.delenv("MC_SIM_DISABLE_MANAGEMENT", raising=False)
    monkeypatch.delenv("MC_SIM_MANAGEMENT_POLICY", raising=False)
    monkeypatch.setenv("MINECRAFT_MANAGEMENT_REVIEW_MODE", "disabled")

    assert run_simulation._management_policy_from_env() == "off"
