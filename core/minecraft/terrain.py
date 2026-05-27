"""Terrain query helpers for the auto-ground build path (issue #873).

Before #873, ``scripts/build_in_minecraft.py`` and the agent-invoked
``RconBuildExecutor`` both placed structures at the literal ``y`` from the
CLI/origin — buildings floated in mid-air on uneven terrain. This module
gives both call sites a shared way to:

1. Find the highest non-air, non-foliage block at ``(x, z)`` via RCON
   (:func:`find_terrain_top`).
2. Emit ``/fill`` foundation commands so steep terrain doesn't leave the
   build hanging over a cliff (:func:`foundation_fill_commands`).

The query layer is split into a ``BlockMatcher`` callable so unit tests
don't need a real Minecraft server — a tiny in-memory matcher exercises
the scan logic. :func:`make_rcon_block_matcher` binds the callable to an
open ``mcrcon.MCRcon`` connection in production code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from core.minecraft.build_script import BuildScript

logger = logging.getLogger(__name__)


AIR_BLOCKS: tuple[str, ...] = (
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
)

# Blocks the terrain scan should treat as "not the ground" — foliage,
# snow caps, hanging vines, surface liquids. Stays as block ids rather
# than tags because not every server normalizes block tags consistently.
DEFAULT_SKIP_BLOCKS: tuple[str, ...] = (
    "#minecraft:leaves",
    "minecraft:vine",
    "minecraft:snow",
    "minecraft:tall_grass",
    "minecraft:short_grass",
    "minecraft:fern",
    "minecraft:large_fern",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:bubble_column",
)


BlockMatcher = Callable[[int, int, int, str], bool]


def make_rcon_block_matcher(mcr: object) -> BlockMatcher:
    """Return a ``BlockMatcher`` bound to an open ``mcrcon`` connection.

    Issues ``execute if block`` commands; parses the response for the
    word "passed" since Minecraft replies "Test passed" / "Test failed".
    Any other response shape is treated as a non-match so the scan keeps
    walking instead of locking onto stale data.
    """

    def matches(x: int, y: int, z: int, block_or_tag: str) -> bool:
        cmd = f"execute if block {x} {y} {z} {block_or_tag}"
        try:
            resp = mcr.command(cmd) or ""  # type: ignore[attr-defined]
        except Exception:
            logger.exception("rcon block query failed at %s,%s,%s", x, y, z)
            return False
        return "passed" in resp.lower()

    return matches


def find_terrain_top(
    *,
    x: int,
    z: int,
    matcher: BlockMatcher,
    y_start: int = 320,
    y_floor: int = -64,
    skip_blocks: tuple[str, ...] = DEFAULT_SKIP_BLOCKS,
) -> int:
    """Return the highest non-air, non-foliage y at column ``(x, z)``.

    Scans downward from ``y_start`` to ``y_floor`` inclusive. A column
    that is entirely air falls back to ``y_floor`` so callers always get
    a placeable integer.
    """
    for y in range(y_start, y_floor - 1, -1):
        if any(matcher(x, y, z, air) for air in AIR_BLOCKS):
            continue
        if any(matcher(x, y, z, blk) for blk in skip_blocks):
            continue
        return y
    return y_floor


def foundation_fill_commands(
    *,
    terrain_top: int,
    base_y: int,
    bbox: tuple[int, int, int, int],
    material: str = "cobblestone",
) -> list[str]:
    """Return ``/fill`` commands that pillar a building above sloped terrain.

    ``bbox`` is the world-space footprint as ``(x1, z1, x2, z2)``. We
    emit four perimeter walls from ``terrain_top + 1`` up to ``base_y - 1``
    so the building has a visible pedestal without filling the entire
    interior (which would be wasteful for large structures).

    Returns an empty list when ``terrain_top + 1 >= base_y`` (the
    building already sits at or below the queried terrain).
    """
    if terrain_top + 1 >= base_y:
        return []
    x1, z1, x2, z2 = bbox
    if x1 > x2:
        x1, x2 = x2, x1
    if z1 > z2:
        z1, z2 = z2, z1
    y1 = terrain_top + 1
    y2 = base_y - 1
    mat = material if material.startswith("minecraft:") else f"minecraft:{material}"
    # Four perimeter walls; corners overlap, which Minecraft handles fine
    # (later /fills just overwrite the same blocks).
    return [
        f"/fill {x1} {y1} {z1} {x2} {y2} {z1} {mat}",
        f"/fill {x1} {y1} {z2} {x2} {y2} {z2} {mat}",
        f"/fill {x1} {y1} {z1} {x1} {y2} {z2} {mat}",
        f"/fill {x2} {y1} {z1} {x2} {y2} {z2} {mat}",
    ]


def script_world_bbox(script: BuildScript) -> tuple[int, int, int, int]:
    """Return ``(x_min, z_min, x_max, z_max)`` covering every command in ``script``.

    Used by the auto-ground path to compute the foundation perimeter
    independently of the source ``BuildPlan`` (the compiler may extend
    beyond ``footprint.bbox`` for roofs, overhangs, etc.).
    """
    xs: list[int] = []
    zs: list[int] = []
    for cmd in script.commands:
        if cmd.kind == "wait":
            continue
        xs.append(cmd.position.x)
        zs.append(cmd.position.z)
        if cmd.region_to is not None:
            xs.append(cmd.region_to.x)
            zs.append(cmd.region_to.z)
    if not xs:
        return (script.origin.x, script.origin.z, script.origin.x, script.origin.z)
    return (min(xs), min(zs), max(xs), max(zs))


def shift_script_y(script: BuildScript, dy: int) -> BuildScript:
    """Return a copy of ``script`` with every command's y-coordinate shifted by ``dy``.

    Origin is shifted as well so downstream consumers see a consistent
    script (the materials manifest and hash are intentionally preserved —
    auto-ground is a placement decision, not a plan change).
    """
    if dy == 0:
        return script

    from core.minecraft.build_plan import Position3D

    new_commands = []
    for cmd in script.commands:
        if cmd.kind == "wait":
            new_commands.append(cmd)
            continue
        new_pos = Position3D(x=cmd.position.x, y=cmd.position.y + dy, z=cmd.position.z)
        new_region = None
        if cmd.region_to is not None:
            new_region = Position3D(
                x=cmd.region_to.x, y=cmd.region_to.y + dy, z=cmd.region_to.z
            )
        new_commands.append(
            cmd.model_copy(update={"position": new_pos, "region_to": new_region})
        )
    new_origin = Position3D(x=script.origin.x, y=script.origin.y + dy, z=script.origin.z)
    return script.model_copy(update={"commands": new_commands, "origin": new_origin})


def auto_ground_script(
    script: BuildScript,
    matcher: BlockMatcher,
    *,
    foundation: str = "cobblestone",
    y_start: int = 320,
    y_floor: int = -64,
) -> tuple[BuildScript, list[str]]:
    """Shift ``script`` so it sits on terrain and return foundation commands.

    Shared between :class:`core.minecraft.build_executors.RconBuildExecutor`
    and ``scripts/build_in_minecraft.py`` so the CLI and the agent-invoked
    paths use one source of truth for grounding behavior.
    """
    terrain_top = find_terrain_top(
        x=script.origin.x,
        z=script.origin.z,
        matcher=matcher,
        y_start=y_start,
        y_floor=y_floor,
    )
    target_y = terrain_top + 1
    dy = target_y - script.origin.y
    shifted = shift_script_y(script, dy)
    bbox = script_world_bbox(shifted)
    base_y = min(
        (cmd.position.y for cmd in shifted.commands if cmd.kind != "wait"),
        default=shifted.origin.y,
    )
    foundation_cmds = foundation_fill_commands(
        terrain_top=terrain_top,
        base_y=base_y,
        bbox=bbox,
        material=foundation,
    )
    logger.info(
        "auto_ground_script: origin=(%d,%d,%d) terrain_top=%d dy=%d foundation_cmds=%d",
        script.origin.x,
        script.origin.y,
        script.origin.z,
        terrain_top,
        dy,
        len(foundation_cmds),
    )
    return shifted, foundation_cmds


__all__ = [
    "AIR_BLOCKS",
    "DEFAULT_SKIP_BLOCKS",
    "BlockMatcher",
    "auto_ground_script",
    "find_terrain_top",
    "foundation_fill_commands",
    "make_rcon_block_matcher",
    "script_world_bbox",
    "shift_script_y",
]
