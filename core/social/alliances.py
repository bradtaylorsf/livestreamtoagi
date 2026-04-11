"""Alliance management — formation, voting, dissolution, and treasury.

Agents can form alliances to coordinate goals, share resources, and
create political dynamics. Alliances persist across conversations and
are visible in core memory and speaker selection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from core.agent_economy import AgentEconomyManager
    from core.repos.alliance_repo import AllianceRepo

logger = logging.getLogger(__name__)

# Max active alliances per agent (prevents fragmentation)
MAX_ALLIANCES_PER_AGENT = 2


class Alliance(BaseModel):
    """A formed alliance between agents."""

    id: str
    name: str
    members: list[str] = Field(default_factory=list)
    founded_by: str
    purpose: str = ""
    shared_treasury: float = 0.0
    created_at: Any = None


class AllianceProposal(BaseModel):
    """A proposal to form a new alliance."""

    id: str
    proposer: str
    alliance_name: str
    purpose: str = ""
    invitees: list[str] = Field(default_factory=list)
    votes: dict[str, bool] = Field(default_factory=dict)
    status: str = "pending"


class AllianceManager:
    """Manages alliance lifecycle — proposals, formation, membership, treasury."""

    def __init__(
        self,
        *,
        alliance_repo: AllianceRepo | None = None,
        economy_manager: AgentEconomyManager | None = None,
        simulation_id: UUID | None = None,
    ) -> None:
        self._repo = alliance_repo
        self._economy = economy_manager
        self.simulation_id = simulation_id

    async def propose_alliance(
        self,
        proposer_id: str,
        name: str,
        invitees: list[str],
        purpose: str = "",
        simulation_id: UUID | None = None,
    ) -> AllianceProposal | None:
        """Create a new alliance proposal.

        Returns None if proposer already has MAX_ALLIANCES_PER_AGENT.
        """
        simulation_id = simulation_id or self.simulation_id
        if self._repo is None:
            logger.warning("No alliance repo available")
            return None

        # Check proposer's current alliance count
        current = await self._repo.get_agent_alliances(proposer_id, simulation_id)
        if len(current) >= MAX_ALLIANCES_PER_AGENT:
            logger.info(
                "%s already in %d alliances (max %d)",
                proposer_id, len(current), MAX_ALLIANCES_PER_AGENT,
            )
            return None

        row = await self._repo.create_proposal(
            simulation_id=simulation_id,
            proposer=proposer_id,
            alliance_name=name,
            purpose=purpose,
            invitees=invitees,
        )

        return AllianceProposal(
            id=str(row["id"]),
            proposer=proposer_id,
            alliance_name=name,
            purpose=purpose,
            invitees=invitees,
            votes={},
            status="pending",
        )

    async def vote_on_proposal(
        self,
        proposal_id: str,
        agent_id: str,
        accept: bool,
        simulation_id: UUID | None = None,
    ) -> Alliance | AllianceProposal | None:
        """Record a vote. If all invitees voted and majority accept, form alliance.

        Returns Alliance if formed, AllianceProposal if still pending, None on error.
        """
        simulation_id = simulation_id or self.simulation_id
        if self._repo is None:
            return None

        pid = UUID(proposal_id)
        updated = await self._repo.vote_on_proposal(pid, agent_id, accept)
        if updated is None:
            return None

        votes = updated.get("votes", {})
        invitees = updated.get("invitees", [])

        # Check if all invitees have voted
        all_voted = all(inv in votes for inv in invitees)
        if not all_voted:
            return AllianceProposal(
                id=proposal_id,
                proposer=updated["proposer"],
                alliance_name=updated["alliance_name"],
                purpose=updated.get("purpose", ""),
                invitees=invitees,
                votes=votes,
                status="pending",
            )

        # Tally votes — majority of invitees must accept
        yes_count = sum(1 for v in votes.values() if v)
        if yes_count > len(invitees) / 2:
            # Form the alliance
            alliance_row = await self._repo.create_alliance(
                simulation_id=simulation_id,
                name=updated["alliance_name"],
                founded_by=updated["proposer"],
                purpose=updated.get("purpose", ""),
            )
            alliance_id = alliance_row["id"]

            # Add proposer + accepting invitees as members
            members = [updated["proposer"]]
            await self._repo.add_member(alliance_id, updated["proposer"], simulation_id)
            for inv in invitees:
                if votes.get(inv, False):
                    await self._repo.add_member(alliance_id, inv, simulation_id)
                    members.append(inv)

            # Update proposal status
            await self._repo.db.execute(
                "UPDATE alliance_proposals SET status = 'accepted' WHERE id = $1",
                pid,
            )

            logger.info("Alliance '%s' formed with members: %s",
                        updated["alliance_name"], members)

            return Alliance(
                id=str(alliance_id),
                name=updated["alliance_name"],
                members=members,
                founded_by=updated["proposer"],
                purpose=updated.get("purpose", ""),
            )
        else:
            # Rejected
            await self._repo.db.execute(
                "UPDATE alliance_proposals SET status = 'rejected' WHERE id = $1",
                pid,
            )
            return AllianceProposal(
                id=proposal_id,
                proposer=updated["proposer"],
                alliance_name=updated["alliance_name"],
                purpose=updated.get("purpose", ""),
                invitees=invitees,
                votes=votes,
                status="rejected",
            )

    async def leave_alliance(
        self,
        agent_id: str,
        alliance_id: str,
    ) -> bool:
        """Remove an agent from an alliance. Dissolve if < 2 members remain."""
        if self._repo is None:
            return False

        aid = UUID(alliance_id)
        await self._repo.remove_member(aid, agent_id)

        # Check remaining members
        members = await self._repo.get_members(aid)
        if len(members) < 2:
            await self._repo.dissolve_alliance(aid)
            logger.info("Alliance %s dissolved (fewer than 2 members)", alliance_id)

        return True

    async def get_alliance_context(
        self, agent_id: str, simulation_id: UUID | None = None,
    ) -> str:
        """Format active alliances for injection into agent context."""
        simulation_id = simulation_id or self.simulation_id
        if self._repo is None:
            return ""

        alliances = await self._repo.get_agent_alliances(agent_id, simulation_id)
        if not alliances:
            return ""

        lines = ["## Your alliances"]
        for a in alliances:
            aid = a["id"]
            members = await self._repo.get_members(aid)
            other_members = [m for m in members if m != agent_id]
            lines.append(
                f"- **{a['name']}** (with {', '.join(other_members)}): {a.get('purpose', 'No stated purpose')}"
            )

        return "\n".join(lines)

    async def get_active_alliances(
        self, simulation_id: UUID | None = None,
    ) -> list[Alliance]:
        """Get all active alliances."""
        simulation_id = simulation_id or self.simulation_id
        if self._repo is None:
            return []

        rows = await self._repo.get_active_alliances(simulation_id)
        result = []
        for r in rows:
            members = r.get("members") or []
            # Filter out None values from array_agg
            members = [m for m in members if m is not None]
            result.append(Alliance(
                id=str(r["id"]),
                name=r["name"],
                members=members,
                founded_by=r["founded_by"],
                purpose=r.get("purpose", ""),
                shared_treasury=float(r.get("shared_treasury", 0)),
                created_at=r.get("created_at"),
            ))
        return result

    async def are_allies(
        self, agent_a: str, agent_b: str, simulation_id: UUID | None = None,
    ) -> bool:
        """Check if two agents are in the same alliance."""
        simulation_id = simulation_id or self.simulation_id
        if self._repo is None:
            return False

        a_alliances = await self._repo.get_agent_alliances(agent_a, simulation_id)
        a_ids = {str(a["id"]) for a in a_alliances}

        b_alliances = await self._repo.get_agent_alliances(agent_b, simulation_id)
        b_ids = {str(a["id"]) for a in b_alliances}

        return bool(a_ids & b_ids)

    async def transfer_to_treasury(
        self,
        agent_id: str,
        alliance_id: str,
        amount: float,
    ) -> bool:
        """Transfer funds from an agent's account to alliance treasury."""
        if self._repo is None:
            return False

        # Deduct from agent's economy account first
        if self._economy is not None:
            from decimal import Decimal
            deducted = await self._economy.deduct_cost(
                agent_id, Decimal(str(amount)), f"alliance treasury contribution: {alliance_id}",
            )
            if not deducted:
                return False

        aid = UUID(alliance_id)
        await self._repo.update_treasury(aid, amount)
        return True
