"""Civilization tools (issues #891 ownership, #892 trade, #893 theft, #894 diplomacy).

Ownership tools (#891) backed by an :class:`OwnershipLedger`:

* :class:`ClaimOwnershipTool` — claim a structure / container / region.
* :class:`ReleaseOwnershipTool` — release an active claim by id.
* :class:`GetOwnershipTool` — read-only lookup; returns owner or null.
* :class:`ListMyClaimsTool` — read-only introspection of the caller's holdings.

Trade tools (#892) backed by a :class:`TradeLedger`:

* :class:`ProposeTradeTool` — open a pairwise offer.
* :class:`AcceptTradeTool` — recipient accepts; inventories swap atomically.
* :class:`RejectTradeTool` — recipient declines with a reason.
* :class:`ListPendingTradesTool` — recipient sees offers awaiting reply.

Theft tools (#893) backed by a :class:`TheftLedger`:

* :class:`StealTool` — attempt to take items from another agent's container.
* :class:`ReportTheftTool` — witness promotes an undetected attempt.

Diplomacy tools (#894) backed by a :class:`DiplomacyLedger`:

* :class:`ProposeTreatyTool` — propose a treaty to another faction.
* :class:`SignTreatyTool` — counterparty leader signs a pending treaty.
* :class:`BreakTreatyTool` — withdraw from an active treaty.
* :class:`DefectFactionTool` — leave one faction for another.
* :class:`ListActiveTreatiesTool` — introspect the diplomatic state.

The mutating tools write an ``ownership_delta`` / ``trade_event`` /
``theft_event`` / ``diplomacy_event`` row to the decision logger directly
when one is injected — the ARTIFACT_CREATED event emitted by
:meth:`BaseTool.run` only carries the tool name, not its args or result, so
we cannot reconstruct the delta from that event alone. The
``ARTIFACT_CREATED`` event still fires (via ``BaseTool.run``) so the
existing tool_intent capture path keeps recording these as tool calls.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core.civilization.conflict import (
    ConflictFailure,
    ConflictLedger,
    Dispute,
    WarIntent,
)
from core.civilization.diplomacy import (
    DiplomacyFailure,
    DiplomacyLedger,
    Treaty,
)
from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
)
from core.civilization.theft import TheftAttempt, TheftFailure, TheftLedger
from core.civilization.trade import TradeFailure, TradeLedger, TradeOffer

from .base import BaseTool

if TYPE_CHECKING:
    from core.agent_goals import AgentGoalManager
    from core.simulation.decision_logger import DecisionLogger

logger = logging.getLogger(__name__)

_TARGET_TYPES = ("region", "structure", "container")
_BUILDER_AGENTS = frozenset({"vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"})
_TRADER_AGENTS = frozenset({"vera", "rex", "pixel", "sentinel", "fork"})
_THIEF_AGENTS = frozenset({"grok", "fork", "pixel"})
_DIPLOMAT_AGENTS = frozenset({"vera", "fork"})

# Magnitude of trust hit per consequence (per spec):
#   detected theft → victim trust toward thief drops 0.5
#   detected theft → each witness trust toward thief drops 0.2
_VICTIM_TRUST_HIT = 0.5
_WITNESS_TRUST_HIT = 0.2
_DEFAULT_TRUST = 0.5
# Extra penalty (over and above the victim trust hit) when the theft also
# violates a non_aggression treaty between the parties' factions (#894).
_BREAKER_TRUST_HIT = 2.0


def _claim_to_dict(claim: OwnershipClaim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "owner_agent_id": claim.owner_agent_id,
        "target_type": claim.target_type,
        "target_ref": claim.target_ref,
        "motivation": claim.motivation,
        "created_at": claim.created_at.isoformat(),
        "released_at": claim.released_at.isoformat() if claim.released_at else None,
        "release_reason": claim.release_reason,
    }


def _log_delta(
    decision_logger: DecisionLogger | None,
    *,
    action: str,
    claim_id: str,
    owner_agent_id: str,
    target_type: str,
    target_ref: dict[str, Any],
    motivation: str | None,
    actor_id: str | None = None,
) -> None:
    if decision_logger is None:
        return
    try:
        decision_logger.log_ownership_delta(
            claim_id=claim_id,
            owner_agent_id=owner_agent_id,
            target_type=target_type,
            target_ref=target_ref,
            action=action,
            motivation=motivation,
            actor_id=actor_id,
        )
    except Exception:  # pragma: no cover - logger must not break the sim
        logger.exception(
            "decision_logger.log_ownership_delta failed (action=%s claim=%s)",
            action,
            claim_id,
        )


class ClaimOwnershipTool(BaseTool):
    """Agent declares ownership of a structure / container / region."""

    ALLOWED_AGENTS = _BUILDER_AGENTS

    name = "claim_ownership"
    description = (
        "Claim ownership of a target so other agents (and the world) know "
        "it's yours. First-claim-wins: if someone already owns it (or, for "
        "regions, an overlapping bounding box) you'll get a conflict result "
        "naming the existing owner. Use 'structure' for a building you "
        "proposed via propose_build (target_ref={'intent_id': <id>}), "
        "'container' for a chest at fixed coords "
        "(target_ref={'x':..,'y':..,'z':..,'dim':?}), or 'region' for a "
        "land area (target_ref={'x1':..,'z1':..,'x2':..,'z2':..,'dim':?})."
    )
    parameters = {
        "target_type": {
            "type": "string",
            "description": "What kind of thing you're claiming.",
            "enum": list(_TARGET_TYPES),
        },
        "target_ref": {
            "type": "object",
            "description": (
                "Structured reference identifying the target. Shape depends "
                "on target_type — see the tool description."
            ),
        },
        "motivation": {
            "type": "string",
            "description": (
                "One short sentence on why you want this — link to a goal, "
                "dream, or felt need. Required."
            ),
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: OwnershipLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "ownership_ledger_unavailable"}

        target_type = kwargs.get("target_type")
        target_ref = kwargs.get("target_ref")
        motivation = kwargs.get("motivation")

        if target_type not in _TARGET_TYPES:
            return {
                "status": "error",
                "reason": f"target_type must be one of {list(_TARGET_TYPES)}",
            }
        if not isinstance(target_ref, dict) or not target_ref:
            return {
                "status": "error",
                "reason": "target_ref must be a non-empty object",
            }
        if not isinstance(motivation, str) or not motivation.strip():
            return {"status": "error", "reason": "motivation is required"}

        try:
            result = self._ledger.claim(
                owner_agent_id=self._agent_id,
                target_type=target_type,
                target_ref=target_ref,
                motivation=motivation.strip(),
            )
        except ValueError as exc:
            return {"status": "error", "reason": str(exc)}

        if isinstance(result, OwnershipConflict):
            _log_delta(
                self._decision_logger,
                action="conflict",
                claim_id=result.existing_claim_id,
                owner_agent_id=self._agent_id,
                target_type=result.target_type,
                target_ref=result.target_ref,
                motivation=motivation.strip(),
                actor_id=self._agent_id,
            )
            return {
                "status": "conflict",
                "target_type": result.target_type,
                "target_ref": result.target_ref,
                "existing_claim_id": result.existing_claim_id,
                "existing_owner_agent_id": result.existing_owner_agent_id,
            }

        _log_delta(
            self._decision_logger,
            action="claim",
            claim_id=result.claim_id,
            owner_agent_id=result.owner_agent_id,
            target_type=result.target_type,
            target_ref=result.target_ref,
            motivation=result.motivation,
            actor_id=result.owner_agent_id,
        )
        return {"status": "claimed", **_claim_to_dict(result)}


class ReleaseOwnershipTool(BaseTool):
    """Release a previously held claim by id."""

    ALLOWED_AGENTS = _BUILDER_AGENTS

    name = "release_ownership"
    description = (
        "Release a claim you previously made by claim_id. Pass a short "
        "reason so the decision log captures *why* you let go (gift, no "
        "longer needed, lost in war, etc.)."
    )
    parameters = {
        "claim_id": {
            "type": "string",
            "description": "The claim_id returned by an earlier claim_ownership call.",
        },
        "reason": {
            "type": "string",
            "description": "Short reason for the release.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: OwnershipLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "ownership_ledger_unavailable"}

        claim_id = kwargs.get("claim_id")
        reason = kwargs.get("reason")

        if not isinstance(claim_id, str) or not claim_id:
            return {"status": "error", "reason": "claim_id is required"}
        if not isinstance(reason, str) or not reason.strip():
            return {"status": "error", "reason": "reason is required"}

        released = self._ledger.release(claim_id, reason=reason.strip())
        if released is None:
            return {
                "status": "error",
                "reason": f"no active claim with id {claim_id}",
            }

        _log_delta(
            self._decision_logger,
            action="release",
            claim_id=released.claim_id,
            owner_agent_id=released.owner_agent_id,
            target_type=released.target_type,
            target_ref=released.target_ref,
            motivation=reason.strip(),
            actor_id=self._agent_id,
        )
        return {"status": "released", **_claim_to_dict(released)}


class GetOwnershipTool(BaseTool):
    """Look up the current owner of a target (read-only)."""

    ALLOWED_AGENTS = _BUILDER_AGENTS

    name = "get_ownership"
    description = (
        "Look up who (if anyone) owns a target. Returns the active claim "
        "or {'owned': false} when nobody owns it. Does not mutate state."
    )
    parameters = {
        "target_type": {
            "type": "string",
            "description": "What kind of thing to look up.",
            "enum": list(_TARGET_TYPES),
        },
        "target_ref": {
            "type": "object",
            "description": "Same shape as claim_ownership target_ref.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: OwnershipLedger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "ownership_ledger_unavailable"}

        target_type = kwargs.get("target_type")
        target_ref = kwargs.get("target_ref")

        if target_type not in _TARGET_TYPES:
            return {
                "status": "error",
                "reason": f"target_type must be one of {list(_TARGET_TYPES)}",
            }
        if not isinstance(target_ref, dict) or not target_ref:
            return {"status": "error", "reason": "target_ref must be a non-empty object"}

        try:
            claim = self._ledger.get(target_type, target_ref)
        except ValueError as exc:
            return {"status": "error", "reason": str(exc)}

        if claim is None:
            return {"status": "ok", "owned": False}
        return {"status": "ok", "owned": True, **_claim_to_dict(claim)}


class ListMyClaimsTool(BaseTool):
    """List all active claims held by the calling agent."""

    ALLOWED_AGENTS = _BUILDER_AGENTS

    name = "list_my_claims"
    description = (
        "List every active ownership claim you currently hold. Use this "
        "to remember what you own before proposing trades, defending "
        "borders, or releasing things you no longer need."
    )
    parameters: dict[str, Any] = {}

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: OwnershipLedger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "ownership_ledger_unavailable"}

        claims = self._ledger.list_owned_by(self._agent_id)
        return {
            "status": "ok",
            "agent_id": self._agent_id,
            "count": len(claims),
            "claims": [_claim_to_dict(c) for c in claims],
        }


def _offer_to_dict(offer: TradeOffer) -> dict[str, Any]:
    return {
        "offer_id": offer.offer_id,
        "proposer_id": offer.proposer_id,
        "recipient_id": offer.recipient_id,
        "give": dict(offer.give),
        "want": dict(offer.want),
        "give_containers": list(offer.give_containers),
        "want_containers": list(offer.want_containers),
        "motivation": offer.motivation,
        "status": offer.status,
        "created_at": offer.created_at.isoformat(),
        "resolved_at": offer.resolved_at.isoformat() if offer.resolved_at else None,
        "reject_reason": offer.reject_reason,
    }


def _log_trade(
    decision_logger: DecisionLogger | None,
    *,
    offer: TradeOffer,
    action: str,
    reject_reason: str | None = None,
    price_observation: dict[str, Any] | None = None,
    actor_id: str | None = None,
) -> None:
    if decision_logger is None:
        return
    try:
        decision_logger.log_trade_event(
            offer_id=offer.offer_id,
            proposer_id=offer.proposer_id,
            recipient_id=offer.recipient_id,
            give=dict(offer.give),
            want=dict(offer.want),
            action=action,
            motivation=offer.motivation,
            reject_reason=reject_reason,
            price_observation=price_observation,
            actor_id=actor_id,
        )
    except Exception:  # pragma: no cover - logger must not break the sim
        logger.exception(
            "decision_logger.log_trade_event failed (action=%s offer=%s)",
            action,
            offer.offer_id,
        )


def _failure_response(failure: TradeFailure) -> dict[str, Any]:
    response: dict[str, Any] = {"status": "error", "reason": failure.reason}
    if failure.offer_id is not None:
        response["offer_id"] = failure.offer_id
    if failure.detail is not None:
        response["detail"] = failure.detail
    return response


class ProposeTradeTool(BaseTool):
    """Propose a pairwise trade to another agent."""

    ALLOWED_AGENTS = _TRADER_AGENTS

    name = "propose_trade"
    description = (
        "Offer another agent a trade: items you'll give them in exchange for "
        "items you want. Both 'give' and 'want' are dicts of material → "
        "quantity (e.g. {'cobblestone': 32, 'wood': 8}). The offer sits "
        "pending until the recipient accepts or rejects. Provide a short "
        "motivation so the decision log captures *why* you proposed it."
    )
    parameters = {
        "recipient_id": {
            "type": "string",
            "description": "The agent_id of the recipient (e.g. 'rex').",
        },
        "give": {
            "type": "object",
            "description": "What you'll give: dict of material → positive integer quantity.",
        },
        "want": {
            "type": "object",
            "description": "What you want back: dict of material → positive integer quantity.",
        },
        "motivation": {
            "type": "string",
            "description": "One short sentence explaining why you want this trade.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: TradeLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "trade_ledger_unavailable"}

        recipient_id = kwargs.get("recipient_id")
        give = kwargs.get("give")
        want = kwargs.get("want")
        motivation = kwargs.get("motivation")

        if not isinstance(recipient_id, str) or not recipient_id:
            return {"status": "error", "reason": "recipient_id is required"}
        if motivation is not None and not isinstance(motivation, str):
            return {"status": "error", "reason": "motivation must be a string"}

        result = self._ledger.propose(
            proposer_id=self._agent_id,
            recipient_id=recipient_id,
            give=give if isinstance(give, dict) else None,
            want=want if isinstance(want, dict) else None,
            motivation=motivation.strip() if isinstance(motivation, str) else None,
            give_containers=kwargs.get("give_containers")
            if isinstance(kwargs.get("give_containers"), list)
            else None,
            want_containers=kwargs.get("want_containers")
            if isinstance(kwargs.get("want_containers"), list)
            else None,
        )
        if isinstance(result, TradeFailure):
            return _failure_response(result)

        _log_trade(
            self._decision_logger,
            offer=result,
            action="proposed",
            actor_id=self._agent_id,
        )
        return {**_offer_to_dict(result), "status": "proposed"}


class AcceptTradeTool(BaseTool):
    """Accept a pending trade offer addressed to this agent."""

    ALLOWED_AGENTS = _TRADER_AGENTS

    name = "accept_trade"
    description = (
        "Accept a pending trade offer by offer_id. Inventories swap "
        "atomically — if either side lacks the promised items the trade "
        "fails with reason='insufficient_inventory' and no state changes. "
        "Container ownership transfers automatically when the offer "
        "included container target_refs."
    )
    parameters = {
        "offer_id": {
            "type": "string",
            "description": "The offer_id from list_pending_trades or an earlier propose.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: TradeLedger | None = None,
        ownership_ledger: OwnershipLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._ownership_ledger = ownership_ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "trade_ledger_unavailable"}

        offer_id = kwargs.get("offer_id")
        if not isinstance(offer_id, str) or not offer_id:
            return {"status": "error", "reason": "offer_id is required"}

        result = self._ledger.accept(
            offer_id,
            accepting_agent_id=self._agent_id,
            ownership_ledger=self._ownership_ledger,
        )
        if isinstance(result, TradeFailure):
            return _failure_response(result)

        _log_trade(
            self._decision_logger,
            offer=result,
            action="accepted",
            price_observation={
                "give_material_qty": dict(result.give),
                "want_material_qty": dict(result.want),
            },
            actor_id=self._agent_id,
        )
        return {**_offer_to_dict(result), "status": "accepted"}


class RejectTradeTool(BaseTool):
    """Reject a pending trade offer addressed to this agent."""

    ALLOWED_AGENTS = _TRADER_AGENTS

    name = "reject_trade"
    description = (
        "Decline a pending trade offer by offer_id. Provide a short reason "
        "so the decision log captures *why* you turned it down."
    )
    parameters = {
        "offer_id": {
            "type": "string",
            "description": "The offer_id you want to reject.",
        },
        "reason": {
            "type": "string",
            "description": "Short reason for declining.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: TradeLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "trade_ledger_unavailable"}

        offer_id = kwargs.get("offer_id")
        reason = kwargs.get("reason")
        if not isinstance(offer_id, str) or not offer_id:
            return {"status": "error", "reason": "offer_id is required"}
        if not isinstance(reason, str) or not reason.strip():
            return {"status": "error", "reason": "reason is required"}

        result = self._ledger.reject(
            offer_id,
            accepting_agent_id=self._agent_id,
            reason=reason.strip(),
        )
        if isinstance(result, TradeFailure):
            return _failure_response(result)

        _log_trade(
            self._decision_logger,
            offer=result,
            action="rejected",
            reject_reason=reason.strip(),
            actor_id=self._agent_id,
        )
        return {**_offer_to_dict(result), "status": "rejected"}


class ListPendingTradesTool(BaseTool):
    """List trade offers awaiting the calling agent's response."""

    ALLOWED_AGENTS = _TRADER_AGENTS

    name = "list_pending_trades"
    description = (
        "List every pending trade offer addressed to you. Returns only "
        "your offers — not offers between other agents. Use the returned "
        "offer_id with accept_trade or reject_trade."
    )
    parameters: dict[str, Any] = {}

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: TradeLedger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "trade_ledger_unavailable"}

        offers = self._ledger.list_pending(self._agent_id)
        return {
            "status": "ok",
            "agent_id": self._agent_id,
            "count": len(offers),
            "offers": [_offer_to_dict(o) for o in offers],
        }


