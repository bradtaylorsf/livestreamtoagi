"""Pure multi-block build-plan verification helpers for E6-4 (#559).

The Node ``!buildFromPlan`` action reports a structure observation through
``perception.report`` and a terminal ``action.result``. This module lets Python
independently recompute actual-vs-intended completion from the observed final
blocks and intended cells; it does not trust the Node-side class label.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from core.embodiment.building import AIR_BLOCK_TYPES, _is_air, _normalize_block_type

PLAN_CLASSES = {
    "success",
    "partial",
    "blocked",
    "timed-out",
    "invalid",
    "bridge-down",
}


BuildPlanVerification = TypedDict(
    "BuildPlanVerification",
    {
        "verified": bool,
        "class": str,
        "intended": int,
        "present": int,
        "missing": int,
        "unexpected": int,
        "steps_verified": int,
        "steps_abandoned": int,
        "completion": float,
    },
)


def _invalid() -> BuildPlanVerification:
    return {
        "verified": False,
        "class": "invalid",
        "intended": 0,
        "present": 0,
        "missing": 0,
        "unexpected": 0,
        "steps_verified": 0,
        "steps_abandoned": 0,
        "completion": 0.0,
    }


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _position_from(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    x = _finite_number(value.get("x"))
    y = _finite_number(value.get("y"))
    z = _finite_number(value.get("z"))
    if x is None or y is None or z is None:
        return None
    return {"x": int(x // 1), "y": int(y // 1), "z": int(z // 1)}


def _position_key(position: Any) -> str | None:
    cell = _position_from(position)
    if cell is None:
        return None
    return f"{cell['x']},{cell['y']},{cell['z']}"


def _key_to_position(key: str) -> dict[str, int] | None:
    parts = key.split(",")
    if len(parts) != 3:
        return None
    try:
        x, y, z = (int(part) for part in parts)
    except ValueError:
        return None
    return {"x": x, "y": y, "z": z}


def _delta_from(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    dx = _finite_number(value.get("dx"))
    dy = _finite_number(value.get("dy"))
    dz = _finite_number(value.get("dz"))
    if dx is None or dy is None or dz is None:
        raise ValueError(f"{label} must include finite dx/dy/dz")
    return {"dx": int(dx // 1), "dy": int(dy // 1), "dz": int(dz // 1)}


def _normalize_palette(raw_palette: Any) -> dict[str, str]:
    if raw_palette is None:
        return {}
    if not isinstance(raw_palette, Mapping):
        raise ValueError("plan.palette must be an object map")

    palette: dict[str, str] = {}
    for key, value in raw_palette.items():
        normalized = _normalize_block_type(value)
        if not normalized or normalized in AIR_BLOCK_TYPES:
            raise ValueError(f"plan.palette.{key} must map to a non-air block type")
        text_key = str(key).strip()
        if text_key:
            palette[text_key] = normalized
        normalized_key = _normalize_block_type(key)
        if normalized_key:
            palette[normalized_key] = normalized
    return palette


def _resolve_block_type(value: Any, palette: Mapping[str, str], label: str) -> str:
    raw = str(value).strip() if value is not None else ""
    mapped = palette.get(raw, value)
    normalized = _normalize_block_type(mapped)
    if normalized and normalized in palette:
        normalized = palette[normalized]
    if not normalized or normalized in AIR_BLOCK_TYPES:
        raise ValueError(f"{label} must resolve to a non-air block type")
    return normalized


def expand_build_plan(origin: Mapping[str, Any], plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand ``origin`` + relative plan deltas into ordered absolute steps."""
    base = _position_from(origin)
    if base is None:
        raise ValueError("origin must include finite x/y/z")
    if not isinstance(plan, Mapping):
        raise ValueError("plan must be an object")

    blocks = plan.get("blocks")
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)) or not blocks:
        raise ValueError("plan.blocks must contain at least one block")
    clear = plan.get("clear", [])
    if clear is None:
        clear = []
    if not isinstance(clear, Sequence) or isinstance(clear, (str, bytes)):
        raise ValueError("plan.clear must be an array when provided")

    palette = _normalize_palette(plan.get("palette"))
    steps: list[dict[str, Any]] = []

    for plan_index, item in enumerate(clear):
        delta = _delta_from(item, f"plan.clear[{plan_index}]")
        steps.append(
            {
                "index": len(steps),
                "plan_index": plan_index,
                "source": "clear",
                "action": "break",
                **delta,
                "position": {
                    "x": base["x"] + delta["dx"],
                    "y": base["y"] + delta["dy"],
                    "z": base["z"] + delta["dz"],
                },
                "expected_block_type": None,
            }
        )

    for plan_index, item in enumerate(blocks):
        if not isinstance(item, Mapping):
            raise ValueError(f"plan.blocks[{plan_index}] must be an object")
        delta = _delta_from(item, f"plan.blocks[{plan_index}]")
        block_type = _resolve_block_type(
            item.get("block_type"),
            palette,
            f"plan.blocks[{plan_index}].block_type",
        )
        steps.append(
            {
                "index": len(steps),
                "plan_index": plan_index,
                "source": "blocks",
                "action": "place",
                **delta,
                "position": {
                    "x": base["x"] + delta["dx"],
                    "y": base["y"] + delta["dy"],
                    "z": base["z"] + delta["dz"],
                },
                "block_type": block_type,
                "expected_block_type": block_type,
            }
        )

    return steps


