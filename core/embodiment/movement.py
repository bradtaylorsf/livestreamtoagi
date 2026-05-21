"""Pure movement verification helpers for E6-2 (#557).

The Node movement skills report a pose observation through ``perception.report``
and a terminal ``action.result``. This module lets Python independently confirm
whether the final observed pose is actually within the requested target
tolerance; it does not depend on the event bus, database, Redis, or Minecraft.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, TypedDict

MOVEMENT_CLASSES = {
    "reached",
    "blocked",
    "interrupted",
    "aborted",
    "timed-out",
    "unreachable",
    "invalid",
    "partial",
}


MovementVerification = TypedDict(
    "MovementVerification",
    {"verified": bool, "class": str, "distance": float},
)


def _number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _pose(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, Mapping):
        return None
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    z = _number(value.get("z"))
    if x is None or y is None or z is None:
        return None
    return (x, y, z)


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _reported_class(observation: Mapping[str, Any]) -> str:
    reported = str(observation.get("class", "")).lower()
    return reported if reported in MOVEMENT_CLASSES else "partial"


def verify_movement(
    pose_observation: Mapping[str, Any],
    target: Mapping[str, Any] | None = None,
    tolerance: float | None = None,
) -> MovementVerification:
    """Verify a movement pose observation against target/tolerance.

    ``verified`` is true only when the observed final pose is within
    ``tolerance`` blocks of ``target``. If the report claims ``class='reached'``
    but the measured final pose is outside tolerance, Python downgrades it to
    ``partial`` rather than trusting the Node-side label.
    """
    after = _pose(pose_observation.get("after") or pose_observation.get("pose"))
    target_pose = _pose(target or pose_observation.get("target"))
    tol = _number(tolerance if tolerance is not None else pose_observation.get("tolerance"))
    if tol is None:
        tol = 0.5
    if tol < 0 or after is None or target_pose is None:
        return {"verified": False, "class": "invalid", "distance": math.inf}

    distance = _distance(after, target_pose)
    if distance <= tol:
        return {"verified": True, "class": "reached", "distance": distance}

    reported = _reported_class(pose_observation)
    if reported == "reached":
        reported = "partial"
    return {"verified": False, "class": reported, "distance": distance}
