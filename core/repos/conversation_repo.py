"""Repository for conversations, conversation_selection_log, interrupt_log."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.models import (
    Conversation,
    ConversationCreate,
    InterruptLogCreate,
    SelectionLog,
    SelectionLogCreate,
)

if TYPE_CHECKING:
    import uuid

    from core.database import Database


def _serialize_jsonb(val: Any) -> str | None:
    if val is None:
        return None
    return json.dumps(val) if not isinstance(val, str) else val


def _row_to_conversation(row) -> Conversation:
    d = dict(row)
    for key in ("trigger_details", "participating_agents", "topics_discussed"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
    return Conversation(**d)


class ConversationRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, conv: ConversationCreate) -> Conversation:
        if conv.id is not None:
            row = await self.db.fetchrow(
                """INSERT INTO conversations
                   (id, trigger_type, trigger_details, initial_energy,
                    participating_agents, location, config_hash)
                   VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7)
                   RETURNING *""",
                conv.id,
                conv.trigger_type,
                _serialize_jsonb(conv.trigger_details),
                conv.initial_energy,
                _serialize_jsonb(conv.participating_agents),
                conv.location,
                conv.config_hash,
            )
        else:
            row = await self.db.fetchrow(
                """INSERT INTO conversations
                   (trigger_type, trigger_details, initial_energy,
                    participating_agents, location, config_hash)
                   VALUES ($1, $2::jsonb, $3, $4::jsonb, $5, $6)
                   RETURNING *""",
                conv.trigger_type,
                _serialize_jsonb(conv.trigger_details),
                conv.initial_energy,
                _serialize_jsonb(conv.participating_agents),
                conv.location,
                conv.config_hash,
            )
        return _row_to_conversation(row)

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        row = await self.db.fetchrow(
            "SELECT * FROM conversations WHERE id = $1", conversation_id
        )
        return _row_to_conversation(row) if row else None

    async def close(
        self,
        conversation_id: uuid.UUID,
        final_energy: float,
        closed_by: str,
    ) -> Conversation | None:
        row = await self.db.fetchrow(
            """UPDATE conversations
               SET ended_at = NOW(), final_energy = $1, closed_by = $2
               WHERE id = $3
               RETURNING *""",
            final_energy,
            closed_by,
            conversation_id,
        )
        return _row_to_conversation(row) if row else None

    async def log_selection(self, entry: SelectionLogCreate) -> None:
        await self.db.execute(
            """INSERT INTO conversation_selection_log
               (conversation_id, turn_number, selected_agent_id, was_interrupt,
                agent_scores, detected_topic, previous_speaker_id,
                conversation_energy, active_agents, trigger_type, config_hash)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9::jsonb, $10, $11)""",
            entry.conversation_id,
            entry.turn_number,
            entry.selected_agent_id,
            entry.was_interrupt,
            _serialize_jsonb(entry.agent_scores),
            entry.detected_topic,
            entry.previous_speaker_id,
            entry.conversation_energy,
            _serialize_jsonb(entry.active_agents),
            entry.trigger_type,
            entry.config_hash,
        )

    async def log_interrupt(self, entry: InterruptLogCreate) -> None:
        await self.db.execute(
            """INSERT INTO interrupt_log
               (conversation_id, attempting_agent_id, would_have_spoken_id,
                interrupt_score, threshold_at_time, succeeded, reason)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            entry.conversation_id,
            entry.attempting_agent_id,
            entry.would_have_spoken_id,
            entry.interrupt_score,
            entry.threshold_at_time,
            entry.succeeded,
            entry.reason,
        )

    async def get_selection_log(
        self, conversation_id: uuid.UUID
    ) -> list[SelectionLog]:
        rows = await self.db.fetch(
            """SELECT * FROM conversation_selection_log
               WHERE conversation_id = $1
               ORDER BY turn_number""",
            conversation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            for key in ("agent_scores", "active_agents"):
                if isinstance(d.get(key), str):
                    d[key] = json.loads(d[key])
            result.append(SelectionLog(**d))
        return result
