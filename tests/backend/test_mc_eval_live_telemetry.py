"""Tests for Minecraft live command telemetry models."""

from __future__ import annotations

import json

import pytest

from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    EvalCategory,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
    classify_eval_category,
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
        ("inventory", "completed", {"inventory": {"torch": 4}}, EvalCategory.OTHER),
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


def test_live_run_summary_to_dict_is_json_round_trippable() -> None:
    event = ActionEvent(
        action_id="move-1",
        kind="start",
        ts_ms=123,
        payload={"command_text": "!move move-1 north 1"},
    )
    result = CaseResult(
        case_id="live-move-0001",
        command_text="!move move-1 north 1",
        params={"action_id": "move-1"},
        action_events=(event,),
        outcome_class=OutcomeClass.SUCCESS,
        final_state={"pose": {"x": 1, "y": 64, "z": 0}},
        latency_ms=4,
    )
    summary = LiveRunSummary(
        command="move",
        resolved_command="move",
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
    assert data["category_counts"][EvalCategory.PATHFINDING] == 1
    assert data["pathfinding_summary"]["success"] == 1
    assert data["pathfinding_summary"]["final_pose"] == 1
    assert data["case_results"][0]["eval_category"] == EvalCategory.PATHFINDING
    assert data["case_results"][0]["pathfinding"]["success"] is True
    assert data["case_results"][0]["pathfinding"]["final_pose"] == {
        "x": 1,
        "y": 64,
        "z": 0,
    }
    assert data["case_results"][0]["action_events"][0]["kind"] == "start"

    assert json.loads(json.dumps(data)) == data


def test_action_event_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="action event kind"):
        ActionEvent(action_id="move-1", kind="middle", ts_ms=1, payload={})
