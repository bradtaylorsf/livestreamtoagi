"""Tests for Minecraft live command telemetry models."""

from __future__ import annotations

import json

import pytest

from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    EvalCategory,
    InventoryDelta,
    LifecycleSignals,
    LiveRunSummary,
    MultiAgentTimingFailure,
    OutcomeClass,
    TimingSignals,
    classify_bridge_status,
    classify_eval_category,
    derive_block_mutation,
    derive_inventory_delta,
    derive_lifecycle_signals,
    derive_pathfinding_signals,
    derive_timing_signals,
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
        (
            "move",
            "death loop after repeated lava deaths",
            {"death_count": 2, "death_loop": True},
            EvalCategory.DEATH_LOOP,
        ),
        (
            "move",
            "respawned at safe spawn",
            {"respawns": 1, "spawn_safe": True},
            EvalCategory.SAFE_SPAWN,
        ),
        (
            "move",
            "unsafe spawn in lava after respawn",
            {"respawns": 1, "spawn": {"safe": False, "reason": "spawn in lava"}},
            EvalCategory.SAFE_SPAWN,
        ),
        (
            "move",
            "unstuck_failed: still_stuck after recovery",
            {"stuck_events": 1, "unstuck_attempts": 1},
            EvalCategory.STUCK_UNSTUCK,
        ),
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


def test_derive_lifecycle_signals_counts_deaths_and_detects_death_loop() -> None:
    signals = derive_lifecycle_signals(
        "move",
        OutcomeClass.WORLD_CONSTRAINT,
        (
            ActionEvent(
                action_id="move-1",
                kind="death",
                ts_ms=1,
                payload={"reason": "died in lava", "pose": {"x": 1, "y": 60, "z": 1}},
            ),
            ActionEvent(
                action_id="move-1",
                kind="death",
                ts_ms=2,
                payload={"reason": "died in lava again"},
            ),
        ),
        params={},
        final_state={"respawns": 2, "spawn": {"safe": False, "reason": "spawn in lava"}},
    )

    assert signals is not None
    assert signals.death_count == 2
    assert signals.death_loop is True
    assert signals.respawns == 2
    assert signals.safe_spawn is False
    assert signals.unsafe_spawn_count >= 1
    assert signals.last_pose == {"x": 1, "y": 60, "z": 1}


def test_derive_lifecycle_signals_marks_safe_spawn_for_clean_respawn() -> None:
    signals = derive_lifecycle_signals(
        "move",
        OutcomeClass.SUCCESS,
        (
            ActionEvent(
                action_id="move-1",
                kind="respawn",
                ts_ms=1,
                payload={"message": "respawned at safe spawn"},
            ),
        ),
        params={},
        final_state={"spawn_safe": True},
    )

    assert signals is not None
    assert signals.respawns == 1
    assert signals.safe_spawn is True
    assert signals.unsafe_spawn_count == 0


def test_derive_lifecycle_signals_marks_unsafe_spawn_from_markers() -> None:
    signals = derive_lifecycle_signals(
        "move",
        OutcomeClass.WORLD_CONSTRAINT,
        (
            ActionEvent(
                action_id="move-1",
                kind="respawn",
                ts_ms=1,
                payload={"reason": "unsafe spawn on cliff spawn"},
            ),
        ),
        params={},
        final_state={"spawn": {"safe": False, "reason": "void spawn"}},
    )

    assert signals is not None
    assert signals.safe_spawn is False
    assert signals.unsafe_spawn_count >= 1
    assert signals.unsafe_spawn_reasons


def test_derive_lifecycle_signals_tracks_unstuck_success_flow() -> None:
    signals = derive_lifecycle_signals(
        "move",
        OutcomeClass.SUCCESS,
        (
            ActionEvent(
                action_id="move-1",
                kind="stuck",
                ts_ms=1,
                payload={"reason": "stuck against fence"},
            ),
            ActionEvent(
                action_id="move-1",
                kind="unstuck_attempt",
                ts_ms=2,
                payload={"message": "free_self recovery"},
            ),
            ActionEvent(
                action_id="move-1",
                kind="unstuck_success",
                ts_ms=3,
                payload={"message": "recovered and freed"},
            ),
        ),
        params={},
        final_state={"pose": {"x": 2, "y": 64, "z": 2}},
    )

    assert signals is not None
    assert signals.stuck is True
    assert signals.stuck_events >= 1
    assert signals.unstuck_attempts >= 1
    assert signals.unstuck_succeeded is True
    assert signals.unstuck_failed is False


