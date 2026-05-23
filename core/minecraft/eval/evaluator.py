"""Semantic evaluator for text-only Minecraft command eval responses."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.minecraft.commands import CommandParam, CommandSchema, CommandSchemaSet
from core.minecraft.eval.parser import ParsedResponse, parse_model_response
from core.minecraft.scenarios import Scenario, SemanticConstraint


class EvalOutcome(StrEnum):
    """Scoring classes for one parsed Minecraft eval response."""

    ACCEPTED = "accepted"
    MALFORMED = "malformed"
    UNKNOWN_COMMAND = "unknown_command"
    WRONG_ARGS = "wrong_args"
    INVALID_ARG = "invalid_arg"
    DISALLOWED_TOOL = "disallowed_tool"
    UNSAFE_CONTEXT = "unsafe_context"
    SEMANTIC_REJECT = "semantic_reject"


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Serializable evaluation result for one scenario response."""

    scenario_id: str
    outcome: EvalOutcome
    reasons: tuple[str, ...]
    parsed: ParsedResponse
    matched_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "parsed": self.parsed.to_dict(),
            "matched_command": self.matched_command,
        }


@dataclass(frozen=True, slots=True)
class _CommandSurface:
    by_token: Mapping[str, CommandSchema]
    disallowed: frozenset[str]


_OUTCOME_PRIORITY: tuple[EvalOutcome, ...] = (
    EvalOutcome.MALFORMED,
    EvalOutcome.UNKNOWN_COMMAND,
    EvalOutcome.DISALLOWED_TOOL,
    EvalOutcome.WRONG_ARGS,
    EvalOutcome.INVALID_ARG,
    EvalOutcome.UNSAFE_CONTEXT,
    EvalOutcome.SEMANTIC_REJECT,
)

_STRING_TYPES = frozenset(
    (
        "string",
        "blockname",
        "itemname",
        "entityname",
        "playername",
        "tag",
        "goal",
    )
)
_INT_TYPES = frozenset(("int", "integer"))
_FLOAT_TYPES = frozenset(("number", "float"))
_BOOL_TYPES = frozenset(("bool", "boolean"))


def evaluate_response(
    scenario: Scenario,
    content: str,
    commands: CommandSchemaSet | Mapping[str, CommandSchema],
) -> EvalReport:
    """Validate one model response against command contracts and scenario constraints."""

    parsed = parse_model_response(content)
    if parsed.parse_error is not None:
        return EvalReport(
            scenario_id=scenario.id,
            outcome=EvalOutcome.MALFORMED,
            reasons=(f"parse_error={parsed.parse_error}",),
            parsed=parsed,
        )

    surface = _command_surface(commands)
    failures: dict[EvalOutcome, list[str]] = {}
    matched_schema: CommandSchema | None = None
    matched_command: str | None = None

    if parsed.kind == "chat":
        _add_semantic_failures(
            failures,
            scenario=scenario,
            parsed=parsed,
            matched_command=None,
        )
        return _report_from_failures(
            scenario_id=scenario.id,
            parsed=parsed,
            matched_command=None,
            failures=failures,
        )

    if parsed.kind == "command" and parsed.command_token is not None:
        matched_schema = surface.by_token.get(parsed.command_token)
        matched_command = matched_schema.name if matched_schema is not None else None
        token_is_disallowed = _token_is_disallowed(
            parsed.command_token,
            matched_schema,
            surface.disallowed,
            scenario.disallowed_commands,
        )

        if matched_schema is None and not token_is_disallowed:
            _add_failure(
                failures,
                EvalOutcome.UNKNOWN_COMMAND,
                f"unknown command: {parsed.command_token}",
            )
        if token_is_disallowed:
            _add_failure(
                failures,
                EvalOutcome.DISALLOWED_TOOL,
                f"command is disallowed: {parsed.command_token}",
            )

        if matched_schema is not None:
            if _should_enforce_available_commands(scenario) and not _is_available_command(
                parsed.command_token,
                matched_schema.name,
                scenario.available_commands,
            ):
                _add_failure(
                    failures,
                    EvalOutcome.DISALLOWED_TOOL,
                    f"command is unavailable in scenario: {parsed.command_token}",
                )
            _add_arg_contract_failures(
                failures,
                parsed=parsed,
                schema=matched_schema,
            )

        if _has_constraint(scenario, "require_chat_only"):
            _add_failure(
                failures,
                EvalOutcome.UNSAFE_CONTEXT,
                "scenario requires a chat-only response",
            )

        _add_semantic_failures(
            failures,
            scenario=scenario,
            parsed=parsed,
            matched_command=matched_command,
        )

    return _report_from_failures(
        scenario_id=scenario.id,
        parsed=parsed,
        matched_command=matched_command,
        failures=failures,
    )


