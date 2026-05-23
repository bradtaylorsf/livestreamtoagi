"""Tests for the text-only Minecraft command semantic evaluator."""

from __future__ import annotations

from core.minecraft.commands import CommandParam, CommandSchema, CommandSchemaSet
from core.minecraft.eval import EvalOutcome, evaluate_response
from core.minecraft.scenarios import (
    InventoryItem,
    Scenario,
    SemanticConstraint,
    ToolAvailability,
)


def _command_surface() -> CommandSchemaSet:
    return CommandSchemaSet(
        commands=(
            CommandSchema(name="!observe", description="Observe the nearby world."),
            CommandSchema(
                name="!move",
                aliases=("!walk",),
                description="Move a verified distance.",
                params=(CommandParam(name="distance", type="int"),),
            ),
            CommandSchema(name="!inventory", description="Inspect inventory."),
            CommandSchema(
                name="!gather",
                description="Gather one available item.",
                params=(CommandParam(name="item", type="ItemName"),),
            ),
            CommandSchema(name="!stop", description="Internal stop.", disallowed=True),
        ),
        disallowed=("!stop",),
    )


def _scenario(
    scenario_id: str,
    *,
    available_commands: tuple[str, ...],
    constraints: tuple[SemanticConstraint, ...],
    inventory: tuple[InventoryItem, ...] = (),
    tools: tuple[ToolAvailability, ...] = (),
    disallowed_commands: tuple[str, ...] = ("!stop",),
) -> Scenario:
    return Scenario(
        id=scenario_id,
        seed=781,
        prompt_context="Choose the next safe text-only Minecraft action.",
        inventory=inventory,
        tools=tools,
        available_commands=available_commands,
        disallowed_commands=disallowed_commands,
        skill_card_ids=("fixture",),
        expected_constraints=constraints,
        tags=("fixture",),
        source="tests/backend/test_mc_eval_evaluator.py",
    )


def _constraint(
    kind: str,
    target: str,
    *,
    value: object | None = None,
    must_be_true: bool = True,
) -> SemanticConstraint:
    return SemanticConstraint(
        kind=kind,
        target=target,
        value=value,
        must_be_true=must_be_true,
    )


def test_accepts_chat_only_response_when_required() -> None:
    scenario = _scenario(
        "chat-only-accepted",
        available_commands=(),
        constraints=(
            _constraint("require_chat_only", "response"),
            _constraint("max_steps", "commands", value=0),
        ),
    )

    report = evaluate_response(scenario, "chat: I cannot run that.", _command_surface())

    assert report.outcome == EvalOutcome.ACCEPTED
    assert report.parsed.kind == "chat"


def test_accepts_valid_observe_command() -> None:
    scenario = _scenario(
        "observe-accepted",
        available_commands=("!observe", "!inventory"),
        constraints=(
            _constraint("require_command", "!observe"),
            _constraint("must_observe_first", "next_action"),
            _constraint("max_steps", "commands", value=1),
        ),
        inventory=(InventoryItem(name="oak_log", count=2),),
    )

    report = evaluate_response(scenario, "!observe", _command_surface())

    assert report.outcome == EvalOutcome.ACCEPTED
    assert report.matched_command == "!observe"


def test_accepts_alias_when_canonical_command_is_available() -> None:
    scenario = _scenario(
        "move-alias-accepted",
        available_commands=("!move",),
        constraints=(_constraint("require_command", "!move"),),
    )

    report = evaluate_response(scenario, "!walk 2", _command_surface())

    assert report.outcome == EvalOutcome.ACCEPTED
    assert report.matched_command == "!move"


def test_rejects_malformed_response() -> None:
    scenario = _scenario(
        "malformed-response",
        available_commands=("!observe",),
        constraints=(_constraint("require_command", "!observe"),),
    )

    report = evaluate_response(scenario, "I should observe.", _command_surface())

    assert report.outcome == EvalOutcome.MALFORMED
    assert report.reasons == ("parse_error=no-leading-command",)


def test_rejects_unknown_command() -> None:
    scenario = _scenario(
        "unknown-command",
        available_commands=("!observe",),
        constraints=(_constraint("require_command", "!observe"),),
    )

    report = evaluate_response(scenario, "!teleport home", _command_surface())

    assert report.outcome == EvalOutcome.UNKNOWN_COMMAND
    assert report.matched_command is None


def test_rejects_wrong_arg_count() -> None:
    scenario = _scenario(
        "wrong-arg-count",
        available_commands=("!move",),
        constraints=(_constraint("require_command", "!move"),),
    )

    missing_arg = evaluate_response(scenario, "!move", _command_surface())
    extra_args = evaluate_response(scenario, "!move 1 2 3", _command_surface())

    assert missing_arg.outcome == EvalOutcome.WRONG_ARGS
    assert extra_args.outcome == EvalOutcome.WRONG_ARGS


