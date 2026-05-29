"""Civilization mechanics MVP — ownership, trade, theft, diplomacy, conflict.

First mechanic landed: :mod:`core.civilization.ownership` (issue #891).
Second mechanic: :mod:`core.civilization.trade` (issue #892).
Third mechanic: :mod:`core.civilization.theft` (issue #893).
Fourth mechanic: :mod:`core.civilization.diplomacy` (issue #894).
Fifth mechanic: :mod:`core.civilization.conflict` (issue #895).

All ledgers share the same per-sim JSONL pattern so the decision log +
headless scorer stay coherent.
"""

from __future__ import annotations

from core.civilization.conflict import (
    ConflictFailure,
    ConflictLedger,
    Dispute,
    EvidenceRef,
    WarIntent,
)
from core.civilization.diplomacy import (
    DiplomacyFailure,
    DiplomacyLedger,
    Faction,
    Treaty,
)
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
    "ConflictFailure",
    "ConflictLedger",
    "DiplomacyFailure",
    "DiplomacyLedger",
    "Dispute",
    "EvidenceRef",
    "Faction",
    "OwnershipClaim",
    "OwnershipConflict",
    "OwnershipLedger",
    "TheftAttempt",
    "TheftFailure",
    "TheftLedger",
    "TradeFailure",
    "TradeLedger",
    "TradeOffer",
    "Treaty",
    "WarIntent",
    "canonical_target_ref",
    "normalize_region_ref",
]
