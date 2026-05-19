"""Embodiment/action-layer helpers."""

from typing import Any

from core.embodiment.build_plan import verify_build_plan
from core.embodiment.building import verify_break, verify_place
from core.embodiment.failure import (
    FAILURE_CLASSES,
    SAFE_FAIL_POLICY,
    RetryBudget,
    SafeFailDecision,
    classify,
    decide_safe_fail,
)
from core.embodiment.movement import verify_movement


def build_perception_snapshot(*args: Any, **kwargs: Any) -> Any:
    """Lazily delegate to perception helpers to avoid bridge import cycles."""
    from core.embodiment.perception import build_perception_snapshot as _impl

    return _impl(*args, **kwargs)


def is_schema_valid_snapshot(*args: Any, **kwargs: Any) -> Any:
    """Lazily delegate to perception helpers to avoid bridge import cycles."""
    from core.embodiment.perception import is_schema_valid_snapshot as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "FAILURE_CLASSES",
    "SAFE_FAIL_POLICY",
    "RetryBudget",
    "SafeFailDecision",
    "build_perception_snapshot",
    "classify",
    "decide_safe_fail",
    "is_schema_valid_snapshot",
    "verify_break",
    "verify_build_plan",
    "verify_movement",
    "verify_place",
]
