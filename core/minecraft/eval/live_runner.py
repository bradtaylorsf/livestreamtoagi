"""Focused live Minecraft command smoke runner with deterministic dry-run support."""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from core.minecraft.eval.live_profile import DEFAULT_PROFILE_NAME, EvalProfile, resolve_profile
from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    EvalCategory,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
    classify_eval_category,
    derive_block_mutation,
    derive_inventory_delta,
    derive_lifecycle_signals,
    derive_pathfinding_signals,
    derive_timing_signals,
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
    {"status": "ok", "reason": "completed", "mutation_mismatch": True},
    {"status": "failed", "reason": "blocked by collision: cannot path to target"},
    {"status": "rejected", "reason": "permission gate rejected command"},
    {"status": "timeout", "reason": "stuck: action timed out while pathfinding"},
    {"status": "malformed", "reason": "parser rejected command before dispatch"},
    {"status": "failed", "reason": "death loop: died in lava after respawn"},
    {"status": "failed", "reason": "unstuck_failed: still_stuck after recovery"},
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
        final_state = response.get("final_state")
        if not isinstance(final_state, Mapping):
            final_state = _fake_final_state(command_name, command_text, response)
        final_state = _state_with_response_signals(final_state, response, agent_id=None)
        return {
            "status": response.get("status", "ok"),
            "reason": response.get("reason"),
            "error": response.get("error"),
            "action_events": response.get("action_events", ()),
            "final_state": final_state,
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

    family_match = _FAMILY_COMMANDS.get(normalized) or _FAMILY_COMMANDS.get(normalized.casefold())
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
    return await _run_case_for_agent(case, bridge=bridge, agent_id=None)


async def _run_case_for_agent(
    case: CommandCase,
    *,
    bridge: BridgeClient,
    agent_id: str | None,
) -> CaseResult:
    started_ms = _now_ms()
    params = _case_params(case, agent_id=agent_id)
    events: list[ActionEvent] = [
        ActionEvent(
            action_id=case.action_id,
            kind="start",
            ts_ms=started_ms,
            payload={
                "agent_id": agent_id,
                "case_id": case.case_id,
                "command": case.command_name,
                "command_text": case.command_text,
                "params": dict(params),
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
    final_state = response.get("final_state")
    if not isinstance(final_state, Mapping):
        final_state = {}
    final_state = _state_with_response_signals(final_state, response, agent_id=agent_id)
    detail = response.get("reason") or response.get("outcome_class") or error
    lifecycle_state = _state_with_detail(final_state, detail)
    lifecycle = derive_lifecycle_signals(
        case.command_name,
        outcome_class,
        tuple(events),
        params=params,
        final_state=lifecycle_state,
    )
    eval_category = classify_eval_category(
        case.command_name,
        outcome_class,
        detail,
        final_state,
        params=params,
    )
    eval_category = _category_with_lifecycle(eval_category, lifecycle)
    pathfinding = derive_pathfinding_signals(
        case.command_name,
        outcome_class,
        reason=response.get("reason") or response.get("outcome_class"),
        error=response.get("error") or error,
        final_state=final_state,
    )
    inventory = derive_inventory_delta(
        case.command_name,
        outcome_class,
        params=params,
        final_state=final_state,
    )
    block_mutation = derive_block_mutation(
        case.command_name,
        outcome_class,
        params=params,
        final_state=final_state,
    )
    timing = None
    if agent_id:
        timing_state = dict(final_state)
        timing_state.setdefault("latency_ms", max(0, ended_ms - started_ms))
        timing = derive_timing_signals(
            agent_id,
            tuple(events),
            params=params,
            final_state=timing_state,
        )
        if timing is not None:
            eval_category = EvalCategory.MULTI_AGENT_TIMING
    events.append(
        ActionEvent(
            action_id=case.action_id,
            kind="end",
            ts_ms=ended_ms,
            payload={
                "agent_id": agent_id,
                "case_id": case.case_id,
                "command": case.command_name,
                "status": response.get("status"),
                "reason": response.get("reason"),
                "outcome_class": outcome_class,
                "eval_category": eval_category,
                "pathfinding": pathfinding.to_dict() if pathfinding else None,
                "inventory": inventory.to_dict() if inventory else None,
                "block_mutation": block_mutation.to_dict() if block_mutation else None,
                "lifecycle": lifecycle.to_dict() if lifecycle else None,
                "timing": timing.to_dict() if timing else None,
                "latency_ms": max(0, ended_ms - started_ms),
            },
        )
    )

    return CaseResult(
        case_id=case.case_id,
        command_text=case.command_text,
        params=params,
        action_events=tuple(events),
        outcome_class=outcome_class,
        final_state=final_state,
        latency_ms=max(0, ended_ms - started_ms),
        agent_id=agent_id,
        error=error,
        eval_category=eval_category,
        pathfinding=pathfinding,
        inventory=inventory,
        block_mutation=block_mutation,
        lifecycle=lifecycle,
        timing=timing,
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
    params = {
        "action_id": action_id,
        "block_type": block_type,
        "expected_inventory_delta": {block_type: -1},
        "expected_blocks": [{"dx": 0, "dy": 0, "dz": 1, "block_type": block_type}],
    }
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
        "expected_inventory_delta": {block_type: -len(plan["blocks"])},
        "max_steps": max_steps,
        "timeout_ms": timeout_ms,
    }
    origin_json = json.dumps(origin, separators=(",", ":"))
    plan_json = json.dumps(plan, separators=(",", ":"))
    command_text = f"!buildFromPlan {action_id} {origin_json} {plan_json} {max_steps} {timeout_ms}"
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
    if command_name in {"move", "searchForBlock", "planAndBuild", "buildFromPlan"}:
        detail = f"{response.get('reason') or ''} {response.get('error') or ''}".casefold()
        state["pose"] = {"x": 1, "y": 64, "z": 0, "yaw": 90}
        state["pathfinding"] = {
            "stuck": "stuck" in detail or "timed out" in detail,
            "collision": "collision" in detail,
            "blocked_path": any(
                marker in detail for marker in ("blocked", "cannot path", "no path", "unreachable")
            ),
        }

    if command_name == "placeHere":
        block_type = _place_here_block_type(command_text)
        initial_inventory = {block_type: 4}
        intended_block = {"x": 0, "y": 64, "z": 1, "block_type": block_type}
        placed_blocks = (
            []
            if response.get("mutation_mismatch") or outcome_class != OutcomeClass.SUCCESS
            else [intended_block]
        )
        final_inventory = _inventory_after_placements(initial_inventory, placed_blocks)
        state.update(
            {
                "pose": {"x": 0, "y": 64, "z": 0, "yaw": 0},
                "initial_inventory": initial_inventory,
                "final_inventory": final_inventory,
                "inventory": final_inventory,
                "initial_blocks": [],
                "placed_blocks": placed_blocks,
                "blocks": placed_blocks,
            }
        )
    elif command_name == "buildFromPlan":
        origin, plan = _build_from_plan_payload(command_text)
        intended_blocks = _translated_plan_blocks(plan, origin)
        placed_blocks = (
            intended_blocks[:-1]
            if (response.get("mutation_mismatch") or outcome_class != OutcomeClass.SUCCESS)
            and intended_blocks
            else intended_blocks
        )
        initial_inventory = _initial_inventory_for_plan(intended_blocks)
        final_inventory = _inventory_after_placements(initial_inventory, placed_blocks)
        state.update(
            {
                "initial_inventory": initial_inventory,
                "final_inventory": final_inventory,
                "inventory": final_inventory,
                "initial_blocks": [],
                "placed_blocks": placed_blocks,
                "blocks": placed_blocks,
            }
        )
    elif command_name == "planAndBuild":
        intended_blocks = [{"x": 0, "y": 64, "z": 1, "block_type": "oak_planks"}]
        placed_blocks = (
            []
            if response.get("mutation_mismatch") or outcome_class != OutcomeClass.SUCCESS
            else intended_blocks
        )
        initial_inventory = _initial_inventory_for_plan(intended_blocks)
        final_inventory = _inventory_after_placements(initial_inventory, placed_blocks)
        state.update(
            {
                "initial_inventory": initial_inventory,
                "final_inventory": final_inventory,
                "inventory": final_inventory,
                "initial_blocks": [],
                "placed_blocks": placed_blocks,
                "blocks": placed_blocks,
            }
        )
    elif command_name == "inventory":
        initial_inventory = {"oak_planks": 8, "cobblestone": 8, "torch": 4}
        final_inventory = (
            {"oak_planks": 8, "cobblestone": 8, "torch": 3}
            if response.get("mutation_mismatch")
            else dict(initial_inventory)
        )
        state["initial_inventory"] = initial_inventory
        state["final_inventory"] = final_inventory
        state["inventory"] = final_inventory
    elif command_name not in {"move", "searchForBlock", "planAndBuild", "buildFromPlan"}:
        state["nearby_blocks"] = [
            {"x": 0, "y": 63, "z": 0, "block_type": "grass_block"},
            {"x": 1, "y": 64, "z": 1, "block_type": "oak_log"},
        ]
    _add_fake_lifecycle_state(state, response)
    return state


def _state_with_detail(
    final_state: Mapping[str, Any],
    detail: object | None,
) -> Mapping[str, Any]:
    if not detail:
        return final_state
    state = dict(final_state)
    state.setdefault("status_detail", str(detail))
    return state


def _state_with_response_signals(
    final_state: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    agent_id: str | None,
) -> dict[str, Any]:
    state = dict(final_state)
    if agent_id:
        state.setdefault("agent_id", agent_id)
        state.setdefault("multi_agent", True)
    for key in (
        "queue_depth",
        "queue_contention",
        "self_interruption_count",
        "director_fanout_count",
        "dropped_commands",
        "command_loss_count",
        "conflicts",
        "conflicting_action_ids",
        "last_command_ts_ms",
        "latency_ms",
    ):
        if key in response and key not in state:
            state[key] = response[key]
    return state


def _case_params(case: CommandCase, *, agent_id: str | None) -> dict[str, Any]:
    params = dict(case.params)
    if agent_id:
        params.setdefault("agent_id", agent_id)
        params.setdefault("multi_agent", True)
    return params


def _category_with_lifecycle(eval_category: str, lifecycle: Any | None) -> str:
    if eval_category == EvalCategory.MULTI_AGENT_TIMING:
        return eval_category
    if lifecycle is None:
        return eval_category
    if lifecycle.death_loop:
        return EvalCategory.DEATH_LOOP
    if lifecycle.respawns or lifecycle.safe_spawn is not None or lifecycle.unsafe_spawn_count:
        return EvalCategory.SAFE_SPAWN
    if (
        lifecycle.unstuck_attempts
        or lifecycle.unstuck_succeeded is not None
        or lifecycle.unstuck_failed
    ):
        return EvalCategory.STUCK_UNSTUCK
    if lifecycle.stuck and eval_category == EvalCategory.OTHER:
        return EvalCategory.STUCK_UNSTUCK
    return eval_category


def _add_fake_lifecycle_state(state: dict[str, Any], response: Mapping[str, Any]) -> None:
    detail = f"{response.get('reason') or ''} {response.get('error') or ''}".casefold()
    if "death" in detail or "died" in detail or "killed" in detail:
        deaths = [{"reason": "died in lava" if "lava" in detail else "death event"}]
        if "loop" in detail or "again" in detail:
            deaths.append({"reason": "repeated death"})
        state["deaths"] = deaths
        state["death_count"] = len(deaths)
        state["death_loop"] = len(deaths) >= 2 or "loop" in detail
        state["respawns"] = max(1, len(deaths))
        state["spawn"] = {
            "safe": "lava" not in detail and "unsafe" not in detail and "void" not in detail,
            "reason": "spawn in lava" if "lava" in detail else "safe spawn",
        }
    if "unsafe spawn" in detail or "spawn in lava" in detail or "void spawn" in detail:
        state["unsafe_spawn_count"] = 1
        state["spawn"] = {"safe": False, "reason": response.get("reason") or "unsafe spawn"}
    elif "safe spawn" in detail or "respawn" in detail:
        state["spawn_safe"] = True
        state["respawns"] = max(1, int(state.get("respawns") or 0))
    if "stuck_events" in detail:
        state["stuck_events"] = max(1, int(state.get("stuck_events") or 0))
    if "unstuck" in detail or "recover" in detail:
        state["stuck_events"] = max(1, int(state.get("stuck_events") or 0))
        state["unstuck_attempts"] = 1
        succeeded = any(marker in detail for marker in ("recovered", "unstuck_ok", "freed"))
        failed = any(marker in detail for marker in ("unstuck_failed", "still_stuck", "failed"))
        if succeeded:
            state["unstuck_succeeded"] = True
        if failed:
            state["unstuck_failed"] = True


def _place_here_block_type(command_text: str) -> str:
    parts = command_text.strip().split()
    if len(parts) >= 2 and parts[1].strip():
        return parts[1].strip()
    return "oak_planks"


def _build_from_plan_payload(command_text: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    parts = command_text.strip().split(maxsplit=5)
    if len(parts) >= 4:
        try:
            origin = json.loads(parts[2])
            plan = json.loads(parts[3])
        except json.JSONDecodeError:
            origin = {"x": 0, "y": 64, "z": 0}
            plan = {"blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "oak_planks"}]}
        if isinstance(origin, Mapping) and isinstance(plan, Mapping):
            return origin, plan
    return {"x": 0, "y": 64, "z": 0}, {
        "blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "oak_planks"}]
    }


def _translated_plan_blocks(
    plan: Mapping[str, Any],
    origin: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_blocks = plan.get("blocks")
    if not isinstance(raw_blocks, Sequence) or isinstance(raw_blocks, (str, bytes)):
        return []
    origin_x = int(origin.get("x", 0))
    origin_y = int(origin.get("y", 64))
    origin_z = int(origin.get("z", 0))
    blocks: list[dict[str, Any]] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, Mapping):
            continue
        block_type = raw_block.get("block_type")
        if not block_type:
            continue
        if all(key in raw_block for key in ("x", "y", "z")):
            x = int(raw_block["x"])
            y = int(raw_block["y"])
            z = int(raw_block["z"])
        else:
            x = origin_x + int(raw_block.get("dx", 0))
            y = origin_y + int(raw_block.get("dy", 0))
            z = origin_z + int(raw_block.get("dz", 0))
        blocks.append({"x": x, "y": y, "z": z, "block_type": str(block_type)})
    return blocks


def _initial_inventory_for_plan(blocks: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(str(block.get("block_type")) for block in blocks if block.get("block_type"))
    return {block_type: count + 4 for block_type, count in sorted(counts.items())}


def _inventory_after_placements(
    initial_inventory: Mapping[str, int],
    placed_blocks: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    final_inventory = dict(initial_inventory)
    for block in placed_blocks:
        block_type = str(block.get("block_type") or "")
        if not block_type:
            continue
        final_inventory[block_type] = final_inventory.get(block_type, 0) - 1
    return final_inventory


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
