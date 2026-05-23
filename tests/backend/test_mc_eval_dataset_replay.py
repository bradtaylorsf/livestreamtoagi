"""Tests for E17 passing-prompt dataset replay helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.minecraft.eval.dataset_replay import (
    DatasetLoadError,
    PassingPrompt,
    build_command_text,
    filter_prompts,
    load_passing_prompts,
    prompt_to_case_id,
)


def test_load_passing_prompts_skips_blank_lines_and_parses_records(tmp_path: Path) -> None:
    path = tmp_path / "passing-prompts.ndjson"
    path.write_text(
        "\n"
        + json.dumps(_record("move-north", "!move", ["north", "2"]))
        + "\n  \n"
        + json.dumps(_record("inventory-check", "!inventory", []))
        + "\n",
        encoding="utf-8",
    )

    prompts = load_passing_prompts(path)

    assert [prompt.scenario_id for prompt in prompts] == [
        "move-north",
        "inventory-check",
    ]
    assert prompts[0].command_token == "!move"
    assert prompts[0].args == ("north", "2")
    assert prompts[0].expected_constraints == ({"kind": "requires_command", "command": "!move"},)


def test_load_passing_prompts_rejects_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.ndjson"

    with pytest.raises(DatasetLoadError) as exc_info:
        load_passing_prompts(missing_path)

    assert isinstance(exc_info.value, FileNotFoundError)
    assert isinstance(exc_info.value, ValueError)
    assert "dataset not found" in str(exc_info.value)


def test_load_passing_prompts_rejects_invalid_json_line(tmp_path: Path) -> None:
    path = tmp_path / "passing-prompts.ndjson"
    path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="invalid JSON"):
        load_passing_prompts(path)


def test_load_passing_prompts_rejects_non_object_record(tmp_path: Path) -> None:
    path = tmp_path / "passing-prompts.ndjson"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="must be a JSON object"):
        load_passing_prompts(path)


@pytest.mark.parametrize("missing_key", ["command_token", "args"])
def test_load_passing_prompts_rejects_missing_required_keys(
    tmp_path: Path,
    missing_key: str,
) -> None:
    path = tmp_path / "passing-prompts.ndjson"
    record = _record("move-north", "!move", ["north", "2"])
    del record[missing_key]
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match=f"missing required keys: {missing_key}"):
        load_passing_prompts(path)


def test_load_passing_prompts_rejects_non_string_command_token(tmp_path: Path) -> None:
    path = tmp_path / "passing-prompts.ndjson"
    record = _record("move-north", "!move", ["north", "2"])
    record["command_token"] = 42
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="field command_token must be a string"):
        load_passing_prompts(path)


def test_load_passing_prompts_rejects_non_list_args(tmp_path: Path) -> None:
    path = tmp_path / "passing-prompts.ndjson"
    record = _record("move-north", "!move", ["north", "2"])
    record["args"] = "north"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="field args must be a list"):
        load_passing_prompts(path)


def test_filter_prompts_by_command_scenario_and_limit() -> None:
    prompts = (
        _prompt("one", "!move", ("north", "1")),
        _prompt("two", "MOVE", ("south", "2")),
        _prompt("three", "!inventory", ()),
        _prompt("four", "!placeHere", ("stone",)),
    )

    assert [prompt.scenario_id for prompt in filter_prompts(prompts, commands=["move"])] == [
        "one",
        "two",
    ]
    assert [
        prompt.scenario_id for prompt in filter_prompts(prompts, commands=["!move", "inventory"])
    ] == ["one", "two", "three"]
    assert [prompt.scenario_id for prompt in filter_prompts(prompts, scenario_ids=["three"])] == [
        "three"
    ]
    assert [
        prompt.scenario_id for prompt in filter_prompts(prompts, commands=["move"], limit=1)
    ] == ["one"]


def test_filter_prompts_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="limit must be non-negative"):
        filter_prompts((_prompt("one", "!move", ("north",)),), limit=-1)


def test_build_command_text_ensures_bang_and_joins_args() -> None:
    assert build_command_text(_prompt("move", "move", ("north", "2"))) == "!move north 2"
    assert build_command_text(_prompt("inventory", "!inventory", ())) == "!inventory"
    assert (
        build_command_text(_prompt("build", "!planAndBuild", ("small oak shelter",)))
        == "!planAndBuild 'small oak shelter'"
    )


def test_prompt_to_case_id_is_stable() -> None:
    prompt = _prompt("move-north", "!move", ("north", "2"))

    assert prompt_to_case_id(prompt, 7) == "replay-move-north-0007"


def _record(
    scenario_id: str,
    command_token: str,
    args: list[str],
) -> dict[str, object]:
    return {
        "args": args,
        "available_commands": ["!move", "!inventory"],
        "command_token": command_token,
        "expected_constraints": [
            {"kind": "requires_command", "command": f"!{command_token.lstrip('!')}"}
        ],
        "prompt_context": f"Prompt for {scenario_id}.",
        "raw_content": " ".join((command_token, *args)),
        "scenario_id": scenario_id,
        "seed": 11,
    }


def _prompt(
    scenario_id: str,
    command_token: str,
    args: tuple[str, ...],
) -> PassingPrompt:
    return PassingPrompt(
        scenario_id=scenario_id,
        command_token=command_token,
        args=args,
        available_commands=("!move", "!inventory", "!placeHere"),
        expected_constraints=(
            {"kind": "requires_command", "command": f"!{command_token.lstrip('!')}"},
        ),
        prompt_context=f"Prompt for {scenario_id}.",
        raw_content=" ".join((command_token, *args)),
        seed=13,
    )
