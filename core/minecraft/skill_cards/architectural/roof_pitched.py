"""Pitched roof — symmetric peaked layers along the long axis of a footprint."""

from __future__ import annotations

from core.minecraft.build_plan import BoundingBox, Position3D
from core.minecraft.build_script import BuildCommand


def roof_pitched(
    *,
    bbox: BoundingBox,
    origin: Position3D,
    base_y: int,
    material: str,
) -> list[BuildCommand]:
    """Stack symmetric roof layers shrinking toward a central ridge.

    The long axis of the footprint is preserved; the short axis shrinks by
    one cell per side per layer until a single ridge row remains. Layers
    are emitted in deterministic ``y``-ascending, then ``inset``-ascending
    order so that re-running the compiler always produces the same script.
    """
    if bbox.w <= 0 or bbox.h <= 0:
        return []

    along_x = bbox.w >= bbox.h
    short_extent = bbox.h if along_x else bbox.w
    layers = (short_extent + 1) // 2

    commands: list[BuildCommand] = []
    for layer in range(layers):
        y = base_y + layer
        if along_x:
            x_start = origin.x + bbox.x
            x_end = origin.x + bbox.x + bbox.w - 1
            z_start = origin.z + bbox.y + layer
            z_end = origin.z + bbox.y + bbox.h - 1 - layer
            if z_end < z_start:
                continue
        else:
            x_start = origin.x + bbox.x + layer
            x_end = origin.x + bbox.x + bbox.w - 1 - layer
            z_start = origin.z + bbox.y
            z_end = origin.z + bbox.y + bbox.h - 1
            if x_end < x_start:
                continue

        commands.append(
            BuildCommand(
                kind="fill",
                position=Position3D(x=x_start, y=y, z=z_start),
                region_to=Position3D(x=x_end, y=y, z=z_end),
                block_type=material,
            )
        )
    return commands
