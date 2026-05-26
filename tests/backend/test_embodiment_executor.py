"""Contract tests for the EmbodimentExecutor abstraction (issue #851).

These tests pin down three load-bearing properties:

1. ``RunMode.headless`` is a valid mode and selects a HeadlessExecutor whose
   ``requires_minecraft_world`` flag is False.
2. HeadlessExecutor records tool intents without importing Director V2,
   Mindcraft, audio FIFO, or TTS modules.
3. The orchestrator selects an executor via a single switch — there is no
   scattered ``if run_mode == ...`` for embodied side effects in the engine.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from datetime import timedelta

import pytest

from core.models import (
    ManagementPolicy,
    RunMode,
    default_management_policy_for_run_mode,
)
from core.simulation.embodiment import (
    EmbodiedExecutor,
    EmbodimentExecutor,
    HeadlessExecutor,
    ToolIntent,
    select_executor,
)


def test_run_mode_headless_is_valid() -> None:
    assert RunMode.headless == RunMode("headless")
    assert RunMode.headless.value == "headless"


def test_headless_default_management_policy_is_shadow() -> None:
    assert default_management_policy_for_run_mode(RunMode.headless) is ManagementPolicy.shadow


def test_select_executor_headless_returns_headless_executor() -> None:
    executor = select_executor(RunMode.headless)
    assert isinstance(executor, HeadlessExecutor)
    assert isinstance(executor, EmbodimentExecutor)
    assert executor.requires_minecraft_world is False


@pytest.mark.parametrize("mode", [RunMode.persistent, RunMode.experimental, None])
def test_select_executor_non_headless_returns_embodied(mode: RunMode | None) -> None:
    executor = select_executor(mode)
    assert isinstance(executor, EmbodiedExecutor)
    assert executor.requires_minecraft_world is True


@pytest.mark.asyncio
async def test_headless_executor_records_tool_intents() -> None:
    executor = HeadlessExecutor()
    await executor.setup(simulation_id="sim-1")
    intent = ToolIntent(tool_name="propose_build", actor_id="rex", args={"kind": "cabin"})
    outcome = await executor.execute_tool_intent(intent)
    assert outcome.status == "simulated"
    assert len(executor.recorded_intents) == 1
    assert executor.recorded_intents[0].intent.tool_name == "propose_build"


def test_headless_executor_can_record_blocked_intent() -> None:
    executor = HeadlessExecutor()
    intent = ToolIntent(tool_name="propose_build", actor_id="rex")
    outcome = executor.record_blocked_intent(intent, reason="management:harmful")
    assert outcome.status == "blocked"
    assert outcome.block_reason == "management:harmful"
    assert len(executor.recorded_intents) == 1


def test_headless_module_does_not_import_embodied_modules() -> None:
    """HeadlessExecutor's module must not pull in Director V2 / Mindcraft / TTS."""
    import ast

    embodiment_mod = importlib.import_module("core.simulation.embodiment")
    src = inspect.getsource(embodiment_mod)
    tree = ast.parse(src)

    forbidden_prefixes = (
        "core.bridge.handlers.director",
        "core.simulation.embodied_supervisor",
        "core.tts",
        "mindcraft",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for needle in forbidden_prefixes:
                assert not module.startswith(needle), (
                    f"embodiment.py must not import from {needle} (found: {module})"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for needle in forbidden_prefixes:
                    assert not alias.name.startswith(needle), (
                        f"embodiment.py must not import {needle} (found: {alias.name})"
                    )


@pytest.mark.asyncio
async def test_headless_run_does_not_load_embodied_modules() -> None:
    """Exercising the headless executor must not transitively import embodied paths.

    We snapshot ``sys.modules`` before instantiating HeadlessExecutor and
    confirm that none of the embodied-only modules are loaded as a side
    effect.
    """
    embodied_only = (
        "core.bridge.handlers.director",
        "core.simulation.embodied_supervisor",
    )
    # Remove these from the test environment so we observe a clean import.
    for name in embodied_only:
        sys.modules.pop(name, None)

    executor = HeadlessExecutor()
    await executor.setup(simulation_id="sim-x")
    await executor.execute_tool_intent(ToolIntent(tool_name="propose_build", actor_id="rex"))
    await executor.on_utterance({"text": "hello", "agent_id": "rex"})
    await executor.tick(0.0)
    await executor.teardown()

    for name in embodied_only:
        assert name not in sys.modules, (
            f"headless executor leaked an import of {name}; that breaks the contract"
        )


def test_orchestrator_run_mode_switch_is_single_point() -> None:
    """Only the executor-selection line should switch on RunMode for embodiment.

    Other ``RunMode.persistent`` / ``RunMode.experimental`` checks are
    permitted for run-mode-specific *bookkeeping* (cost caps, persistent
    heartbeat, experimental progress) — they are not embodiment branches.
    What we forbid is a new world-provisioning or executor-dispatch branch
    that re-derives behavior from RunMode at the orchestrator level. The
    canary: ``_provision_world_for_run`` must gate on
    ``self._executor.requires_minecraft_world``, not on the run mode.
    """
    from core.simulation import orchestrator as orch

    src = inspect.getsource(orch.SimulationOrchestrator._provision_world_for_run)
    assert "requires_minecraft_world" in src
    assert "RunMode.headless" not in src


def test_headless_config_is_constructible_with_duration() -> None:
    """Constructing a SimulationConfig with run_mode=headless succeeds."""
    from core.simulation.orchestrator import SimulationConfig

    cfg = SimulationConfig(
        name="hl",
        agents=["vera"],
        run_mode=RunMode.headless,
        duration=timedelta(seconds=60),
    )
    assert cfg.run_mode is RunMode.headless
    assert cfg.management_policy is ManagementPolicy.shadow


def test_headless_config_requires_duration_or_seed_or_goal() -> None:
    from core.simulation.orchestrator import SimulationConfig

    with pytest.raises(ValueError, match="headless mode requires"):
        SimulationConfig(name="hl", agents=["vera"], run_mode=RunMode.headless)


def test_run_headless_sim_cli_accepts_required_flags() -> None:
    """The CLI parser accepts all the flags called out in the spec."""
    from scripts.run_headless_sim import _build_parser

    parser = _build_parser()
    ns = parser.parse_args(
        [
            "--scenario",
            "scenarios/dream_smoke_test.yaml",
            "--duration",
            "12h",
            "--speed-multiplier",
            "42",
            "--max-cost",
            "0.01",
            "--seed",
            "7",
            "--output-dir",
            "/tmp/headless-out",
        ]
    )
    assert ns.scenario == "scenarios/dream_smoke_test.yaml"
    assert ns.duration == "12h"
    assert ns.speed_multiplier == 42.0
    assert ns.max_cost == 0.01
    assert ns.seed == 7
    assert ns.output_dir == "/tmp/headless-out"
