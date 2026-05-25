"""Perimeter walls for one rectangular footprint at one level."""

from __future__ import annotations

from core.minecraft.build_plan import BoundingBox, Position3D
from core.minecraft.build_script import BuildCommand


def wall_segment(
    *,
    bbox: BoundingBox,
    origin: Position3D,
    base_y: int,
    height: int,
    material: str,
) -> list[BuildCommand]:
    """Place the four perimeter walls of a rectangular footprint.

    Emits four ``fill`` commands (one per side) in a stable N → E → S → W
    order. Corner cells are placed by both abutting sides; Minecraft's
    ``/fill`` is idempotent for the same block so the duplicate write is
    harmless and keeps each side's command shape simple.
    """
    if height <= 0:
        return []
    if bbox.w <= 0 or bbox.h <= 0:
        return []

    top_y = base_y + height - 1
    x0 = origin.x + bbox.x
    x1 = origin.x + bbox.x + bbox.w - 1
    z0 = origin.z + bbox.y
    z1 = origin.z + bbox.y + bbox.h - 1

    north = BuildCommand(
        kind="fill",
        position=Position3D(x=x0, y=base_y, z=z0),
        region_to=Position3D(x=x1, y=top_y, z=z0),
        block_type=material,
    )
    east = BuildCommand(
        kind="fill",
        position=Position3D(x=x1, y=base_y, z=z0),
        region_to=Position3D(x=x1, y=top_y, z=z1),
        block_type=material,
    )
    south = BuildCommand(
        kind="fill",
        position=Position3D(x=x0, y=base_y, z=z1),
        region_to=Position3D(x=x1, y=top_y, z=z1),
        block_type=material,
    )
    west = BuildCommand(
        kind="fill",
        position=Position3D(x=x0, y=base_y, z=z0),
        region_to=Position3D(x=x0, y=top_y, z=z1),
        block_type=material,
    )
    return [north, east, south, west]