def test_derive_lifecycle_signals_marks_unstuck_failed_when_recovery_missing() -> None:
    signals = derive_lifecycle_signals(
        "move",
        OutcomeClass.TIMEOUT,
        (
            ActionEvent(
                action_id="move-1",
                kind="unstuck_attempt",
                ts_ms=1,
                payload={"reason": "unstuck recovery started"},
            ),
        ),
        params={},
        final_state={"stuck_events": 1},
    )

    assert signals is not None
    assert signals.stuck is True
    assert signals.unstuck_attempts == 1
    assert signals.unstuck_succeeded is False
    assert signals.unstuck_failed is True


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
    assert data["lifecycle_summary"]["cases"] == 1
    assert data["case_results"][0]["eval_category"] == EvalCategory.BLOCK_MUTATION
    assert data["case_results"][0]["inventory"]["matches_expected"] is True
    assert data["case_results"][0]["inventory"]["net"] == {"oak_planks": -1}
    assert data["case_results"][0]["block_mutation"]["matches_expected"] is True
    assert data["case_results"][0]["block_mutation"]["actual_placements"] == [
        {"x": 0, "y": 64, "z": 1, "block_type": "oak_planks"}
    ]
    assert data["case_results"][0]["action_events"][0]["kind"] == "start"

    assert json.loads(json.dumps(data)) == data


def test_live_run_summary_lifecycle_summary_aggregates_mixed_cases() -> None:
    death_loop = CaseResult(
        case_id="live-move-0001",
        command_text="!move move-1 north 1 10000",
        params={"action_id": "move-1"},
        action_events=(),
        outcome_class=OutcomeClass.WORLD_CONSTRAINT,
        final_state={},
        latency_ms=4,
        eval_category=EvalCategory.DEATH_LOOP,
        lifecycle=LifecycleSignals(death_count=2, death_loop=True, respawns=2, safe_spawn=False),
    )
    recovered = CaseResult(
        case_id="live-move-0002",
        command_text="!move move-2 north 1 10000",
        params={"action_id": "move-2"},
        action_events=(),
        outcome_class=OutcomeClass.SUCCESS,
        final_state={},
        latency_ms=4,
        eval_category=EvalCategory.STUCK_UNSTUCK,
        lifecycle=LifecycleSignals(
            stuck=True,
            stuck_events=1,
            unstuck_attempts=1,
            unstuck_succeeded=True,
        ),
    )
    failed = CaseResult(
        case_id="live-move-0003",
        command_text="!move move-3 north 1 10000",
        params={"action_id": "move-3"},
        action_events=(),
        outcome_class=OutcomeClass.TIMEOUT,
        final_state={},
        latency_ms=4,
        eval_category=EvalCategory.STUCK_UNSTUCK,
        lifecycle=LifecycleSignals(
            stuck=True,
            stuck_events=1,
            unstuck_attempts=1,
            unstuck_succeeded=False,
            unstuck_failed=True,
        ),
    )
    summary = LiveRunSummary(
        command="move",
        resolved_command="move",
        profile="flat-eval",
        seed=7,
        dry_run=True,
        verbose=True,
        case_results=(death_loop, recovered, failed),
        profile_detail={},
    )

    assert summary.lifecycle_summary == {
        "cases": 3,
        "deaths": 2,
        "death_loops": 1,
        "safe_spawns": 0,
        "unsafe_spawns": 1,
        "stuck_events": 2,
        "unstuck_attempts": 2,
        "unstuck_successes": 1,
        "unstuck_failures": 1,
    }
    assert summary.to_dict()["case_results"][0]["lifecycle"]["death_loop"] is True


def test_derive_timing_signals_classifies_multi_agent_queue_and_loss_markers() -> None:
    signals = derive_timing_signals(
        "vera",
        (
            ActionEvent(
                action_id="move-1",
                kind="queued",
                ts_ms=100,
                payload={
                    "queue_depth": 3,
                    "queue_contention": True,
                    "conflicting_action_ids": ["place-2"],
                },
            ),
            ActionEvent(
                action_id="move-1",
                kind="interrupted",
                ts_ms=110,
                payload={"self_interruption_count": 2},
            ),
            ActionEvent(
                action_id="move-1",
                kind="fanout",
                ts_ms=120,
                payload={"director_fanout_count": 2},
            ),
            ActionEvent(
                action_id="move-1",
                kind="dropped",
                ts_ms=130,
                payload={"dropped_commands": 1, "command_loss_count": 1},
            ),
        ),
        params={"agent_id": "vera", "multi_agent": True},
        final_state={"agents": {"vera": {}}, "last_command_ts_ms": 130},
    )

    assert signals is not None
    assert signals.agent_id == "vera"
    assert signals.queue_depth == 3
    assert signals.queue_contention is True
    assert signals.self_interruption_count == 2
    assert signals.director_fanout_count == 2
    assert signals.dropped_commands == 1
    assert signals.command_loss_count == 1
    assert signals.conflicting_action_ids == ("place-2",)
    assert signals.last_command_ts_ms == 130