def _steps_from_observation(observation: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps = observation.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        return []

    normalized: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        position = _position_from(step.get("position"))
        if position is None:
            continue
        action = str(step.get("action") or "").lower()
        if action not in {"place", "break"}:
            continue
        block_type = _normalize_block_type(
            step.get("block_type") or step.get("expected_block_type")
        )
        normalized.append(
            {
                "index": int(step.get("index") if isinstance(step.get("index"), int) else idx),
                "source": step.get("source"),
                "action": action,
                "position": position,
                "block_type": block_type,
                "expected_block_type": _normalize_block_type(step.get("expected_block_type")),
                "before_block": _normalize_block_type(step.get("before_block")),
                "after_block": _normalize_block_type(step.get("after_block")),
                "final_block": _normalize_block_type(step.get("final_block")),
                "class": str(step.get("class") or "").lower(),
                "status": str(step.get("status") or "").lower(),
                "abandoned": bool(step.get("abandoned")),
            }
        )
    return normalized


def _plan_from_arg(
    observation: Mapping[str, Any], plan: Mapping[str, Any] | None
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    if plan is None:
        embedded = observation.get("plan")
        if not isinstance(embedded, Mapping):
            return None
        plan = embedded

    if "origin" in plan and "plan" in plan:
        origin = plan.get("origin")
        raw_plan = plan.get("plan")
    else:
        origin = observation.get("origin")
        raw_plan = plan

    if not isinstance(origin, Mapping) or not isinstance(raw_plan, Mapping):
        return None
    return origin, raw_plan


def _block_type_from_final_entry(entry: Any) -> str | None:
    if isinstance(entry, Mapping):
        return _normalize_block_type(
            entry.get("block_type")
            or entry.get("blockType")
            or entry.get("final_block")
            or entry.get("after_block")
            or entry.get("name")
            or entry.get("displayName")
        )
    return _normalize_block_type(entry)


def _final_blocks_map(observation: Mapping[str, Any]) -> dict[str, str | None]:
    final_blocks = observation.get("final_blocks")
    observed: dict[str, str | None] = {}

    if isinstance(final_blocks, Mapping):
        for key, value in final_blocks.items():
            if _key_to_position(str(key)) is not None:
                observed[str(key)] = _block_type_from_final_entry(value)
    elif isinstance(final_blocks, Sequence) and not isinstance(final_blocks, (str, bytes)):
        for entry in final_blocks:
            if not isinstance(entry, Mapping):
                continue
            key = _position_key(entry.get("position") or entry)
            if key is not None:
                observed[key] = _block_type_from_final_entry(entry)

    if observed:
        return observed

    for step in _steps_from_observation(observation):
        key = _position_key(step.get("position"))
        if key is None:
            continue
        observed[key] = _normalize_block_type(step.get("final_block") or step.get("after_block"))
    return observed


def _step_final_block(
    step: Mapping[str, Any], final_blocks: Mapping[str, str | None]
) -> str | None:
    key = _position_key(step.get("position"))
    if key and key in final_blocks:
        return final_blocks[key]
    return _normalize_block_type(step.get("final_block") or step.get("after_block"))


def _is_step_abandoned(step: Mapping[str, Any]) -> bool:
    return (
        bool(step.get("abandoned"))
        or str(step.get("class") or "").lower() == "abandoned"
        or str(step.get("status") or "").lower() == "abandoned"
    )


def _reported_plan_class(observation: Mapping[str, Any]) -> str:
    reported = str(observation.get("class", "")).lower()
    return reported if reported in PLAN_CLASSES else "partial"


def verify_build_plan(
    structure_observation: Mapping[str, Any],
    plan: Mapping[str, Any] | None = None,
) -> BuildPlanVerification:
    """Verify a final structure observation against intended build-plan cells."""
    if not isinstance(structure_observation, Mapping):
        return _invalid()

    plan_args = _plan_from_arg(structure_observation, plan)
    if plan_args is not None:
        try:
            steps = expand_build_plan(*plan_args)
        except ValueError:
            return _invalid()
        observed_steps = _steps_from_observation(structure_observation)
        if observed_steps:
            observed_by_key = {
                _position_key(step.get("position")): step
                for step in observed_steps
                if _position_key(step.get("position")) is not None
            }
            steps = [
                {**step, **observed_by_key.get(_position_key(step.get("position")), {})}
                for step in steps
            ]
    else:
        steps = _steps_from_observation(structure_observation)

    final_blocks = _final_blocks_map(structure_observation)
    if not steps or not final_blocks:
        return _invalid()

    intended: dict[str, str] = {}
    for step in steps:
        key = _position_key(step.get("position"))
        if key is None:
            continue
        if step.get("action") == "place":
            block_type = _normalize_block_type(
                step.get("block_type") or step.get("expected_block_type")
            )
            if block_type and block_type not in AIR_BLOCK_TYPES:
                intended[key] = block_type

    intended_count = len(intended)
    if intended_count <= 0:
        return _invalid()

    present = 0
    missing = 0
    for key, expected in intended.items():
        actual = final_blocks.get(key)
        if actual == expected:
            present += 1
        else:
            missing += 1

    unexpected = 0
    for key, actual in final_blocks.items():
        if _is_air(actual):
            continue
        expected = intended.get(key)
        if expected is None or expected != actual:
            unexpected += 1

    steps_abandoned = sum(1 for step in steps if _is_step_abandoned(step))
    steps_verified = 0
    for step in steps:
        if _is_step_abandoned(step):
            continue
        final_block = _step_final_block(step, final_blocks)
        if step.get("action") == "place":
            expected = _normalize_block_type(
                step.get("block_type") or step.get("expected_block_type")
            )
            if expected and final_block == expected:
                steps_verified += 1
        elif step.get("action") == "break" and _is_air(final_block):
            steps_verified += 1

    completion = present / intended_count if intended_count else 0.0
    if missing == 0 and unexpected == 0 and steps_abandoned == 0:
        outcome_class = "success"
    else:
        reported = _reported_plan_class(structure_observation)
        outcome_class = "partial" if reported == "success" else reported

    return {
        "verified": outcome_class == "success",
        "class": outcome_class,
        "intended": intended_count,
        "present": present,
        "missing": missing,
        "unexpected": unexpected,
        "steps_verified": steps_verified,
        "steps_abandoned": steps_abandoned,
        "completion": completion,
    }
