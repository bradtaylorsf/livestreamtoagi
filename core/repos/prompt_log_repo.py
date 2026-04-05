"""Repository for prompt_logs — stores assembled LLM context for debugging."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.models import PromptLog, PromptLogCreate

if TYPE_CHECKING:
    import uuid

    from core.database import Database


class PromptLogRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, log: PromptLogCreate) -> PromptLog:
        row = await self.db.fetchrow(
            """INSERT INTO prompt_logs
               (conversation_id, simulation_id, agent_id, turn_number,
                full_prompt, sections_included, total_tokens)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
               RETURNING *""",
            log.conversation_id,
            log.simulation_id,
            log.agent_id,
            log.turn_number,
            log.full_prompt,
            json.dumps(log.sections_included),
            log.total_tokens,
        )
        return PromptLog(**dict(row))

    async def get_by_conversation(
        self,
        conversation_id: uuid.UUID,
    ) -> list[PromptLog]:
        rows = await self.db.fetch(
            """SELECT * FROM prompt_logs
               WHERE conversation_id = $1
               ORDER BY turn_number""",
            conversation_id,
        )
        return [PromptLog(**dict(r)) for r in rows]
