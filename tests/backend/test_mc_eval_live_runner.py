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
        assert result.eval_category == EvalCategory.INVENTORY
        assert result.inventory is not None
        assert result.inventory.initial
        assert result.inventory.final
        assert result.action_events[-1].payload["inventory"] is not None


async def test_fake_bridge_surfaces_queue_signals_in_final_state() -> None:
    bridge = FakeBridgeClient(
        {
            "move": (
                {
                    "status": "ok",
                    "reason": "completed",
                    "queue_depth": 2,
                    "conflicting_action_ids": ["rex-place-1"],
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
    assert result.final_state["queue_depth"] == 2
    assert result.final_state["conflicting_action_ids"] == ["rex-place-1"]


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


async def test_place_here_records_inventory_and_block_mutation_success() -> None:
    summary = await run_live_command_smoke(
        "placeHere",
        1,
        bridge=FakeBridgeClient(),
        profile="flat-eval",
        seed=2,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    result = summary.case_results[0]
    assert result.eval_category == EvalCategory.BLOCK_MUTATION
    assert result.inventory is not None
    assert result.inventory.matches_expected is True
    assert result.inventory.net == {result.params["block_type"]: -1}
    assert result.block_mutation is not None
    assert result.block_mutation.matches_expected is True
    assert result.block_mutation.missing_placements == ()
    assert result.action_events[-1].payload["inventory"]["matches_expected"] is True
    assert result.action_events[-1].payload["block_mutation"]["matches_expected"] is True


async def test_place_here_records_block_mutation_mismatch_when_expected_block_missing() -> None:
    summary = await run_live_command_smoke(
        "placeHere",
        1,
        bridge=FakeBridgeClient(
            {
                "placeHere": (
                    {
                        "status": "ok",
                        "reason": "completed",
                        "final_state": {
                            "pose": {"x": 0, "y": 64, "z": 0},
                            "initial_inventory": {"oak_planks": 2},
                            "inventory": {"oak_planks": 2},
                            "initial_blocks": [],
                            "blocks": [],
                        },
                    },
                )
            }
        ),
        profile="flat-eval",
        seed=2,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    result = summary.case_results[0]
    assert result.block_mutation is not None
    assert result.block_mutation.matches_expected is False
    assert result.block_mutation.missing_placements == result.block_mutation.intended_placements
    assert result.inventory is not None
    assert result.inventory.matches_expected is False


async def test_build_from_plan_compares_plan_blocks_to_actual_placements() -> None:
    summary = await run_live_command_smoke(
        "buildFromPlan",
        1,
        bridge=FakeBridgeClient(),
        profile="flat-eval",
        seed=4,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    result = summary.case_results[0]
    assert result.eval_category == EvalCategory.BLOCK_MUTATION
    assert result.block_mutation is not None
    assert result.block_mutation.matches_expected is True
    assert len(result.block_mutation.intended_placements) == 2
    assert result.block_mutation.actual_placements == result.block_mutation.intended_placements
    assert result.inventory is not None
    assert result.inventory.matches_expected is True


async def test_run_live_command_smoke_records_lifecycle_categories_from_bridge_events() -> None:
    bridge = FakeBridgeClient(
        {
            "move": (
                {
                    "status": "failed",
                    "reason": "death loop: died in lava after respawn",
                    "action_events": (
                        {
                            "kind": "death",
                            "ts_ms": 1,
                            "payload": {"reason": "died in lava"},
                        },
                        {
                            "kind": "death",
                            "ts_ms": 2,
                            "payload": {"reason": "died in lava again"},
                        },
                        {
                            "kind": "respawn",
                            "ts_ms": 3,
                            "payload": {"reason": "unsafe spawn in lava"},
                        },
                    ),
                    "final_state": {
                        "death_count": 2,
                        "death_loop": True,
                        "respawns": 2,
                        "spawn": {"safe": False, "reason": "spawn in lava"},
                    },
                },
                {
                    "status": "ok",
                    "reason": "respawned at safe spawn",
                    "action_events": (
                        {
                            "kind": "respawn",
                            "ts_ms": 1,
                            "payload": {"message": "respawned at safe spawn"},
                        },
                    ),
                    "final_state": {"respawns": 1, "spawn_safe": True},
                },
                {
                    "status": "timeout",
                    "reason": "stuck state detected",
                    "action_events": (
                        {
                            "kind": "stuck",
                            "ts_ms": 1,
                            "payload": {"reason": "stuck against fence"},
                        },
                    ),
                    "final_state": {"stuck_events": 1},
                },
                {
                    "status": "ok",
                    "reason": "recovered after unstuck attempt",
                    "action_events": (
                        {
                            "kind": "unstuck_attempt",
                            "ts_ms": 1,
                            "payload": {"message": "free_self recovery"},
                        },
                        {
                            "kind": "unstuck_success",
                            "ts_ms": 2,
                            "payload": {"message": "recovered"},
                        },
                    ),
                    "final_state": {
                        "stuck_events": 1,
                        "unstuck_attempts": 1,
                        "unstuck_succeeded": True,
                    },
                },
                {
                    "status": "failed",
                    "reason": "unstuck_failed: still_stuck after recovery",
                    "action_events": (
                        {
                            "kind": "unstuck_attempt",
                            "ts_ms": 1,
                            "payload": {"message": "recovery"},
                        },
                    ),
                    "final_state": {
                        "stuck_events": 1,
                        "unstuck_attempts": 1,
                        "unstuck_failed": True,
                    },
                },
            )
        }
    )

    summary = await run_live_command_smoke(
        "move",
        5,
        bridge=bridge,
        profile="flat-eval",
        seed=1,
        env={},
        project_root=REPO_ROOT,
        dry_run=True,
    )

    death_loop, safe_spawn, stuck, unstuck_success, unstuck_failure = summary.case_results
    assert death_loop.eval_category == EvalCategory.DEATH_LOOP
    assert death_loop.outcome_class == OutcomeClass.WORLD_CONSTRAINT
    assert death_loop.lifecycle is not None
    assert death_loop.lifecycle.death_count == 2
    assert death_loop.lifecycle.death_loop is True
    assert death_loop.lifecycle.safe_spawn is False

    assert safe_spawn.eval_category == EvalCategory.SAFE_SPAWN
    assert safe_spawn.lifecycle is not None
    assert safe_spawn.lifecycle.safe_spawn is True

    assert stuck.eval_category == EvalCategory.STUCK_UNSTUCK
    assert stuck.lifecycle is not None
    assert stuck.lifecycle.stuck is True
    assert stuck.lifecycle.unstuck_attempts == 0

    assert unstuck_success.eval_category == EvalCategory.STUCK_UNSTUCK
    assert unstuck_success.lifecycle is not None
    assert unstuck_success.lifecycle.unstuck_succeeded is True
    assert unstuck_success.lifecycle.unstuck_failed is False

    assert unstuck_failure.eval_category == EvalCategory.STUCK_UNSTUCK
    assert unstuck_failure.lifecycle is not None
    assert unstuck_failure.lifecycle.unstuck_succeeded is False
    assert unstuck_failure.lifecycle.unstuck_failed is True
    assert unstuck_failure.action_events[-1].payload["lifecycle"]["unstuck_failed"] is True
