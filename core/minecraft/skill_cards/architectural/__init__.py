"""Architectural skill cards used by the ``BuildPlan`` macro compiler (issue #857).

Distinct from the LLM-prompt skill cards in
:mod:`core.minecraft.skill_cards.registry` (which describe agent action
surfaces for command-eval prompts). An *architectural* skill card is a pure
deterministic function that emits a list of
:class:`core.minecraft.build_script.BuildCommand` for one architectural
primitive — a floor slab, a wall segment, a peaked roof, a doorway, a
column, an arch.

Every card:

- takes typed Pydantic inputs (region rect, materials dict, opening list)
- returns ``list[BuildCommand]`` in a stable order
- never reads from the filesystem, network, or RNG
"""

from core.minecraft.skill_cards.architectural.arch_round import arch_round
from core.minecraft.skill_cards.architectural.column_doric import column_doric
from core.minecraft.skill_cards.architectural.door_frame import door_frame
from core.minecraft.skill_cards.architectural.foundation_lay import foundation_lay
from core.minecraft.skill_cards.architectural.registry import (
    ARCHITECTURAL_CARDS,
    ArchitecturalCard,
    get_card,
)
from core.minecraft.skill_cards.architectural.roof_pitched import roof_pitched
from core.minecraft.skill_cards.architectural.wall_segment import wall_segment

__all__ = [
    "ARCHITECTURAL_CARDS",
    "ArchitecturalCard",
    "arch_round",
    "column_doric",
    "door_frame",
    "foundation_lay",
    "get_card",
    "roof_pitched",
    "wall_segment",
]
