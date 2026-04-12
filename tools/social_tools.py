"""Agent tools for alliance management — propose, vote, leave, view."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.base import BaseTool

if TYPE_CHECKING:
    from core.social.alliances import AllianceManager

logger = logging.getLogger(__name__)


class ProposeAllianceTool(BaseTool):
    """Propose forming an alliance with other agents."""

    name = "propose_alliance"
    description = (
        "Propose a new alliance with other agents. Invitees will vote to accept or reject. "
        "Alliances let you coordinate goals, share resources, and boost each other."
    )
    parameters = {
        "alliance_name": {
            "type": "string",
            "description": "A name for the alliance (chosen by you)",
        },
        "invitees": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of agent IDs to invite (e.g., ['rex', 'aurora'])",
        },
        "purpose": {
            "type": "string",
            "description": "Why this alliance should exist",
        },
    }

    def __init__(
        self,
        *,
        alliance_manager: AllianceManager | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._alliance_mgr = alliance_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._alliance_mgr is None:
            return {"status": "error", "reason": "Alliance system not available"}

        proposal = await self._alliance_mgr.propose_alliance(
            proposer_id=self._agent_id,
            name=kwargs["alliance_name"],
            invitees=kwargs["invitees"],
            purpose=kwargs.get("purpose", ""),
            simulation_id=kwargs.get("simulation_id"),
        )

        if proposal is None:
            return {
                "status": "error",
                "reason": "Cannot propose alliance (you may already be in too many)",
            }

        return {
            "status": "proposed",
            "proposal_id": proposal.id,
            "alliance_name": proposal.alliance_name,
            "invitees": proposal.invitees,
            "message": f"Alliance '{proposal.alliance_name}' proposed. Waiting for votes.",
        }


class VoteAllianceTool(BaseTool):
    """Vote on a pending alliance proposal."""

    name = "vote_alliance"
    description = (
        "Accept or reject a pending alliance proposal. "
        "Consider whether the alliance aligns with your goals."
    )
    parameters = {
        "proposal_id": {
            "type": "string",
            "description": "The ID of the alliance proposal",
        },
        "accept": {
            "type": "string",
            "description": "'yes' to join the alliance, 'no' to reject",
            "enum": ["yes", "no"],
        },
    }

    def __init__(
        self,
        *,
        alliance_manager: AllianceManager | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._alliance_mgr = alliance_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._alliance_mgr is None:
            return {"status": "error", "reason": "Alliance system not available"}

        accept = kwargs["accept"].lower() == "yes"
        try:
            from uuid import UUID
            UUID(kwargs["proposal_id"])
        except (ValueError, AttributeError):
            return {"status": "error", "reason": "Invalid proposal_id (not a valid UUID)"}
        result = await self._alliance_mgr.vote_on_proposal(
            proposal_id=kwargs["proposal_id"],
            agent_id=self._agent_id,
            accept=accept,
            simulation_id=kwargs.get("simulation_id"),
        )

        if result is None:
            return {"status": "error", "reason": "Proposal not found"}

        from core.social.alliances import Alliance
        if isinstance(result, Alliance):
            return {
                "status": "alliance_formed",
                "alliance_name": result.name,
                "members": result.members,
                "message": f"Alliance '{result.name}' has been formed!",
            }

        return {
            "status": "voted",
            "vote": "accepted" if accept else "rejected",
            "proposal_status": result.status,
            "message": "Your vote has been recorded.",
        }


class LeaveAllianceTool(BaseTool):
    """Leave an alliance you're a member of."""

    name = "leave_alliance"
    description = "Leave an alliance. The alliance may dissolve if fewer than 2 members remain."
    parameters = {
        "alliance_id": {
            "type": "string",
            "description": "The ID of the alliance to leave",
        },
    }

    def __init__(
        self,
        *,
        alliance_manager: AllianceManager | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._alliance_mgr = alliance_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._alliance_mgr is None:
            return {"status": "error", "reason": "Alliance system not available"}

        try:
            success = await self._alliance_mgr.leave_alliance(
                agent_id=self._agent_id,
                alliance_id=kwargs["alliance_id"],
            )
        except (ValueError, KeyError):
            return {"status": "error", "reason": f"Invalid alliance_id: {kwargs['alliance_id']!r}"}

        if success:
            return {"status": "left", "message": "You have left the alliance."}
        return {"status": "error", "reason": "Failed to leave alliance"}


class ViewAlliancesTool(BaseTool):
    """View all active alliances and their members."""

    name = "view_alliances"
    description = "See all active alliances, their members, and purposes."
    parameters = {}

    def __init__(
        self,
        *,
        alliance_manager: AllianceManager | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._alliance_mgr = alliance_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._alliance_mgr is None:
            return {"status": "error", "reason": "Alliance system not available"}

        alliances = await self._alliance_mgr.get_active_alliances()
        return {
            "status": "ok",
            "alliances": [
                {
                    "id": a.id,
                    "name": a.name,
                    "members": a.members,
                    "purpose": a.purpose,
                    "founded_by": a.founded_by,
                }
                for a in alliances
            ],
        }
