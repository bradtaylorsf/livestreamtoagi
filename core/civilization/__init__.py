"""Civilization mechanics MVP — ownership, trade, theft, diplomacy, conflict.

First mechanic landed: :mod:`core.civilization.ownership` (issue #891).
Second mechanic: :mod:`core.civilization.trade` (issue #892). The trade
ledger shares the same per-sim JSONL pattern so the decision log + headless
scorer stay coherent. Other mechanics arrive in sibling tickets (#893–#895).
"""

from __future__ import annotations

from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
    canonical_target_ref,
    normalize_region_ref,
)
from core.civilization.trade import (
    TradeFailure,
    TradeLedger,
    TradeOffer,
)

__all__ = [
    "OwnershipClaim",
    "OwnershipConflict",
    "OwnershipLedger",
    "TradeFailure",
    "TradeLedger",
    "TradeOffer",
    "canonical_target_ref",
    "normalize_region_ref",
]
