"""Tests for Minecraft live command telemetry models."""

from __future__ import annotations

import json

import pytest

from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    EvalCategory,
    InventoryDelta,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
    classify_eval_category,
    derive_block_mutation,
    derive_inventory_delta,
    derive_pathfinding_signals,
)


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("ok", None, OutcomeClass.SUCCESS),
        ("success", None, OutcomeClass.SUCCESS),
        ("malformed", "parser rejected command", OutcomeClass.MALFORMED),
        ("rejected", "permission gate", OutcomeClass.REJECTED),
        ("failed", "blocked by world collision", OutcomeClass.WORLD_CONSTRAINT),
        ("partial", "missing inventory", OutcomeClass.WORLD_CONSTRAINT),
        ("timeout", "action timed out", OutcomeClass.TIMEOUT),
        ("failed", "unexpected bridge error", OutcomeClass.ERROR),
    ],
)
def test_classify_bridge_status_returns_stable_outcome_classes(
    status: str,
    reason: str | None,
    expected: str,
) -> None:
    assert classify_bridge_status(status, reason=reason) == expected


@pytest.mark.parametrize(
    ("command_name", "reason", "final_state", "expected"),
    [
        ("move", "completed", {"pose": {"x": 1}}, EvalCategory.PATHFINDING),
        (
            "searchForBlock",
            "blocked by collision: cannot path to target",
            {"pathfinding": {"collision": True}},
            EvalCategory.COLLISION,
        ),
        ("inventory", "completed", {"inventory": {"torch": 4}}, EvalCategory.INVENTORY),
        ("placeHere", "completed", {"blocks": []}, EvalCategory.BLOCK_MUTATION),
        ("buildFromPlan", "completed", {"blocks": []}, EvalCategory.BLOCK_MUTATION),
        ("buildFromPlan", "no path to target", {"blocked_path": True}, EvalCategory.PATHFINDING),
        ("nearbyBlocks", "completed", {"inventory": {"torch": 4}}, EvalCategory.INVENTORY),
    ],
)
def test_classify_eval_category_separates_pathfinding_collision_and_other(
    command_name: str,
    reason: str,
    final_state: dict[str, object],
    expected: str,
) -> None:
    assert (
        classify_eval_category(command_name, OutcomeClass.SUCCESS, reason, final_state) == expected
    )


@pytest.mark.parametrize(
    ("outcome_class", "reason", "final_state", "expected"),
    [
        (
            OutcomeClass.SUCCESS,
            "completed",
            {"pose": {"x": 1, "y": 64, "z": 0}},
            {
                "success": True,
                "stuck": False,
                "collision": False,
                "blocked_path": False,
            },
        ),
        (
            OutcomeClass.WORLD_CONSTRAINT,
            "no path to target",
            {"pose": {"x": 0, "y": 64, "z": 0}},
            {
                "success": False,
                "stuck": False,
                "collision": False,
                "blocked_path": True,
            },
        ),
        (
            OutcomeClass.TIMEOUT,
            "stuck: action timed out while pathfinding",
            {"pathfinding": {"stuck": True, "pose": {"x": 0, "y": 64, "z": 0}}},
            {
                "success": False,
                "stuck": True,
                "collision": False,
                "blocked_path": False,
            },
        ),
        (
            OutcomeClass.WORLD_CONSTRAINT,
            "blocked by collision: cannot path to target",
            {
                "pathfinding": {"collision": True, "blocked_path": True},
                "pose": {"x": 2, "y": 64, "z": 0},
            },
            {
                "success": False,
                "stuck": False,
                "collision": True,
                "blocked_path": True,
            },
        ),
        (
            OutcomeClass.WORLD_CONSTRAINT,
            "stuck against terrain",
            {"pathfinding": {"stuck": True}, "final_pose": {"x": 3, "y": 64, "z": 0}},
            {
                "success": False,
                "stuck": True,
                "collision": False,
                "blocked_path": False,
            },
        ),
    ],
)
def test_derive_pathfinding_signals_for_success_blocked_timeout_collision_and_stuck(
    outcome_class: str,
    reason: str,
    final_state: dict[str, object],
    expected: dict[str, bool | None],
) -> None:
    signals = derive_pathfinding_signals(
        "move",
        outcome_class,
        reason=reason,
        final_state=final_state,
    )

    assert signals is not None
    assert signals.success is expected["success"]
    assert signals.stuck is expected["stuck"]
    assert signals.collision is expected["collision"]
    assert signals.blocked_path is expected["blocked_path"]
    assert signals.final_pose is not None


