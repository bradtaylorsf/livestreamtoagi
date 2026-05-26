"""Vision-comparison feedback for the build refinement loop (issue #861).

The comparison vision call ingests the source image and a post-build
screenshot and emits structured :class:`RefinementFeedback`. The
:class:`RefinementLoop` applies the feedback's
``recommended_buildplan_patches`` (material reassignments, level-height
adjustments, key-feature add/remove) to the live ``BuildPlan`` and
re-compiles — it never re-generates the source image.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from core.minecraft.build_plan import BuildPlan

PatchOp = Literal[
    "material_reassign",
    "level_height_adjust",
    "key_feature_add",
    "key_feature_remove",
]


class BuildPlanPatch(BaseModel):
    """A small, validated mutation against a ``BuildPlan``."""

    model_config = ConfigDict(extra="forbid")

    op: PatchOp
    region: str | None = None
    material: str | None = None
    level_index: int | None = Field(default=None, ge=0)
    delta_height: int | None = None
    feature_kind: str | None = None
    feature_position: dict[str, int] | None = None
    feature_size: dict[str, int] | None = None
    notes: str | None = None


class RefinementFeedback(BaseModel):
    """Vision-comparison output for one iteration of the refinement loop."""

    model_config = ConfigDict(extra="forbid")

    match_score: float = Field(ge=0.0, le=1.0)
    feature_deltas: list[str] = Field(default_factory=list)
    per_region_critique: dict[str, str] = Field(default_factory=dict)
    recommended_buildplan_patches: list[BuildPlanPatch] = Field(
        default_factory=list
    )
    provider_model_id: str = Field(min_length=1)


@runtime_checkable
class VisionComparisonProvider(Protocol):
    """Pluggable vision backend that scores screenshot vs. source image."""

    model_id: str
    cost_per_call: Decimal

    async def compare(
        self,
        *,
        source_image: bytes,
        screenshot: bytes,
        build_plan: BuildPlan,
    ) -> RefinementFeedback: ...


class FakeComparisonProvider:
    """Deterministic stub for tests.

    Returns the feedback queue in order, looping back to the final entry
    once the queue is exhausted so tests can drive arbitrary iteration
    counts without manually padding the queue.
    """

    model_id = "fake/comparison-v0"
    cost_per_call = Decimal("0")

    def __init__(self, queue: list[RefinementFeedback]) -> None:
        if not queue:
            raise ValueError("FakeComparisonProvider requires a non-empty queue")
        self._queue = list(queue)
        self.calls: list[dict[str, Any]] = []

    async def compare(
        self,
        *,
        source_image: bytes,
        screenshot: bytes,
        build_plan: BuildPlan,
    ) -> RefinementFeedback:
        idx = min(len(self.calls), len(self._queue) - 1)
        self.calls.append(
            {
                "iteration": len(self.calls),
                "source_bytes": len(source_image),
                "screenshot_bytes": len(screenshot),
                "structure_type": build_plan.structure_type,
            }
        )
        return self._queue[idx]


__all__ = [
    "BuildPlanPatch",
    "FakeComparisonProvider",
    "PatchOp",
    "RefinementFeedback",
    "VisionComparisonProvider",
]
