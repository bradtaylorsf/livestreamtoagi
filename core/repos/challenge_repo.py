"""Repository for /challenges — community-shared simulation scenarios.

A challenge is a simulation row that the submitter explicitly opted to share
with the community (``simulations.shared_as_challenge = TRUE``) plus a
``challenges`` row that carries the scenario description, tags, and votes.
Legacy challenge rows (created before issue #433) point at the live
simulation; they remain in the database for upvote-history continuity but
are filtered out of the public feed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import Challenge

if TYPE_CHECKING:
    import uuid

    from core.database import Database


_BASE_SELECT = """
    SELECT c.id, c.description, c.submitted_by, c.source, c.status,
           c.assigned_agents, c.result, c.cost_estimate, c.actual_cost,
           c.votes, c.category, c.tags, c.simulation_id, c.shared_at,
           c.created_at, c.completed_at,
           s.name AS simulation_name,
           s.video_url AS simulation_video_url,
           s.total_turns AS simulation_total_turns,
           s.agents_participated AS simulation_agents
"""


class ChallengeRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def list_shared(
        self,
        *,
        tag: str | None = None,
        sort: str = "newest",
        include_legacy: bool = False,
    ) -> list[dict]:
        """List challenges whose linked simulation is shared as a challenge.

        Returned dicts include the joined simulation fields (``simulation_*``)
        for the card view. Legacy rows pointing at the live simulation are
        excluded by default — pass ``include_legacy=True`` to keep them.
        """
        clauses: list[str] = []
        params: list[object] = []
        idx = 1
        if not include_legacy:
            clauses.append("s.shared_as_challenge = TRUE")
        if tag is not None:
            clauses.append(f"${idx} = ANY(c.tags)")
            params.append(tag)
            idx += 1
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        order_map = {
            "newest": "c.created_at DESC",
            "most_upvoted": "c.votes DESC",
        }
        order = order_map.get(sort, "c.created_at DESC")

        rows = await self.db.fetch(
            f"""{_BASE_SELECT}
                  FROM challenges c
                  JOIN simulations s ON s.id = c.simulation_id
                  {where}
                 ORDER BY {order}""",  # noqa: S608
            *params,
        )
        return [dict(r) for r in rows]

    async def get_shared(self, challenge_id: int) -> dict | None:
        row = await self.db.fetchrow(
            f"""{_BASE_SELECT}
                  FROM challenges c
                  JOIN simulations s ON s.id = c.simulation_id
                 WHERE c.id = $1""",
            challenge_id,
        )
        return dict(row) if row else None

    async def create_for_simulation(
        self,
        *,
        simulation_id: uuid.UUID,
        description: str,
        submitted_by: str | None,
        tags: list[str],
    ) -> Challenge:
        """Insert a challenges row pointing at a user-submitted simulation."""
        row = await self.db.fetchrow(
            """INSERT INTO challenges
                   (description, submitted_by, source, category, votes,
                    simulation_id, tags, shared_at)
                 VALUES ($1, $2, 'shared_simulation', NULL, 0, $3, $4, now())
              RETURNING *""",
            description,
            submitted_by,
            simulation_id,
            tags,
        )
        return Challenge(**dict(row))

    async def upvote(self, challenge_id: int) -> Challenge | None:
        row = await self.db.fetchrow(
            """UPDATE challenges
                  SET votes = votes + 1
                WHERE id = $1
            RETURNING *""",
            challenge_id,
        )
        return Challenge(**dict(row)) if row else None
