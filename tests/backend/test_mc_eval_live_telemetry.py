"""Tests for Minecraft live command telemetry models."""

from __future__ import annotations

import json

import pytest

from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
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
    assert data["case_results"][0]["action_events"][0]["kind"] == "start"

    assert json.loads(json.dumps(data)) == data


def test_action_event_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="action event kind"):
        ActionEvent(action_id="move-1", kind="middle", ts_ms=1, payload={})
