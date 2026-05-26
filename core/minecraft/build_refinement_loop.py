"""Reflective build-to-image refinement loop (issue #861).

Pipeline per iteration:

1. (iter 0 only) image-gen produces a source blueprint image
2. Vision decomposer extracts a ``BuildPlan`` from the source image
3. Macro compiler emits a ``BuildScript`` from the ``BuildPlan``
4. ``build_executor`` runs the script and returns a screenshot
5. Vision-comparison call scores the screenshot against the source image
6. Apply recommended patches to the ``BuildPlan`` (not the source image)
7. Stop when match score ≥ threshold, max iterations hit, or cost cap hit
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from core.agents.build_intent import StructureType
from core.agents.new_building_intent import NewBuildingIntent
from core.minecraft.blueprint_generator import BlueprintGenerator
from core.minecraft.build_plan import (
    BuildPlan,
    KeyFeature,
    Position3D,
)
from core.minecraft.build_plan_compiler import BuildPlanCompiler
from core.minecraft.build_script import BuildScript
from core.minecraft.refinement_feedback import (
    BuildPlanPatch,
    RefinementFeedback,
    VisionComparisonProvider,
)

logger = logging.getLogger(__name__)

DEFAULT_MATCH_THRESHOLD = 0.85
DEFAULT_MAX_ITERATIONS = 4
DEFAULT_PER_ATTEMPT_COST_CAP_USD = Decimal("1.00")
DEFAULT_BUILD_EXECUTOR_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc"
    b"\x00\x01\x00\x00\x05\x00\x01\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

TerminationReason = str  # "matched" | "max_iterations" | "cost_cap" | "error"

BuildExecutor = Callable[[BuildScript], Awaitable[bytes]]


@runtime_checkable
class DecomposerProvider(Protocol):
    """Vision backend that produces a ``BuildPlan``-shaped dict from raw bytes."""

    model_id: str

    async def decompose_bytes(
        self,
        *,
        image_bytes: bytes,
        intent: NewBuildingIntent,
    ) -> dict[str, Any]: ...


class FakeDecomposerProvider:
    """Deterministic decomposer for tests/dry-runs.

    Returns the same minimal ``BuildPlan`` payload regardless of input
    image bytes — enough to compile and screenshot.
    """

    model_id = "fake/dream-decomposer"
    cost_per_call = Decimal("0")

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self._payload = payload
        self.calls: int = 0

    async def decompose_bytes(
        self,
        *,
        image_bytes: bytes,
        intent: NewBuildingIntent,
    ) -> dict[str, Any]:
        self.calls += 1
        if self._payload is not None:
            return dict(self._payload)
        return {
            "structure_type": StructureType.cabin.value,
            "size_class": intent.size_class,
            "source_image_id": f"{intent.intent_id}:source",
            "footprint": {
                "shape": "rectangle",
                "bbox": {"x": 0, "y": 0, "w": 8, "h": 8},
            },
            "levels": [
                {"index": 0, "height_blocks": 3, "floor_material": "oak_planks"}
            ],
            "materials": [
                {"region": "walls", "material": "oak_log"},
                {"region": "roof", "material": "spruce_planks"},
            ],
            "key_features": [],
            "openings": [],
            "decomposer_version": 1,
            "provider_model_id": "fake/dream-decomposer",
        }


@dataclass
class IterationRecord:
    """Per-iteration provenance row recorded into ``final_summary.json``."""

    iteration: int
    match_score: float
    cost_usd: Decimal
    feedback_path: Path
    screenshot_path: Path
    script_path: Path
    buildplan_path: Path
    feature_deltas: list[str] = field(default_factory=list)


class RefinementLoop:
    """Orchestrate the decompose → compile → build → compare → revise loop."""

    def __init__(
        self,
        *,
        blueprint_generator: BlueprintGenerator,
        decomposer: DecomposerProvider,
        compiler: BuildPlanCompiler,
        build_executor: BuildExecutor,
        comparison_provider: VisionComparisonProvider,
        decision_logger: Any | None = None,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        per_attempt_cost_cap_usd: Decimal | str | float = DEFAULT_PER_ATTEMPT_COST_CAP_USD,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if not 0.0 < match_threshold <= 1.0:
            raise ValueError("match_threshold must be in (0, 1]")
        self._generator = blueprint_generator
        self._decomposer = decomposer
        self._compiler = compiler
        self._build_executor = build_executor
        self._comparison = comparison_provider
        self._decision_logger = decision_logger
        self._match_threshold = match_threshold
        self._max_iterations = max_iterations
        self._per_attempt_cost_cap = Decimal(str(per_attempt_cost_cap_usd))

    @property
    def match_threshold(self) -> float:
        return self._match_threshold

    @property
    def max_iterations(self) -> int:
        return self._max_iterations

    async def run(
        self,
        intent: NewBuildingIntent,
        *,
        sim_folder: Path | str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the refinement loop end-to-end for ``intent`` and persist artifacts.

        Returns the contents of ``final_summary.json`` for direct use by
        the tool layer.
        """
        intent_folder = Path(sim_folder) / "new_buildings" / intent.intent_id
        intent_folder.mkdir(parents=True, exist_ok=True)
        decompositions_dir = intent_folder / "decompositions"
        scripts_dir = intent_folder / "scripts"
        screenshots_dir = intent_folder / "screenshots"
        feedback_dir = intent_folder / "feedback"
        for d in (decompositions_dir, scripts_dir, screenshots_dir, feedback_dir):
            d.mkdir(parents=True, exist_ok=True)

        actor_id = agent_id or intent.proposer_id

        # 1) Source image — generate or fetch from cache.
        image_bytes, prompt, cache_hit = await self._generator.generate(intent)
        (intent_folder / "source_image.png").write_bytes(image_bytes)
        (intent_folder / "image_prompt.txt").write_text(prompt, encoding="utf-8")

        accumulated_cost = (
            Decimal("0") if cache_hit else self._generator.cost_per_call
        )
        self._log_iteration_event(
            actor_id=actor_id,
            iteration=-1,
            phase="image_generated",
            intent_id=intent.intent_id,
            details={
                "cache_hit": cache_hit,
                "cost_usd": str(accumulated_cost),
                "provider_model_id": self._generator.provider_model_id,
            },
        )

        # 2) Initial decomposition.
        plan_payload = await self._decomposer.decompose_bytes(
            image_bytes=image_bytes, intent=intent
        )
        plan = BuildPlan.model_validate(plan_payload)

        iterations: list[IterationRecord] = []
        last_feedback: RefinementFeedback | None = None
        termination_reason: TerminationReason = "max_iterations"

        for n in range(self._max_iterations):
            # 3) Compile.
            script = self._compiler.compile(plan, intent_id=intent.intent_id)

            # Persist current plan + script.
            plan_path = decompositions_dir / f"iter_{n}.buildplan.json"
            plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            script_path = scripts_dir / f"iter_{n}.script.json"
            script_path.write_text(
                json.dumps(script.to_jsonable(), sort_keys=True, indent=2),
                encoding="utf-8",
            )

            # 4) Build + screenshot.
            try:
                screenshot_bytes = await self._build_executor(script)
            except Exception:
                logger.exception(
                    "build executor failed for intent %s iteration %d",
                    intent.intent_id,
                    n,
                )
                termination_reason = "error"
                break
            screenshot_path = screenshots_dir / f"iter_{n}.png"
            screenshot_path.write_bytes(screenshot_bytes or DEFAULT_BUILD_EXECUTOR_PNG)

            # 5) Compare.
            feedback = await self._comparison.compare(
                source_image=image_bytes,
                screenshot=screenshot_bytes or DEFAULT_BUILD_EXECUTOR_PNG,
                build_plan=plan,
            )
            last_feedback = feedback
            feedback_path = feedback_dir / f"iter_{n}.json"
            feedback_path.write_text(
                feedback.model_dump_json(indent=2), encoding="utf-8"
            )

            iter_cost = self._comparison.cost_per_call
            accumulated_cost += iter_cost
            iterations.append(
                IterationRecord(
                    iteration=n,
                    match_score=feedback.match_score,
                    cost_usd=accumulated_cost,
                    feedback_path=feedback_path,
                    screenshot_path=screenshot_path,
                    script_path=script_path,
                    buildplan_path=plan_path,
                    feature_deltas=list(feedback.feature_deltas),
                )
            )

            self._log_iteration_event(
                actor_id=actor_id,
                iteration=n,
                phase="compared",
                intent_id=intent.intent_id,
                details={
                    "match_score": feedback.match_score,
                    "feature_deltas": feedback.feature_deltas,
                    "cost_usd": str(accumulated_cost),
                    "patches": [p.model_dump(mode="json") for p in feedback.recommended_buildplan_patches],
                },
            )

            # 6) Termination checks.
            if feedback.match_score >= self._match_threshold:
                termination_reason = "matched"
                break

            if accumulated_cost >= self._per_attempt_cost_cap:
                termination_reason = "cost_cap"
                break

            if n == self._max_iterations - 1:
                termination_reason = "max_iterations"
                break

            # 7) Apply patches to the plan and loop.
            plan = _apply_patches(plan, feedback.recommended_buildplan_patches)

        summary = self._build_summary(
            intent=intent,
            prompt=prompt,
            iterations=iterations,
            termination_reason=termination_reason,
            cache_hit=cache_hit,
            accumulated_cost=accumulated_cost,
            last_feedback=last_feedback,
        )
        (intent_folder / "final_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return summary

    # ─── helpers ───────────────────────────────────────────────────

    def _log_iteration_event(
        self,
        *,
        actor_id: str,
        iteration: int,
        phase: str,
        intent_id: str,
        details: dict[str, Any],
    ) -> None:
        if self._decision_logger is None:
            return
        try:
            self._decision_logger.log_world_event(
                event_type="new_building_iteration",
                trigger=actor_id,
                details={
                    "intent_id": intent_id,
                    "iteration": iteration,
                    "phase": phase,
                    **details,
                },
            )
        except Exception:  # pragma: no cover - logger must not break the loop
            logger.exception("decision_logger.log_world_event failed")

    def _build_summary(
        self,
        *,
        intent: NewBuildingIntent,
        prompt: str,
        iterations: list[IterationRecord],
        termination_reason: TerminationReason,
        cache_hit: bool,
        accumulated_cost: Decimal,
        last_feedback: RefinementFeedback | None,
    ) -> dict[str, Any]:
        final_match_score = (
            iterations[-1].match_score if iterations else 0.0
        )
        return {
            "intent": intent.to_log_payload(),
            "image_prompt": prompt,
            "providers": {
                "image": self._generator.provider_model_id,
                "comparison": self._comparison.model_id,
                "decomposer": self._decomposer.model_id,
            },
            "image_cache_hit": cache_hit,
            "image_prompt_version": self._generator.version,
            "iteration_count": len(iterations),
            "max_iterations": self._max_iterations,
            "match_threshold": self._match_threshold,
            "per_attempt_cost_cap_usd": str(self._per_attempt_cost_cap),
            "total_cost_usd": str(accumulated_cost),
            "final_match_score": final_match_score,
            "termination_reason": termination_reason,
            "iterations": [
                {
                    "iteration": rec.iteration,
                    "match_score": rec.match_score,
                    "cumulative_cost_usd": str(rec.cost_usd),
                    "feature_deltas": rec.feature_deltas,
                    "feedback_path": rec.feedback_path.as_posix(),
                    "screenshot_path": rec.screenshot_path.as_posix(),
                    "script_path": rec.script_path.as_posix(),
                    "buildplan_path": rec.buildplan_path.as_posix(),
                }
                for rec in iterations
            ],
            "final_feedback": (
                last_feedback.model_dump(mode="json") if last_feedback else None
            ),
            "completed_at": datetime.now(UTC).isoformat(),
        }


# ─── plan-patch application ───────────────────────────────────────


def _apply_patches(
    plan: BuildPlan, patches: list[BuildPlanPatch]
) -> BuildPlan:
    """Return a new ``BuildPlan`` with ``patches`` applied.

    Unknown or contradictory patches are skipped rather than raising — the
    loop will see the same plan in the next iteration and accept the
    upstream comparison's verdict.
    """
    payload = plan.model_dump(mode="json")
    materials: list[dict[str, Any]] = list(payload.get("materials") or [])
    levels: list[dict[str, Any]] = list(payload.get("levels") or [])
    key_features: list[dict[str, Any]] = list(payload.get("key_features") or [])

    for patch in patches:
        if patch.op == "material_reassign" and patch.region and patch.material:
            region = patch.region.strip().lower()
            replaced = False
            for entry in materials:
                if entry.get("region", "").lower() == region:
                    entry["material"] = patch.material
                    replaced = True
                    break
            if not replaced:
                materials.append({"region": patch.region, "material": patch.material})

        elif patch.op == "level_height_adjust":
            if patch.level_index is None or patch.delta_height is None:
                continue
            for entry in levels:
                if entry.get("index") == patch.level_index:
                    current = int(entry.get("height_blocks", 1))
                    new = max(1, current + int(patch.delta_height))
                    entry["height_blocks"] = new
                    break

        elif patch.op == "key_feature_add" and patch.feature_kind and patch.feature_position:
            try:
                feature = KeyFeature(
                    kind=patch.feature_kind,  # type: ignore[arg-type]
                    position=Position3D(**patch.feature_position),
                    size=patch.feature_size,
                )
            except Exception:
                continue
            key_features.append(feature.model_dump(mode="json"))

        elif patch.op == "key_feature_remove" and patch.feature_kind and patch.feature_position:
            target = patch.feature_position
            key_features = [
                f
                for f in key_features
                if not (
                    f.get("kind") == patch.feature_kind
                    and f.get("position", {}).get("x") == target.get("x")
                    and f.get("position", {}).get("y") == target.get("y")
                    and f.get("position", {}).get("z") == target.get("z")
                )
            ]

    payload["materials"] = materials
    payload["levels"] = levels
    payload["key_features"] = key_features
    return BuildPlan.model_validate(payload)


# ─── default fake-bridge build executor for tests/dry-runs ───────


async def screenshotting_build_executor(script: BuildScript) -> bytes:
    """Default build executor that returns a deterministic PNG.

    Real executors run the script through the live Minecraft bridge and
    return the post-build screenshot. Tests use this stub or override it
    via constructor injection.
    """
    _ = script  # script is consumed by the bridge in the real executor
    return DEFAULT_BUILD_EXECUTOR_PNG


__all__ = [
    "DEFAULT_MATCH_THRESHOLD",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_PER_ATTEMPT_COST_CAP_USD",
    "BuildExecutor",
    "DecomposerProvider",
    "FakeDecomposerProvider",
    "IterationRecord",
    "RefinementLoop",
    "screenshotting_build_executor",
]