def _command_surface(
    commands: CommandSchemaSet | Mapping[str, CommandSchema],
) -> _CommandSurface:
    by_token: dict[str, CommandSchema] = {}
    disallowed: set[str] = set()

    if isinstance(commands, CommandSchemaSet):
        schemas = commands.commands
        disallowed.update(commands.disallowed)
    else:
        schemas = tuple(commands.values())
        for token, schema in commands.items():
            by_token[token] = schema

    for schema in schemas:
        by_token[schema.name] = schema
        for alias in schema.aliases:
            by_token[alias] = schema
        if schema.disallowed or schema.internal:
            disallowed.add(schema.name)
            disallowed.update(schema.aliases)

    return _CommandSurface(by_token=by_token, disallowed=frozenset(disallowed))


def _token_is_disallowed(
    token: str,
    schema: CommandSchema | None,
    command_surface_disallowed: frozenset[str],
    scenario_disallowed: tuple[str, ...],
) -> bool:
    canonical = schema.name if schema is not None else None
    tokens = {token}
    if canonical is not None:
        tokens.add(canonical)
    return bool(
        tokens.intersection(command_surface_disallowed) or tokens.intersection(scenario_disallowed)
    )


def _is_available_command(
    token: str,
    canonical: str,
    available_commands: tuple[str, ...],
) -> bool:
    return token in available_commands or canonical in available_commands


def _should_enforce_available_commands(scenario: Scenario) -> bool:
    if scenario.available_commands:
        return True
    return not _has_constraint(scenario, "require_chat_only") and not _has_max_steps_zero(scenario)


def _add_arg_contract_failures(
    failures: dict[EvalOutcome, list[str]],
    *,
    parsed: ParsedResponse,
    schema: CommandSchema,
) -> None:
    required_count = len(schema.required_param_names)
    max_count = required_count + len(schema.optional_param_names)
    arg_count = len(parsed.args)
    if arg_count < required_count or arg_count > max_count:
        _add_failure(
            failures,
            EvalOutcome.WRONG_ARGS,
            f"{schema.name} expected {required_count}-{max_count} args, got {arg_count}",
        )
        return

    for index, arg in enumerate(parsed.args):
        if index >= len(schema.params):
            break
        param = schema.params[index]
        if not _arg_matches_type(arg, param):
            _add_failure(
                failures,
                EvalOutcome.INVALID_ARG,
                f"{schema.name} arg {param.name} expected {param.type}, got {arg!r}",
            )


def _arg_matches_type(arg: str, param: CommandParam) -> bool:
    normalized_type = param.type.casefold()
    if normalized_type in _STRING_TYPES:
        return bool(arg)
    if normalized_type in _INT_TYPES:
        return _is_int(arg)
    if normalized_type in _FLOAT_TYPES:
        return _is_float(arg)
    if normalized_type in _BOOL_TYPES:
        return arg.casefold() in {"true", "false"}
    if normalized_type == "vec3":
        return _is_vec3(arg)
    return bool(arg)


def _is_int(value: str) -> bool:
    try:
        int(value, 10)
    except ValueError:
        return False
    return True


def _is_float(value: str) -> bool:
    try:
        parsed = float(value)
    except ValueError:
        return False
    return math.isfinite(parsed)


