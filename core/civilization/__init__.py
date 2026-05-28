"""Civilization mechanics MVP — ownership, trade, theft, diplomacy, conflict.

First mechanic landed: :mod:`core.civilization.ownership` (issue #891). Other
mechanics arrive in sibling tickets (#892–#895) and will share the same
ledger/JSONL pattern so the decision log + headless scorer stay coherent.
"""

from __future__ import annotations

from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
    canonical_target_ref,
    normalize_region_ref,
)

__all__ = [
    "OwnershipClaim",
    "OwnershipConflict",
    "OwnershipLedger",
    "canonical_target_ref",
    "normalize_region_ref",
]
