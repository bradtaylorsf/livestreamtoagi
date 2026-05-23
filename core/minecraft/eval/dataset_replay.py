"""Dataset loading helpers for Minecraft live replay evals."""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DatasetLoadError(ValueError):
    """Raised when an E17 passing-prompt dataset cannot be loaded."""


class _MissingDatasetError(DatasetLoadError, FileNotFoundError):
    """Raised when a dataset path does not exist."""


@dataclass(frozen=True, slots=True)
class PassingPrompt:
    """One accepted command prompt emitted by the E17 text-only eval harness."""

    scenario_id: str
    command_token: str
    args: tuple[str, ...]
    available_commands: tuple[str, ...]
    expected_constraints: tuple[Mapping[str, Any], ...]
    prompt_context: str
    raw_content: str
    seed: int | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "available_commands", tuple(self.available_commands))
        object.__setattr__(
            self,
            "expected_constraints",
            tuple(dict(constraint) for constraint in self.expected_constraints),
        )


_REQUIRED_KEYS = frozenset(
    (
        "args",
        "available_commands",
        "command_token",
        "expected_constraints",
        "prompt_context",
        "raw_content",
        "scenario_id",
        "seed",
    )
)


def load_passing_prompts(path: str | Path) -> tuple[PassingPrompt, ...]:
    """Load E17 accepted command prompts from a passing-prompts NDJSON artifact."""

    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise _MissingDatasetError(f"dataset not found: {dataset_path}")

    prompts: list[PassingPrompt] = []
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetLoadError(
                f"invalid JSON in dataset {dataset_path} on line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(record, Mapping):
            raise DatasetLoadError(
                f"dataset {dataset_path} line {line_number} must be a JSON object"
            )
        prompts.append(_passing_prompt_from_record(record, dataset_path, line_number))
    return tuple(prompts)


def filter_prompts(
    prompts: Iterable[PassingPrompt],
    *,
    commands: Iterable[str] | None = None,
    scenario_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> tuple[PassingPrompt, ...]:
    """Filter passing prompts by command token, scenario id, and optional prefix limit."""

    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    allowed_commands = (
        None if commands is None else frozenset(_command_key(command) for command in commands)
    )
    allowed_scenario_ids = (
        None if scenario_ids is None else frozenset(str(scenario) for scenario in scenario_ids)
    )

    selected: list[PassingPrompt] = []
    for prompt in prompts:
        if (
            allowed_commands is not None
            and _command_key(prompt.command_token) not in allowed_commands
        ):
            continue
        if allowed_scenario_ids is not None and prompt.scenario_id not in allowed_scenario_ids:
            continue
        selected.append(prompt)
        if limit is not None and len(selected) >= limit:
            break
    return tuple(selected)


def build_command_text(prompt: PassingPrompt) -> str:
    """Rebuild the command line sent to the live bridge."""

    command_token = prompt.command_token.strip()
    if not command_token.startswith("!"):
        command_token = f"!{command_token}"
    return " ".join((command_token, *(shlex.quote(arg) for arg in prompt.args)))


def prompt_to_case_id(prompt: PassingPrompt, index: int) -> str:
    """Return the stable replay case id for a prompt and 1-based replay index."""

    return f"replay-{prompt.scenario_id}-{index:04d}"


def _passing_prompt_from_record(
    record: Mapping[str, Any],
    path: Path,
    line_number: int,
) -> PassingPrompt:
    missing = sorted(_REQUIRED_KEYS.difference(record))
    if missing:
        missing_text = ", ".join(missing)
        raise DatasetLoadError(
            f"dataset {path} line {line_number} missing required keys: {missing_text}"
        )

    scenario_id = _string_field(record, "scenario_id", path, line_number)
    command_token = _string_field(record, "command_token", path, line_number)
    args = _string_list_field(record, "args", path, line_number)
    available_commands = _string_list_field(record, "available_commands", path, line_number)
    expected_constraints = _constraint_list_field(record, path, line_number)
    prompt_context = _string_field(record, "prompt_context", path, line_number)
    raw_content = _string_field(record, "raw_content", path, line_number)
    seed = record["seed"]
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise DatasetLoadError(
            f"dataset {path} line {line_number} field seed must be an integer or null"
        )

    return PassingPrompt(
        scenario_id=scenario_id,
        command_token=command_token,
        args=tuple(args),
        available_commands=tuple(available_commands),
        expected_constraints=tuple(expected_constraints),
        prompt_context=prompt_context,
        raw_content=raw_content,
        seed=seed,
    )


def _string_field(
    record: Mapping[str, Any],
    key: str,
    path: Path,
    line_number: int,
) -> str:
    value = record[key]
    if not isinstance(value, str):
        raise DatasetLoadError(f"dataset {path} line {line_number} field {key} must be a string")
    return value


def _string_list_field(
    record: Mapping[str, Any],
    key: str,
    path: Path,
    line_number: int,
) -> tuple[str, ...]:
    value = record[key]
    if not isinstance(value, list):
        raise DatasetLoadError(f"dataset {path} line {line_number} field {key} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise DatasetLoadError(
            f"dataset {path} line {line_number} field {key} must contain only strings"
        )
    return tuple(value)


def _constraint_list_field(
    record: Mapping[str, Any],
    path: Path,
    line_number: int,
) -> tuple[dict[str, Any], ...]:
    value = record["expected_constraints"]
    if not isinstance(value, list):
        raise DatasetLoadError(
            f"dataset {path} line {line_number} field expected_constraints must be a list"
        )
    constraints: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise DatasetLoadError(
                f"dataset {path} line {line_number} field expected_constraints "
                "must contain only objects"
            )
        constraints.append(dict(item))
    return tuple(constraints)


def _command_key(command: str) -> str:
    normalized = command.strip()
    if normalized.startswith("!"):
        normalized = normalized[1:]
    return normalized.casefold()
