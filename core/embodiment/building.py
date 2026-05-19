"""Pure block placement/break verification helpers for E6-3 (#558).

The Node building actions report a block observation through
``perception.report`` and a terminal ``action.result``. This module lets Python
independently confirm whether the post-action world read actually matches the
requested placement/removal; it does not depend on the event bus, database,
Redis, or Minecraft.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

BUILD_CLASSES = {
    "placed",
    "removed",
    "blocked",
    "protected",
    "invalid",
    "tool-missing",
    "timed-out",
    "partial",
}

AIR_BLOCK_TYPES = {"air", "cave_air", "void_air"}


BuildVerification = TypedDict(
    "BuildVerification",
    {"verified": bool, "class": str},
)


def _block_name(value: Any) -> Any:
    if isinstance(value, Mapping):
        return (
            value.get("name")
            or value.get("block_type")
            or value.get("blockType")
            or value.get("displayName")
        )
    return value


def _normalize_block_type(value: Any) -> str | None:
    raw = _block_name(value)
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    if normalized.startswith("minecraft:"):
        normalized = normalized.removeprefix("minecraft:")
    normalized = "_".join(normalized.split())
    return normalized or None


def _is_air(value: Any) -> bool:
    normalized = _normalize_block_type(value)
    return normalized is None or normalized in AIR_BLOCK_TYPES


def _reported_class(observation: Mapping[str, Any]) -> str:
    reported = str(observation.get("class", "")).lower()
    return reported if reported in BUILD_CLASSES else "partial"


def verify_place(
    block_observation: Mapping[str, Any],
    block_type: Any | None = None,
) -> BuildVerification:
    """Verify a block placement observation against the requested block type.

    ``verified`` is true only when the observed ``after_block`` equals the
    requested block type. If the report claims ``class='placed'`` but the
    measured block does not match, Python downgrades it to ``partial`` rather
    than trusting the Node-side label.
    """
    if not isinstance(block_observation, Mapping) or "after_block" not in block_observation:
        return {"verified": False, "class": "invalid"}

    expected = _normalize_block_type(block_type or block_observation.get("expected_block_type"))
    after = _normalize_block_type(block_observation.get("after_block"))
    if not expected or expected in AIR_BLOCK_TYPES:
        return {"verified": False, "class": "invalid"}

    if after == expected:
        return {"verified": True, "class": "placed"}

    reported = _reported_class(block_observation)
    if reported == "placed":
        reported = "partial"
    return {"verified": False, "class": reported}


def verify_break(
    block_observation: Mapping[str, Any],
    expected_block_type: Any | None = None,
) -> BuildVerification:
    """Verify a block break observation from the post-action world read.

    ``verified`` is true only when a non-air before block was observed and the
    post-action ``after_block`` is air/absent. If an expected block type is
    supplied, the before block must match it.
    """
    if not isinstance(block_observation, Mapping) or "after_block" not in block_observation:
        return {"verified": False, "class": "invalid"}

    before = _normalize_block_type(block_observation.get("before_block"))
    after = block_observation.get("after_block")
    expected = _normalize_block_type(
        expected_block_type or block_observation.get("expected_block_type")
    )
    if not before or before in AIR_BLOCK_TYPES:
        return {"verified": False, "class": "invalid"}
    if expected and before != expected:
        return {"verified": False, "class": "invalid"}

    if _is_air(after):
        return {"verified": True, "class": "removed"}

    reported = _reported_class(block_observation)
    if reported == "removed":
        reported = "partial"
    return {"verified": False, "class": reported}
