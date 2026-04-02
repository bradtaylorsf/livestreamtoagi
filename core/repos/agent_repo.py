"""Repository for the agents table."""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg

from core.models import Agent, AgentCreate

if TYPE_CHECKING:
    from core.database import Database


def _row_to_agent(row: asyncpg.Record) -> Agent:
    return Agent(**dict(row))


class AgentRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get(self, agent_id: str) -> Agent | None:
        row = await self.db.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
        return _row_to_agent(row) if row else None

    async def list(self, status: str | None = None) -> list[Agent]:
        if status:
            rows = await self.db.fetch(
                "SELECT * FROM agents WHERE status = $1 ORDER BY id", status
            )
        else:
            rows = await self.db.fetch("SELECT * FROM agents ORDER BY id")
        return [_row_to_agent(r) for r in rows]

    async def create(self, agent: AgentCreate) -> Agent:
        row = await self.db.fetchrow(
            """INSERT INTO agents
               (id, display_name, model_conversation,
                model_building, voice_id, status)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            agent.id,
            agent.display_name,
            agent.model_conversation,
            agent.model_building,
            agent.voice_id,
            agent.status,
        )
        return _row_to_agent(row)

    async def update_status(self, agent_id: str, status: str) -> Agent | None:
        row = await self.db.fetchrow(
            "UPDATE agents SET status = $1 WHERE id = $2 RETURNING *",
            status,
            agent_id,
        )
        return _row_to_agent(row) if row else None
