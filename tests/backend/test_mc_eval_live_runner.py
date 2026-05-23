"""Tests for the focused Minecraft live command smoke runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.minecraft.eval.live_runner import (
    CaseGenerator,
    FakeBridgeClient,
    resolve_command_name,
    run_live_command_smoke,
    supported_command_inputs,
)
from core.minecraft.eval.live_telemetry import EvalCategory, OutcomeClass

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_case_generator_is_deterministic_for_same_seed() -> None:
    first = CaseGenerator("move", 5, seed=42).generate()
    second = CaseGenerator("move", 5, seed=42).generate()

    assert [case.command_text for case in first] == [case.command_text for case in second]
    assert len({case.command_text for case in first}) > 1


@pytest.mark.parametrize(
    "command",
    [
        "move",
        "placeHere",
        "searchForBlock",
        "inventory",
        "nearbyBlocks",
        "planAndBuild",
        "buildFromPlan",
    ],
)
def test_case_generator_produces_expected_command_tokens(command: str) -> None:
    generated = CaseGenerator(command, 3, seed=3).generate()

    assert len(generated) == 3
    assert all(case.command_name == command for case in generated)
    assert all(case.command_text.startswith(f"!{command}") for case in generated)
    assert all(case.params["action_id"] for case in generated)


def test_family_resolution_accepts_skill_card_family_ids_and_command_names() -> None:
    assert resolve_command_name("build") == "planAndBuild"
    assert resolve_command_name("observe") == "nearbyBlocks"
    assert resolve_command_name("!move") == "move"
    assert "build" in supported_command_inputs()


def test_unknown_command_rejects_with_helpful_message() -> None:
    with pytest.raises(ValueError, match="unknown Minecraft live eval command"):
        CaseGenerator("teleport", 1)


async def test_fake_bridge_maps_statuses_to_outcome_classes() -> None:
    bridge = FakeBridgeClient(
        {
            "move": (
                {"status": "ok", "reason": "completed"},
                {"status": "malformed", "reason": "parser rejected"},
                {"status": "rejected", "reason": "permission gate"},
                {"status": "failed", "reason": "blocked by world collision"},
                {"status": "timeout", "reason": "action timed out"},
                {"status": "failed", "reason": "unexpected bridge error"},
            )
        }
    )

    summary = await run_live_command_smoke(
        "move",
        6,
        bridge=bridge,
        profile="flat-eval",
        seed=1,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    assert [result.outcome_class for result in summary.case_results] == [
        OutcomeClass.SUCCESS,
        OutcomeClass.MALFORMED,
        OutcomeClass.REJECTED,
        OutcomeClass.WORLD_CONSTRAINT,
        OutcomeClass.TIMEOUT,
        OutcomeClass.ERROR,
    ]
    assert len(bridge.calls) == 6
    assert summary.outcome_counts[OutcomeClass.SUCCESS] == 1
    assert summary.outcome_counts[OutcomeClass.WORLD_CONSTRAINT] == 1
    assert all(
        result.eval_category in {EvalCategory.PATHFINDING, EvalCategory.COLLISION}
        for result in summary.case_results
    )
    assert summary.case_results[3].eval_category == EvalCategory.COLLISION


async def test_run_live_command_smoke_records_action_start_and_end_events() -> None:
    summary = await run_live_command_smoke(
        "inventory",
        2,
        bridge=FakeBridgeClient(),
        profile="flat-eval",
        seed=0,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    assert len(summary.case_results) == 2
    for result in summary.case_results:
        assert [event.kind for event in result.action_events] == ["start", "end"]
        assert result.final_state["command"] == "inventory"
        assert result.eval_category == EvalCategory.OTHER


async def test_run_live_command_smoke_records_collision_pathfinding_signals() -> None:
    bridge = FakeBridgeClient(
        {
            "move": (
                {
                    "status": "failed",
                    "reason": "blocked by collision: cannot path to target",
                    "final_state": {
                        "pose": {"x": 4, "y": 64, "z": 1, "yaw": 180},
                        "pathfinding": {"collision": True, "blocked_path": True},
                    },
                },
            )
        }
    )

    summary = await run_live_command_smoke(
        "move",
        1,
        bridge=bridge,
        profile="flat-eval",
        seed=1,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    result = summary.case_results[0]
    assert result.outcome_class == OutcomeClass.WORLD_CONSTRAINT
    assert result.eval_category == EvalCategory.COLLISION
    assert result.pathfinding is not None
    assert result.pathfinding.collision is True
    assert result.pathfinding.blocked_path is True
    assert result.pathfinding.final_pose == {"x": 4, "y": 64, "z": 1, "yaw": 180}
    assert result.final_state["pose"] == {"x": 4, "y": 64, "z": 1, "yaw": 180}
    assert result.action_events[-1].payload["eval_category"] == EvalCategory.COLLISION