def test_rejects_invalid_arg_type() -> None:
    scenario = _scenario(
        "invalid-arg-type",
        available_commands=("!move",),
        constraints=(_constraint("require_command", "!move"),),
    )

    report = evaluate_response(scenario, "!move north", _command_surface())

    assert report.outcome == EvalOutcome.INVALID_ARG
    assert any("expected int" in reason for reason in report.reasons)


def test_rejects_disallowed_command() -> None:
    scenario = _scenario(
        "disallowed-command",
        available_commands=("!observe",),
        constraints=(_constraint("require_command", "!observe"),),
    )

    report = evaluate_response(scenario, "!stop", _command_surface())

    assert report.outcome == EvalOutcome.DISALLOWED_TOOL


def test_rejects_command_not_available_in_scenario() -> None:
    scenario = _scenario(
        "unavailable-command",
        available_commands=("!observe",),
        constraints=(_constraint("require_command", "!observe"),),
    )

    report = evaluate_response(scenario, "!inventory", _command_surface())

    assert report.outcome == EvalOutcome.DISALLOWED_TOOL
    assert any("unavailable" in reason for reason in report.reasons)


def test_rejects_command_when_no_available_surface_is_declared() -> None:
    scenario = _scenario(
        "empty-available-command-surface",
        available_commands=(),
        constraints=(),
    )

    report = evaluate_response(scenario, "!observe", _command_surface())

    assert report.outcome == EvalOutcome.DISALLOWED_TOOL


def test_rejects_command_in_chat_only_context_as_unsafe() -> None:
    scenario = _scenario(
        "unsafe-chat-only",
        available_commands=(),
        constraints=(
            _constraint("require_chat_only", "response"),
            _constraint("max_steps", "commands", value=0),
        ),
    )

    report = evaluate_response(scenario, "!observe", _command_surface())

    assert report.outcome == EvalOutcome.UNSAFE_CONTEXT
    assert any("chat-only" in reason for reason in report.reasons)


def test_rejects_command_that_violates_required_command_semantics() -> None:
    scenario = _scenario(
        "semantic-required-command",
        available_commands=("!move", "!inventory"),
        constraints=(_constraint("require_command", "!move"),),
    )

    report = evaluate_response(scenario, "!inventory", _command_surface())

    assert report.outcome == EvalOutcome.SEMANTIC_REJECT
    assert any("require_command" in reason for reason in report.reasons)


def test_rejects_when_required_inventory_count_is_too_low() -> None:
    scenario = _scenario(
        "semantic-inventory-count",
        available_commands=("!move",),
        constraints=(
            _constraint("require_command", "!move"),
            _constraint("require_inventory", "bread", value=2),
        ),
        inventory=(InventoryItem(name="bread", count=1),),
    )

    report = evaluate_response(scenario, "!move 3", _command_surface())

    assert report.outcome == EvalOutcome.SEMANTIC_REJECT
    assert any("require_inventory" in reason for reason in report.reasons)


def test_rejects_when_forbidden_tool_is_present() -> None:
    scenario = _scenario(
        "semantic-forbidden-tool",
        available_commands=("!gather",),
        constraints=(
            _constraint("require_command", "!gather"),
            _constraint("forbid_tool", "iron_pickaxe"),
        ),
        tools=(ToolAvailability(name="iron_pickaxe", durability_pct=80),),
    )

    report = evaluate_response(scenario, "!gather oak_log", _command_surface())

    assert report.outcome == EvalOutcome.SEMANTIC_REJECT
    assert any("forbid_tool" in reason for reason in report.reasons)


def test_rejects_max_steps_zero_without_hiding_unsafe_context_precedence() -> None:
    scenario = _scenario(
        "semantic-max-steps",
        available_commands=(),
        constraints=(_constraint("max_steps", "commands", value=0),),
    )

    report = evaluate_response(scenario, "!observe", _command_surface())

    assert report.outcome == EvalOutcome.SEMANTIC_REJECT
    assert all("chat-only" not in reason for reason in report.reasons)


def test_report_to_dict_is_serializable_shape() -> None:
    scenario = _scenario(
        "report-dict",
        available_commands=("!observe",),
        constraints=(_constraint("require_command", "!observe"),),
    )

    report = evaluate_response(scenario, "!observe", _command_surface())

    assert set(report.to_dict()) == {
        "scenario_id",
        "outcome",
        "reasons",
        "parsed",
        "matched_command",
    }
    assert report.to_dict()["parsed"] == {
        "kind": "command",
        "raw": "!observe",
        "command_token": "!observe",
        "args": [],
        "chat_text": None,
        "parse_error": None,
    }
