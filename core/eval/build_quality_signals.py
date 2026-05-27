"""Build-quality signals for ``headless_scorer`` (issue #876).

The existing scorer categories are LLM-judged on conversation text and
don't distinguish "agents talked richly about building" from "agents
actually built something coherent". These six pure signals close that
gap by comparing the architectural :class:`BuildPlan` against the
compiled :class:`BuildScript` block placements:

1. :func:`wall_coverage_ratio`
2. :func:`opening_accessible_count`
3. :func:`interior_volume_realized`
4. :func:`material_variety_ratio`
5. :func:`skill_card_invocation_ratio`
6. :func:`vertical_placement_check`

Each helper takes a ``BuildPlan`` + ``BuildScript`` (and optionally
``terrain_top`` for the vertical check) and returns a small dict with
the headline number plus evidence counts. They are intentionally pure —
no I/O — so they can act as both (a) final-eval contributors and
(b) stop-conditions for ``RefinementLoop`` callers.

The :func:`score_build_quality` aggregator walks a sim folder's
``new_buildings/<intent_id>/final_summary.json`` files, loads the final
iteration's plan/script JSON, and folds the six signals into a single
scorer-shaped record.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.minecraft.build_executors import normalize_block
from core.minecraft.build_plan import BuildPlan, Opening
from core.minecraft.build_script import BuildCommand, BuildScript
from core.simulation.decision_log_schema import DecisionLogRow, WorldEventRow

logger = logging.getLogger(__name__)

_WALL_REGION_KEYS = ("walls", "wall", "exterior")


# ─── pure signal helpers ───────────────────────────────────────────


def _total_level_height(plan: BuildPlan) -> int:
    return sum(max(1, level.height_blocks) for level in plan.levels)


def _wall_materials(plan: BuildPlan) -> set[str]:
    out: set[str] = set()
    for assignment in plan.materials:
        if assignment.region.strip().lower() in _WALL_REGION_KEYS:
            out.add(normalize_block(assignment.material))
    return out


def _placement_commands(script: BuildScript) -> list[BuildCommand]:
    return [c for c in script.commands if c.kind in ("setblock", "fill")]


def wall_coverage_ratio(plan: BuildPlan, script: BuildScript) -> dict[str, Any]:
    """Placed wall blocks ÷ expected perimeter × height.

    Counts setblock/fill placements whose normalized block id matches a
    material declared for a wall region. Over-fill is clamped to ``1.0``
    so a builder can't game the signal by spamming wall blocks beyond
    the perimeter.
    """
    bbox = plan.footprint.bbox
    total_height = _total_level_height(plan)
    # Perimeter of a 1-block-thick rectangle (corners counted once):
    # 2*(w+h) - 4 for w,h >= 2; full area for degenerate strips.
    if bbox.w >= 2 and bbox.h >= 2:
        perimeter = 2 * (bbox.w + bbox.h) - 4
    else:
        perimeter = bbox.w * bbox.h
    expected = perimeter * total_height
    wall_blocks = _wall_materials(plan)
    if expected <= 0 or not wall_blocks:
        return {"value": 1.0, "placed": 0, "expected": expected, "wall_materials": []}

    placed = 0
    for cmd in _placement_commands(script):
        if normalize_block(cmd.block_type) in wall_blocks:
            placed += cmd.block_count()

    ratio = max(0.0, min(1.0, placed / expected))
    return {
        "value": ratio,
        "placed": placed,
        "expected": expected,
        "wall_materials": sorted(wall_blocks),
    }


def _build_occupancy_grid(
    script: BuildScript,
    bbox_min: tuple[int, int, int],
    bbox_max: tuple[int, int, int],
) -> set[tuple[int, int, int]]:
    """Return the set of cells occupied after replaying every placement.

    Commands are processed in order, so a later ``setblock minecraft:air``
    or ``fill ... air`` correctly *carves* cells out of the grid — that's
    how the executor would model door/window openings.
    """
    min_x, min_y, min_z = bbox_min
    max_x, max_y, max_z = bbox_max
    occupied: set[tuple[int, int, int]] = set()
    for cmd in _placement_commands(script):
        if cmd.kind == "setblock":
            cells: Iterable[tuple[int, int, int]] = [
                (cmd.position.x, cmd.position.y, cmd.position.z)
            ]
        else:  # fill
            if cmd.region_to is None:
                continue
            x0, x1 = sorted((cmd.position.x, cmd.region_to.x))
            y0, y1 = sorted((cmd.position.y, cmd.region_to.y))
            z0, z1 = sorted((cmd.position.z, cmd.region_to.z))
            cells = (
                (x, y, z)
                for x in range(x0, x1 + 1)
                for y in range(y0, y1 + 1)
                for z in range(z0, z1 + 1)
            )
        is_air = normalize_block(cmd.block_type) == "air"
        for cell in cells:
            x, y, z = cell
            if not (min_x <= x <= max_x and min_y <= y <= max_y and min_z <= z <= max_z):
                continue
            if is_air:
                occupied.discard(cell)
            else:
                occupied.add(cell)
    return occupied


def _plan_world_bbox(
    plan: BuildPlan, origin: tuple[int, int, int]
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """World-space ``(min, max)`` AABB for the build per ``BuildPlanCompiler``."""
    ox, oy, oz = origin
    bbox = plan.footprint.bbox
    total_height = _total_level_height(plan)
    # Compiler indexes z by bbox.y (footprint uses (x, y)=(x, z) tile-space).
    min_x = ox + bbox.x
    max_x = ox + bbox.x + bbox.w - 1
    min_z = oz + bbox.y
    max_z = oz + bbox.y + bbox.h - 1
    min_y = oy
    # Foundation row + per-level heights + roof row.
    max_y = oy + total_height + 1
    return (min_x, min_y, min_z), (max_x, max_y, max_z)


def opening_accessible_count(
    plan: BuildPlan,
    script: BuildScript,
) -> dict[str, Any]:
    """Number of declared openings reachable from outside via a 6-neighbour flood fill.

    Builds an occupancy grid covering the build's bbox plus a 1-block
    margin, then flood-fills air starting from the margin. An opening
    counts as accessible when its world-space cell is reachable from
    that margin — i.e., it isn't walled off.
    """
    origin = (script.origin.x, script.origin.y, script.origin.z)
    (min_x, min_y, min_z), (max_x, max_y, max_z) = _plan_world_bbox(plan, origin)
    # 1-block margin so the flood-fill has somewhere "outside" to start.
    min_x -= 1
    min_y -= 1
    min_z -= 1
    max_x += 1
    max_y += 1
    max_z += 1

    occupied = _build_occupancy_grid(script, (min_x, min_y, min_z), (max_x, max_y, max_z))

    # Flood-fill air from every cell on the margin surface.
    reachable: set[tuple[int, int, int]] = set()
    stack: list[tuple[int, int, int]] = []
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                on_margin = x in (min_x, max_x) or y in (min_y, max_y) or z in (min_z, max_z)
                if on_margin and (x, y, z) not in occupied:
                    if (x, y, z) not in reachable:
                        reachable.add((x, y, z))
                        stack.append((x, y, z))
    while stack:
        x, y, z = stack.pop()
        for dx, dy, dz in (
            (1, 0, 0),
            (-1, 0, 0),
            (0, 1, 0),
            (0, -1, 0),
            (0, 0, 1),
            (0, 0, -1),
        ):
            nx, ny, nz = x + dx, y + dy, z + dz
            if not (min_x <= nx <= max_x and min_y <= ny <= max_y and min_z <= nz <= max_z):
                continue
            if (nx, ny, nz) in occupied or (nx, ny, nz) in reachable:
                continue
            reachable.add((nx, ny, nz))
            stack.append((nx, ny, nz))

    openings = plan.openings or []
    accessible: list[Opening] = []
    for op in openings:
        wx = script.origin.x + op.position.x
        wy = script.origin.y + op.position.y
        wz = script.origin.z + op.position.z
        if (wx, wy, wz) in reachable:
            accessible.append(op)
    return {
        "value": len(accessible),
        "declared": len(openings),
        "accessible_positions": [
            {
                "x": script.origin.x + o.position.x,
                "y": script.origin.y + o.position.y,
                "z": script.origin.z + o.position.z,
                "kind": o.kind,
            }
            for o in accessible
        ],
    }


def interior_volume_realized(plan: BuildPlan, script: BuildScript) -> dict[str, Any]:
    """Air cells inside the bbox interior ÷ expected hollow volume.

    The "interior" is the bbox inset by one block on each horizontal side
    (and bounded vertically by the sum of level heights). A perfectly
    hollow build → ~1.0; a solid box → 0.
    """
    bbox = plan.footprint.bbox
    total_height = _total_level_height(plan)
    interior_w = max(0, bbox.w - 2)
    interior_h = max(0, bbox.h - 2)
    expected = interior_w * interior_h * total_height
    if expected <= 0:
        return {"value": 1.0, "air_cells": 0, "expected": 0}

    origin = (script.origin.x, script.origin.y, script.origin.z)
    (min_x, _world_min_y, min_z), (max_x, _world_max_y, max_z) = _plan_world_bbox(plan, origin)
    # Inset to interior; vertical range is foundation+1 up to foundation+total_height.
    int_min_x = min_x + 1
    int_max_x = max_x - 1
    int_min_z = min_z + 1
    int_max_z = max_z - 1
    int_min_y = script.origin.y + 1
    int_max_y = script.origin.y + total_height

    occupied = _build_occupancy_grid(
        script,
        (int_min_x, int_min_y, int_min_z),
        (int_max_x, int_max_y, int_max_z),
    )

    air_cells = 0
    for x in range(int_min_x, int_max_x + 1):
        for y in range(int_min_y, int_max_y + 1):
            for z in range(int_min_z, int_max_z + 1):
                if (x, y, z) not in occupied:
                    air_cells += 1
    ratio = max(0.0, min(1.0, air_cells / expected))
    return {"value": ratio, "air_cells": air_cells, "expected": expected}


def material_variety_ratio(plan: BuildPlan, script: BuildScript) -> dict[str, Any]:
    """Unique placed materials ÷ unique declared materials, clamped to ``[0, 1]``."""
    declared = {normalize_block(m.material) for m in plan.materials}
    placed = {normalize_block(c.block_type) for c in _placement_commands(script) if c.block_type}
    if not declared:
        return {"value": 1.0, "placed": sorted(placed), "declared": []}
    ratio = max(0.0, min(1.0, len(placed) / len(declared)))
    return {
        "value": ratio,
        "placed": sorted(placed),
        "declared": sorted(declared),
    }


def skill_card_invocation_ratio(plan: BuildPlan, script: BuildScript) -> dict[str, Any]:
    """``len(script.skill_cards_invoked) ÷ max(1, len(plan.key_features))``.

    Reported as a raw ratio (not clamped to 1) so the scorer can surface
    over-invocation as well — e.g. a recipe firing 4 columns for a plan
    that only declared 2 will show ``value=2.0``.
    """
    declared_features = len(plan.key_features)
    invocations = len(script.skill_cards_invoked)
    ratio = invocations / max(1, declared_features)
    return {
        "value": ratio,
        "invocations": invocations,
        "declared_features": declared_features,
        "cards": list(script.skill_cards_invoked),
    }


def vertical_placement_check(
    plan: BuildPlan,
    script: BuildScript,
    terrain_top: int | None = None,
) -> dict[str, Any]:
    """``True`` iff every placed block sits at-or-above the terrain surface.

    Defaults to ``script.origin.y - 1`` when no explicit terrain_top is
    provided, so a build that doesn't dig below its own foundation passes.
    Returns the boolean plus the observed min-y for debugging.
    """
    del plan  # signature is symmetric with the other signals
    threshold = terrain_top if terrain_top is not None else script.origin.y - 1
    ys = [c.position.y for c in _placement_commands(script)]
    for c in script.commands:
        if c.kind == "fill" and c.region_to is not None:
            ys.append(c.region_to.y)
    if not ys:
        return {"value": True, "min_y": None, "terrain_top": threshold}
    min_y = min(ys)
    return {
        "value": bool(min_y >= threshold),
        "min_y": min_y,
        "terrain_top": threshold,
    }


# ─── stop-condition helper for RefinementLoop callers ──────────────


def build_quality_threshold_met(
    plan: BuildPlan,
    script: BuildScript,
    *,
    interior_min: float = 0.9,
    openings_required: int | None = None,
) -> bool:
    """Return True when the build is "good enough" to stop iterating early.

    Used by ``RefinementLoop`` callers that want to short-circuit when
    structural signals already say the build matches the plan, even if
    the vision-comparison score hasn't crossed its own threshold yet.

    The default check: interior_volume_realized ≥ ``interior_min`` AND
    opening_accessible_count == declared openings (or
    ``openings_required`` when set explicitly).
    """
    interior = interior_volume_realized(plan, script)["value"]
    if interior < interior_min:
        return False
    accessible = opening_accessible_count(plan, script)["value"]
    target = openings_required if openings_required is not None else len(plan.openings)
    return bool(accessible >= target)


# ─── aggregator for headless_scorer ────────────────────────────────


def _final_iteration_paths(summary: dict[str, Any]) -> tuple[str, str] | None:
    iterations = summary.get("iterations") or []
    if not iterations:
        return None
    final = iterations[-1]
    plan_path = final.get("buildplan_path")
    script_path = final.get("script_path")
    if not plan_path or not script_path:
        return None
    return plan_path, script_path


def _load_plan_and_script(
    plan_path: Path, script_path: Path
) -> tuple[BuildPlan, BuildScript] | None:
    try:
        plan = BuildPlan.model_validate_json(plan_path.read_text())
        script = BuildScript.model_validate_json(script_path.read_text())
    except Exception as exc:
        logger.warning(
            "build_quality: could not load plan/script %s / %s: %s",
            plan_path,
            script_path,
            exc,
        )
        return None
    return plan, script


def _intent_ids_from_world_events(rows: list[DecisionLogRow]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, WorldEventRow):
            continue
        if r.payload.event_type != "new_building_iteration":
            continue
        intent_id = r.payload.details.get("intent_id")
        if isinstance(intent_id, str) and intent_id not in seen:
            seen.add(intent_id)
            out.append(intent_id)
    return out


def _resolve_path(raw: str, sim_folder: Path) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    # Relative paths are written by the loop with ``.as_posix()`` from a
    # ``sim_folder``-relative ``Path``; try both as-is and sim-rooted.
    candidate = sim_folder / p
    return candidate if candidate.exists() else p


def score_build_quality(
    rows: list[DecisionLogRow],
    *,
    sim_folder: Path | None = None,
) -> dict[str, Any]:
    """Aggregate build-quality signals across a sim's completed buildings.

    The scorer dispatches this with ``sim_folder=<sim path>``. We walk
    every ``new_buildings/<intent_id>/final_summary.json`` produced by
    :class:`core.minecraft.build_refinement_loop.RefinementLoop`, load
    each final iteration's ``BuildPlan`` + ``BuildScript`` JSON, run the
    six signals, and fold the per-build numbers into a single category
    record. If the sim folder is missing or contains no completed
    buildings we return a low-confidence neutral score so the scorer
    doesn't crash.
    """
    if sim_folder is None:
        return _neutral_result(reason="sim_folder not provided to build_quality scorer")
    new_buildings_dir = sim_folder / "new_buildings"
    if not new_buildings_dir.is_dir():
        return _neutral_result(reason="no new_buildings/ directory")

    intent_ids_hint = _intent_ids_from_world_events(rows)

    per_build: list[dict[str, Any]] = []
    for intent_dir in sorted(p for p in new_buildings_dir.iterdir() if p.is_dir()):
        if intent_ids_hint and intent_dir.name not in intent_ids_hint:
            # The sim may contain orphan folders from prior runs; skip
            # anything not referenced by this run's decision log.
            continue
        summary_path = intent_dir / "final_summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("build_quality: cannot read %s: %s", summary_path, exc)
            continue
        paths = _final_iteration_paths(summary)
        if paths is None:
            continue
        plan_path = _resolve_path(paths[0], sim_folder)
        script_path = _resolve_path(paths[1], sim_folder)
        loaded = _load_plan_and_script(plan_path, script_path)
        if loaded is None:
            continue
        plan, script = loaded
        per_build.append(
            {
                "intent_id": intent_dir.name,
                **_signals_for_build(plan, script),
            }
        )

    if not per_build:
        return _neutral_result(reason="no completed builds with plan+script artifacts")

    return _aggregate_per_build(per_build)


def _signals_for_build(plan: BuildPlan, script: BuildScript) -> dict[str, Any]:
    return {
        "wall_coverage_ratio": wall_coverage_ratio(plan, script),
        "opening_accessible_count": opening_accessible_count(plan, script),
        "interior_volume_realized": interior_volume_realized(plan, script),
        "material_variety_ratio": material_variety_ratio(plan, script),
        "skill_card_invocation_ratio": skill_card_invocation_ratio(plan, script),
        "vertical_placement_check": vertical_placement_check(plan, script),
        "declared_openings": len(plan.openings),
    }


def _aggregate_per_build(per_build: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold per-build signals into the scorer's category shape."""
    n = len(per_build)

    def _mean(key: str) -> float:
        return sum(b[key]["value"] for b in per_build) / n

    wall_avg = _mean("wall_coverage_ratio")
    interior_avg = _mean("interior_volume_realized")
    variety_avg = _mean("material_variety_ratio")

    skill_avg = min(1.0, _mean("skill_card_invocation_ratio"))

    accessibility_ratios: list[float] = []
    for b in per_build:
        declared = b["declared_openings"]
        accessible = b["opening_accessible_count"]["value"]
        if declared <= 0:
            accessibility_ratios.append(1.0)
        else:
            accessibility_ratios.append(min(1.0, accessible / declared))
    accessibility_avg = sum(accessibility_ratios) / n

    vertical_ok = all(b["vertical_placement_check"]["value"] for b in per_build)

    components = [wall_avg, interior_avg, variety_avg, accessibility_avg, skill_avg]
    aggregate = sum(components) / len(components)
    score = max(0.0, min(100.0, aggregate * 100.0))
    if not vertical_ok:
        score = 0.0

    return {
        "score": score,
        "reasoning": (
            f"{n} build(s): wall={wall_avg:.2f} interior={interior_avg:.2f} "
            f"variety={variety_avg:.2f} access={accessibility_avg:.2f} "
            f"skill={skill_avg:.2f} vertical_ok={vertical_ok}"
        ),
        "evidence": per_build,
        "sub_scores": {
            "wall_coverage_ratio": wall_avg,
            "interior_volume_realized": interior_avg,
            "material_variety_ratio": variety_avg,
            "opening_accessibility_ratio": accessibility_avg,
            "skill_card_invocation_ratio_clamped": skill_avg,
            "vertical_placement_ok": float(vertical_ok),
            "build_count": float(n),
        },
        "confidence": 0.85,
    }


def _neutral_result(*, reason: str) -> dict[str, Any]:
    return {
        "score": 0.0,
        "reasoning": reason,
        "evidence": [],
        "sub_scores": {},
        "confidence": 0.3,
    }


__all__ = [
    "build_quality_threshold_met",
    "interior_volume_realized",
    "material_variety_ratio",
    "opening_accessible_count",
    "score_build_quality",
    "skill_card_invocation_ratio",
    "vertical_placement_check",
    "wall_coverage_ratio",
]
