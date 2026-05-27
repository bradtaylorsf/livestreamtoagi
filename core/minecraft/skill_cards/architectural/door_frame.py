"""Carve a door / window opening + place its frame."""

from __future__ import annotations

from typing import Literal

from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand

AIR_BLOCK = "air"


def door_frame(
    *,
    position: Position3D,
    kind: Literal["door", "window"],
    frame_material: str,
) -> list[BuildCommand]:
    """Carve an opening and place a one-block-thick frame around it.

    For a door the opening is 2 wide × 3 tall (unsneaking-player walkable);
    for a window it is 1×1. Carves are always emitted before frame writes
    so the frame cannot reseal the opening if a later wall fill is added
    in the wrong order.
    """
    commands: list[BuildCommand] = []

    if kind == "door":
        for dx in (0, 1):
            for dy in (0, 1, 2):
                commands.append(
                    BuildCommand(
                        kind="setblock",
                        position=Position3D(x=position.x + dx, y=position.y + dy, z=position.z),
                        block_type=AIR_BLOCK,
                    )
                )
        for dx in (0, 1):
            lintel = Position3D(x=position.x + dx, y=position.y + 3, z=position.z)
            commands.append(
                BuildCommand(kind="setblock", position=lintel, block_type=frame_material)
            )
    else:
        commands.append(BuildCommand(kind="setblock", position=position, block_type=AIR_BLOCK))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            frame_pos = Position3D(x=position.x + dx, y=position.y + dy, z=position.z)
            commands.append(
                BuildCommand(kind="setblock", position=frame_pos, block_type=frame_material)
            )
    return commands
