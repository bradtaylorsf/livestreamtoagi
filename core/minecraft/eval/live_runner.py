"""Focused live Minecraft command smoke runner with deterministic dry-run support."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from core.minecraft.eval.live_profile import DEFAULT_PROFILE_NAME, EvalProfile, resolve_profile
from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
)


@dataclass(frozen=True, slots=True)
class CommandCase:
    """One generated command invocation for the live smoke runner."""

    case_id: str
    command_name: str
    command_text: str
    params: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", dict(self.params))

    @property
    def action_id(self) -> str:
        return str(self.params.get("action_id") or self.case_id)


class BridgeClient(Protocol):
    """Minimal command dispatch surface used by live command smoke runs."""

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        """Run one Minecraft command and return status/action telemetry."""


_SUPPORTED_COMMANDS = (
    "move",
    "placeHere",
    "searchForBlock",
    "inventory",
    "nearbyBlocks",
    "planAndBuild",
    "buildFromPlan",
)
_COMMAND_KEY_MAP = {command.casefold(): command for command in _SUPPORTED_COMMANDS}
_COMMAND_KEY_MAP.update({f"!{command}".casefold(): command for command in _SUPPORTED_COMMANDS})
_FAMILY_COMMANDS = {
    "build": "planAndBuild",
    "observe": "nearbyBlocks",
}
_FAMILY_COMMANDS.update({command: command for command in _SUPPORTED_COMMANDS})

_DEFAULT_FAKE_CYCLE: tuple[Mapping[str, Any], ...] = (
    {"status": "ok", "reason": "completed"},
    {"status": "ok", "reason": "completed"},
    {"status": "failed", "reason": "blocked by world constraint"},
    {"status": "rejected", "reason": "permission gate rejected command"},
    {"status": "timeout", "reason": "action timed out"},
    {"status": "malformed", "reason": "parser rejected command before dispatch"},
)


class CaseGenerator:
    """Generate deterministic command variants for one command family."""

    def __init__(self, command: str, count: int, *, seed: int = 0) -> None:
        if count < 0:
            raise ValueError("--cases must be non-negative")
        self.command_input = command
        self.command_name = resolve_command_name(command)
        self.count = count
        self.seed = seed

    def generate(self) -> tuple[CommandCase, ...]:
        rng = random.Random(self.seed)
        cases: list[CommandCase] = []
        for index in range(self.count):
            case_id = f"live-{self.command_name}-{index + 1:04d}"
            action_id = f"{self.command_name}-{self.seed}-{index + 1:04d}"
            cases.append(_generate_case(self.command_name, case_id, action_id, index, rng))
        return tuple(cases)


class FakeBridgeClient:
    """Deterministic bridge client for CI and local dry-run smoke checks."""

    def __init__(
        self,
        responses_by_command: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.responses_by_command = {
            resolve_command_name(command): tuple(responses)
            for command, responses in (responses_by_command or {}).items()
        }
        self.calls: list[str] = []
        self._counts: dict[str, int] = {}

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        self.calls.append(command_text)
        command_name = _command_name_from_text(command_text)
        count = self._counts.get(command_name, 0)
        self._counts[command_name] = count + 1
        response = self._response_for(command_name, count)
        return {
            "status": response.get("status", "ok"),
            "reason": response.get("reason"),
            "error": response.get("error"),
            "action_events": response.get("action_events", ()),
            "final_state": response.get("final_state")
            or _fake_final_state(command_name, command_text, response),
        }

    def _response_for(self, command_name: str, count: int) -> Mapping[str, Any]:
        responses = self.responses_by_command.get(command_name)
        if responses:
            return responses[count % len(responses)]
        return _DEFAULT_FAKE_CYCLE[count % len(_DEFAULT_FAKE_CYCLE)]


async def run_live_command_smoke(
    command: str,
    cases: int,
    *,
    bridge: BridgeClient,
    verbose: bool = False,
    profile: str = DEFAULT_PROFILE_NAME,
    seed: int = 0,
    env: Mapping[str, str] | None = None,
    project_root: Any | None = None,
    dry_run: bool = False,
) -> LiveRunSummary:
    """Run deterministic command variants through a live or fake bridge client."""

    resolved_profile = resolve_profile(profile, env=env, project_root=project_root)
    generator = CaseGenerator(command, cases, seed=seed)
    generated_cases = generator.generate()
    results: list[CaseResult] = []

    for case in generated_cases:
        results.append(await _run_case(case, bridge=bridge))

    return LiveRunSummary(
        command=command,
        resolved_command=generator.command_name,
        profile=resolved_profile.name,
        profile_detail=_profile_detail(resolved_profile),
        seed=seed,
        dry_run=dry_run,
        verbose=verbose,
        case_results=tuple(results),
    )


def resolve_command_name(command: str) -> str:
    """Resolve a family id, bare command, or !command token to a supported command."""

    normalized = command.strip()
    if not normalized:
        raise ValueError(_unknown_command_message(command))

    family_match = _FAMILY_COMMANDS.get(normalized) or _FAMILY_COMMANDS.get(
        normalized.casefold()
    )
    if family_match is not None:
        return family_match

    command_match = _COMMAND_KEY_MAP.get(normalized.casefold())
    if command_match is not None:
        return command_match

    raise ValueError(_unknown_command_message(command))


def supported_command_inputs() -> tuple[str, ...]:
    """Return the supported command/family inputs accepted by the live CLI."""

    return tuple(sorted({*_SUPPORTED_COMMANDS, *_FAMILY_COMMANDS}))


async def _run_case(case: CommandCase, *, bridge: BridgeClient) -> CaseResult:
    started_ms = _now_ms()
    events: list[ActionEvent] = [
        ActionEvent(
            action_id=case.action_id,
            kind="start",
            ts_ms=started_ms,
            payload={
                "case_id": case.case_id,
                "command": case.command_name,
                "command_text": case.command_text,
                "params": dict(case.params),
            },
        )
    ]
    response: Mapping[str, Any]
    error: str | None = None
    try:
        response = await bridge.send_command(case.command_text)
    except TimeoutError as exc:
        response = {"status": "timeout", "error": str(exc), "final_state": {}}
        error = str(exc)
    except Exception as exc:
        response = {"status": "error", "error": str(exc), "final_state": {}}
        error = str(exc)

    events.extend(_coerce_action_events(response.get("action_events"), case.action_id))
    ended_ms = _now_ms()
    outcome_class = classify_bridge_status(
        response.get("status"),
        reason=response.get("reason") or response.get("outcome_class"),
        error=response.get("error"),
    )
    error = error or _case_error(outcome_class, response)
    events.append(
        ActionEvent(
            action_id=case.action_id,
            kind="end",
            ts_ms=ended_ms,
            payload={
                "case_id": case.case_id,
                "command": case.command_name,
                "status": response.get("status"),
                "reason": response.get("reason"),
                "outcome_class": outcome_class,
                "latency_ms": max(0, ended_ms - started_ms),
            },
        )
    )

    final_state = response.get("final_state")
    if not isinstance(final_state, Mapping):
        final_state = {}

    return CaseResult(
        case_id=case.case_id,
        command_text=case.command_text,
        params=case.params,
        action_events=tuple(events),
        outcome_class=outcome_class,
        final_state=final_state,
        latency_ms=max(0, ended_ms - started_ms),
        error=error,
    )


def _generate_case(
    command_name: str,
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    if command_name == "move":
        return _move_case(case_id, action_id, index, rng)
    if command_name == "placeHere":
        return _place_here_case(case_id, action_id, index, rng)
    if command_name == "searchForBlock":
        return _search_for_block_case(case_id, action_id, index, rng)
    if command_name == "inventory":
        return _inventory_case(case_id, action_id)
    if command_name == "nearbyBlocks":
        return _nearby_blocks_case(case_id, action_id, index, rng)
    if command_name == "planAndBuild":
        return _plan_and_build_case(case_id, action_id, index, rng)
    if command_name == "buildFromPlan":
        return _build_from_plan_case(case_id, action_id, index, rng)
    raise ValueError(_unknown_command_message(command_name))


def _move_case(
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    directions = ("north", "south", "east", "west", "forward", "back")
    distances = (1, 2, 3, 4)
    direction = directions[(index + rng.randrange(len(directions))) % len(directions)]
    distance = distances[(index + rng.randrange(len(distances))) % len(distances)]
    timeout_ms = 10_000
    params = {
        "action_id": action_id,
        "direction": direction,
        "distance_blocks": distance,
        "timeout_ms": timeout_ms,
    }
    command_text = f"!move {action_id} {direction} {distance} {timeout_ms}"
    return CommandCase(case_id, "move", command_text, params)


def _place_here_case(
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    blocks = ("oak_log", "cobblestone", "oak_planks", "torch", "glass")
    block_type = blocks[(index + rng.randrange(len(blocks))) % len(blocks)]
    params = {"action_id": action_id, "block_type": block_type}
    return CommandCase(case_id, "placeHere", f"!placeHere {block_type}", params)


def _search_for_block_case(
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    blocks = ("oak_log", "stone", "grass_block", "water", "torch")
    radii = (6, 8, 10, 12, 16)
    block_type = blocks[(index + rng.randrange(len(blocks))) % len(blocks)]
    radius = radii[(index + rng.randrange(len(radii))) % len(radii)]
    params = {"action_id": action_id, "block_type": block_type, "radius": radius}
    return CommandCase(
        case_id,
        "searchForBlock",
        f"!searchForBlock {block_type} {radius}",
        params,
    )


def _inventory_case(case_id: str, action_id: str) -> CommandCase:
    return CommandCase(case_id, "inventory", "!inventory", {"action_id": action_id})


def _nearby_blocks_case(
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    radii = (4, 6, 8, 10)
    radius = radii[(index + rng.randrange(len(radii))) % len(radii)]
    include_air = (index + rng.randrange(2)) % 2 == 0
    params = {"action_id": action_id, "radius": radius, "include_air": include_air}
    include_air_text = "true" if include_air else "false"
    return CommandCase(
        case_id,
        "nearbyBlocks",
        f"!nearbyBlocks {radius} {include_air_text}",
        params,
    )


def _plan_and_build_case(
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    descriptions = (
        "small oak shelter",
        "three block cobblestone marker",
        "torch lit storage corner",
        "low glass window frame",
    )
    description = descriptions[(index + rng.randrange(len(descriptions))) % len(descriptions)]
    params = {"action_id": action_id, "description": description}
    return CommandCase(
        case_id,
        "planAndBuild",
        f"!planAndBuild {json.dumps(description)}",
        params,
    )


def _build_from_plan_case(
    case_id: str,
    action_id: str,
    index: int,
    rng: random.Random,
) -> CommandCase:
    blocks = ("oak_planks", "cobblestone", "glass")
    block_type = blocks[(index + rng.randrange(len(blocks))) % len(blocks)]
    origin = {"x": 0, "y": 64, "z": 0}
    plan = {
        "blocks": [
            {"dx": 0, "dy": 0, "dz": 0, "block_type": block_type},
            {"dx": 1, "dy": 0, "dz": 0, "block_type": block_type},
        ]
    }
    max_steps = 8
    timeout_ms = 30_000
    params = {
        "action_id": action_id,
        "origin": origin,
        "plan": plan,
        "max_steps": max_steps,
        "timeout_ms": timeout_ms,
    }
    origin_json = json.dumps(origin, separators=(",", ":"))
    plan_json = json.dumps(plan, separators=(",", ":"))
    command_text = (
        f"!buildFromPlan {action_id} {origin_json} {plan_json} {max_steps} {timeout_ms}"
    )
    return CommandCase(case_id, "buildFromPlan", command_text, params)


def _command_name_from_text(command_text: str) -> str:
    token = command_text.strip().split(maxsplit=1)[0] if command_text.strip() else ""
    return resolve_command_name(token)


def _fake_final_state(
    command_name: str,
    command_text: str,
    response: Mapping[str, Any],
) -> dict[str, Any]:
    outcome_class = classify_bridge_status(
        response.get("status"),
        reason=response.get("reason"),
        error=response.get("error"),
    )
    state: dict[str, Any] = {
        "command": command_name,
        "command_text": command_text,
        "bridge_status": response.get("status", "ok"),
        "outcome_class": outcome_class,
    }
    if command_name == "move":
        state["pose"] = {"x": 1, "y": 64, "z": 0, "yaw": 90}
    elif command_name in {"placeHere", "buildFromPlan", "planAndBuild"}:
        state["blocks"] = [{"x": 0, "y": 64, "z": 1, "block_type": "oak_planks"}]
        state["inventory"] = {"oak_planks": 7, "cobblestone": 8}
    elif command_name == "inventory":
        state["inventory"] = {"oak_planks": 8, "cobblestone": 8, "torch": 4}
    else:
        state["nearby_blocks"] = [
            {"x": 0, "y": 63, "z": 0, "block_type": "grass_block"},
            {"x": 1, "y": 64, "z": 1, "block_type": "oak_log"},
        ]
    return state


def _coerce_action_events(raw_events: object, fallback_action_id: str) -> tuple[ActionEvent, ...]:
    if raw_events is None:
        return ()
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
        return ()

    events: list[ActionEvent] = []
    for raw_event in raw_events:
        if isinstance(raw_event, ActionEvent):
            events.append(raw_event)
            continue
        if not isinstance(raw_event, Mapping):
            continue
        try:
            events.append(
                ActionEvent(
                    action_id=str(raw_event.get("action_id") or fallback_action_id),
                    kind=str(raw_event.get("kind")),
                    ts_ms=int(raw_event.get("ts_ms") or _now_ms()),
                    payload=raw_event.get("payload")
                    if isinstance(raw_event.get("payload"), Mapping)
                    else {},
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(events)


def _case_error(outcome_class: str, response: Mapping[str, Any]) -> str | None:
    if outcome_class == OutcomeClass.SUCCESS:
        return None
    for key in ("error", "reason"):
        value = response.get(key)
        if value:
            return str(value)
    return outcome_class


def _profile_detail(profile: EvalProfile) -> dict[str, Any]:
    return {
        "world_config_path": str(profile.world_config_path),
        "server_dir": str(profile.server_dir),
        "mc_host": profile.mc_host,
        "mc_port": profile.mc_port,
        "level_seed": profile.level_seed,
        "level_type": profile.level_type,
        "level_name": profile.level_name,
        "generate_structures": profile.generate_structures,
        "spawn_protection": profile.spawn_protection,
        "keep_server_running": profile.keep_server_running,
    }


def _unknown_command_message(command: str) -> str:
    supported = ", ".join(supported_command_inputs())
    return f"unknown Minecraft live eval command {command!r}; supported: {supported}"


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
