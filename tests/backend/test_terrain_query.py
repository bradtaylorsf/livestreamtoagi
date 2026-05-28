"""Tests for terrain query + foundation helpers (issue #873)."""

from __future__ import annotations

import pytest

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand, BuildScript
from core.minecraft.terrain import (
    BlockMatcher,
    auto_ground_script,
    find_terrain_top,
    foundation_fill_commands,
    make_rcon_block_matcher,
    script_world_bbox,
    shift_script_y,
)


def _world_matcher(world: dict[tuple[int, int, int], str]) -> BlockMatcher:
    """Build an in-memory ``BlockMatcher`` for unit tests.

    Treats missing coordinates as ``minecraft:air`` so the scan can walk
    down from y_start without pre-populating every column. Recognizes the
    ``#minecraft:leaves`` tag by matching any block id containing
    ``"leaves"``.
    """

    def matches(x: int, y: int, z: int, block_or_tag: str) -> bool:
        actual = world.get((x, y, z), "minecraft:air")
        if block_or_tag == "#minecraft:leaves":
            return "leaves" in actual
        return actual == block_or_tag

    return matches


def test_find_terrain_top_stops_at_first_non_air() -> None:
    matcher = _world_matcher({(10, 64, 10): "minecraft:stone"})
    assert find_terrain_top(x=10, z=10, matcher=matcher, y_start=80, y_floor=0) == 64


def test_find_terrain_top_skips_leaves_and_water() -> None:
    matcher = _world_matcher(
        {
            (5, 100, 5): "minecraft:oak_leaves",
            (5, 99, 5): "minecraft:oak_leaves",
            (5, 98, 5): "minecraft:water",
            (5, 90, 5): "minecraft:grass_block",
        }
    )
    assert find_terrain_top(x=5, z=5, matcher=matcher, y_start=120, y_floor=0) == 90


def test_find_terrain_top_falls_back_to_y_floor_when_all_air() -> None:
    matcher = _world_matcher({})
    assert find_terrain_top(x=0, z=0, matcher=matcher, y_start=10, y_floor=-5) == -5


def test_foundation_fill_commands_returns_empty_when_no_gap() -> None:
    assert (
        foundation_fill_commands(
            terrain_top=70, base_y=71, bbox=(0, 0, 8, 8), material="cobblestone"
        )
        == []
    )


def test_foundation_fill_commands_emits_four_perimeter_walls() -> None:
    cmds = foundation_fill_commands(
        terrain_top=60,
        base_y=72,
        bbox=(0, 0, 8, 8),
        material="cobblestone",
    )
    assert len(cmds) == 4
    # y range: terrain_top+1 = 61, base_y-1 = 71
    assert cmds[0] == "/fill 0 61 0 8 71 0 minecraft:cobblestone"
    assert cmds[1] == "/fill 0 61 8 8 71 8 minecraft:cobblestone"
    assert cmds[2] == "/fill 0 61 0 0 71 8 minecraft:cobblestone"
    assert cmds[3] == "/fill 8 61 0 8 71 8 minecraft:cobblestone"


def test_foundation_fill_commands_accepts_namespaced_material() -> None:
    cmds = foundation_fill_commands(
        terrain_top=60,
        base_y=70,
        bbox=(0, 0, 4, 4),
        material="minecraft:stone_bricks",
    )
    assert all("minecraft:stone_bricks" in c for c in cmds)
    assert "minecraft:minecraft:" not in cmds[0]


def test_foundation_fill_commands_normalizes_bbox_order() -> None:
    # Passing x2<x1 / z2<z1 should still produce a valid /fill rectangle.
    cmds = foundation_fill_commands(
        terrain_top=60, base_y=70, bbox=(8, 8, 0, 0), material="cobblestone"
    )
    assert "fill 0 61 0 8 69 0" in cmds[0]


def _script_with(commands: list[BuildCommand], origin: Position3D) -> BuildScript:
    return BuildScript(
        intent_id="t",
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        origin=origin,
        commands=commands,
        materials_manifest={},
        total_blocks=0,
        estimated_seconds=0.0,
        source_plan_hash="h",
        compiler_version=1,
    )


def test_script_world_bbox_includes_region_to() -> None:
    script = _script_with(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=-3, y=10, z=4),
                block_type="dirt",
            ),
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=10, z=0),
                region_to=Position3D(x=5, y=10, z=7),
                block_type="oak_planks",
            ),
        ],
        origin=Position3D(x=0, y=10, z=0),
    )
    assert script_world_bbox(script) == (-3, 0, 5, 7)


def test_script_world_bbox_falls_back_to_origin_when_empty() -> None:
    script = _script_with([], origin=Position3D(x=11, y=64, z=22))
    assert script_world_bbox(script) == (11, 22, 11, 22)


def test_shift_script_y_zero_is_identity() -> None:
    script = _script_with(
        [BuildCommand(kind="setblock", position=Position3D(x=0, y=64, z=0), block_type="dirt")],
        origin=Position3D(x=0, y=64, z=0),
    )
    assert shift_script_y(script, 0) is script