def _attempt_to_dict(attempt: TheftAttempt) -> dict[str, Any]:
    return {
        "attempt_id": attempt.attempt_id,
        "thief_id": attempt.thief_id,
        "victim_id": attempt.victim_id,
        "container_ref": attempt.target_container,
        "items": dict(attempt.items),
        "detected": attempt.detected,
        "witnesses": list(attempt.witnesses),
        "motivation": attempt.motivation,
        "created_at": attempt.created_at.isoformat(),
    }


def _log_theft(
    decision_logger: DecisionLogger | None,
    *,
    attempt: TheftAttempt,
    actor_id: str | None = None,
) -> None:
    if decision_logger is None:
        return
    try:
        decision_logger.log_theft_event(
            attempt_id=attempt.attempt_id,
            thief_id=attempt.thief_id,
            victim_id=attempt.victim_id,
            container_ref=attempt.target_container,
            items=dict(attempt.items),
            detected=attempt.detected,
            witnesses=list(attempt.witnesses),
            motivation=attempt.motivation,
            actor_id=actor_id or attempt.thief_id,
        )
    except Exception:  # pragma: no cover - logger must not break the sim
        logger.exception(
            "decision_logger.log_theft_event failed (attempt=%s)",
            attempt.attempt_id,
        )


def _emit_theft_consequences(
    decision_logger: DecisionLogger | None,
    *,
    attempt: TheftAttempt,
    diplomacy_ledger: DiplomacyLedger | None = None,
    goal_manager: AgentGoalManager | None = None,
    simulation_id: Any | None = None,
) -> None:
    """Apply victim + witness trust hits as relationship_delta rows.

    When a diplomacy ledger is supplied, also check for treaty consequences:
    a ``non_aggression`` treaty between the thief and victim factions adds
    an extra trust hit *and* auto-breaks the treaty; a ``mutual_defense``
    treaty injects a defend-the-victim goal for each ally agent.
    """
    if decision_logger is None or not attempt.detected:
        return
    try:
        victim_reason = "theft_detected"
        victim_trust_hit = _VICTIM_TRUST_HIT
        thief_faction = None
        victim_faction = None
        broken_treaty_ids: list[str] = []
        if diplomacy_ledger is not None:
            thief_faction = diplomacy_ledger.get_faction_for(attempt.thief_id)
            victim_faction = diplomacy_ledger.get_faction_for(attempt.victim_id)
            if (
                thief_faction is not None
                and victim_faction is not None
                and thief_faction.faction_id != victim_faction.faction_id
            ):
                for treaty in diplomacy_ledger.treaties_between(
                    thief_faction.faction_id, victim_faction.faction_id
                ):
                    if not treaty.terms.get("non_aggression"):
                        continue
                    victim_reason = "theft_non_aggression_breach"
                    victim_trust_hit = _VICTIM_TRUST_HIT + _BREAKER_TRUST_HIT
                    broken = diplomacy_ledger.break_(
                        treaty.treaty_id,
                        breaker_id=attempt.thief_id,
                        reason="theft_non_aggression_breach",
                    )
                    if isinstance(broken, Treaty):
                        broken_treaty_ids.append(broken.treaty_id)
                        try:
                            decision_logger.log_diplomacy_event(
                                treaty_id=broken.treaty_id,
                                parties=list(broken.parties),
                                action="broken",
                                terms=dict(broken.terms),
                                breaker_id=attempt.thief_id,
                                reason="theft_non_aggression_breach",
                                actor_id=attempt.thief_id,
                            )
                        except Exception:  # pragma: no cover
                            logger.exception(
                                "decision_logger.log_diplomacy_event failed (auto-break treaty=%s)",
                                broken.treaty_id,
                            )

        decision_logger.log_relationship_delta(
            a=attempt.victim_id,
            b=attempt.thief_id,
            before={"trust": _DEFAULT_TRUST},
            after={"trust": _DEFAULT_TRUST - victim_trust_hit},
            reason=victim_reason,
        )
        for witness in attempt.witnesses:
            if witness == attempt.victim_id or witness == attempt.thief_id:
                continue
            decision_logger.log_relationship_delta(
                a=witness,
                b=attempt.thief_id,
                before={"trust": _DEFAULT_TRUST},
                after={"trust": _DEFAULT_TRUST - _WITNESS_TRUST_HIT},
                reason="theft_witnessed",
            )

        if (
            diplomacy_ledger is not None
            and victim_faction is not None
            and goal_manager is not None
        ):
            _inject_defense_goals(
                diplomacy_ledger=diplomacy_ledger,
                goal_manager=goal_manager,
                victim_id=attempt.victim_id,
                thief_id=attempt.thief_id,
                victim_faction_id=victim_faction.faction_id,
                simulation_id=simulation_id,
                decision_logger=decision_logger,
            )
    except Exception:  # pragma: no cover
        logger.exception(
            "decision_logger.log_relationship_delta failed (theft attempt=%s)",
            attempt.attempt_id,
        )


