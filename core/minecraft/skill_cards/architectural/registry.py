"""Card-id → callable registry for the architectural skill cards (issue #857)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.minecraft.skill_cards.architectural.arch_round import arch_round
from core.minecraft.skill_cards.architectural.column_doric import column_doric
from core.minecraft.skill_cards.architectural.door_frame import door_frame
from core.minecraft.skill_cards.architectural.foundation_lay import foundation_lay
from core.minecraft.skill_cards.architectural.roof_pitched import roof_pitched
from core.minecraft.skill_cards.architectural.wall_segment import wall_segment

ArchitecturalCard = Callable[..., list[Any]]

ARCHITECTURAL_CARDS: dict[str, ArchitecturalCard] = {
    "arch_round": arch_round,
    "column_doric": column_doric,
    "door_frame": door_frame,
    "foundation_lay": foundation_lay,
    "roof_pitched": roof_pitched,
    "wall_segment": wall_segment,
}


def get_card(card_id: str) -> ArchitecturalCard:
    """Return the architectural card callable for ``card_id``."""
    try:
        return ARCHITECTURAL_CARDS[card_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown architectural card: {card_id!r}; known ids: {sorted(ARCHITECTURAL_CARDS)}"
        ) from exc


__all__ = ["ARCHITECTURAL_CARDS", "ArchitecturalCard", "get_card"]
