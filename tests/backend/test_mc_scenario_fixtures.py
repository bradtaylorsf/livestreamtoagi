"""Tests for E17 Minecraft text-command scenario fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.minecraft.commands import (
    DEFAULT_DISALLOWED_COMMANDS,
    CommandParam,
    CommandSchema,
    CommandSchemaSet,
)
from core.minecraft.scenarios import (
    SCHEMA_VERSION,
    ScenarioSet,
    ScenarioValidationError,
    generate_scenarios,
    load_scenario,
    load_scenario_set,
)
from core.minecraft.skill_cards import get_default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "mc_scenarios"
VALID_FIXTURES = FIXTURES / "valid"
INVALID_FIXTURES = FIXTURES / "invalid"


def _schema(
    name: str,
    *,
    params: tuple[CommandParam, ...] = (),
    aliases: tuple[str, ...] = (),
    disallowed: bool = False,
    internal: bool = False,
) -> CommandSchema:
    return CommandSchema(
        name=name,
        aliases=aliases,
        description=f"{name} fixture command.",
        params=params,
        source="fixture",
        disallowed=disallowed,
        internal=internal,
    )


def _command_surface() -> CommandSchemaSet:
    return CommandSchemaSet(
        commands=(
            _schema(
                "!move",
                aliases=("!walk",),
                params=(
                    CommandParam(name="action_id", type="string"),
                    CommandParam(name="direction", type="string"),
                    CommandParam(name="distance_blocks", type="float"),
                ),
            ),
            _schema("!observe"),
            _schema("!inventory"),
            _schema(
                "!planAndBuild",
                params=(CommandParam(name="description", type="string"),),
            ),
            _schema("!place"),
            _schema("!craftRecipe"),
            _schema("!collectBlocks"),
            _schema("!equip"),
            _schema("!startConversation"),
        ),
        disallowed=DEFAULT_DISALLOWED_COMMANDS,
    )


def test_valid_fixtures_load_and_round_trip() -> None:
    scenario_set = load_scenario_set(VALID_FIXTURES, commands=_command_surface())

    assert [scenario["id"] for scenario in scenario_set.to_dict()["scenarios"]] == [
        "baseline-observe-area",
        "build-owner-starter-cabin",
        "chat-only-blocked-command",
        "movement-with-inventory",
    ]
    assert any(
        constraint.kind == "require_chat_only"
        for scenario in scenario_set.scenarios
        for constraint in scenario.expected_constraints
    )

    round_tripped = ScenarioSet.from_dict(scenario_set.to_dict())
    assert round_tripped.to_dict() == scenario_set.to_dict()

    movement = load_scenario(VALID_FIXTURES / "movement-inventory.json")
    assert movement.inventory[0].name == "bread"
    assert movement.available_commands == ("!move", "!inventory")


@pytest.mark.parametrize(
    ("fixture_name", "error_kind"),
    (
        ("missing-required-field.json", "missing-field"),
        ("malformed-command-token.json", "invalid-command-token"),
        ("malformed-json.json", "malformed-json"),
    ),
)
def test_invalid_fixtures_raise_meaningful_validation_errors(
    fixture_name: str,
    error_kind: str,
) -> None:
    with pytest.raises(ScenarioValidationError) as exc_info:
        load_scenario(INVALID_FIXTURES / fixture_name)

    assert exc_info.value.kind == error_kind


def test_loader_rejects_schema_version_mismatch(tmp_path: Path) -> None:
    payload = _valid_scenario_payload()
    payload["schema_version"] = SCHEMA_VERSION + 1
    path = tmp_path / "wrong-version.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScenarioValidationError) as exc_info:
        load_scenario(path)

    assert exc_info.value.kind == "schema-version"


def test_loader_rejects_unknown_constraint_kind(tmp_path: Path) -> None:
    payload = _valid_scenario_payload()
    payload["expected_constraints"] = [
        {
            "kind": "invent_command",
            "target": "!observe",
        }
    ]
    path = tmp_path / "unknown-constraint.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScenarioValidationError) as exc_info:
        load_scenario(path)

    assert exc_info.value.kind == "unknown-constraint-kind"


def test_generator_is_reproducible_for_same_seed() -> None:
    commands = _command_surface()
    skill_cards = get_default_registry()

    first = generate_scenarios(
        seed=779,
        count=8,
        commands=commands,
        skill_cards=skill_cards,
    ).to_dict()
    second = generate_scenarios(
        seed=779,
        count=8,
        commands=commands,
        skill_cards=skill_cards,
    ).to_dict()

    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_generator_changes_ids_for_different_seeds() -> None:
    commands = _command_surface()
    skill_cards = get_default_registry()

    first = generate_scenarios(
        seed=779,
        count=5,
        commands=commands,
        skill_cards=skill_cards,
    )
    second = generate_scenarios(
        seed=780,
        count=5,
        commands=commands,
        skill_cards=skill_cards,
    )

    assert [scenario.id for scenario in first.scenarios] != [
        scenario.id for scenario in second.scenarios
    ]


def test_generator_respects_registered_skill_card_command_surface() -> None:
    commands = _command_surface()
    skill_cards = get_default_registry()
    scenario_set = generate_scenarios(
        seed=779,
        count=20,
        commands=commands,
        skill_cards=skill_cards,
    )
    registered = {command.name for command in commands.commands}
    registered.update(alias for command in commands.commands for alias in command.aliases)
    allowed_by_skill_cards = {
        command_name for card in skill_cards.cards for command_name in card.allowed_commands
    }

    for scenario in scenario_set.scenarios:
        assert set(scenario.available_commands).issubset(registered)
        assert set(scenario.available_commands).issubset(allowed_by_skill_cards)
        assert set(scenario.available_commands).isdisjoint(DEFAULT_DISALLOWED_COMMANDS)


def test_loader_rejects_commands_outside_supplied_schema_set() -> None:
    limited_commands = CommandSchemaSet(
        commands=(_schema("!observe"),),
        disallowed=DEFAULT_DISALLOWED_COMMANDS,
    )

    with pytest.raises(ScenarioValidationError) as exc_info:
        load_scenario(
            VALID_FIXTURES / "movement-inventory.json",
            commands=limited_commands,
        )

    assert exc_info.value.kind == "command-not-registered"


def _valid_scenario_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "tmp-observe-fixture",
        "seed": 301,
        "prompt_context": "Inspect the area before acting.",
        "inventory": [],
        "tools": [],
        "available_commands": ["!observe"],
        "disallowed_commands": [],
        "skill_card_ids": ["observe"],
        "expected_constraints": [
            {
                "kind": "require_command",
                "target": "!observe",
            }
        ],
        "tags": ["fixture"],
        "source": "tmp",
    }
