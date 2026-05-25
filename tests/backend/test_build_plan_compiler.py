"""Tests for the ``BuildPlan`` → ``BuildScript`` macro compiler (issue #857)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from core.agents.build_intent import BuildIntent, SizeClass, StructureType
from core.minecraft.build_plan import (
    BoundingBox,
    BuildPlan,
    Footprint,
    KeyFeature,
    Level,
    MaterialAssignment,
    Opening,
    Position3D,
    Room,
)
from core.minecraft.build_plan_compiler import DEFAULT_ORIGIN, BuildPlanCompiler
from core.minecraft.build_script import (
    COMPILER_VERSION,
    BuildCommand,
    BuildScript,
    BuildScriptManifest,
)
from core.minecraft.skill_cards.architectural import (
    ARCHITECTURAL_CARDS,
    arch_round,
    column_doric,
    door_frame,
    foundation_lay,
    get_card,
    roof_pitched,
    wall_segment,
)

# ─── Fixtures ────────────────────────────────────────────────────


def _intent(structure: str = "cabin") -> BuildIntent:
    return BuildIntent(
        proposer_id="vera",
        structure_type=structure,
        size_class="medium",
        location_intent="open_area",
        motivation="testing the compiler",
    )


def _cabin_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="cabin",
        size_class="medium",
        source_image_id="cabin:image.png",
        footprint=Footprint(
            shape="rectangle", bbox=BoundingBox(x=0, y=0, w=6, h=5)
        ),
        levels=[Level(index=0, height_blocks=3, floor_material="oak_planks")],
        materials=[
            MaterialAssignment(region="floor", material="oak_planks"),
            MaterialAssignment(region="walls", material="oak_log"),
            MaterialAssignment(region="roof", material="dark_oak_planks"),
            MaterialAssignment(region="frame", material="oak_log"),
        ],
        openings=[Opening(kind="door", position=Position3D(x=3, y=0, z=0), level_index=0)],
        decomposer_version=1,
        provider_model_id="fake/test",
    )


def _watchtower_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="watchtower",
        size_class="medium",
        source_image_id="watchtower:image.png",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=4, h=4)),
        levels=[
            Level(index=0, height_blocks=3, floor_material="stone_bricks"),
            Level(index=1, height_blocks=3, floor_material="stone_bricks"),
            Level(index=2, height_blocks=3, floor_material="stone_bricks"),
        ],
        materials=[
            MaterialAssignment(region="floor", material="stone_bricks"),
            MaterialAssignment(region="walls", material="cobblestone"),
            MaterialAssignment(region="roof", material="dark_oak_planks"),
        ],
        decomposer_version=1,
        provider_model_id="fake/test",
    )


def _farm_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="farm",
        size_class="medium",
        source_image_id="farm:image.png",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=8, h=6)),
        levels=[Level(index=0, height_blocks=1, floor_material="farmland")],
        materials=[
            MaterialAssignment(region="field", material="farmland"),
            MaterialAssignment(region="fence", material="oak_fence"),
        ],
        decomposer_version=1,
        provider_model_id="fake/test",
    )


def _wall_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="wall",
        size_class="large",
        source_image_id="wall:image.png",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=12, h=8)),
        levels=[Level(index=0, height_blocks=5, floor_material="stone")],
        materials=[MaterialAssignment(region="walls", material="stone_bricks")],
        decomposer_version=1,
        provider_model_id="fake/test",
    )


def _coliseum_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="coliseum",
        size_class="epic",
        source_image_id="coliseum:image.png",
        footprint=Footprint(shape="oval", bbox=BoundingBox(x=0, y=0, w=24, h=20)),
        levels=[Level(index=0, height_blocks=8, floor_material="sand")],
        rooms=[
            Room(name="gladiator", level_index=0, relative_bbox=BoundingBox(x=2, y=2, w=4, h=3)),
            Room(name="entry", level_index=0, relative_bbox=BoundingBox(x=18, y=2, w=4, h=3)),
        ],
        materials=[
            MaterialAssignment(region="floor", material="sand"),
            MaterialAssignment(region="walls", material="stone_bricks"),
            MaterialAssignment(region="columns", material="quartz_pillar"),
        ],
        key_features=[
            KeyFeature(kind="column", position=Position3D(x=2, y=0, z=2), size={"height": 6}),
            KeyFeature(kind="column", position=Position3D(x=20, y=0, z=2), size={"height": 6}),
            KeyFeature(
                kind="arch", position=Position3D(x=10, y=0, z=0), size={"span": 4, "height": 4}
            ),
        ],
        decomposer_version=1,
        provider_model_id="fake/test",
    )


def _market_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="market",
        size_class="large",
        source_image_id="market:image.png",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=14, h=14)),
        levels=[Level(index=0, height_blocks=3, floor_material="stone_bricks")],
        rooms=[
            Room(name="stall_n", level_index=0, relative_bbox=BoundingBox(x=2, y=0, w=3, h=2)),
            Room(name="stall_s", level_index=0, relative_bbox=BoundingBox(x=9, y=12, w=3, h=2)),
            Room(name="stall_e", level_index=0, relative_bbox=BoundingBox(x=12, y=6, w=2, h=3)),
        ],
        materials=[
            MaterialAssignment(region="plaza", material="stone_bricks"),
            MaterialAssignment(region="stall", material="oak_planks"),
            MaterialAssignment(region="walls", material="oak_planks"),
        ],
        decomposer_version=1,
        provider_model_id="fake/test",
    )


_REFERENCE_PLANS = {
    "cabin": _cabin_plan,
    "farm": _farm_plan,
    "wall": _wall_plan,
    "watchtower": _watchtower_plan,
    "coliseum": _coliseum_plan,
    "market": _market_plan,
}


# ─── Per-card unit tests ────────────────────────────────────────


def test_foundation_lay_emits_single_fill() -> None:
    commands = foundation_lay(
        bbox=BoundingBox(x=0, y=0, w=4, h=3),
        origin=Position3D(x=0, y=64, z=0),
        floor_y=64,
        material="oak_planks",
    )
    assert len(commands) == 1
    cmd = commands[0]
    assert cmd.kind == "fill"
    assert cmd.block_type == "oak_planks"
    assert cmd.block_count() == 4 * 3


def test_wall_segment_emits_four_sides() -> None:
    commands = wall_segment(
        bbox=BoundingBox(x=0, y=0, w=5, h=4),
        origin=Position3D(x=0, y=64, z=0),
        base_y=65,
        height=3,
        material="oak_log",
    )
    assert len(commands) == 4
    assert all(cmd.kind == "fill" for cmd in commands)
    assert all(cmd.block_type == "oak_log" for cmd in commands)


def test_roof_pitched_shrinks_to_a_ridge() -> None:
    commands = roof_pitched(
        bbox=BoundingBox(x=0, y=0, w=6, h=5),
        origin=Position3D(x=0, y=64, z=0),
        base_y=70,
        material="dark_oak_planks",
    )
    assert commands, "expected at least one roof layer"
    ys = [cmd.position.y for cmd in commands]
    assert ys == sorted(ys), "roof layers must be emitted bottom-up"


def test_door_frame_door_carves_two_cells_plus_lintel() -> None:
    commands = door_frame(
        position=Position3D(x=4, y=64, z=0),
        kind="door",
        frame_material="oak_log",
    )
    kinds = [(cmd.kind, cmd.block_type) for cmd in commands]
    assert kinds == [
        ("setblock", "air"),
        ("setblock", "air"),
        ("setblock", "oak_log"),
    ]


def test_door_frame_window_emits_ring_of_frame() -> None:
    commands = door_frame(
        position=Position3D(x=4, y=64, z=0),
        kind="window",
        frame_material="oak_log",
    )
    assert commands[0].block_type == "air"
    assert sum(1 for cmd in commands if cmd.block_type == "oak_log") == 4


def test_column_doric_emits_shaft_and_capital() -> None:
    commands = column_doric(
        position=Position3D(x=0, y=64, z=0),
        height=5,
        material="quartz_pillar",
        capital_material="quartz_block",
    )
    assert commands[0].kind == "fill"
    assert commands[0].block_count() == 5
    assert commands[-1].kind == "setblock"
    assert commands[-1].block_type == "quartz_block"


def test_arch_round_includes_pillars_and_voussoirs() -> None:
    commands = arch_round(
        position=Position3D(x=0, y=64, z=0),
        span=5,
        height=4,
        material="stone_bricks",
    )
    fills = [cmd for cmd in commands if cmd.kind == "fill"]
    voussoirs = [cmd for cmd in commands if cmd.kind == "setblock"]
    assert fills, "arch must include pillar fills"
    assert voussoirs, "arch must include curved voussoir blocks"


def test_architectural_card_registry_exposes_six_cards() -> None:
    assert set(ARCHITECTURAL_CARDS) == {
        "arch_round",
        "column_doric",
        "door_frame",
        "foundation_lay",
        "roof_pitched",
        "wall_segment",
    }
    assert get_card("foundation_lay") is foundation_lay
    with pytest.raises(KeyError):
        get_card("unknown_card")


# ─── Compiler-level tests ───────────────────────────────────────


def test_compile_cabin_returns_buildscript_with_expected_fields() -> None:
    compiler = BuildPlanCompiler()
    intent = _intent("cabin")
    script = compiler.compile(_cabin_plan(), intent=intent)
    assert isinstance(script, BuildScript)
    assert script.intent_id == intent.intent_id
    assert script.structure_type == StructureType.cabin
    assert script.size_class == SizeClass.medium
    assert script.origin == DEFAULT_ORIGIN
    assert script.commands, "cabin must compile to at least one command"
    assert script.total_blocks > 0
    assert script.estimated_seconds > 0.0
    assert script.compiler_version == COMPILER_VERSION
    assert script.materials_manifest, "manifest must be non-empty"


@pytest.mark.parametrize("structure_name", sorted(_REFERENCE_PLANS))
def test_dry_run_returns_manifest_for_each_reference(structure_name: str) -> None:
    compiler = BuildPlanCompiler()
    plan = _REFERENCE_PLANS[structure_name]()
    manifest = compiler.dry_run(plan, intent=_intent(structure_name))
    assert isinstance(manifest, BuildScriptManifest)
    assert manifest.total_blocks > 0
    assert manifest.materials_manifest
    expected_total = sum(manifest.materials_manifest.values())
    assert manifest.total_blocks == expected_total
    assert manifest.estimated_seconds > 0.0


@pytest.mark.parametrize("structure_name", sorted(_REFERENCE_PLANS))
def test_each_reference_structure_compiles_without_error(structure_name: str) -> None:
    compiler = BuildPlanCompiler()
    plan = _REFERENCE_PLANS[structure_name]()
    script = compiler.compile(plan, intent=_intent(structure_name))
    assert script.commands, f"{structure_name} must emit commands"
    assert all(isinstance(cmd, BuildCommand) for cmd in script.commands)


def test_multi_room_coliseum_compiles_with_columns_and_arch() -> None:
    compiler = BuildPlanCompiler()
    script = compiler.compile(_coliseum_plan(), intent=_intent("coliseum"))
    # Coliseum should hit the column and arch primitives.
    assert script.total_blocks > 100
    # Columns place quartz_pillar; arches reuse the wall material.
    assert "quartz_pillar" in script.materials_manifest
    assert "stone_bricks" in script.materials_manifest


def test_compile_requires_intent_or_intent_id() -> None:
    compiler = BuildPlanCompiler()
    with pytest.raises(ValueError):
        compiler.compile(_cabin_plan())


def test_compile_is_byte_identical_for_same_inputs() -> None:
    compiler = BuildPlanCompiler()
    intent = _intent("cabin")
    a = compiler.compile(_cabin_plan(), intent=intent)
    b = compiler.compile(_cabin_plan(), intent=intent)
    assert json.dumps(a.to_jsonable(), sort_keys=True) == json.dumps(
        b.to_jsonable(), sort_keys=True
    )
    assert a.source_plan_hash == b.source_plan_hash


def test_property_compile_determinism_across_random_plans() -> None:
    """Compiling 100 random plans twice must produce byte-identical scripts."""
    rng = random.Random(20260525)
    compiler = BuildPlanCompiler()
    for _ in range(100):
        plan = _random_plan(rng)
        intent = _intent(plan.structure_type)
        first = compiler.compile(plan, intent=intent)
        second = compiler.compile(plan, intent=intent)
        assert json.dumps(first.to_jsonable(), sort_keys=True) == json.dumps(
            second.to_jsonable(), sort_keys=True
        )


def test_buildscript_roundtrips_through_pydantic_json() -> None:
    compiler = BuildPlanCompiler()
    script = compiler.compile(_cabin_plan(), intent=_intent("cabin"))
    raw = script.model_dump_json()
    rebuilt = BuildScript.model_validate(json.loads(raw))
    assert rebuilt.model_dump() == script.model_dump()


def test_to_jsonable_is_sort_key_stable() -> None:
    compiler = BuildPlanCompiler()
    script = compiler.compile(_cabin_plan(), intent=_intent("cabin"))
    payload = script.to_jsonable()
    serialized = json.dumps(payload, sort_keys=True)
    # Sorting again must not move any keys.
    again = json.dumps(payload, sort_keys=True)
    assert serialized == again
    assert json.loads(serialized) == payload


def test_materials_manifest_matches_total_blocks() -> None:
    compiler = BuildPlanCompiler()
    for name, factory in _REFERENCE_PLANS.items():
        script = compiler.compile(factory(), intent=_intent(name))
        assert script.total_blocks == sum(script.materials_manifest.values()), name


# ─── Embodiment wiring ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_headless_executor_writes_build_script_when_resolver_attached(
    tmp_path: Path,
) -> None:
    from core.simulation.embodiment import HeadlessExecutor, ToolIntent

    compiler = BuildPlanCompiler()
    plan = _cabin_plan()

    def resolver(args: dict[str, Any]) -> BuildPlan | None:
        return plan

    executor = HeadlessExecutor(
        build_plan_compiler=compiler, build_plan_resolver=resolver
    )
    await executor.setup(simulation_id="sim-1", sim_folder=tmp_path)

    intent = _intent("cabin")
    tool_intent = ToolIntent(
        tool_name="propose_build",
        actor_id="vera",
        args=intent.to_log_payload(),
        intent_id=intent.intent_id,
    )
    await executor.execute_tool_intent(tool_intent)

    target = tmp_path / "build_scripts" / f"{intent.intent_id}.script.json"
    assert target.is_file()
    payload = json.loads(target.read_text())
    assert payload["intent_id"] == intent.intent_id
    assert payload["structure_type"] == "cabin"
    assert payload["total_blocks"] > 0


@pytest.mark.asyncio
async def test_headless_executor_skips_script_when_resolver_missing(
    tmp_path: Path,
) -> None:
    from core.simulation.embodiment import HeadlessExecutor, ToolIntent

    executor = HeadlessExecutor()  # no compiler / resolver
    await executor.setup(simulation_id="sim-2", sim_folder=tmp_path)

    intent = _intent("cabin")
    await executor.execute_tool_intent(
        ToolIntent(
            tool_name="propose_build",
            actor_id="vera",
            args=intent.to_log_payload(),
            intent_id=intent.intent_id,
        )
    )

    assert not (tmp_path / "build_scripts").exists()


# ─── Helpers ────────────────────────────────────────────────────


_RANDOM_STRUCTURES = ("cabin", "farm", "wall", "watchtower", "coliseum", "market")
_RANDOM_MATERIALS = (
    ("floor", "oak_planks"),
    ("walls", "oak_log"),
    ("roof", "dark_oak_planks"),
    ("frame", "stone_bricks"),
    ("columns", "quartz_pillar"),
    ("field", "farmland"),
    ("fence", "oak_fence"),
    ("plaza", "stone_bricks"),
    ("stall", "oak_planks"),
)


def _random_plan(rng: random.Random) -> BuildPlan:
    structure = rng.choice(_RANDOM_STRUCTURES)
    width = rng.randint(4, 16)
    depth = rng.randint(4, 16)
    levels = [
        Level(
            index=idx,
            height_blocks=rng.randint(2, 4),
            floor_material=rng.choice(["oak_planks", "stone_bricks", "cobblestone"]),
        )
        for idx in range(rng.randint(1, 3))
    ]
    rooms: list[Room] = []
    if rng.random() < 0.5 and width > 6 and depth > 6:
        for i, name in enumerate(["a", "b", "c"][: rng.randint(1, 3)]):
            rooms.append(
                Room(
                    name=name,
                    level_index=0,
                    relative_bbox=BoundingBox(
                        x=1 + i, y=1 + i, w=max(2, width // 4), h=max(2, depth // 4)
                    ),
                )
            )
    materials = [MaterialAssignment(region=r, material=m) for r, m in _RANDOM_MATERIALS]
    key_features: list[KeyFeature] = []
    if rng.random() < 0.5:
        key_features.append(
            KeyFeature(
                kind="column",
                position=Position3D(x=rng.randint(0, width - 1), y=0, z=rng.randint(0, depth - 1)),
                size={"height": rng.randint(2, 6)},
            )
        )
    if rng.random() < 0.3:
        key_features.append(
            KeyFeature(
                kind="arch",
                position=Position3D(x=0, y=0, z=0),
                size={"span": rng.randint(2, 6), "height": rng.randint(2, 5)},
            )
        )
    return BuildPlan(
        structure_type=structure,
        size_class=rng.choice(["small", "medium", "large", "epic"]),
        source_image_id=f"{structure}:rand",
        footprint=Footprint(
            shape="rectangle", bbox=BoundingBox(x=0, y=0, w=width, h=depth)
        ),
        levels=levels,
        rooms=rooms,
        materials=materials,
        key_features=key_features,
        decomposer_version=1,
        provider_model_id="fake/test",
    )
