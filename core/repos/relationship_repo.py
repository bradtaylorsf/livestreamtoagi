"""Repository for agent_relationships table."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.models import Relationship
from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from core.database import Database


def _parse_row(row: dict) -> dict:
    for key in ("evolution_log",):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


class RelationshipRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert(
        self,
        simulation_id: uuid.UUID,
        agent_id: str,
        target_agent_id: str,
        *,
        sentiment_score: float | None = None,
        trust_score: float | None = None,
        interaction_count: int | None = None,
        relationship_summary: str | None = None,
        last_interaction_at: datetime | None = None,
    ) -> Relationship:
        """Insert or update a relationship record."""
        row = await self.db.fetchrow(
            """INSERT INTO agent_relationships
               (simulation_id, agent_id, target_agent_id,
                sentiment_score, trust_score, interaction_count,
                relationship_summary, last_interaction_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (simulation_id, agent_id, target_agent_id)
               DO UPDATE SET
                 sentiment_score = COALESCE($4, agent_relationships.sentiment_score),
                 trust_score = COALESCE($5, agent_relationships.trust_score),
                 interaction_count = COALESCE($6, agent_relationships.interaction_count),
                 relationship_summary = COALESCE($7, agent_relationships.relationship_summary),
                 last_interaction_at = COALESCE($8, agent_relationships.last_interaction_at),
                 updated_at = NOW()
               RETURNING *""",
            simulation_id,
            agent_id,
            target_agent_id,
            sentiment_score,
            trust_score,
            interaction_count,
            relationship_summary,
            last_interaction_at,
        )
        return Relationship(**_parse_row(dict(row)))

    async def get(
        self,
        simulation_id: uuid.UUID,
        agent_id: str,
        target_agent_id: str,
    ) -> Relationship | None:
        row = await self.db.fetchrow(
            """SELECT * FROM agent_relationships
               WHERE simulation_id = $1 AND agent_id = $2 AND target_agent_id = $3""",
            simulation_id,
            agent_id,
            target_agent_id,
        )
        if row is None:
            return None
        return Relationship(**_parse_row(dict(row)))

    async def get_all_for_agent(
        self, simulation_id: uuid.UUID | None, agent_id: str
    ) -> list[Relationship]:
        if simulation_id is None:
            rows = await self.db.fetch(
                """SELECT * FROM agent_relationships
                   WHERE agent_id = $1
                   ORDER BY target_agent_id""",
                agent_id,
            )
        else:
            rows = await self.db.fetch(
                """SELECT * FROM agent_relationships
                   WHERE simulation_id = $1 AND agent_id = $2
                   ORDER BY target_agent_id""",
                simulation_id,
                agent_id,
            )
        return [Relationship(**_parse_row(dict(r))) for r in rows]

    async def get_social_graph(self, simulation_id: uuid.UUID) -> list[Relationship]:
        rows = await self.db.fetch(
            """SELECT * FROM agent_relationships
               WHERE simulation_id = $1
               ORDER BY agent_id, target_agent_id""",
            simulation_id,
        )
        return [Relationship(**_parse_row(dict(r))) for r in rows]

    async def get_relationships_missing_sentiment(
        self, simulation_id: uuid.UUID
    ) -> list[Relationship]:
        """Return relationship rows where sentiment or trust is NULL."""
        rows = await self.db.fetch(
            """SELECT * FROM agent_relationships
               WHERE simulation_id = $1
                 AND (sentiment_score IS NULL OR trust_score IS NULL)
               ORDER BY agent_id, target_agent_id""",
            simulation_id,
        )
        return [Relationship(**_parse_row(dict(r))) for r in rows]

    async def increment_interaction(
        self,
        simulation_id: uuid.UUID,
        agent_id: str,
        target_agent_id: str,
        interaction_at: datetime | None = None,
    ) -> Relationship:
        """Increment interaction count and update last_interaction_at."""
        row = await self.db.fetchrow(
            """INSERT INTO agent_relationships
               (simulation_id, agent_id, target_agent_id, interaction_count, last_interaction_at)
               VALUES ($1, $2, $3, 1, $4)
               ON CONFLICT (simulation_id, agent_id, target_agent_id)
               DO UPDATE SET
                 interaction_count = agent_relationships.interaction_count + 1,
                 last_interaction_at = COALESCE($4, NOW()),
                 updated_at = NOW()
               RETURNING *""",
            simulation_id,
            agent_id,
            target_agent_id,
            interaction_at,
        )
        return Relationship(**_parse_row(dict(row)))

    async def append_evolution_event(
        self,
        simulation_id: uuid.UUID,
        agent_id: str,
        target_agent_id: str,
        event: dict[str, Any],
    ) -> None:
        """Append an event to the evolution_log JSONB array."""
        await self.db.execute(
            """UPDATE agent_relationships
               SET evolution_log = evolution_log || $4::jsonb,
                   updated_at = NOW()
               WHERE simulation_id = $1 AND agent_id = $2 AND target_agent_id = $3""",
            simulation_id,
            agent_id,
            target_agent_id,
            serialize_jsonb([event]),
        )

    async def get_evolution(
        self,
        simulation_id: uuid.UUID,
        agent_id: str,
        target_agent_id: str,
    ) -> list[dict[str, Any]]:
        """Return the evolution timeline for a specific relationship."""
        row = await self.db.fetchrow(
            """SELECT evolution_log FROM agent_relationships
               WHERE simulation_id = $1 AND agent_id = $2 AND target_agent_id = $3""",
            simulation_id,
            agent_id,
            target_agent_id,
        )
        if row is None:
            return []
        log = row["evolution_log"]
        if isinstance(log, str):
            return json.loads(log)
        return log or []
