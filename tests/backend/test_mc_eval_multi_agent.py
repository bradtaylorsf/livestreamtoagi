"""Tests for Minecraft multi-agent timing eval mode."""

from __future__ import annotations

from pathlib import Path

from core.minecraft.eval.live_telemetry import EvalCategory, MultiAgentTimingFailure
from core.minecraft.eval.multi_agent import (
    AgentSpec,
    MultiAgentFakeBridge,
    MultiAgentScheduler,
    run_multi_agent_timing_eval,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_multi_agent_scheduler_interleaves_cases_deterministically_for_same_seed() -> None:
    agents = (
        AgentSpec("vera", "move", 2),
        AgentSpec("rex", "placeHere", 2),
    )
    first = MultiAgentScheduler(agents, seed=42, tick_ms=200, stagger_ms=50).schedule()
    second = MultiAgentScheduler(agents, seed=42, tick_ms=200, stagger_ms=50).schedule()

    assert [(case.agent_id, case.scheduled_ts_ms) for case in first] == [
        ("vera", 0),
        ("rex", 50),
        ("vera", 200),
        ("rex", 250),
    ]
    assert [case.case.command_text for case in first] == [case.case.command_text for case in second]
    assert all(case.case.params["multi_agent"] is True for case in first)


async def test_multi_agent_fake_bridge_produces_timing_failure_classes() -> None:
    summary = await run_multi_agent_timing_eval(
        (AgentSpec("vera", "move", 5),),
        bridge=MultiAgentFakeBridge(),
        profile="flat-eval",
        seed=1,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
        tick_ms=200,
        stagger_ms=50,
        director_fanout=3,
    )

    failure_classes = [
        MultiAgentTimingFailure.NONE,
        MultiAgentTimingFailure.QUEUE_CONTENTION,
        MultiAgentTimingFailure.SELF_INTERRUPTION,
        MultiAgentTimingFailure.DIRECTOR_FANOUT,
        MultiAgentTimingFailure.COMMAND_LOSS,
    ]
    assert [
        summary.timing_summary["failure_classes"][failure_class]
        for failure_class in failure_classes
    ] == [1, 1, 1, 1, 1]
    assert summary.timing_summary["contention"] == 1
    assert summary.timing_summary["interruptions"] == 2
    assert summary.timing_summary["fanouts"] == 3
    assert summary.timing_summary["command_loss"] == 1


async def test_run_multi_agent_timing_eval_returns_profile_and_per_case_timing() -> None:
    agents = (
        AgentSpec("vera", "move", 2),
        AgentSpec("rex", "placeHere", 2),
    )
    bridge = MultiAgentFakeBridge()

    summary = await run_multi_agent_timing_eval(
        agents,
        bridge=bridge,
        profile="flat-eval",
        seed=3,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
        tick_ms=200,
        stagger_ms=50,
        director_fanout=2,
    )

    assert summary.command == "multi-agent-timing"
    assert summary.resolved_command == "multi-agent-timing"
    assert summary.profile == "flat-eval"
    assert summary.dry_run is True
    assert len(summary.case_results) == 4
    assert [call["agent_id"] for call in bridge.calls] == ["vera", "rex", "vera", "rex"]
    assert all(result.agent_id in {"vera", "rex"} for result in summary.case_results)
    assert all(result.timing is not None for result in summary.case_results)
    assert all(
        result.eval_category == EvalCategory.MULTI_AGENT_TIMING for result in summary.case_results
    )

    detail = summary.profile_detail["multi_agent"]
    assert detail["tick_ms"] == 200
    assert detail["stagger_ms"] == 50
    assert detail["director_fanout"] == 2
    assert detail["per_agent_outcome_counts"]["vera"]
    assert summary.timing_summary["per_agent"]["vera"]["cases"] == 2