def _inject_defense_goals(
    *,
    diplomacy_ledger: DiplomacyLedger,
    goal_manager: AgentGoalManager,
    victim_id: str,
    thief_id: str,
    victim_faction_id: str,
    simulation_id: Any | None,
    decision_logger: DecisionLogger | None,
) -> None:
    """Add a `defend <victim>` goal to each mutual-defense ally agent."""
    try:
        defenders = diplomacy_ledger.mutual_defenders_of(victim_faction_id)
    except Exception:  # pragma: no cover
        logger.exception("diplomacy_ledger.mutual_defenders_of failed")
        return
    if not defenders:
        return
    description = f"defend {victim_id} from {thief_id}"
    for defender_id in defenders:
        if defender_id in {victim_id, thief_id}:
            continue
        try:
            coro = goal_manager.add_goal(
                agent_id=defender_id,
                goal_text=description,
                priority=2,
                source="treaty_mutual_defense",
                category="defense",
                simulation_id=simulation_id,
            )
        except TypeError:
            try:
                coro = goal_manager.add_goal(
                    agent_id=defender_id,
                    goal_text=description,
                    priority=2,
                    source="treaty_mutual_defense",
                )
            except Exception:  # pragma: no cover
                logger.exception(
                    "goal_manager.add_goal failed for defender=%s", defender_id
                )
                continue
        except Exception:  # pragma: no cover
            logger.exception(
                "goal_manager.add_goal failed for defender=%s", defender_id
            )
            continue
        if asyncio.iscoroutine(coro):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(coro)
            else:
                try:
                    asyncio.run(coro)
                except Exception:  # pragma: no cover
                    logger.exception("asyncio.run(add_goal) failed")
        if decision_logger is not None:
            try:
                decision_logger.log_new_goal(
                    actor_id=defender_id,
                    description=description,
                    category="defense",
                    priority=2,
                    source="treaty_mutual_defense",
                )
            except Exception:  # pragma: no cover
                logger.exception("decision_logger.log_new_goal failed")


