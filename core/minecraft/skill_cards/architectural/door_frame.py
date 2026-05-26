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

    For a door the opening is 1×2 (head + foot); for a window it is 1×1.
    The frame is emitted as ``setblock`` commands so it composes cleanly
    over a previously-filled wall (the air carve runs first, then the
    frame). All positions are absolute world coordinates.
    """
    commands: list[BuildCommand] = []

    if kind == "door":
        head = Position3D(x=position.x, y=position.y + 1, z=position.z)
        commands.append(BuildCommand(kind="setblock", position=position, block_type=AIR_BLOCK))
        commands.append(BuildCommand(kind="setblock", position=head, block_type=AIR_BLOCK))
        # Frame above the head (lintel)
        lintel = Position3D(x=position.x, y=position.y + 2, z=position.z)
        commands.append(BuildCommand(kind="setblock", position=lintel, block_type=frame_material))
    else:
        commands.append(BuildCommand(kind="setblock", position=position, block_type=AIR_BLOCK))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            frame_pos = Position3D(x=position.x + dx, y=position.y + dy, z=position.z)
            commands.append(
                BuildCommand(kind="setblock", position=frame_pos, block_type=frame_material)
            )
    return commands
