"""Repository for persistent agent goals (DB-backed)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from core.models import AgentGoal

if TYPE_CHECKING:
    import uuid

    from core.database import Database

logger = logging.getLogger(__name__)


class GoalRepo:
    """CRUD operations for agent goals in PostgreSQL."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_active_goals(
        self, agent_id: str, *, limit: int = 10
    ) -> list[AgentGoal]:
        """Get active (non-completed, non-abandoned) goals for an agent."""
        rows = await self.db.fetch(
            """SELECT * FROM agent_goals
               WHERE agent_id = $1 AND status IN ('active', 'blocked')
               ORDER BY priority ASC, created_at ASC
               LIMIT $2""",
            agent_id,
            limit,
        )
        return [AgentGoal(**dict(r)) for r in rows]

    async def get_all_goals(
        self, agent_id: str, *, limit: int = 20
    ) -> list[AgentGoal]:
        """Get all goals for an agent regardless of status."""
        rows = await self.db.fetch(
            """SELECT * FROM agent_goals
               WHERE agent_id = $1
               ORDER BY priority ASC, created_at DESC
               LIMIT $2""",
            agent_id,
            limit,
        )
        return [AgentGoal(**dict(r)) for r in rows]

    async def add_goal(
        self,
        agent_id: str,
        goal: str,
        *,
        priority: int = 5,
        source: str = "self",
        parent_goal_id: uuid.UUID | None = None,
    ) -> AgentGoal:
        """Add a new goal for an agent."""
        row = await self.db.fetchrow(
            """INSERT INTO agent_goals
               (agent_id, goal, priority, source, parent_goal_id)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING *""",
            agent_id,
            goal,
            priority,
            source,
            parent_goal_id,
        )
        return AgentGoal(**dict(row))

    async def update_status(
        self,
        goal_id: uuid.UUID,
        status: str,
    ) -> bool:
        """Update a goal's status. Returns True if found."""
        result = await self.db.execute(
            """UPDATE agent_goals
               SET status = $1,
                   completed_at = CASE WHEN $1 IN ('completed', 'abandoned')
                                       THEN now() ELSE completed_at END
               WHERE id = $2""",
            status,
            goal_id,
        )
        return "UPDATE 1" in result

    async def update_progress(
        self, goal_id: uuid.UUID, notes: str
    ) -> bool:
        """Update progress notes for a goal."""
        result = await self.db.execute(
            "UPDATE agent_goals SET progress_notes = $1 WHERE id = $2",
            notes,
            goal_id,
        )
        return "UPDATE 1" in result

    async def get_goal(self, goal_id: uuid.UUID) -> AgentGoal | None:
        """Get a specific goal by ID."""
        row = await self.db.fetchrow(
            "SELECT * FROM agent_goals WHERE id = $1", goal_id
        )
        if row is None:
            return None
        return AgentGoal(**dict(row))

    async def get_goals_for_simulation(
        self,
        agent_ids: list[str] | None = None,
        *,
        since: Any = None,
    ) -> list[AgentGoal]:
        """Get goals across agents, optionally filtered by creation time."""
        if since is not None:
            rows = await self.db.fetch(
                """SELECT * FROM agent_goals
                   WHERE created_at >= $1
                   ORDER BY agent_id, priority ASC""",
                since,
            )
        else:
            rows = await self.db.fetch(
                "SELECT * FROM agent_goals ORDER BY agent_id, priority ASC"
            )
        goals = [AgentGoal(**dict(r)) for r in rows]
        if agent_ids:
            goals = [g for g in goals if g.agent_id in agent_ids]
        return goals
