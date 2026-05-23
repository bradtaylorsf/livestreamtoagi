"""Tests for the E17 Minecraft command schema extractor."""

from __future__ import annotations

import json
from pathlib import Path

from core.minecraft.commands import (
    DEFAULT_DISALLOWED_COMMANDS,
    CommandSchema,
    CommandSchemaSet,
    extract_commands,
    extract_from_default_locations,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "mc_commands"


def _by_name(path: Path, *, source_label: str = "fixture") -> dict[str, CommandSchema]:
    return {
        command.name: command for command in extract_commands([path], source_label=source_label)
    }


def test_extracts_upstream_commands_and_aliases() -> None:
    commands = _by_name(FIXTURES / "upstream", source_label="upstream")

    go_to_place = commands["!goToPlace"]
    assert go_to_place.aliases == ("!goto", "!walkToPlace")
    assert go_to_place.description == "Go to a named place."
    assert go_to_place.required_param_names == ("place_name", "arrive_within_blocks")
    assert go_to_place.optional_param_names == ("safe_mode",)
    assert [param.type for param in go_to_place.params] == ["string", "float", "boolean"]
    assert go_to_place.source == "upstream"

    inventory = commands["!inventory"]
    assert inventory.params == ()
    assert inventory.required_param_names == ()
    assert inventory.optional_param_names == ()


def test_extracts_fork_required_and_optional_parameter_shapes() -> None:
    commands = _by_name(FIXTURES / "fork", source_label="fork")

    move = commands["!move"]
    assert move.aliases == ("!walk", "!step")
    assert move.description == "Move a verified number of blocks and report the outcome."
    assert move.required_param_names == ("action_id", "direction", "distance_blocks")
    assert move.optional_param_names == ("timeout_ms",)
    assert {param.name: param.type for param in move.params} == {
        "action_id": "string",
        "direction": "string",
        "distance_blocks": "float",
        "timeout_ms": "int",
    }

    observe = commands["!observe"]
    assert observe.required_param_names == ()
    assert observe.optional_param_names == ("radius_blocks", "scope", "include_air")
    assert {param.name: param.type for param in observe.params} == {
        "radius_blocks": "float",
        "scope": "string",
        "include_air": "boolean",
    }


def test_flags_disallowed_and_internal_commands() -> None:
    [stop] = extract_commands(
        [FIXTURES / "internal"],
        disallowed=["!stop"],
        internal_prefixes=["stop"],
        source_label="internal",
    )

    assert stop.name == "!stop"
    assert stop.disallowed is True
    assert stop.internal is True


def test_schema_set_to_dict_is_byte_stable() -> None:
    first = CommandSchemaSet(
        commands=tuple(
            extract_commands(
                [FIXTURES / "fork", FIXTURES / "upstream", FIXTURES / "internal"],
                disallowed=["!stop"],
                internal_prefixes=["stop"],
                source_label="fixture",
            )
        ),
        disallowed=("!stop",),
    ).to_dict()
    second = CommandSchemaSet(
        commands=tuple(
            extract_commands(
                [FIXTURES / "fork", FIXTURES / "upstream", FIXTURES / "internal"],
                disallowed=["!stop"],
                internal_prefixes=["stop"],
                source_label="fixture",
            )
        ),
        disallowed=("!stop",),
    ).to_dict()

    assert json.dumps(first, separators=(",", ":")) == json.dumps(
        second,
        separators=(",", ":"),
    )
    assert [command["name"] for command in first["commands"]] == [
        "!goToPlace",
        "!inventory",
        "!move",
        "!observe",
        "!stop",
    ]
    assert first["commands"][2]["required"] == [
        "action_id",
        "direction",
        "distance_blocks",
    ]
    assert first["commands"][2]["optional"] == ["timeout_ms"]


def test_edge_cases_skip_non_commands_and_tolerate_missing_fields() -> None:
    commands = _by_name(FIXTURES / "edge", source_label="edge")

    missing_description = commands["!missingDescription"]
    assert missing_description.description == ""
    assert missing_description.required_param_names == ("reason",)
    assert missing_description.params[0].description == ""

    no_params = commands["!noParams"]
    assert no_params.params == ()
    assert no_params.required_param_names == ()
    assert no_params.optional_param_names == ()
    assert "!helper" not in commands


def test_default_locations_include_fork_and_optional_mindcraft_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fork_dir = tmp_path / "scripts" / "minecraft" / "fork-src" / "agent" / "commands"
    fork_dir.mkdir(parents=True)
    (fork_dir / "fork_command.js").write_text(
        "export default { name: '!forkOnly', params: { id: { type: 'string' } } };",
        encoding="utf-8",
    )

    mindcraft_dir = tmp_path / "custom-mindcraft"
    upstream_dir = mindcraft_dir / "src" / "agent" / "commands"
    upstream_dir.mkdir(parents=True)
    (upstream_dir / "upstream_command.js").write_text(
        "export default { name: '!upstreamOnly', params: {} };",
        encoding="utf-8",
    )
    monkeypatch.setenv("MINDCRAFT_DIR", str(mindcraft_dir))

    schema_set = extract_from_default_locations(tmp_path)
    commands = {command["name"]: command for command in schema_set.to_dict()["commands"]}

    assert set(commands) == {"!forkOnly", "!upstreamOnly"}
    assert commands["!forkOnly"]["source"] == "fork"
    assert commands["!upstreamOnly"]["source"] == "mindcraft"
    assert schema_set.disallowed == DEFAULT_DISALLOWED_COMMANDS
