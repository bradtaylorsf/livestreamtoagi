"""Vertical pillar — single ``fill`` from base to capital."""

from __future__ import annotations

from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand


def column_doric(
    *,
    position: Position3D,
    height: int,
    material: str,
    capital_material: str | None = None,
) -> list[BuildCommand]:
    """Place a one-block-thick column of ``material`` rising ``height`` blocks.

    The top block is swapped to ``capital_material`` when supplied so a
    coliseum or temple gets a visually distinct capital. Both commands are
    deterministic (no RNG).
    """
    if height <= 0:
        return []

    shaft_top = Position3D(x=position.x, y=position.y + height - 1, z=position.z)
    commands: list[BuildCommand] = [
        BuildCommand(
            kind="fill",
            position=position,
            region_to=shaft_top,
            block_type=material,
        )
    ]
    if capital_material is not None and capital_material != material:
        commands.append(
            BuildCommand(
                kind="setblock",
                position=shaft_top,
                block_type=capital_material,
            )
        )
    return commands