def test_classify_eval_category_returns_multi_agent_timing_for_timing_context() -> None:
    assert (
        classify_eval_category(
            "move",
            OutcomeClass.SUCCESS,
            "queue contention",
            {
                "agents": {"vera": {}, "rex": {}},
                "queue_depth": 2,
            },
            params={"multi_agent": True},
        )
        == EvalCategory.MULTI_AGENT_TIMING
    )


def test_case_result_coerces_timing_mapping_to_timing_signals() -> None:
    result = CaseResult(
        case_id="vera-live-move-0001",
        command_text="!move move-1 north 1 10000",
        params={"agent_id": "vera", "multi_agent": True},
        action_events=(),
        outcome_class=OutcomeClass.SUCCESS,
        final_state={"agents": {"vera": {}}, "queue_depth": 2},
        latency_ms=5,
        timing={
            "agent_id": "vera",
            "queue_depth": 2,
            "queue_contention": True,
            "conflicting_action_ids": ["rex-place-1"],
        },
    )

    assert result.agent_id == "vera"
    assert result.eval_category == EvalCategory.MULTI_AGENT_TIMING
    assert isinstance(result.timing, TimingSignals)
    assert result.timing.queue_depth == 2
    assert result.to_dict()["timing"]["conflicting_action_ids"] == ["rex-place-1"]


def test_live_run_summary_timing_summary_aggregates_by_agent_and_failure_class() -> None:
    queue_case = CaseResult(
        case_id="vera-live-move-0001",
        command_text="!move move-1 north 1 10000",
        params={"agent_id": "vera", "multi_agent": True},
        action_events=(),
        outcome_class=OutcomeClass.ERROR,
        final_state={"agents": {"vera": {}}, "queue_depth": 3},
        latency_ms=4,
        eval_category=EvalCategory.MULTI_AGENT_TIMING,
        timing=TimingSignals(agent_id="vera", queue_depth=3, queue_contention=True),
    )
    interruption_case = CaseResult(
        case_id="rex-live-move-0001",
        command_text="!move move-1 north 1 10000",
        params={"agent_id": "rex", "multi_agent": True},
        action_events=(),
        outcome_class=OutcomeClass.TIMEOUT,
        final_state={"agents": {"rex": {}}, "self_interruption_count": 2},
        latency_ms=6,
        eval_category=EvalCategory.MULTI_AGENT_TIMING,
        timing=TimingSignals(agent_id="rex", self_interruption_count=2),
    )
    loss_case = CaseResult(
        case_id="rex-live-move-0002",
        command_text="!move move-2 north 1 10000",
        params={"agent_id": "rex", "multi_agent": True},
        action_events=(),
        outcome_class=OutcomeClass.ERROR,
        final_state={"agents": {"rex": {}}, "command_loss_count": 1},
        latency_ms=8,
        eval_category=EvalCategory.MULTI_AGENT_TIMING,
        timing=TimingSignals(
            agent_id="rex",
            dropped_commands=1,
            command_loss_count=1,
        ),
    )
    summary = LiveRunSummary(
        command="multi-agent-timing",
        resolved_command="multi-agent-timing",
        profile="flat-eval",
        seed=7,
        dry_run=True,
        verbose=True,
        case_results=(queue_case, interruption_case, loss_case),
        profile_detail={},
    )

    timing = summary.timing_summary
    assert timing["cases"] == 3
    assert timing["agents"] == 2
    assert timing["contention"] == 1
    assert timing["interruptions"] == 2
    assert timing["command_loss"] == 1
    assert timing["failure_classes"][MultiAgentTimingFailure.QUEUE_CONTENTION] == 1
    assert timing["failure_classes"][MultiAgentTimingFailure.SELF_INTERRUPTION] == 1
    assert timing["failure_classes"][MultiAgentTimingFailure.COMMAND_LOSS] == 1
    assert timing["per_agent"]["rex"]["cases"] == 2
    assert summary.to_dict()["case_results"][0]["timing"]["queue_contention"] is True


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
