"""Rounded arch — pillars + stepped voussoirs approximating a semicircle."""

from __future__ import annotations

from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand


def arch_round(
    *,
    position: Position3D,
    span: int,
    height: int,
    material: str,
) -> list[BuildCommand]:
    """Build a stepped semicircular arch spanning ``span`` blocks.

    ``position`` is the lower-left foot of the arch (its left pillar
    base). The arch rises ``height`` blocks; pillars take the lower
    ``height - radius`` blocks, voussoirs approximate the upper half-disk
    with one ``setblock`` per cell so the curve is visible in low-res
    Minecraft.
    """
    if span < 2 or height <= 0:
        return []

    radius = max(1, span // 2)
    pillar_height = max(0, height - radius)
    commands: list[BuildCommand] = []

    if pillar_height > 0:
        left_top = Position3D(x=position.x, y=position.y + pillar_height - 1, z=position.z)
        right_base = Position3D(x=position.x + span - 1, y=position.y, z=position.z)
        right_top = Position3D(
            x=position.x + span - 1,
            y=position.y + pillar_height - 1,
            z=position.z,
        )
        commands.append(
            BuildCommand(
                kind="fill",
                position=position,
                region_to=left_top,
                block_type=material,
            )
        )
        commands.append(
            BuildCommand(
                kind="fill",
                position=right_base,
                region_to=right_top,
                block_type=material,
            )
        )

    # Voussoirs: scan each column above the pillars and place a block when
    # the arch curve covers it. Iteration order is column-major, y-major
    # for determinism.
    centre_x = position.x + (span - 1) / 2.0
    for dx in range(span):
        col_x = position.x + dx
        offset = abs(col_x - centre_x)
        for dy in range(radius):
            y = position.y + pillar_height + dy
            row = radius - 1 - dy
            if offset <= row + 0.5:
                commands.append(
                    BuildCommand(
                        kind="setblock",
                        position=Position3D(x=col_x, y=y, z=position.z),
                        block_type=material,
                    )
                )
    return commands