def test_derive_pathfinding_signals_returns_none_for_non_navigation_command() -> None:
    assert (
        derive_pathfinding_signals(
            "inventory",
            OutcomeClass.SUCCESS,
            reason="completed",
            final_state={"inventory": {"torch": 4}},
        )
        is None
    )


def test_derive_inventory_delta_compares_expected_net_changes() -> None:
    match = derive_inventory_delta(
        "placeHere",
        OutcomeClass.SUCCESS,
        params={"expected_inventory_delta": {"oak_planks": -1}},
        final_state={
            "initial_inventory": {"oak_planks": 3, "torch": 1},
            "inventory": {"oak_planks": 2, "torch": 1},
        },
    )

    assert match is not None
    assert match.initial == {"oak_planks": 3, "torch": 1}
    assert match.final == {"oak_planks": 2, "torch": 1}
    assert match.removed == {"oak_planks": 1}
    assert match.net == {"oak_planks": -1}
    assert match.matches_expected is True
    assert match.missing_expected == {}
    assert match.unexpected == {}

    missing = derive_inventory_delta(
        "placeHere",
        OutcomeClass.SUCCESS,
        params={"expected_inventory_delta": {"oak_planks": -1}},
        final_state={
            "initial_inventory": {"oak_planks": 3},
            "inventory": {"oak_planks": 3},
        },
    )

    assert missing is not None
    assert missing.matches_expected is False
    assert missing.missing_expected == {"oak_planks": -1}
    assert missing.unexpected == {}

    unexpected = derive_inventory_delta(
        "placeHere",
        OutcomeClass.SUCCESS,
        params={"expected_inventory_delta": {"oak_planks": -1}},
        final_state={
            "initial_inventory": {"oak_planks": 3},
            "inventory": {"oak_planks": 2, "torch": 1},
        },
    )

    assert unexpected is not None
    assert unexpected.matches_expected is False
    assert unexpected.missing_expected == {}
    assert unexpected.unexpected == {"torch": 1}


def test_derive_inventory_delta_returns_none_for_non_inventory_commands_without_state() -> None:
    assert (
        derive_inventory_delta(
            "nearbyBlocks",
            OutcomeClass.SUCCESS,
            params={},
            final_state={"nearby_blocks": []},
        )
        is None
    )


def test_derive_block_mutation_compares_intended_and_actual_placements() -> None:
    match = derive_block_mutation(
        "placeHere",
        OutcomeClass.SUCCESS,
        params={
            "expected_blocks": [
                {"x": 1, "y": 64, "z": 2, "block_type": "oak_planks"},
            ]
        },
        final_state={
            "initial_blocks": [],
            "blocks": [{"x": 1, "y": 64, "z": 2, "block_type": "oak_planks"}],
        },
    )

    assert match is not None
    assert match.matches_expected is True
    assert match.matched_placements == ({"x": 1, "y": 64, "z": 2, "block_type": "oak_planks"},)
    assert match.missing_placements == ()
    assert match.extra_placements == ()

    missing = derive_block_mutation(
        "buildFromPlan",
        OutcomeClass.SUCCESS,
        params={
            "origin": {"x": 10, "y": 64, "z": 10},
            "plan": {
                "blocks": [
                    {"dx": 0, "dy": 0, "dz": 0, "block_type": "glass"},
                    {"dx": 1, "dy": 0, "dz": 0, "block_type": "glass"},
                ]
            },
        },
        final_state={
            "blocks": [{"x": 10, "y": 64, "z": 10, "block_type": "glass"}],
        },
    )

    assert missing is not None
    assert missing.matches_expected is False
    assert missing.missing_placements == ({"x": 11, "y": 64, "z": 10, "block_type": "glass"},)
    assert missing.extra_placements == ()

    extra = derive_block_mutation(
        "placeHere",
        OutcomeClass.SUCCESS,
        params={
            "expected_blocks": [
                {"x": 1, "y": 64, "z": 2, "block_type": "oak_planks"},
            ]
        },
        final_state={
            "blocks": [
                {"x": 1, "y": 64, "z": 2, "block_type": "oak_planks"},
                {"x": 1, "y": 64, "z": 3, "block_type": "torch"},
            ],
        },
    )

    assert extra is not None
    assert extra.matches_expected is False
    assert extra.extra_placements == ({"x": 1, "y": 64, "z": 3, "block_type": "torch"},)


