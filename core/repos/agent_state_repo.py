"""Repository for agent_internal_state table."""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

from core.agent_state import AgentState

if TYPE_CHECKING:
    from core.database import Database


class AgentStateRepo:
    """CRUD operations for persisted agent internal state."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(
        self, agent_id: str, simulation_id: _uuid.UUID | None = None
    ) -> AgentState | None:
        """Load state from DB, or None if no record exists."""
        row = await self.db.fetchrow(
            "SELECT * FROM agent_internal_state WHERE agent_id = $1 AND simulation_id = $2",
            agent_id,
            simulation_id,
        )
        if row is None:
            return None
        return AgentState(**dict(row))

    async def upsert(
        self, state: AgentState, simulation_id: _uuid.UUID | None = None
    ) -> AgentState:
        """Insert or update agent state, incrementing version on update."""
        row = await self.db.fetchrow(
            """INSERT INTO agent_internal_state
                   (agent_id, simulation_id, energy, satisfaction, boredom, frustration,
                    social_need, creative_need, recognition_need, mood,
                    version, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 1, NOW())
               ON CONFLICT (agent_id, simulation_id)
               DO UPDATE SET
                   energy = EXCLUDED.energy,
                   satisfaction = EXCLUDED.satisfaction,
                   boredom = EXCLUDED.boredom,
                   frustration = EXCLUDED.frustration,
                   social_need = EXCLUDED.social_need,
                   creative_need = EXCLUDED.creative_need,
                   recognition_need = EXCLUDED.recognition_need,
                   mood = EXCLUDED.mood,
                   version = agent_internal_state.version + 1,
                   updated_at = NOW()
               RETURNING *""",
            state.agent_id,
            state.simulation_id,
            state.energy,
            state.satisfaction,
            state.boredom,
            state.frustration,
            state.social_need,
            state.creative_need,
            state.recognition_need,
            state.mood,
        )
        return AgentState(**dict(row))

    async def get_all(self, simulation_id: _uuid.UUID | None = None) -> list[AgentState]:
        """Load all agent states from DB."""
        rows = await self.db.fetch(
            "SELECT * FROM agent_internal_state WHERE simulation_id = $1 ORDER BY agent_id",
            simulation_id,
        )
        return [AgentState(**dict(row)) for row in rows]
