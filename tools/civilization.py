"""Civilization ownership tools (issue #891).

Four BaseTool subclasses backed by a shared
:class:`core.civilization.ownership.OwnershipLedger`:

* :class:`ClaimOwnershipTool` — claim a structure / container / region.
* :class:`ReleaseOwnershipTool` — release an active claim by id.
* :class:`GetOwnershipTool` — read-only lookup; returns owner or null.
* :class:`ListMyClaimsTool` — read-only introspection of the caller's holdings.

The mutating tools (claim/release) write an ``ownership_delta`` row to the
decision logger directly when one is injected — the ARTIFACT_CREATED event
emitted by :meth:`BaseTool.run` only carries the tool name, not its args
or result, so we cannot reconstruct the delta from that event alone. The
``ARTIFACT_CREATED`` event still fires (via ``BaseTool.run``) so the
existing tool_intent capture path keeps recording these as tool calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
)

from .base import BaseTool

if TYPE_CHECKING:
    from core.simulation.decision_logger import DecisionLogger

logger = logging.getLogger(__name__)

_TARGET_TYPES = ("region", "structure", "container")
_BUILDER_AGENTS = frozenset({"vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"})


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


__all__ = [
    "ClaimOwnershipTool",
    "GetOwnershipTool",
    "ListMyClaimsTool",
    "ReleaseOwnershipTool",
]
