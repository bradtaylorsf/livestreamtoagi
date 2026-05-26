"""Floor / foundation slab — single ``fill`` command across the footprint."""

from __future__ import annotations

from core.minecraft.build_plan import BoundingBox, Position3D
from core.minecraft.build_script import BuildCommand


def foundation_lay(
    *,
    bbox: BoundingBox,
    origin: Position3D,
    floor_y: int,
    material: str,
) -> list[BuildCommand]:
    """Lay a rectangular floor of ``material`` at ``floor_y``.

    ``bbox`` is in tile-space relative to ``origin``; the output positions
    are absolute world coordinates so the bridge can issue them directly.
    """
    start = Position3D(
        x=origin.x + bbox.x,
        y=floor_y,
        z=origin.z + bbox.y,
    )
    end = Position3D(
        x=origin.x + bbox.x + bbox.w - 1,
        y=floor_y,
        z=origin.z + bbox.y + bbox.h - 1,
    )
    return [
        BuildCommand(
            kind="fill",
            position=start,
            region_to=end,
            block_type=material,
        )
    ]
