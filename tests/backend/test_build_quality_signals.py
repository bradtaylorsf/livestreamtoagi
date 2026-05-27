"""Tests for ``core.eval.build_quality_signals`` (issue #876).

Three scenarios cover the acceptance matrix:

* **Perfect cabin** — hollow 6×6 walls + carved door → every signal near
  1.0, vertical_placement_check True.
* **Solid box** — single fill spanning the bbox interior → interior
  volume realized → 0, opening_accessible_count → 0.
* **Floating build** — every command well above the terrain threshold →
  vertical_placement_check False.

Plus small unit tests for material_variety_ratio bounds and
skill_card_invocation_ratio's safe denominator.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.agents.build_intent import SizeClass, StructureType
from core.eval.build_quality_signals import (
    build_quality_threshold_met,
    interior_volume_realized,
    material_variety_ratio,
    opening_accessible_count,
    score_build_quality,
    skill_card_invocation_ratio,
    vertical_placement_check,
    wall_coverage_ratio,
)
from core.minecraft.build_plan import (
    BoundingBox,
    BuildPlan,
    Footprint,
    KeyFeature,
    Level,
    MaterialAssignment,
    Opening,
    Position3D,
)
from core.minecraft.build_script import BuildCommand, BuildScript

# ─── Fixture helpers ──────────────────────────────────────────────


def _cabin_plan(
    *,
    width: int = 6,
    depth: int = 6,
    height: int = 4,
    openings: tuple[Opening, ...] = (),
    materials: tuple[MaterialAssignment, ...] = (
        MaterialAssignment(region="walls", material="oak_log"),
        MaterialAssignment(region="roof", material="spruce_planks"),
        MaterialAssignment(region="floor", material="cobblestone"),
    ),
    key_features: tuple[KeyFeature, ...] = (),
) -> BuildPlan:
    return BuildPlan(
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        source_image_id="test:source",
        footprint=Footprint(
            shape="rectangle",
            bbox=BoundingBox(x=0, y=0, w=width, h=depth),
        ),
        levels=[Level(index=0, height_blocks=height, floor_material="cobblestone")],
        materials=list(materials),
        key_features=list(key_features),
        openings=list(openings),
        decomposer_version=1,
        provider_model_id="test/decomposer",
    )


def _make_script(
    commands: list[BuildCommand],
    *,
    origin: Position3D | None = None,
    skill_cards: list[str] | None = None,
) -> BuildScript:
    return BuildScript(
        intent_id="test-intent",
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        origin=origin or Position3D(x=0, y=64, z=0),
        commands=commands,
        materials_manifest={},
        total_blocks=sum(c.block_count() for c in commands),
        estimated_seconds=0.0,
        source_plan_hash="hash",
        compiler_version=1,
        skill_cards_invoked=skill_cards or [],
    )


def _perfect_cabin_commands(
    *,
    origin: Position3D,
    width: int = 6,
    depth: int = 6,
    height: int = 4,
    door_at: tuple[int, int, int] | None = None,
) -> list[BuildCommand]:
    """Build a hollow cabin: foundation, four walls, roof, optional carved door."""
    ox, oy, oz = origin.x, origin.y, origin.z
    cmds: list[BuildCommand] = []
    # Foundation slab.
    cmds.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=ox, y=oy, z=oz),
            region_to=Position3D(x=ox + width - 1, y=oy, z=oz + depth - 1),
            block_type="cobblestone",
        )
    )
    # Four wall faces (height blocks tall, one block thick).
    wall_top_y = oy + height
    # +z face
    cmds.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=ox, y=oy + 1, z=oz),
            region_to=Position3D(x=ox + width - 1, y=wall_top_y, z=oz),
            block_type="oak_log",
        )
    )
    # -z face
    cmds.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=ox, y=oy + 1, z=oz + depth - 1),
            region_to=Position3D(x=ox + width - 1, y=wall_top_y, z=oz + depth - 1),
            block_type="oak_log",
        )
    )
    # +x face (excluding corners already placed)
    cmds.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=ox, y=oy + 1, z=oz + 1),
            region_to=Position3D(x=ox, y=wall_top_y, z=oz + depth - 2),
            block_type="oak_log",
        )
    )
    # -x face
    cmds.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=ox + width - 1, y=oy + 1, z=oz + 1),
            region_to=Position3D(x=ox + width - 1, y=wall_top_y, z=oz + depth - 2),
            block_type="oak_log",
        )
    )
    # Roof.
    cmds.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=ox, y=wall_top_y + 1, z=oz),
            region_to=Position3D(x=ox + width - 1, y=wall_top_y + 1, z=oz + depth - 1),
            block_type="spruce_planks",
        )
    )
    # Carve out a door (single block of air → represented by skipping the
    # placement; the executor would normally /setblock minecraft:air).
    if door_at is not None:
        cmds.append(
            BuildCommand(
                kind="setblock",
                position=Position3D(x=door_at[0], y=door_at[1], z=door_at[2]),
                block_type="air",
            )
        )
    return cmds


# ─── Scenario A: perfect cabin ────────────────────────────────────


def test_perfect_cabin_signals_are_near_one() -> None:
    origin = Position3D(x=10, y=64, z=10)
    # Door is on the +z wall, ground level, at x=12 (interior of the 6×6 bbox).
    door = (12, 65, 10)
    plan = _cabin_plan(
        openings=(
            Opening(kind="door", level_index=0, position=Position3D(x=2, y=1, z=0)),
        ),
        key_features=(
            KeyFeature(kind="roof", position=Position3D(x=3, y=5, z=3)),
        ),
    )
    script = _make_script(
        _perfect_cabin_commands(origin=origin, door_at=door),
        origin=origin,
        skill_cards=["roof_pitched"],
    )

    wall = wall_coverage_ratio(plan, script)
    # Walls: 4 faces × 6 wide × 4 tall = 96; expected = 2*(6+6)*4 = 96.
    assert wall["value"] >= 0.95

    interior = interior_volume_realized(plan, script)
    # interior = (6-2)*(6-2)*4 = 64 air cells inside.
    assert interior["value"] >= 0.9

    accessible = opening_accessible_count(plan, script)
    assert accessible["value"] == 1
    assert accessible["declared"] == 1

    variety = material_variety_ratio(plan, script)
    # Declared: oak_log, spruce_planks, cobblestone = 3.
    # Placed: cobblestone, oak_log, spruce_planks, air = 4 → clamped to 1.0.
    assert variety["value"] == 1.0

    skill = skill_card_invocation_ratio(plan, script)
    assert skill["value"] == 1.0
    assert skill["invocations"] == 1
    assert skill["declared_features"] == 1

    vertical = vertical_placement_check(plan, script)
    assert vertical["value"] is True


# ─── Scenario B: solid box (no interior, no openings) ─────────────


def test_solid_box_collapses_interior_and_openings() -> None:
    origin = Position3D(x=0, y=64, z=0)
    plan = _cabin_plan(
        openings=(
            Opening(kind="door", level_index=0, position=Position3D(x=2, y=1, z=0)),
        ),
    )
    # A single fill spanning the entire bbox interior + the perimeter.
    commands = [
        BuildCommand(
            kind="fill",
            position=Position3D(x=0, y=64, z=0),
            region_to=Position3D(x=5, y=68, z=5),
            block_type="oak_log",
        )
    ]
    script = _make_script(commands, origin=origin)

    interior = interior_volume_realized(plan, script)
    assert interior["value"] == 0.0

    accessible = opening_accessible_count(plan, script)
    assert accessible["value"] == 0
    assert accessible["declared"] == 1


# ─── Scenario C: floating build ───────────────────────────────────


def test_floating_build_fails_vertical_check() -> None:
    """A build placed well above the terrain_top must trip the vertical check."""
    origin = Position3D(x=0, y=64, z=0)
    plan = _cabin_plan()
    # All commands are 50 blocks above the script origin.
    commands = [
        BuildCommand(
            kind="setblock",
            position=Position3D(x=1, y=114, z=1),
            block_type="oak_log",
        ),
        BuildCommand(
            kind="setblock",
            position=Position3D(x=2, y=114, z=2),
            block_type="oak_log",
        ),
    ]
    script = _make_script(commands, origin=origin)

    # With an explicit terrain_top above the build, the check fails.
    result = vertical_placement_check(plan, script, terrain_top=200)
    assert result["value"] is False
    assert result["min_y"] == 114
    assert result["terrain_top"] == 200


def test_buried_build_fails_vertical_check_with_default_threshold() -> None:
    """Without a terrain_top, blocks below ``origin.y - 1`` still fail."""
    origin = Position3D(x=0, y=64, z=0)
    plan = _cabin_plan()
    commands = [
        BuildCommand(
            kind="setblock",
            position=Position3D(x=0, y=30, z=0),
            block_type="oak_log",
        )
    ]
    script = _make_script(commands, origin=origin)
    result = vertical_placement_check(plan, script)
    assert result["value"] is False
    assert result["min_y"] == 30


# ─── Edge cases on individual helpers ─────────────────────────────


def test_material_variety_ratio_caps_at_one_when_more_placed_than_declared() -> None:
    plan = _cabin_plan(
        materials=(MaterialAssignment(region="walls", material="oak_log"),),
    )
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="oak_log",
            ),
            BuildCommand(
                kind="setblock",
                position=Position3D(x=1, y=64, z=0),
                block_type="cobblestone",
            ),
            BuildCommand(
                kind="setblock",
                position=Position3D(x=2, y=64, z=0),
                block_type="spruce_planks",
            ),
        ]
    )
    assert material_variety_ratio(plan, script)["value"] == 1.0


def test_material_variety_ratio_under_declared() -> None:
    plan = _cabin_plan(
        materials=(
            MaterialAssignment(region="walls", material="oak_log"),
            MaterialAssignment(region="roof", material="spruce_planks"),
            MaterialAssignment(region="floor", material="cobblestone"),
        ),
    )
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="oak_log",
            )
        ]
    )
    result = material_variety_ratio(plan, script)
    assert result["value"] == 1 / 3


def test_skill_card_ratio_safe_denominator_when_no_features() -> None:
    plan = _cabin_plan()
    assert not plan.key_features  # sanity
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="oak_log",
            )
        ],
        skill_cards=["wall_segment", "wall_segment"],
    )
    # Denominator clamps to 1 → ratio = 2 / 1 = 2.
    result = skill_card_invocation_ratio(plan, script)
    assert result["value"] == 2.0
    assert result["declared_features"] == 0


def test_build_quality_threshold_helper() -> None:
    origin = Position3D(x=0, y=64, z=0)
    plan = _cabin_plan(
        openings=(
            Opening(kind="door", level_index=0, position=Position3D(x=2, y=1, z=0)),
        ),
    )
    door_world = (2, 65, 0)
    script = _make_script(
        _perfect_cabin_commands(origin=origin, door_at=door_world),
        origin=origin,
    )
    assert build_quality_threshold_met(plan, script) is True


# ─── Aggregator: sim folder integration ───────────────────────────


def test_score_build_quality_aggregates_from_sim_folder(tmp_path: Path) -> None:
    sim_folder = tmp_path
    origin = Position3D(x=0, y=64, z=0)
    plan = _cabin_plan(
        openings=(
            Opening(kind="door", level_index=0, position=Position3D(x=2, y=1, z=0)),
        ),
    )
    door_world = (2, 65, 0)
    script = _make_script(
        _perfect_cabin_commands(origin=origin, door_at=door_world),
        origin=origin,
    )

    intent_id = "intent-perfect"
    intent_dir = sim_folder / "new_buildings" / intent_id
    decompositions = intent_dir / "decompositions"
    scripts_dir = intent_dir / "scripts"
    decompositions.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    plan_path = decompositions / "iter_0.buildplan.json"
    script_path = scripts_dir / "iter_0.script.json"
    plan_path.write_text(plan.model_dump_json())
    script_path.write_text(json.dumps(script.to_jsonable()))

    summary = {
        "intent": {"intent_id": intent_id},
        "iterations": [
            {
                "iteration": 0,
                "match_score": 0.9,
                "cumulative_cost_usd": "0",
                "feature_deltas": [],
                "feedback_path": str(intent_dir / "feedback" / "iter_0.json"),
                "screenshot_path": str(intent_dir / "screenshots" / "iter_0.png"),
                "script_path": script_path.as_posix(),
                "buildplan_path": plan_path.as_posix(),
            }
        ],
    }
    (intent_dir / "final_summary.json").write_text(json.dumps(summary))

    result = score_build_quality([], sim_folder=sim_folder)
    assert result["score"] > 0
    assert result["sub_scores"]["build_count"] == 1.0
    assert result["sub_scores"]["interior_volume_realized"] >= 0.9
    # vertical_ok must remain True for the perfect cabin.
    assert result["sub_scores"]["vertical_placement_ok"] == 1.0


def test_score_build_quality_handles_missing_sim_folder() -> None:
    result = score_build_quality([], sim_folder=None)
    assert result["score"] == 0.0
    assert result["confidence"] == 0.3


def test_score_build_quality_handles_empty_new_buildings(tmp_path: Path) -> None:
    result = score_build_quality([], sim_folder=tmp_path)
    assert result["score"] == 0.0
    assert "no new_buildings/" in result["reasoning"]