def _is_vec3(value: str) -> bool:
    parts = value.replace(",", " ").split()
    return len(parts) == 3 and all(_is_float(part) for part in parts)


def _add_semantic_failures(
    failures: dict[EvalOutcome, list[str]],
    *,
    scenario: Scenario,
    parsed: ParsedResponse,
    matched_command: str | None,
) -> None:
    for constraint in scenario.expected_constraints:
        reason = _semantic_failure_reason(
            constraint,
            scenario=scenario,
            parsed=parsed,
            matched_command=matched_command,
        )
        if reason is not None:
            _add_failure(failures, EvalOutcome.SEMANTIC_REJECT, reason)


def _semantic_failure_reason(
    constraint: SemanticConstraint,
    *,
    scenario: Scenario,
    parsed: ParsedResponse,
    matched_command: str | None,
) -> str | None:
    condition = _semantic_condition(
        constraint,
        scenario=scenario,
        parsed=parsed,
        matched_command=matched_command,
    )
    if condition == constraint.must_be_true:
        return None
    return f"constraint failed: {constraint.kind} {constraint.target}"


def _semantic_condition(
    constraint: SemanticConstraint,
    *,
    scenario: Scenario,
    parsed: ParsedResponse,
    matched_command: str | None,
) -> bool:
    command_token = parsed.command_token if parsed.kind == "command" else None
    if constraint.kind == "require_command":
        return _command_matches(command_token, matched_command, constraint.target)
    if constraint.kind == "forbid_command":
        return not _command_matches(command_token, matched_command, constraint.target)
    if constraint.kind == "require_inventory":
        return _inventory_count(scenario, constraint.target) >= _quantity(constraint.value)
    if constraint.kind == "forbid_inventory":
        return _inventory_count(scenario, constraint.target) < _quantity(constraint.value)
    if constraint.kind == "require_tool":
        return constraint.target in {tool.name for tool in scenario.tools}
    if constraint.kind == "forbid_tool":
        return constraint.target not in {tool.name for tool in scenario.tools}
    if constraint.kind == "require_chat_only":
        return parsed.kind == "chat"
    if constraint.kind == "max_steps":
        max_steps = constraint.value if type(constraint.value) is int else 0
        return (1 if parsed.kind == "command" else 0) <= max_steps
    if constraint.kind == "must_observe_first":
        return _command_matches(command_token, matched_command, "!observe")
    return True


def _command_matches(
    command_token: str | None,
    matched_command: str | None,
    expected: str,
) -> bool:
    return expected in {command_token, matched_command}


def _inventory_count(scenario: Scenario, target: str) -> int:
    return sum(item.count for item in scenario.inventory if item.name == target)


def _quantity(value: Any) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    return 1


def _has_constraint(scenario: Scenario, kind: str) -> bool:
    return any(
        constraint.kind == kind and constraint.must_be_true
        for constraint in scenario.expected_constraints
    )


def _has_max_steps_zero(scenario: Scenario) -> bool:
    return any(
        constraint.kind == "max_steps" and constraint.must_be_true and constraint.value == 0
        for constraint in scenario.expected_constraints
    )


def _add_failure(
    failures: dict[EvalOutcome, list[str]],
    outcome: EvalOutcome,
    reason: str,
) -> None:
    failures.setdefault(outcome, []).append(reason)


def _report_from_failures(
    *,
    scenario_id: str,
    parsed: ParsedResponse,
    matched_command: str | None,
    failures: dict[EvalOutcome, list[str]],
) -> EvalReport:
    for outcome in _OUTCOME_PRIORITY:
        if outcome in failures:
            return EvalReport(
                scenario_id=scenario_id,
                outcome=outcome,
                reasons=tuple(reason for reasons in failures.values() for reason in reasons),
                parsed=parsed,
                matched_command=matched_command,
            )
    return EvalReport(
        scenario_id=scenario_id,
        outcome=EvalOutcome.ACCEPTED,
        reasons=(),
        parsed=parsed,
        matched_command=matched_command,
    )