def _theft_failure_response(failure: TheftFailure) -> dict[str, Any]:
    response: dict[str, Any] = {"status": "error", "reason": failure.reason}
    if failure.detail is not None:
        response["detail"] = failure.detail
    return response


class StealTool(BaseTool):
    """Attempt to steal items from another agent's container."""

    ALLOWED_AGENTS = _THIEF_AGENTS

    name = "steal"
    description = (
        "Attempt to take items from another agent's container. The ledger "
        "rolls a deterministic detection check; on detection the victim and "
        "any witnesses within proximity see the event and their trust in "
        "you drops. Items move atomically: if the container holds less than "
        "you asked for, you take only what's there. Provide a short "
        "motivation so the decision log captures *why* you stole."
    )
    parameters = {
        "victim_id": {
            "type": "string",
            "description": "Agent you're stealing from (e.g. 'rex').",
        },
        "container_ref": {
            "type": "object",
            "description": ("Container coords {x, y, z, dim?} — the chest you're taking from."),
        },
        "items": {
            "type": "object",
            "description": (
                "What you want to take: dict of material → positive integer "
                "quantity. Quantities above what the container holds are "
                "capped to available."
            ),
        },
        "motivation": {
            "type": "string",
            "description": "One short sentence on why you're risking it.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        theft_ledger: TheftLedger | None = None,
        decision_logger: DecisionLogger | None = None,
        tick_provider: Callable[[], int] | None = None,
        victim_online_provider: Callable[[str], bool] | None = None,
        diplomacy_ledger: DiplomacyLedger | None = None,
        goal_manager: AgentGoalManager | None = None,
        simulation_id_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = theft_ledger
        self._decision_logger = decision_logger
        self._tick_provider = tick_provider
        self._victim_online_provider = victim_online_provider
        self._diplomacy_ledger = diplomacy_ledger
        self._goal_manager = goal_manager
        self._simulation_id_provider = simulation_id_provider

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        simulation_id = kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "theft_ledger_unavailable"}

        victim_id = kwargs.get("victim_id")
        container_ref = kwargs.get("container_ref")
        items = kwargs.get("items")
        motivation = kwargs.get("motivation")

        if not isinstance(victim_id, str) or not victim_id:
            return {"status": "error", "reason": "victim_id is required"}
        if not isinstance(container_ref, dict) or not container_ref:
            return {
                "status": "error",
                "reason": "container_ref must be a non-empty object",
            }
        if items is not None and not isinstance(items, dict):
            return {"status": "error", "reason": "items must be an object"}
        if motivation is not None and not isinstance(motivation, str):
            return {"status": "error", "reason": "motivation must be a string"}

        tick = 0
        if self._tick_provider is not None:
            try:
                tick = int(self._tick_provider())
            except Exception:
                tick = 0
        victim_online = False
        if self._victim_online_provider is not None:
            try:
                victim_online = bool(self._victim_online_provider(victim_id))
            except Exception:
                victim_online = False

        result = self._ledger.attempt(
            thief_id=self._agent_id,
            victim_id=victim_id,
            container_ref=container_ref,
            items=items if isinstance(items, dict) else None,
            motivation=motivation if isinstance(motivation, str) else None,
            tick=tick,
            victim_online=victim_online,
        )
        if isinstance(result, TheftFailure):
            return _theft_failure_response(result)

        if simulation_id is None and self._simulation_id_provider is not None:
            try:
                simulation_id = self._simulation_id_provider()
            except Exception:
                simulation_id = None

        _log_theft(self._decision_logger, attempt=result, actor_id=self._agent_id)
        _emit_theft_consequences(
            self._decision_logger,
            attempt=result,
            diplomacy_ledger=self._diplomacy_ledger,
            goal_manager=self._goal_manager,
            simulation_id=simulation_id,
        )

        return {"status": "stolen", **_attempt_to_dict(result)}


class ReportTheftTool(BaseTool):
    """Witness reports a theft they observed; promotes undetected → detected."""

    ALLOWED_AGENTS = _BUILDER_AGENTS

    name = "report_theft"
    description = (
        "Report a theft you witnessed. If the ledger has a matching "
        "undetected attempt by this thief on this container, the report "
        "promotes it to detected — victim + witnesses see consequences "
        "applied even though the original roll missed."
    )
    parameters = {
        "thief_id": {
            "type": "string",
            "description": "The agent you saw stealing (e.g. 'grok').",
        },
        "container_ref": {
            "type": "object",
            "description": "Container coords {x, y, z, dim?} that was robbed.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        theft_ledger: TheftLedger | None = None,
        decision_logger: DecisionLogger | None = None,
        diplomacy_ledger: DiplomacyLedger | None = None,
        goal_manager: AgentGoalManager | None = None,
        simulation_id_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = theft_ledger
        self._decision_logger = decision_logger
        self._diplomacy_ledger = diplomacy_ledger
        self._goal_manager = goal_manager
        self._simulation_id_provider = simulation_id_provider

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        simulation_id = kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "theft_ledger_unavailable"}

        thief_id = kwargs.get("thief_id")
        container_ref = kwargs.get("container_ref")
        if not isinstance(thief_id, str) or not thief_id:
            return {"status": "error", "reason": "thief_id is required"}
        if not isinstance(container_ref, dict) or not container_ref:
            return {
                "status": "error",
                "reason": "container_ref must be a non-empty object",
            }

        result = self._ledger.report_theft(
            witness_id=self._agent_id,
            thief_id=thief_id,
            container_ref=container_ref,
        )
        if isinstance(result, TheftFailure):
            return _theft_failure_response(result)

        if simulation_id is None and self._simulation_id_provider is not None:
            try:
                simulation_id = self._simulation_id_provider()
            except Exception:
                simulation_id = None

        _log_theft(self._decision_logger, attempt=result, actor_id=self._agent_id)
        _emit_theft_consequences(
            self._decision_logger,
            attempt=result,
            diplomacy_ledger=self._diplomacy_ledger,
            goal_manager=self._goal_manager,
            simulation_id=simulation_id,
        )

        return {"status": "reported", **_attempt_to_dict(result)}


def _treaty_to_dict(treaty: Treaty) -> dict[str, Any]:
    return {
        "treaty_id": treaty.treaty_id,
        "parties": list(treaty.parties),
        "terms": dict(treaty.terms),
        "status": treaty.status,
        "proposer_id": treaty.proposer_id,
        "proposer_faction_id": treaty.proposer_faction_id,
        "motivation": treaty.motivation,
        "created_at": treaty.created_at.isoformat(),
        "signed_at": treaty.signed_at.isoformat() if treaty.signed_at else None,
        "broken_at": treaty.broken_at.isoformat() if treaty.broken_at else None,
        "breaker_id": treaty.breaker_id,
        "break_reason": treaty.break_reason,
    }


def _diplomacy_failure_response(failure: DiplomacyFailure) -> dict[str, Any]:
    response: dict[str, Any] = {"status": "error", "reason": failure.reason}
    if failure.treaty_id is not None:
        response["treaty_id"] = failure.treaty_id
    if failure.detail is not None:
        response["detail"] = failure.detail
    return response


def _log_diplomacy(
    decision_logger: DecisionLogger | None,
    *,
    treaty_id: str | None,
    parties: list[str],
    action: str,
    terms: dict[str, Any] | None = None,
    breaker_id: str | None = None,
    defector_id: str | None = None,
    from_faction: str | None = None,
    to_faction: str | None = None,
    motivation: str | None = None,
    reason: str | None = None,
    actor_id: str | None = None,
) -> None:
    if decision_logger is None:
        return
    try:
        decision_logger.log_diplomacy_event(
            treaty_id=treaty_id,
            parties=list(parties or []),
            action=action,
            terms=dict(terms or {}),
            breaker_id=breaker_id,
            defector_id=defector_id,
            from_faction=from_faction,
            to_faction=to_faction,
            motivation=motivation,
            reason=reason,
            actor_id=actor_id,
        )
    except Exception:  # pragma: no cover - logger must not break the sim
        logger.exception(
            "decision_logger.log_diplomacy_event failed (action=%s treaty=%s)",
            action,
            treaty_id,
        )


class ProposeTreatyTool(BaseTool):
    """Propose a treaty (alliance/non-aggression/etc.) to another faction."""

    ALLOWED_AGENTS = _DIPLOMAT_AGENTS

    name = "propose_treaty"
    description = (
        "Offer another faction a treaty: pass the other faction_id and a "
        "terms object with any of {'non_aggression': true, "
        "'trade_preference': true, 'mutual_defense': true}. The treaty "
        "sits in 'proposed' status until a member of the other faction "
        "signs it. Provide a short motivation so the decision log captures "
        "why."
    )
    parameters = {
        "other_faction_id": {
            "type": "string",
            "description": "Counterparty faction_id (slug from scenario YAML).",
        },
        "terms": {
            "type": "object",
            "description": (
                "Treaty terms: any of non_aggression, trade_preference, "
                "mutual_defense — boolean values."
            ),
        },
        "motivation": {
            "type": "string",
            "description": "One short sentence on why this treaty matters now.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: DiplomacyLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "diplomacy_ledger_unavailable"}

        other_faction_id = kwargs.get("other_faction_id")
        terms = kwargs.get("terms")
        motivation = kwargs.get("motivation")

        if not isinstance(other_faction_id, str) or not other_faction_id:
            return {"status": "error", "reason": "other_faction_id is required"}
        if terms is not None and not isinstance(terms, dict):
            return {"status": "error", "reason": "terms must be an object"}
        if motivation is not None and not isinstance(motivation, str):
            return {"status": "error", "reason": "motivation must be a string"}

        proposer_faction = self._ledger.get_faction_for(self._agent_id)
        if proposer_faction is None:
            return {
                "status": "error",
                "reason": "agent_not_in_faction",
                "detail": f"{self._agent_id!r} is not a member of any faction",
            }

        result = self._ledger.propose(
            proposer_id=self._agent_id,
            proposer_faction_id=proposer_faction.faction_id,
            other_faction_id=other_faction_id,
            terms=terms if isinstance(terms, dict) else None,
            motivation=motivation if isinstance(motivation, str) else None,
        )
        if isinstance(result, DiplomacyFailure):
            return _diplomacy_failure_response(result)

        _log_diplomacy(
            self._decision_logger,
            treaty_id=result.treaty_id,
            parties=list(result.parties),
            action="proposed",
            terms=dict(result.terms),
            motivation=result.motivation,
            actor_id=self._agent_id,
        )
        return {**_treaty_to_dict(result), "status": "proposed"}


class SignTreatyTool(BaseTool):
    """Sign a proposed treaty on behalf of your faction."""

    ALLOWED_AGENTS = _DIPLOMAT_AGENTS

    name = "sign_treaty"
    description = (
        "Sign a treaty that was proposed to your faction. Treaties activate "
        "as soon as a counterparty member signs — the proposer faction "
        "cannot also sign. Returns an error if the treaty is unknown, "
        "already active, or addressed to a faction you don't belong to."
    )
    parameters = {
        "treaty_id": {
            "type": "string",
            "description": "treaty_id from an earlier propose_treaty.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: DiplomacyLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "diplomacy_ledger_unavailable"}

        treaty_id = kwargs.get("treaty_id")
        if not isinstance(treaty_id, str) or not treaty_id:
            return {"status": "error", "reason": "treaty_id is required"}

        signer_faction = self._ledger.get_faction_for(self._agent_id)
        signer_faction_id = signer_faction.faction_id if signer_faction else None

        result = self._ledger.sign(
            treaty_id,
            signer_id=self._agent_id,
            signer_faction_id=signer_faction_id,
        )
        if isinstance(result, DiplomacyFailure):
            return _diplomacy_failure_response(result)

        _log_diplomacy(
            self._decision_logger,
            treaty_id=result.treaty_id,
            parties=list(result.parties),
            action="signed",
            terms=dict(result.terms),
            actor_id=self._agent_id,
        )
        return {**_treaty_to_dict(result), "status": "signed"}


class BreakTreatyTool(BaseTool):
    """Withdraw from an active treaty."""

    ALLOWED_AGENTS = _DIPLOMAT_AGENTS

    name = "break_treaty"
    description = (
        "Break an active treaty by treaty_id. Other parties take a trust "
        "hit toward your faction and the treaty is recorded as broken. "
        "Provide a short reason so the decision log captures why."
    )
    parameters = {
        "treaty_id": {
            "type": "string",
            "description": "treaty_id of the active treaty to break.",
        },
        "reason": {
            "type": "string",
            "description": "Short reason for breaking the treaty.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: DiplomacyLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "diplomacy_ledger_unavailable"}

        treaty_id = kwargs.get("treaty_id")
        reason = kwargs.get("reason")
        if not isinstance(treaty_id, str) or not treaty_id:
            return {"status": "error", "reason": "treaty_id is required"}
        if not isinstance(reason, str) or not reason.strip():
            return {"status": "error", "reason": "reason is required"}

        result = self._ledger.break_(
            treaty_id, breaker_id=self._agent_id, reason=reason.strip()
        )
        if isinstance(result, DiplomacyFailure):
            return _diplomacy_failure_response(result)

        _log_diplomacy(
            self._decision_logger,
            treaty_id=result.treaty_id,
            parties=list(result.parties),
            action="broken",
            terms=dict(result.terms),
            breaker_id=self._agent_id,
            reason=reason.strip(),
            actor_id=self._agent_id,
        )

        # Apply the breaker trust hit to every member of every other
        # treaty party — those members see their faction's word betrayed.
        if self._decision_logger is not None:
            breaker_faction = self._ledger.get_faction_for(self._agent_id)
            breaker_faction_id = (
                breaker_faction.faction_id if breaker_faction else None
            )
            for party_id in result.parties:
                if party_id == breaker_faction_id:
                    continue
                party = self._ledger.get_faction(party_id)
                if party is None:
                    continue
                for member_id in sorted(party.members):
                    if member_id == self._agent_id:
                        continue
                    try:
                        self._decision_logger.log_relationship_delta(
                            a=member_id,
                            b=self._agent_id,
                            before={"trust": _DEFAULT_TRUST},
                            after={"trust": _DEFAULT_TRUST - _BREAKER_TRUST_HIT},
                            reason="treaty_broken",
                        )
                    except Exception:  # pragma: no cover
                        logger.exception(
                            "decision_logger.log_relationship_delta failed (treaty break)"
                        )

        return {**_treaty_to_dict(result), "status": "broken"}


class DefectFactionTool(BaseTool):
    """Leave the calling agent's current faction for another."""

    ALLOWED_AGENTS = _DIPLOMAT_AGENTS

    name = "defect_faction"
    description = (
        "Leave your current faction and join another. The target faction "
        "must exist in the scenario. Provide a short motivation so the "
        "decision log captures why."
    )
    parameters = {
        "target_faction_id": {
            "type": "string",
            "description": "The faction_id you want to join.",
        },
        "motivation": {
            "type": "string",
            "description": "One short sentence on why you're switching sides.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: DiplomacyLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "diplomacy_ledger_unavailable"}

        target_faction_id = kwargs.get("target_faction_id")
        motivation = kwargs.get("motivation")
        if not isinstance(target_faction_id, str) or not target_faction_id:
            return {"status": "error", "reason": "target_faction_id is required"}
        if motivation is not None and not isinstance(motivation, str):
            return {"status": "error", "reason": "motivation must be a string"}

        result = self._ledger.defect(
            agent_id=self._agent_id,
            target_faction_id=target_faction_id,
            motivation=motivation if isinstance(motivation, str) else None,
        )
        if isinstance(result, DiplomacyFailure):
            return _diplomacy_failure_response(result)

        old_faction_id, new_faction_id = result
        _log_diplomacy(
            self._decision_logger,
            treaty_id=None,
            parties=[],
            action="defected",
            defector_id=self._agent_id,
            from_faction=old_faction_id,
            to_faction=new_faction_id,
            motivation=motivation.strip() if isinstance(motivation, str) else None,
            actor_id=self._agent_id,
        )
        return {
            "status": "defected",
            "agent_id": self._agent_id,
            "from_faction_id": old_faction_id,
            "to_faction_id": new_faction_id,
            "motivation": motivation.strip() if isinstance(motivation, str) else None,
        }


class ListActiveTreatiesTool(BaseTool):
    """List active treaties involving the calling agent's faction."""

    ALLOWED_AGENTS = _DIPLOMAT_AGENTS

    name = "list_active_treaties"
    description = (
        "List every active treaty your faction is currently a party to. "
        "Returns an empty list when you're not in a faction or no "
        "treaties are active."
    )
    parameters: dict[str, Any] = {}

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: DiplomacyLedger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "diplomacy_ledger_unavailable"}

        faction = self._ledger.get_faction_for(self._agent_id)
        faction_id = faction.faction_id if faction else None
        treaties = self._ledger.list_active_treaties(faction_id)
        return {
            "status": "ok",
            "agent_id": self._agent_id,
            "faction_id": faction_id,
            "count": len(treaties),
            "treaties": [_treaty_to_dict(t) for t in treaties],
        }


_CONFLICT_AGENTS = _BUILDER_AGENTS


def _dispute_to_dict(dispute: Dispute) -> dict[str, Any]:
    return {
        "dispute_id": dispute.dispute_id,
        "initiator_id": dispute.initiator_id,
        "respondent_id": dispute.respondent_id,
        "dispute_type": dispute.dispute_type,
        "evidence": [e.model_dump() for e in dispute.evidence],
        "status": dispute.status,
        "motivation": dispute.motivation,
        "judgement": dispute.judgement,
        "outcome": dict(dispute.outcome or {}),
        "created_at": dispute.created_at.isoformat(),
        "judged_at": dispute.judged_at.isoformat() if dispute.judged_at else None,
        "resolved_at": dispute.resolved_at.isoformat() if dispute.resolved_at else None,
    }


def _war_to_dict(war: WarIntent) -> dict[str, Any]:
    return {
        "war_id": war.war_id,
        "initiator_id": war.initiator_id,
        "initiator_faction_id": war.initiator_faction_id,
        "target_faction_id": war.target_faction_id,
        "casus_belli": war.casus_belli,
        "motivation": war.motivation,
        "seconders": sorted(war.seconders),
        "required_quorum": war.required_quorum,
        "status": war.status,
        "created_at": war.created_at.isoformat(),
        "activated_at": war.activated_at.isoformat() if war.activated_at else None,
        "resolved_at": war.resolved_at.isoformat() if war.resolved_at else None,
        "surrender_terms": dict(war.surrender_terms or {}),
    }


def _conflict_failure_response(failure: ConflictFailure) -> dict[str, Any]:
    response: dict[str, Any] = {"status": "error", "reason": failure.reason}
    if failure.dispute_id is not None:
        response["dispute_id"] = failure.dispute_id
    if failure.war_id is not None:
        response["war_id"] = failure.war_id
    if failure.detail is not None:
        response["detail"] = failure.detail
    return response


def _log_conflict(
    decision_logger: DecisionLogger | None,
    *,
    action: str,
    dispute_id: str | None = None,
    war_id: str | None = None,
    initiator_id: str | None = None,
    respondent_id: str | None = None,
    dispute_type: str | None = None,
    outcome: dict[str, Any] | None = None,
    judgement: str | None = None,
    terms: dict[str, Any] | None = None,
    motivation: str | None = None,
    reason: str | None = None,
    casus_belli: str | None = None,
    target_faction_id: str | None = None,
    initiator_faction_id: str | None = None,
    seconders: list[str] | None = None,
    required_quorum: int | None = None,
    actor_id: str | None = None,
) -> None:
    if decision_logger is None:
        return
    try:
        decision_logger.log_conflict_event(
            action=action,
            dispute_id=dispute_id,
            war_id=war_id,
            initiator_id=initiator_id,
            respondent_id=respondent_id,
            dispute_type=dispute_type,
            outcome=outcome,
            judgement=judgement,
            terms=terms,
            motivation=motivation,
            reason=reason,
            casus_belli=casus_belli,
            target_faction_id=target_faction_id,
            initiator_faction_id=initiator_faction_id,
            seconders=seconders,
            required_quorum=required_quorum,
            actor_id=actor_id,
        )
    except Exception:  # pragma: no cover - logger must not break the sim
        logger.exception(
            "decision_logger.log_conflict_event failed (action=%s)", action
        )


def _emit_conflict_consequences(
    decision_logger: DecisionLogger | None,
    *,
    consequences: list[dict[str, Any]],
    actor_id: str | None = None,
) -> None:
    """Mirror the ledger's consequence summaries into the decision log."""
    if decision_logger is None:
        return
    for c in consequences:
        kind = c.get("kind")
        try:
            if kind == "relationship_delta":
                decision_logger.log_relationship_delta(
                    a=str(c.get("a") or ""),
                    b=str(c.get("b") or ""),
                    before=dict(c.get("before") or {}),
                    after=dict(c.get("after") or {}),
                    reason=c.get("reason"),
                )
            elif kind == "ownership_transfer":
                target_type = c.get("target_type")
                target_ref = c.get("target_ref") or {}
                if c.get("released_claim_id"):
                    decision_logger.log_ownership_delta(
                        claim_id=c["released_claim_id"],
                        owner_agent_id=str(c.get("from_agent") or ""),
                        target_type=str(target_type or "structure"),
                        target_ref=dict(target_ref),
                        action="release",
                        motivation="dispute_resolution",
                        actor_id=actor_id,
                    )
                if c.get("new_claim_id"):
                    decision_logger.log_ownership_delta(
                        claim_id=c["new_claim_id"],
                        owner_agent_id=str(c.get("to_agent") or ""),
                        target_type=str(target_type or "structure"),
                        target_ref=dict(target_ref),
                        action="claim",
                        motivation="dispute_resolution",
                        actor_id=actor_id,
                    )
            elif kind == "restitution_offer":
                decision_logger.log_trade_event(
                    offer_id=str(c.get("offer_id") or ""),
                    proposer_id=str(c.get("from_agent") or ""),
                    recipient_id=str(c.get("to_agent") or ""),
                    give=dict(c.get("items") or {}),
                    want={},
                    action="proposed",
                    motivation="restitution",
                    actor_id=actor_id,
                )
            elif kind == "treaty_break":
                decision_logger.log_diplomacy_event(
                    treaty_id=str(c.get("treaty_id") or ""),
                    parties=list(c.get("parties") or []),
                    action="broken",
                    breaker_id=c.get("breaker_id"),
                    reason=c.get("reason"),
                    actor_id=actor_id,
                )
        except Exception:  # pragma: no cover
            logger.exception("conflict consequence logging failed (kind=%s)", kind)


class OpenDisputeTool(BaseTool):
    """File a dispute against another agent (#895)."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "open_dispute"
    description = (
        "Open a formal dispute against another agent. Pick a dispute_type "
        "(territorial / theft / trade_breach / treaty_violation / personal) "
        "and pass evidence_refs as a list of {ref_type, ref_id, narrative?} "
        "pointing at prior theft, trade, ownership, diplomacy, or utterance "
        "events. The dispute sits in 'open' status until someone requests "
        "judgement."
    )
    parameters = {
        "respondent_id": {
            "type": "string",
            "description": "The agent you're filing the dispute against.",
        },
        "dispute_type": {
            "type": "string",
            "description": "One of territorial/theft/trade_breach/treaty_violation/personal.",
            "enum": [
                "territorial",
                "theft",
                "trade_breach",
                "treaty_violation",
                "personal",
            ],
        },
        "evidence_refs": {
            "type": "array",
            "description": (
                "List of evidence entries: each is {ref_type, ref_id, narrative?}."
            ),
        },
        "motivation": {
            "type": "string",
            "description": "One short sentence on why this dispute matters now.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        respondent_id = kwargs.get("respondent_id")
        dispute_type = kwargs.get("dispute_type")
        evidence_refs = kwargs.get("evidence_refs")
        motivation = kwargs.get("motivation")

        if not isinstance(respondent_id, str) or not respondent_id:
            return {"status": "error", "reason": "respondent_id is required"}
        if not isinstance(dispute_type, str):
            return {"status": "error", "reason": "dispute_type is required"}
        if evidence_refs is not None and not isinstance(evidence_refs, list):
            return {"status": "error", "reason": "evidence_refs must be a list"}
        if motivation is not None and not isinstance(motivation, str):
            return {"status": "error", "reason": "motivation must be a string"}

        result = self._ledger.open_dispute(
            initiator_id=self._agent_id,
            respondent_id=respondent_id,
            dispute_type=dispute_type,
            evidence_refs=evidence_refs if isinstance(evidence_refs, list) else None,
            motivation=motivation if isinstance(motivation, str) else None,
        )
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        _log_conflict(
            self._decision_logger,
            action="opened",
            dispute_id=result.dispute_id,
            initiator_id=result.initiator_id,
            respondent_id=result.respondent_id,
            dispute_type=result.dispute_type,
            motivation=result.motivation,
            actor_id=self._agent_id,
        )
        return {**_dispute_to_dict(result), "status": "opened"}


class SubmitEvidenceTool(BaseTool):
    """Add an evidence ref to an open dispute (#895)."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "submit_evidence"
    description = (
        "Attach an additional evidence ref to an open dispute you're a "
        "party to. Pass evidence_ref={ref_type, ref_id} plus an optional "
        "narrative. Duplicate (ref_type, ref_id) pairs are rejected."
    )
    parameters = {
        "dispute_id": {
            "type": "string",
            "description": "The dispute_id from open_dispute.",
        },
        "evidence_ref": {
            "type": "object",
            "description": "{ref_type, ref_id} pointing to a prior log entry.",
        },
        "narrative": {
            "type": "string",
            "description": "Short narrative tying the evidence to the dispute.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        dispute_id = kwargs.get("dispute_id")
        evidence_ref = kwargs.get("evidence_ref")
        narrative = kwargs.get("narrative")

        if not isinstance(dispute_id, str) or not dispute_id:
            return {"status": "error", "reason": "dispute_id is required"}
        if not isinstance(evidence_ref, dict) or not evidence_ref:
            return {"status": "error", "reason": "evidence_ref must be an object"}

        result = self._ledger.submit_evidence(
            dispute_id,
            submitter_id=self._agent_id,
            evidence_ref=evidence_ref,
            narrative=narrative if isinstance(narrative, str) else None,
        )
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        _log_conflict(
            self._decision_logger,
            action="evidence_submitted",
            dispute_id=result.dispute_id,
            initiator_id=result.initiator_id,
            respondent_id=result.respondent_id,
            dispute_type=result.dispute_type,
            actor_id=self._agent_id,
        )
        return {**_dispute_to_dict(result), "status": "evidence_submitted"}


class RequestJudgementTool(BaseTool):
    """Ask a neutral judge (or majority vote) to rule on a dispute (#895)."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "request_judgement"
    description = (
        "Request judgement on an open dispute. The ledger auto-judges "
        "deterministically: same seed + same evidence → same ruling. The "
        "judge_id is optional metadata so the decision log captures who "
        "arbitrated. Returns the dispute with judgement + outcome."
    )
    parameters = {
        "dispute_id": {
            "type": "string",
            "description": "The dispute_id to rule on.",
        },
        "judge_id": {
            "type": "string",
            "description": "Optional id of the agent acting as judge.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        dispute_id = kwargs.get("dispute_id")
        judge_id = kwargs.get("judge_id")
        if not isinstance(dispute_id, str) or not dispute_id:
            return {"status": "error", "reason": "dispute_id is required"}

        result = self._ledger.request_judgement(
            dispute_id,
            judge_id=judge_id if isinstance(judge_id, str) and judge_id else None,
        )
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        _log_conflict(
            self._decision_logger,
            action="judged",
            dispute_id=result.dispute_id,
            initiator_id=result.initiator_id,
            respondent_id=result.respondent_id,
            dispute_type=result.dispute_type,
            judgement=result.judgement,
            outcome=dict(result.outcome or {}),
            actor_id=self._agent_id,
        )
        return {**_dispute_to_dict(result), "status": "judged"}


class AcceptJudgementTool(BaseTool):
    """Losing party accepts a judgement (or escalates to war) (#895)."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "accept_judgement"
    description = (
        "Only the losing party of a judged dispute can call this. Pass "
        "accept=true to resolve the dispute (consequences apply per "
        "dispute_type — ownership transfer, restitution, treaty break, or "
        "relationship hit). Pass accept=false to escalate, marking the "
        "dispute escalated so callers can issue a declare_war if desired."
    )
    parameters = {
        "dispute_id": {
            "type": "string",
            "description": "The dispute_id under judgement.",
        },
        "accept": {
            "type": "boolean",
            "description": "true to accept and resolve, false to escalate.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        dispute_id = kwargs.get("dispute_id")
        accept = kwargs.get("accept")
        if not isinstance(dispute_id, str) or not dispute_id:
            return {"status": "error", "reason": "dispute_id is required"}
        if not isinstance(accept, bool):
            return {"status": "error", "reason": "accept must be boolean"}

        result = self._ledger.accept_judgement(
            dispute_id,
            accepting_agent_id=self._agent_id,
            accept=accept,
        )
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        updated, consequences = result
        action = "resolved" if accept else "escalated"
        _log_conflict(
            self._decision_logger,
            action=action,
            dispute_id=updated.dispute_id,
            initiator_id=updated.initiator_id,
            respondent_id=updated.respondent_id,
            dispute_type=updated.dispute_type,
            judgement=updated.judgement,
            outcome=dict(updated.outcome or {}),
            actor_id=self._agent_id,
        )
        if accept:
            _emit_conflict_consequences(
                self._decision_logger,
                consequences=consequences,
                actor_id=self._agent_id,
            )
        return {
            **_dispute_to_dict(updated),
            "status": action,
            "consequences": consequences,
        }


class DeclareWarTool(BaseTool):
    """Declare war on another faction (#895). Requires faction quorum."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "declare_war"
    description = (
        "Declare war on another faction. The war is 'pending' until a "
        "majority of your faction members second the call via second_war "
        "(your declaration counts as the first second). Provide a "
        "casus_belli describing what justifies it."
    )
    parameters = {
        "target_faction_id": {
            "type": "string",
            "description": "The faction_id you're declaring war on.",
        },
        "casus_belli": {
            "type": "string",
            "description": "Short justification for the war.",
        },
        "motivation": {
            "type": "string",
            "description": "Optional one-line motivation for the decision log.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        target_faction_id = kwargs.get("target_faction_id")
        casus_belli = kwargs.get("casus_belli")
        motivation = kwargs.get("motivation")
        if not isinstance(target_faction_id, str) or not target_faction_id:
            return {"status": "error", "reason": "target_faction_id is required"}
        if not isinstance(casus_belli, str) or not casus_belli.strip():
            return {"status": "error", "reason": "casus_belli is required"}

        result = self._ledger.declare_war(
            initiator_id=self._agent_id,
            target_faction_id=target_faction_id,
            casus_belli=casus_belli,
            motivation=motivation if isinstance(motivation, str) else None,
        )
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        _log_conflict(
            self._decision_logger,
            action="war_declared",
            war_id=result.war_id,
            initiator_id=result.initiator_id,
            initiator_faction_id=result.initiator_faction_id,
            target_faction_id=result.target_faction_id,
            casus_belli=result.casus_belli,
            motivation=result.motivation,
            seconders=sorted(result.seconders),
            required_quorum=result.required_quorum,
            actor_id=self._agent_id,
        )
        if result.status == "active":
            _log_conflict(
                self._decision_logger,
                action="war_activated",
                war_id=result.war_id,
                initiator_faction_id=result.initiator_faction_id,
                target_faction_id=result.target_faction_id,
                actor_id=self._agent_id,
            )
        return {**_war_to_dict(result), "status": result.status}


class SecondWarTool(BaseTool):
    """Second a pending war declaration to push toward quorum (#895)."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "second_war"
    description = (
        "Second a pending war declaration to help reach faction quorum. "
        "You must be a member of the declaring faction. Returns the war "
        "with updated seconders list; activates automatically once "
        "majority is reached."
    )
    parameters = {
        "war_id": {
            "type": "string",
            "description": "The war_id you want to second.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        war_id = kwargs.get("war_id")
        if not isinstance(war_id, str) or not war_id:
            return {"status": "error", "reason": "war_id is required"}

        prev_status = None
        existing = self._ledger.get_war(war_id)
        if existing is not None:
            prev_status = existing.status

        result = self._ledger.second_war(war_id, seconder_id=self._agent_id)
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        _log_conflict(
            self._decision_logger,
            action="war_seconded",
            war_id=result.war_id,
            initiator_id=result.initiator_id,
            initiator_faction_id=result.initiator_faction_id,
            target_faction_id=result.target_faction_id,
            seconders=sorted(result.seconders),
            required_quorum=result.required_quorum,
            actor_id=self._agent_id,
        )
        if result.status == "active" and prev_status != "active":
            _log_conflict(
                self._decision_logger,
                action="war_activated",
                war_id=result.war_id,
                initiator_faction_id=result.initiator_faction_id,
                target_faction_id=result.target_faction_id,
                actor_id=self._agent_id,
            )
        return {**_war_to_dict(result), "status": result.status}


class SurrenderTool(BaseTool):
    """Surrender a war or open/judged dispute with concessions (#895)."""

    ALLOWED_AGENTS = _CONFLICT_AGENTS

    name = "surrender"
    description = (
        "Yield concessions to end a conflict. Pass either a war_id or a "
        "dispute_id under 'target_id' (the tool accepts both). 'terms' is "
        "a free-form object describing the concessions — they are "
        "recorded on the resolution but the ledger does not auto-apply "
        "them; the surrendering side is responsible for honouring them "
        "via subsequent tool calls."
    )
    parameters = {
        "target_id": {
            "type": "string",
            "description": "A war_id or dispute_id to surrender.",
        },
        "terms": {
            "type": "object",
            "description": "Concessions offered to end the conflict.",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._ledger = ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        if self._ledger is None:
            return {"status": "error", "reason": "conflict_ledger_unavailable"}

        target_id = kwargs.get("target_id")
        terms = kwargs.get("terms")
        if not isinstance(target_id, str) or not target_id:
            return {"status": "error", "reason": "target_id is required"}
        if terms is not None and not isinstance(terms, dict):
            return {"status": "error", "reason": "terms must be an object"}

        result = self._ledger.surrender(
            target_id,
            surrendering_agent_id=self._agent_id,
            terms=terms if isinstance(terms, dict) else None,
        )
        if isinstance(result, ConflictFailure):
            return _conflict_failure_response(result)

        if isinstance(result, WarIntent):
            _log_conflict(
                self._decision_logger,
                action="surrendered",
                war_id=result.war_id,
                initiator_faction_id=result.initiator_faction_id,
                target_faction_id=result.target_faction_id,
                terms=dict(result.surrender_terms or {}),
                actor_id=self._agent_id,
            )
            return {**_war_to_dict(result), "status": "surrendered"}

        _log_conflict(
            self._decision_logger,
            action="surrendered",
            dispute_id=result.dispute_id,
            initiator_id=result.initiator_id,
            respondent_id=result.respondent_id,
            dispute_type=result.dispute_type,
            terms=dict((result.outcome or {}).get("terms") or {}),
            actor_id=self._agent_id,
        )
        return {**_dispute_to_dict(result), "status": "surrendered"}


__all__ = [
    "AcceptJudgementTool",
    "AcceptTradeTool",
    "BreakTreatyTool",
    "ClaimOwnershipTool",
    "DeclareWarTool",
    "DefectFactionTool",
    "GetOwnershipTool",
    "ListActiveTreatiesTool",
    "ListMyClaimsTool",
    "ListPendingTradesTool",
    "OpenDisputeTool",
    "ProposeTradeTool",
    "ProposeTreatyTool",
    "RejectTradeTool",
    "ReleaseOwnershipTool",
    "ReportTheftTool",
    "RequestJudgementTool",
    "SecondWarTool",
    "SignTreatyTool",
    "StealTool",
    "SubmitEvidenceTool",
    "SurrenderTool",
]
