"""Tests for the build-to-image refinement loop (issue #861)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.build_intent import SizeClass
from core.agents.new_building_intent import (
    BiomeFit,
    NewBuildingIntent,
    Vibe,
)
from core.minecraft.blueprint_generator import (
    BlueprintGenerator,
    FakeImageProvider,
)
from core.minecraft.build_plan_compiler import BuildPlanCompiler
from core.minecraft.build_refinement_loop import (
    DEFAULT_BUILD_EXECUTOR_PNG,
    FakeDecomposerProvider,
    RefinementLoop,
)
from core.minecraft.refinement_feedback import (
    BuildPlanPatch,
    FakeComparisonProvider,
    RefinementFeedback,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader


def _intent() -> NewBuildingIntent:
    return NewBuildingIntent(
        proposer_id="rex",
        concept="modular timber lighthouse",
        intended_use="navigation beacon for the alliance",
        vibe=Vibe.rustic,
        size_class=SizeClass.small,
        biome_fit=BiomeFit.water,
        motivation="dream-9 — guidance for night travel",
    )


def _feedback(score: float, *, patches: list[BuildPlanPatch] | None = None) -> RefinementFeedback:
    return RefinementFeedback(
        match_score=score,
        feature_deltas=[f"score={score:.2f}"],
        per_region_critique={},
        recommended_buildplan_patches=patches or [],
        provider_model_id="fake/comparison-v0",
    )


async def _build_executor(_script) -> bytes:
    return DEFAULT_BUILD_EXECUTOR_PNG + b"\x00"


def _loop_with(
    *,
    tmp_path: Path,
    feedback_queue: list[RefinementFeedback],
    match_threshold: float = 0.85,
    max_iterations: int = 4,
    per_attempt_cost_cap_usd: Decimal | str = "1.00",
    decision_logger=None,
) -> tuple[RefinementLoop, FakeComparisonProvider, FakeDecomposerProvider]:
    gen = BlueprintGenerator(FakeImageProvider(), cache_dir=tmp_path / "img_cache")
    decomposer = FakeDecomposerProvider()
    compiler = BuildPlanCompiler()
    comparison = FakeComparisonProvider(feedback_queue)
    loop = RefinementLoop(
        blueprint_generator=gen,
        decomposer=decomposer,
        compiler=compiler,
        build_executor=_build_executor,
        comparison_provider=comparison,
        decision_logger=decision_logger,
        match_threshold=match_threshold,
        max_iterations=max_iterations,
        per_attempt_cost_cap_usd=per_attempt_cost_cap_usd,
    )
    return loop, comparison, decomposer


@pytest.mark.asyncio
async def test_terminates_on_match_threshold(tmp_path: Path) -> None:
    loop, comparison, _ = _loop_with(
        tmp_path=tmp_path,
        feedback_queue=[_feedback(0.6), _feedback(0.95)],
    )
    summary = await loop.run(_intent(), sim_folder=tmp_path / "sim")
    assert summary["termination_reason"] == "matched"
    assert summary["iteration_count"] == 2
    assert summary["final_match_score"] == 0.95
    assert len(comparison.calls) == 2


@pytest.mark.asyncio
async def test_terminates_on_max_iterations(tmp_path: Path) -> None:
    loop, _, _ = _loop_with(
        tmp_path=tmp_path,
        feedback_queue=[_feedback(0.10), _feedback(0.20), _feedback(0.30)],
        max_iterations=3,
    )
    summary = await loop.run(_intent(), sim_folder=tmp_path / "sim")
    assert summary["termination_reason"] == "max_iterations"
    assert summary["iteration_count"] == 3
    assert summary["final_match_score"] == 0.30


@pytest.mark.asyncio
async def test_terminates_on_cost_cap(tmp_path: Path) -> None:
    # The fake comparison provider has cost_per_call = $0. Use a cost cap
    # of $0 so the cap is hit immediately after the first iteration even
    # with the zero-cost fake; combine with an image-gen cost above the
    # cap to exercise the path deterministically.
    class ExpensiveImageProvider(FakeImageProvider):
        cost_per_call = Decimal("5.00")

    gen = BlueprintGenerator(
        ExpensiveImageProvider(), cache_dir=tmp_path / "img_cache"
    )
    loop = RefinementLoop(
        blueprint_generator=gen,
        decomposer=FakeDecomposerProvider(),
        compiler=BuildPlanCompiler(),
        build_executor=_build_executor,
        comparison_provider=FakeComparisonProvider([_feedback(0.1), _feedback(0.2)]),
        match_threshold=0.85,
        max_iterations=4,
        per_attempt_cost_cap_usd="0.50",
    )
    summary = await loop.run(_intent(), sim_folder=tmp_path / "sim")
    assert summary["termination_reason"] == "cost_cap"
    # We always run at least one iteration before deciding to stop.
    assert summary["iteration_count"] == 1


@pytest.mark.asyncio
async def test_persists_all_artifacts_under_new_buildings(tmp_path: Path) -> None:
    intent = _intent()
    loop, _, _ = _loop_with(
        tmp_path=tmp_path,
        feedback_queue=[_feedback(0.1), _feedback(0.95)],
    )
    await loop.run(intent, sim_folder=tmp_path / "sim")
    base = tmp_path / "sim" / "new_buildings" / intent.intent_id
    assert (base / "source_image.png").is_file()
    assert (base / "image_prompt.txt").is_file()
    assert (base / "final_summary.json").is_file()
    assert (base / "decompositions" / "iter_0.buildplan.json").is_file()
    assert (base / "decompositions" / "iter_1.buildplan.json").is_file()
    assert (base / "scripts" / "iter_0.script.json").is_file()
    assert (base / "scripts" / "iter_1.script.json").is_file()
    assert (base / "screenshots" / "iter_0.png").is_file()
    assert (base / "screenshots" / "iter_1.png").is_file()
    assert (base / "feedback" / "iter_0.json").is_file()
    assert (base / "feedback" / "iter_1.json").is_file()

    final = json.loads((base / "final_summary.json").read_text())
    assert final["intent"]["intent_id"] == intent.intent_id
    assert final["termination_reason"] == "matched"
    assert final["providers"]["image"]
    assert final["providers"]["comparison"]
    assert final["providers"]["decomposer"]
    assert final["image_prompt"]
    assert isinstance(final["total_cost_usd"], str)
    # Summary mirrors what was logged.
    assert final["match_threshold"] == 0.85
    assert "iterations" in final
    assert len(final["iterations"]) == 2


@pytest.mark.asyncio
async def test_decision_logger_records_new_building_iteration_rows(
    tmp_path: Path,
) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    logger = DecisionLogger(sim_folder)
    loop, _, _ = _loop_with(
        tmp_path=tmp_path,
        feedback_queue=[_feedback(0.1), _feedback(0.95)],
        decision_logger=logger,
    )
    await loop.run(_intent(), sim_folder=sim_folder)
    logger.close()
    rows = [r for r in DecisionLogReader(sim_folder).replay()]
    event_types = [r.event_type for r in rows]
    assert "world_event" in event_types
    world_events = [r for r in rows if r.event_type == "world_event"]
    assert all(r.payload.event_type == "new_building_iteration" for r in world_events)
    phases = [r.payload.details.get("phase") for r in world_events]
    assert "image_generated" in phases
    assert "compared" in phases


@pytest.mark.asyncio
async def test_image_cache_short_circuits_second_run(tmp_path: Path) -> None:
    intent = _intent()
    loop, _, _ = _loop_with(
        tmp_path=tmp_path,
        feedback_queue=[_feedback(0.95)],
    )
    summary1 = await loop.run(intent, sim_folder=tmp_path / "sim1")
    summary2 = await loop.run(intent, sim_folder=tmp_path / "sim2")
    assert summary1["image_cache_hit"] is False
    assert summary2["image_cache_hit"] is True


@pytest.mark.asyncio
async def test_patches_applied_between_iterations(tmp_path: Path) -> None:
    intent = _intent()
    patches = [
        BuildPlanPatch(op="material_reassign", region="walls", material="stone"),
        BuildPlanPatch(op="level_height_adjust", level_index=0, delta_height=2),
    ]
    loop, _, _ = _loop_with(
        tmp_path=tmp_path,
        feedback_queue=[_feedback(0.4, patches=patches), _feedback(0.95)],
    )
    await loop.run(intent, sim_folder=tmp_path / "sim")
    base = tmp_path / "sim" / "new_buildings" / intent.intent_id
    plan_0 = json.loads((base / "decompositions" / "iter_0.buildplan.json").read_text())
    plan_1 = json.loads((base / "decompositions" / "iter_1.buildplan.json").read_text())
    wall_0 = next(m for m in plan_0["materials"] if m["region"] == "walls")
    wall_1 = next(m for m in plan_1["materials"] if m["region"] == "walls")
    assert wall_0["material"] == "oak_log"
    assert wall_1["material"] == "stone"
    height_0 = plan_0["levels"][0]["height_blocks"]
    height_1 = plan_1["levels"][0]["height_blocks"]
    assert height_1 == height_0 + 2