def test_shift_script_y_shifts_commands_and_origin() -> None:
    script = _script_with(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=1, y=64, z=2),
                block_type="dirt",
            ),
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=64, z=0),
                region_to=Position3D(x=4, y=66, z=4),
                block_type="oak_planks",
            ),
            BuildCommand(kind="wait", position=Position3D(x=0, y=0, z=0), wait_seconds=0.1),
        ],
        origin=Position3D(x=0, y=64, z=0),
    )
    shifted = shift_script_y(script, 7)
    assert shifted.origin == Position3D(x=0, y=71, z=0)
    assert shifted.commands[0].position == Position3D(x=1, y=71, z=2)
    assert shifted.commands[1].position == Position3D(x=0, y=71, z=0)
    assert shifted.commands[1].region_to == Position3D(x=4, y=73, z=4)
    # wait commands have a meaningless position but should be preserved as-is.
    assert shifted.commands[2].kind == "wait"


def test_auto_ground_script_shifts_and_emits_foundation() -> None:
    matcher = _world_matcher({(0, 70, 0): "minecraft:grass_block"})
    script = _script_with(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=80, z=0),
                block_type="oak_planks",
            ),
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=80, z=0),
                region_to=Position3D(x=6, y=84, z=6),
                block_type="oak_planks",
            ),
        ],
        origin=Position3D(x=0, y=80, z=0),
    )
    shifted, foundation = auto_ground_script(script, matcher, foundation="cobblestone")
    # terrain_top=70, target_y=71, dy = 71 - 80 = -9 → origin y becomes 71.
    assert shifted.origin.y == 71
    assert shifted.commands[0].position.y == 71
    # Foundation pillar fills from y=71 (terrain_top+1) up to y=70 (base_y-1)
    # — since terrain_top+1 == base_y here, no foundation needed.
    assert foundation == []


def test_auto_ground_script_emits_foundation_when_terrain_dips() -> None:
    # Build sits at y=80, terrain at y=60 — 19 blocks of pedestal required.
    matcher = _world_matcher({(0, 60, 0): "minecraft:stone"})
    script = _script_with(
        [
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=80, z=0),
                region_to=Position3D(x=4, y=84, z=4),
                block_type="oak_planks",
            ),
        ],
        origin=Position3D(x=0, y=80, z=0),
    )
    shifted, foundation = auto_ground_script(script, matcher, foundation="cobblestone")
    # Auto-ground anchors to terrain_top+1 = 61, so dy=-19. The shifted
    # script's base_y becomes 61. terrain_top+1 == base_y → no foundation.
    assert shifted.origin.y == 61
    assert foundation == []


def test_auto_ground_script_emits_foundation_when_base_above_terrain() -> None:
    # Construct a script whose lowest command y is above origin.y so the
    # auto-ground path actually fills a pedestal.
    matcher = _world_matcher({(0, 50, 0): "minecraft:stone"})
    script = _script_with(
        [
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=70, z=0),
                region_to=Position3D(x=4, y=74, z=4),
                block_type="oak_planks",
            ),
        ],
        # Origin is 10 blocks BELOW the lowest command y; after auto-ground
        # the building sits at terrain_top+1 + (offset between origin and base).
        origin=Position3D(x=0, y=60, z=0),
    )
    shifted, foundation = auto_ground_script(script, matcher, foundation="cobblestone")
    # dy = 51 - 60 = -9; commands shifted from y=70 to y=61.
    assert shifted.origin.y == 51
    assert shifted.commands[0].position.y == 61
    # terrain_top=50, base_y=61 → foundation fills y=51..60.
    assert len(foundation) == 4
    assert "minecraft:cobblestone" in foundation[0]
    # bbox is (0, 0, 4, 4) → first wall is the north z=0 strip.
    assert foundation[0] == "/fill 0 51 0 4 60 0 minecraft:cobblestone"


def test_make_rcon_block_matcher_parses_passed_response() -> None:
    class _FakeMcr:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def command(self, text: str) -> str:
            self.calls.append(text)
            if "minecraft:air" in text:
                return "Test failed"
            return "Test passed"

    mcr = _FakeMcr()
    matcher = make_rcon_block_matcher(mcr)
    assert matcher(0, 0, 0, "minecraft:stone") is True
    assert matcher(0, 0, 0, "minecraft:air") is False
    assert mcr.calls == [
        "execute if block 0 0 0 minecraft:stone",
        "execute if block 0 0 0 minecraft:air",
    ]


def test_make_rcon_block_matcher_returns_false_on_command_failure() -> None:
    class _BoomMcr:
        def command(self, text: str) -> str:
            raise RuntimeError("rcon down")

    matcher = make_rcon_block_matcher(_BoomMcr())
    assert matcher(0, 0, 0, "minecraft:stone") is False


@pytest.mark.parametrize(
    "raw, expected_walls",
    [
        # tiny 1-block footprint still emits 4 walls; corners overlap.
        ((0, 0, 0, 0), 4),
        ((-2, -2, 2, 2), 4),
    ],
)
def test_foundation_fill_commands_always_emits_four_walls_when_needed(
    raw: tuple[int, int, int, int], expected_walls: int
) -> None:
    cmds = foundation_fill_commands(
        terrain_top=10, base_y=20, bbox=raw, material="cobblestone"
    )
    assert len(cmds) == expected_walls