def test_derive_block_mutation_returns_none_for_non_mutation_commands() -> None:
    assert (
        derive_block_mutation(
            "inventory",
            OutcomeClass.SUCCESS,
            params={"expected_blocks": [{"x": 0, "y": 64, "z": 0, "block_type": "stone"}]},
            final_state={"blocks": [{"x": 0, "y": 64, "z": 0, "block_type": "stone"}]},
        )
        is None
    )


def test_live_run_summary_to_dict_is_json_round_trippable() -> None:
    event = ActionEvent(
        action_id="place-1",
        kind="start",
        ts_ms=123,
        payload={"command_text": "!placeHere oak_planks"},
    )
    result = CaseResult(
        case_id="live-placeHere-0001",
        command_text="!placeHere oak_planks",
        params={
            "action_id": "place-1",
            "expected_blocks": [{"x": 0, "y": 64, "z": 1, "block_type": "oak_planks"}],
            "expected_inventory_delta": {"oak_planks": -1},
        },
        action_events=(event,),
        outcome_class=OutcomeClass.SUCCESS,
        final_state={
            "initial_inventory": {"oak_planks": 2},
            "inventory": {"oak_planks": 1},
            "initial_blocks": [],
            "blocks": [{"x": 0, "y": 64, "z": 1, "block_type": "oak_planks"}],
        },
        latency_ms=4,
    )
    summary = LiveRunSummary(
        command="placeHere",
        resolved_command="placeHere",
        profile="flat-eval",
        seed=7,
        dry_run=True,
        verbose=True,
        case_results=(result,),
        profile_detail={"mc_port": 25568},
    )

    data = summary.to_dict()
    assert data["cases"] == 1
    assert data["passed"] == 1
    assert data["failed"] == 0
    assert data["outcome_counts"][OutcomeClass.SUCCESS] == 1
    assert data["category_counts"][EvalCategory.BLOCK_MUTATION] == 1
    assert data["inventory_summary"]["matches"] == 1
    assert data["inventory_summary"]["cases_with_state"] == 1
    assert data["block_mutation_summary"]["matches"] == 1
    assert data["block_mutation_summary"]["cases_with_state"] == 1
    assert data["case_results"][0]["eval_category"] == EvalCategory.BLOCK_MUTATION
    assert data["case_results"][0]["inventory"]["matches_expected"] is True
    assert data["case_results"][0]["inventory"]["net"] == {"oak_planks": -1}
    assert data["case_results"][0]["block_mutation"]["matches_expected"] is True
    assert data["case_results"][0]["block_mutation"]["actual_placements"] == [
        {"x": 0, "y": 64, "z": 1, "block_type": "oak_planks"}
    ]
    assert data["case_results"][0]["action_events"][0]["kind"] == "start"

    assert json.loads(json.dumps(data)) == data


def test_inventory_delta_mapping_coerces_to_json_shape() -> None:
    delta = InventoryDelta(
        initial={"oak_planks": 2},
        final={"oak_planks": 1},
        added={},
        removed={"oak_planks": 1},
        net={"oak_planks": -1},
        matches_expected=True,
        missing_expected={},
        unexpected={},
    )

    assert delta.to_dict()["net"] == {"oak_planks": -1}


def test_action_event_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="action event kind"):
        ActionEvent(action_id="move-1", kind="middle", ts_ms=1, payload={})
