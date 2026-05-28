"""Civilization tools (issues #891 ownership, #892 trade, #893 theft).

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

The mutating tools write an ``ownership_delta`` / ``trade_event`` /
``theft_event`` row to the decision logger directly when one is injected —
the ARTIFACT_CREATED event emitted by :meth:`BaseTool.run` only carries the
tool name, not its args or result, so we cannot reconstruct the delta from
that event alone. The ``ARTIFACT_CREATED`` event still fires (via
``BaseTool.run``) so the existing tool_intent capture path keeps recording
these as tool calls.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
)
from core.civilization.theft import TheftAttempt, TheftFailure, TheftLedger
from core.civilization.trade import TradeFailure, TradeLedger, TradeOffer

from .base import BaseTool

if TYPE_CHECKING:
    from core.simulation.decision_logger import DecisionLogger

logger = logging.getLogger(__name__)

_TARGET_TYPES = ("region", "structure", "container")
_BUILDER_AGENTS = frozenset({"vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"})
_TRADER_AGENTS = frozenset({"vera", "rex", "pixel", "sentinel", "fork"})
_THIEF_AGENTS = frozenset({"grok", "fork", "pixel"})

# Magnitude of trust hit per consequence (per spec):
#   detected theft → victim trust toward thief drops 0.5
#   detected theft → each witness trust toward thief drops 0.2
_VICTIM_TRUST_HIT = 0.5
_WITNESS_TRUST_HIT = 0.2
_DEFAULT_TRUST = 0.5


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
) -> None:
    """Apply victim + witness trust hits as relationship_delta rows."""
    if decision_logger is None or not attempt.detected:
        return
    try:
        decision_logger.log_relationship_delta(
            a=attempt.victim_id,
            b=attempt.thief_id,
            before={"trust": _DEFAULT_TRUST},
            after={"trust": _DEFAULT_TRUST - _VICTIM_TRUST_HIT},
            reason="theft_detected",
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
    except Exception:  # pragma: no cover
        logger.exception(
            "decision_logger.log_relationship_delta failed (theft attempt=%s)",
            attempt.attempt_id,
        )


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
    ) -> None:
        self._agent_id = agent_id
        self._ledger = theft_ledger
        self._decision_logger = decision_logger
        self._tick_provider = tick_provider
        self._victim_online_provider = victim_online_provider

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
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

        _log_theft(self._decision_logger, attempt=result, actor_id=self._agent_id)
        _emit_theft_consequences(self._decision_logger, attempt=result)

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
    ) -> None:
        self._agent_id = agent_id
        self._ledger = theft_ledger
        self._decision_logger = decision_logger

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
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

        _log_theft(self._decision_logger, attempt=result, actor_id=self._agent_id)
        _emit_theft_consequences(self._decision_logger, attempt=result)

        return {"status": "reported", **_attempt_to_dict(result)}


__all__ = [
    "AcceptTradeTool",
    "ClaimOwnershipTool",
    "GetOwnershipTool",
    "ListMyClaimsTool",
    "ListPendingTradesTool",
    "ProposeTradeTool",
    "RejectTradeTool",
    "ReleaseOwnershipTool",
    "ReportTheftTool",
    "StealTool",
]
