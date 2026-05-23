"""Versioned scenario fixture models for text-only Minecraft command evals."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

SCENARIO_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMAND_TOKEN_RE = re.compile(r"^![A-Za-z][A-Za-z0-9_]*$")

VALID_CONSTRAINT_KINDS: frozenset[str] = frozenset(
    (
        "require_command",
        "forbid_command",
        "require_inventory",
        "forbid_inventory",
        "require_tool",
        "forbid_tool",
        "require_chat_only",
        "max_steps",
        "must_observe_first",
    )
)

_COMMAND_CONSTRAINT_KINDS = frozenset(("require_command", "forbid_command"))
_INVENTORY_CONSTRAINT_KINDS = frozenset(("require_inventory", "forbid_inventory"))
_TOOL_CONSTRAINT_KINDS = frozenset(("require_tool", "forbid_tool"))


class ScenarioValidationError(ValueError):
    """Raised when a scenario fixture is malformed or inconsistent."""

    def __init__(self, kind: str, message: str, *, field: str | None = None) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.field = field


@dataclass(frozen=True, slots=True)
class InventoryItem:
    name: str
    count: int
    slot: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ScenarioValidationError(
                "invalid-value",
                "inventory item name must be a non-empty string",
                field="inventory.name",
            )
        if type(self.count) is not int or self.count < 0:
            raise ScenarioValidationError(
                "invalid-value",
                f"inventory item {self.name!r} count must be a non-negative integer",
                field="inventory.count",
            )
        if self.slot is not None and (not isinstance(self.slot, str) or not self.slot):
            raise ScenarioValidationError(
                "invalid-value",
                f"inventory item {self.name!r} slot must be a non-empty string",
                field="inventory.slot",
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "count": self.count}
        if self.slot is not None:
            data["slot"] = self.slot
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InventoryItem:
        return cls(
            name=_require_str(data, "name"),
            count=_require_int(data, "count"),
            slot=_optional_str(data, "slot"),
        )


@dataclass(frozen=True, slots=True)
class ToolAvailability:
    name: str
    durability_pct: float | int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ScenarioValidationError(
                "invalid-value",
                "tool name must be a non-empty string",
                field="tools.name",
            )
        if self.durability_pct is not None:
            if not isinstance(self.durability_pct, int | float) or isinstance(
                self.durability_pct,
                bool,
            ):
                raise ScenarioValidationError(
                    "invalid-value",
                    f"tool {self.name!r} durability_pct must be numeric",
                    field="tools.durability_pct",
                )
            if self.durability_pct < 0 or self.durability_pct > 100:
                raise ScenarioValidationError(
                    "invalid-value",
                    f"tool {self.name!r} durability_pct must be between 0 and 100",
                    field="tools.durability_pct",
                )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.durability_pct is not None:
            data["durability_pct"] = self.durability_pct
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ToolAvailability:
        return cls(
            name=_require_str(data, "name"),
            durability_pct=_optional_number(data, "durability_pct"),
        )


@dataclass(frozen=True, slots=True)
class SemanticConstraint:
    kind: str
    target: str
    value: Any | None = None
    must_be_true: bool = True

    def __post_init__(self) -> None:
        if self.kind not in VALID_CONSTRAINT_KINDS:
            raise ScenarioValidationError(
                "unknown-constraint-kind",
                f"unknown semantic constraint kind: {self.kind!r}",
                field="expected_constraints.kind",
            )
        if not isinstance(self.target, str) or not self.target:
            raise ScenarioValidationError(
                "invalid-value",
                f"constraint {self.kind!r} target must be a non-empty string",
                field="expected_constraints.target",
            )
        if type(self.must_be_true) is not bool:
            raise ScenarioValidationError(
                "invalid-value",
                f"constraint {self.kind!r} must_be_true must be a boolean",
                field="expected_constraints.must_be_true",
            )
        if self.kind in _COMMAND_CONSTRAINT_KINDS:
            _validate_command_token(self.target, field="expected_constraints.target")
        if self.kind == "max_steps" and (type(self.value) is not int or self.value < 0):
            raise ScenarioValidationError(
                "invalid-value",
                "max_steps constraint value must be a non-negative integer",
                field="expected_constraints.value",
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "target": self.target,
            "must_be_true": self.must_be_true,
        }
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SemanticConstraint:
        return cls(
            kind=_require_str(data, "kind"),
            target=_require_str(data, "target"),
            value=data.get("value"),
            must_be_true=_optional_bool(data, "must_be_true", default=True),
        )


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    seed: int
    prompt_context: str
    inventory: tuple[InventoryItem, ...]
    tools: tuple[ToolAvailability, ...]
    available_commands: tuple[str, ...]
    disallowed_commands: tuple[str, ...]
    skill_card_ids: tuple[str, ...]
    expected_constraints: tuple[SemanticConstraint, ...]
    tags: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not SCENARIO_ID_RE.fullmatch(self.id):
            raise ScenarioValidationError(
                "invalid-id",
                f"scenario id must be stable kebab-case: {self.id!r}",
                field="id",
            )
        if type(self.seed) is not int:
            raise ScenarioValidationError(
                "invalid-value",
                f"scenario {self.id!r} seed must be an integer",
                field="seed",
            )
        if not isinstance(self.prompt_context, str) or not self.prompt_context.strip():
            raise ScenarioValidationError(
                "invalid-value",
                f"scenario {self.id!r} prompt_context must be a non-empty string",
                field="prompt_context",
            )
        if not isinstance(self.source, str) or not self.source:
            raise ScenarioValidationError(
                "invalid-value",
                f"scenario {self.id!r} source must be a non-empty string",
                field="source",
            )

        inventory = _require_tuple_of_type(self.inventory, InventoryItem, "inventory")
        tools = _require_tuple_of_type(self.tools, ToolAvailability, "tools")
        constraints = _require_tuple_of_type(
            self.expected_constraints,
            SemanticConstraint,
            "expected_constraints",
        )
        available_commands = _tuple_of_command_tokens(
            self.available_commands,
            field="available_commands",
        )
        disallowed_commands = _tuple_of_command_tokens(
            self.disallowed_commands,
            field="disallowed_commands",
        )
        skill_card_ids = _tuple_of_kebab_ids(self.skill_card_ids, field="skill_card_ids")
        tags = _tuple_of_strings(self.tags, field="tags")

        overlap = set(available_commands).intersection(disallowed_commands)
        if overlap:
            raise ScenarioValidationError(
                "command-conflict",
                f"scenario {self.id!r} marks commands as both available and disallowed: "
                f"{sorted(overlap)!r}",
                field="available_commands",
            )

        _validate_constraints_against_fixture(
            self.id,
            available_commands=available_commands,
            inventory=inventory,
            tools=tools,
            constraints=constraints,
        )

        object.__setattr__(self, "inventory", inventory)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "expected_constraints", constraints)
        object.__setattr__(self, "available_commands", available_commands)
        object.__setattr__(self, "disallowed_commands", disallowed_commands)
        object.__setattr__(self, "skill_card_ids", skill_card_ids)
        object.__setattr__(self, "tags", tags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seed": self.seed,
            "prompt_context": self.prompt_context,
            "inventory": [item.to_dict() for item in self.inventory],
            "tools": [tool.to_dict() for tool in self.tools],
            "available_commands": list(self.available_commands),
            "disallowed_commands": list(self.disallowed_commands),
            "skill_card_ids": list(self.skill_card_ids),
            "expected_constraints": [
                constraint.to_dict() for constraint in self.expected_constraints
            ],
            "tags": list(self.tags),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Scenario:
        required_fields = (
            "id",
            "seed",
            "prompt_context",
            "inventory",
            "tools",
            "available_commands",
            "disallowed_commands",
            "skill_card_ids",
            "expected_constraints",
            "tags",
            "source",
        )
        for field_name in required_fields:
            _require_field(data, field_name)

        inventory = tuple(
            InventoryItem.from_dict(_require_mapping(item, "inventory"))
            for item in _require_list(data, "inventory")
        )
        tools = tuple(
            ToolAvailability.from_dict(_require_mapping(item, "tools"))
            for item in _require_list(data, "tools")
        )
        constraints = tuple(
            SemanticConstraint.from_dict(_require_mapping(item, "expected_constraints"))
            for item in _require_list(data, "expected_constraints")
        )

        return cls(
            id=_require_str(data, "id"),
            seed=_require_int(data, "seed"),
            prompt_context=_require_str(data, "prompt_context"),
            inventory=inventory,
            tools=tools,
            available_commands=_tuple_of_strings(
                _require_list(data, "available_commands"),
                field="available_commands",
            ),
            disallowed_commands=_tuple_of_strings(
                _require_list(data, "disallowed_commands"),
                field="disallowed_commands",
            ),
            skill_card_ids=_tuple_of_strings(
                _require_list(data, "skill_card_ids"),
                field="skill_card_ids",
            ),
            expected_constraints=constraints,
            tags=_tuple_of_strings(_require_list(data, "tags"), field="tags"),
            source=_require_str(data, "source"),
        )


@dataclass(frozen=True, slots=True)
class ScenarioSet:
    scenarios: tuple[Scenario, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ScenarioValidationError(
                "schema-version",
                f"unsupported scenario schema version: {self.schema_version!r}",
                field="schema_version",
            )
        scenarios = _require_tuple_of_type(self.scenarios, Scenario, "scenarios")
        ids = [scenario.id for scenario in scenarios]
        duplicate_ids = sorted({scenario_id for scenario_id in ids if ids.count(scenario_id) > 1})
        if duplicate_ids:
            raise ScenarioValidationError(
                "duplicate-scenario-id",
                f"scenario ids must be unique: {duplicate_ids!r}",
                field="scenarios",
            )
        object.__setattr__(self, "scenarios", scenarios)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenarios": [
                scenario.to_dict() for scenario in sorted(self.scenarios, key=lambda item: item.id)
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScenarioSet:
        _require_schema_version(data)
        scenarios = tuple(
            Scenario.from_dict(_require_mapping(item, "scenarios"))
            for item in _require_list(data, "scenarios")
        )
        return cls(scenarios=scenarios, schema_version=_require_int(data, "schema_version"))


def _validate_constraints_against_fixture(
    scenario_id: str,
    *,
    available_commands: tuple[str, ...],
    inventory: tuple[InventoryItem, ...],
    tools: tuple[ToolAvailability, ...],
    constraints: tuple[SemanticConstraint, ...],
) -> None:
    inventory_names = {item.name for item in inventory}
    tool_names = {tool.name for tool in tools}
    available_command_names = set(available_commands)

    for constraint in constraints:
        if (
            constraint.kind == "require_command"
            and constraint.target not in available_command_names
        ):
            raise ScenarioValidationError(
                "constraint-command-unavailable",
                f"scenario {scenario_id!r} requires unavailable command {constraint.target!r}",
                field="expected_constraints.target",
            )
        if (
            constraint.kind in _INVENTORY_CONSTRAINT_KINDS
            and constraint.must_be_true
            and constraint.target not in inventory_names
        ):
            raise ScenarioValidationError(
                "constraint-inventory-unavailable",
                f"scenario {scenario_id!r} references inventory item absent from fixture: "
                f"{constraint.target!r}",
                field="expected_constraints.target",
            )
        if (
            constraint.kind in _TOOL_CONSTRAINT_KINDS
            and constraint.must_be_true
            and constraint.target not in tool_names
        ):
            raise ScenarioValidationError(
                "constraint-tool-unavailable",
                f"scenario {scenario_id!r} references tool absent from fixture: "
                f"{constraint.target!r}",
                field="expected_constraints.target",
            )


def _require_schema_version(data: Mapping[str, Any]) -> None:
    version = _require_int(data, "schema_version")
    if version != SCHEMA_VERSION:
        raise ScenarioValidationError(
            "schema-version",
            f"unsupported scenario schema version: {version!r}",
            field="schema_version",
        )


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be an object",
            field=field,
        )
    return value


def _require_field(data: Mapping[str, Any], field: str) -> Any:
    if field not in data:
        raise ScenarioValidationError(
            "missing-field",
            f"missing required field: {field}",
            field=field,
        )
    return data[field]


def _require_str(data: Mapping[str, Any], field: str) -> str:
    value = _require_field(data, field)
    if not isinstance(value, str):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be a string",
            field=field,
        )
    return value


def _optional_str(data: Mapping[str, Any], field: str) -> str | None:
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, str):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be a string",
            field=field,
        )
    return value


def _require_int(data: Mapping[str, Any], field: str) -> int:
    value = _require_field(data, field)
    if type(value) is not int:
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be an integer",
            field=field,
        )
    return value


def _optional_number(data: Mapping[str, Any], field: str) -> float | int | None:
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be numeric",
            field=field,
        )
    return value


def _optional_bool(data: Mapping[str, Any], field: str, *, default: bool) -> bool:
    if field not in data:
        return default
    value = data[field]
    if type(value) is not bool:
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be a boolean",
            field=field,
        )
    return value


def _require_list(data: Mapping[str, Any], field: str) -> list[Any]:
    value = _require_field(data, field)
    if not isinstance(value, list):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be a list",
            field=field,
        )
    return value


def _tuple_of_strings(values: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, tuple | list):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be a list of strings",
            field=field,
        )
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ScenarioValidationError(
                "invalid-value",
                f"{field} must contain only strings",
                field=field,
            )
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise ScenarioValidationError(
            "duplicate-value",
            f"{field} contains duplicate values",
            field=field,
        )
    return tuple(normalized)


def _tuple_of_command_tokens(values: Any, *, field: str) -> tuple[str, ...]:
    tokens = _tuple_of_strings(values, field=field)
    for token in tokens:
        _validate_command_token(token, field=field)
    return tokens


def _tuple_of_kebab_ids(values: Any, *, field: str) -> tuple[str, ...]:
    ids = _tuple_of_strings(values, field=field)
    for value in ids:
        if not SCENARIO_ID_RE.fullmatch(value):
            raise ScenarioValidationError(
                "invalid-id",
                f"{field} values must be kebab-case ids: {value!r}",
                field=field,
            )
    return ids


def _require_tuple_of_type(values: Any, expected_type: type[Any], field: str) -> tuple[Any, ...]:
    if isinstance(values, str) or not isinstance(values, tuple | list):
        raise ScenarioValidationError(
            "invalid-value",
            f"{field} must be a list",
            field=field,
        )
    normalized = tuple(values)
    for value in normalized:
        if not isinstance(value, expected_type):
            raise ScenarioValidationError(
                "invalid-value",
                f"{field} contains an invalid entry",
                field=field,
            )
    return normalized


def _validate_command_token(token: str, *, field: str) -> None:
    if not isinstance(token, str) or not COMMAND_TOKEN_RE.fullmatch(token):
        raise ScenarioValidationError(
            "invalid-command-token",
            f"command token must match {COMMAND_TOKEN_RE.pattern}: {token!r}",
            field=field,
        )
