"""Repository for alliance persistence — alliances, members, and proposals."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


class AllianceRepo:
    """CRUD operations for alliances, alliance members, and proposals."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Alliances ──────────────────────────────────────────

    async def create_alliance(
        self,
        simulation_id: UUID | None,
        name: str,
        founded_by: str,
        purpose: str = "",
    ) -> dict[str, Any]:
        """Create a new alliance and return its record."""
        row = await self.db.fetchrow(
            """INSERT INTO alliances (simulation_id, name, founded_by, purpose)
               VALUES ($1, $2, $3, $4)
               RETURNING *""",
            simulation_id,
            name,
            founded_by,
            purpose,
        )
        return dict(row)

    async def get_alliance(self, alliance_id: UUID) -> dict[str, Any] | None:
        row = await self.db.fetchrow(
            "SELECT * FROM alliances WHERE id = $1",
            alliance_id,
        )
        return dict(row) if row else None

    async def get_active_alliances(
        self,
        simulation_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Get all non-dissolved alliances."""
        rows = await self.db.fetch(
            """SELECT a.*, array_agg(am.agent_id) FILTER (WHERE am.left_at IS NULL) AS members
               FROM alliances a
               LEFT JOIN alliance_members am ON am.alliance_id = a.id
               WHERE a.dissolved_at IS NULL
                 AND ($1::uuid IS NULL OR a.simulation_id = $1)
               GROUP BY a.id
               ORDER BY a.created_at DESC""",
            simulation_id,
        )
        return [dict(r) for r in rows]

    async def get_agent_alliances(
        self,
        agent_id: str,
        simulation_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Get all active alliances an agent belongs to."""
        rows = await self.db.fetch(
            """SELECT a.*
               FROM alliances a
               JOIN alliance_members am ON am.alliance_id = a.id
               WHERE am.agent_id = $1
                 AND am.left_at IS NULL
                 AND a.dissolved_at IS NULL
                 AND ($2::uuid IS NULL OR a.simulation_id = $2)""",
            agent_id,
            simulation_id,
        )
        return [dict(r) for r in rows]

    async def add_member(
        self,
        alliance_id: UUID,
        agent_id: str,
        simulation_id: UUID | None = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO alliance_members (alliance_id, agent_id, simulation_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (alliance_id, agent_id)
               DO UPDATE SET left_at = NULL, joined_at = NOW()""",
            alliance_id,
            agent_id,
            simulation_id,
        )

    async def remove_member(self, alliance_id: UUID, agent_id: str) -> None:
        await self.db.execute(
            """UPDATE alliance_members SET left_at = NOW()
               WHERE alliance_id = $1 AND agent_id = $2 AND left_at IS NULL""",
            alliance_id,
            agent_id,
        )

    async def get_members(self, alliance_id: UUID) -> list[str]:
        """Get active member IDs for an alliance."""
        rows = await self.db.fetch(
            """SELECT agent_id FROM alliance_members
               WHERE alliance_id = $1 AND left_at IS NULL""",
            alliance_id,
        )
        return [r["agent_id"] for r in rows]

    async def dissolve_alliance(self, alliance_id: UUID) -> None:
        await self.db.execute(
            "UPDATE alliances SET dissolved_at = NOW() WHERE id = $1",
            alliance_id,
        )
        # Mark all members as left
        await self.db.execute(
            "UPDATE alliance_members SET left_at = NOW() WHERE alliance_id = $1 AND left_at IS NULL",
            alliance_id,
        )

    async def update_treasury(
        self,
        alliance_id: UUID,
        amount: float,
    ) -> None:
        """Add (or subtract) from the alliance treasury."""
        await self.db.execute(
            "UPDATE alliances SET shared_treasury = shared_treasury + $1 WHERE id = $2",
            amount,
            alliance_id,
        )

    # ── Proposals ──────────────────────────────────────────

    async def create_proposal(
        self,
        simulation_id: UUID | None,
        proposer: str,
        alliance_name: str,
        purpose: str,
        invitees: list[str],
    ) -> dict[str, Any]:
        row = await self.db.fetchrow(
            """INSERT INTO alliance_proposals
               (simulation_id, proposer, alliance_name, purpose, invitees)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING *""",
            simulation_id,
            proposer,
            alliance_name,
            purpose,
            invitees,
        )
        return dict(row)

    async def get_pending_proposals(
        self,
        simulation_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetch(
            """SELECT * FROM alliance_proposals
               WHERE status = 'pending'
                 AND ($1::uuid IS NULL OR simulation_id = $1)
               ORDER BY created_at DESC""",
            simulation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("votes"), str):
                d["votes"] = json.loads(d["votes"])
            result.append(d)
        return result

    async def get_proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        row = await self.db.fetchrow(
            "SELECT * FROM alliance_proposals WHERE id = $1",
            proposal_id,
        )
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("votes"), str):
            d["votes"] = json.loads(d["votes"])
        return d

    async def vote_on_proposal(
        self,
        proposal_id: UUID,
        agent_id: str,
        accept: bool,
    ) -> dict[str, Any] | None:
        """Record a vote on an alliance proposal. Returns updated proposal.

        Uses SELECT FOR UPDATE inside a transaction to prevent lost votes
        when multiple agents vote concurrently.
        """
        async with self.db.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT votes FROM alliance_proposals WHERE id = $1 FOR UPDATE",
                proposal_id,
            )
            if row is None:
                return None

            votes = row["votes"] or {}
            if isinstance(votes, str):
                votes = json.loads(votes)
            votes[agent_id] = accept

            await conn.execute(
                "UPDATE alliance_proposals SET votes = $1::jsonb WHERE id = $2",
                json.dumps(votes),
                proposal_id,
            )

        return await self.get_proposal(proposal_id)
