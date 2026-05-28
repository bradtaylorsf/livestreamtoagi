"""Civilization mechanics MVP — ownership, trade, theft, diplomacy, conflict.

First mechanic landed: :mod:`core.civilization.ownership` (issue #891).
Second mechanic: :mod:`core.civilization.trade` (issue #892).
Third mechanic: :mod:`core.civilization.theft` (issue #893). All ledgers
share the same per-sim JSONL pattern so the decision log + headless
scorer stay coherent. Other mechanics arrive in sibling tickets (#894–#895).
"""

from __future__ import annotations

from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
    canonical_target_ref,
    normalize_region_ref,
)
from core.civilization.theft import (
    TheftAttempt,
    TheftFailure,
    TheftLedger,
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
    "TheftAttempt",
    "TheftFailure",
    "TheftLedger",
    "TradeFailure",
    "TradeLedger",
    "TradeOffer",
    "canonical_target_ref",
    "normalize_region_ref",
]
