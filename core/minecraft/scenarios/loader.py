"""Load and validate Minecraft text-command eval scenario fixtures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.minecraft.commands.schema import CommandSchema, CommandSchemaSet
from core.minecraft.scenarios.schema import (
    SCHEMA_VERSION,
    Scenario,
    ScenarioSet,
    ScenarioValidationError,
)
from core.minecraft.skill_cards.schema import command_schema_map


def load_scenario(
    path: str | Path,
    *,
    commands: CommandSchemaSet | Mapping[str, CommandSchema] | None = None,
) -> Scenario:
    """Load one versioned scenario fixture from a JSON file."""

    payload = _read_json_object(Path(path))
    scenario = _scenario_from_payload(payload)
    if commands is not None:
        _validate_registered_commands(ScenarioSet(scenarios=(scenario,)), commands)
    return scenario


def load_scenario_set(
    path_or_dir: str | Path,
    *,
    commands: CommandSchemaSet | Mapping[str, CommandSchema] | None = None,
) -> ScenarioSet:
    """Load a scenario set from one JSON file or a directory of JSON fixtures."""

    path = Path(path_or_dir)
    if path.is_dir():
        json_files = sorted(path.glob("*.json"), key=lambda item: item.as_posix())
        if not json_files:
            raise ScenarioValidationError(
                "invalid-dataset",
                f"scenario fixture directory contains no .json files: {path}",
            )

        scenarios: list[Scenario] = []
        for fixture_path in json_files:
            payload = _read_json_object(fixture_path)
            scenarios.extend(_scenarios_from_payload(payload))
        scenario_set = ScenarioSet(scenarios=tuple(scenarios))
    else:
        payload = _read_json_object(path)
        scenario_set = ScenarioSet(scenarios=tuple(_scenarios_from_payload(payload)))

    if commands is not None:
        _validate_registered_commands(scenario_set, commands)
    return scenario_set


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ScenarioValidationError(
            "malformed-json",
            f"malformed JSON in {path}: {exc.msg}",
        ) from exc

    if not isinstance(payload, Mapping):
        raise ScenarioValidationError(
            "invalid-dataset",
            f"scenario JSON root must be an object: {path}",
        )
    return payload


def _scenario_from_payload(payload: Mapping[str, Any]) -> Scenario:
    scenarios = _scenarios_from_payload(payload)
    if len(scenarios) != 1:
        raise ScenarioValidationError(
            "invalid-dataset",
            "load_scenario expected exactly one scenario fixture",
        )
    return scenarios[0]


def _scenarios_from_payload(payload: Mapping[str, Any]) -> tuple[Scenario, ...]:
    _require_supported_schema_version(payload)

    if "scenarios" in payload:
        return ScenarioSet.from_dict(payload).scenarios

    if "scenario" in payload:
        scenario_payload = payload["scenario"]
        if not isinstance(scenario_payload, Mapping):
            raise ScenarioValidationError(
                "invalid-dataset",
                "scenario wrapper field must be an object",
                field="scenario",
            )
        return (Scenario.from_dict(scenario_payload),)

    scenario_payload = dict(payload)
    scenario_payload.pop("schema_version", None)
    return (Scenario.from_dict(scenario_payload),)


def _require_supported_schema_version(payload: Mapping[str, Any]) -> None:
    version = payload.get("schema_version")
    if type(version) is not int:
        raise ScenarioValidationError(
            "schema-version",
            "scenario fixture must include an integer schema_version",
            field="schema_version",
        )
    if version != SCHEMA_VERSION:
        raise ScenarioValidationError(
            "schema-version",
            f"unsupported scenario schema version: {version!r}",
            field="schema_version",
        )


def _validate_registered_commands(
    scenario_set: ScenarioSet,
    commands: CommandSchemaSet | Mapping[str, CommandSchema],
) -> None:
    command_map = command_schema_map(commands)
    registered = set(command_map)
    unavailable: set[str] = set()
    if isinstance(commands, CommandSchemaSet):
        registered.update(commands.disallowed)
        unavailable.update(commands.disallowed)
    unavailable.update(
        command_name
        for command_name, schema in command_map.items()
        if schema.disallowed or schema.internal
    )

    for scenario in scenario_set.scenarios:
        for token in (*scenario.available_commands, *scenario.disallowed_commands):
            _require_registered_command(token, registered, scenario.id)
        for token in scenario.available_commands:
            if token in unavailable:
                raise ScenarioValidationError(
                    "command-not-available",
                    f"scenario {scenario.id!r} exposes unavailable command: {token!r}",
                    field="available_commands",
                )
        for constraint in scenario.expected_constraints:
            if constraint.kind in ("require_command", "forbid_command"):
                _require_registered_command(constraint.target, registered, scenario.id)


def _require_registered_command(token: str, registered: set[str], scenario_id: str) -> None:
    if token not in registered:
        raise ScenarioValidationError(
            "command-not-registered",
            f"scenario {scenario_id!r} references command outside supplied schema set: {token!r}",
        )
