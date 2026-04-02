"""Repository for core_memory, core_memory_history, recall_memory, conversation_buffer."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from core.models import (
    ConversationBuffer,
    ConversationBufferCreate,
    CoreMemory,
    CoreMemoryHistory,
    RecallMemory,
    RecallMemoryCreate,
)

if TYPE_CHECKING:
    import asyncpg

    from core.database import Database


MAX_LIMIT = 500


def _parse_embedding(val: str) -> list[float]:
    """Parse pgvector text representation '[1,2,3]' into list[float]."""
    try:
        return [float(x) for x in val.strip("[]").split(",")]
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Malformed pgvector embedding: {val!r}") from exc


def _format_embedding(values: list[float]) -> str:
    """Validate and format a list of floats for pgvector insertion."""
    if not values:
        raise ValueError("Embedding must not be empty")
    for i, v in enumerate(values):
        if not isinstance(v, (int, float)):
            raise ValueError(f"Embedding[{i}] is not a number: {v!r}")
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"Embedding[{i}] is not finite: {v}")
    return "[" + ",".join(f"{v:.10f}" for v in values) + "]"


def _row_to_recall(row: asyncpg.Record) -> RecallMemory:
    d = dict(row)
    if isinstance(d.get("embedding"), str):
        d["embedding"] = _parse_embedding(d["embedding"])
    return RecallMemory(**d)


class MemoryRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Core Memory ─────────────────────────────────────────

    async def get_core_memory(self, agent_id: str) -> CoreMemory | None:
        row = await self.db.fetchrow(
            "SELECT * FROM core_memory WHERE agent_id = $1", agent_id
        )
        return CoreMemory(**dict(row)) if row else None

    async def upsert_core_memory(
        self, agent_id: str, content: str, token_count: int, reason: str | None = None
    ) -> CoreMemory:
        """Atomically upsert core memory and insert history record."""
        async with self.db.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO core_memory (agent_id, content, token_count, version)
                       VALUES ($1, $2, $3, 1)
                       ON CONFLICT (agent_id) DO UPDATE
                       SET content = $2,
                           token_count = $3,
                           version = core_memory.version + 1,
                           last_updated = NOW()
                       RETURNING *""",
                agent_id,
                content,
                token_count,
            )
            await conn.execute(
                """INSERT INTO core_memory_history
                       (agent_id, content, version, change_reason)
                       VALUES ($1, $2, $3, $4)""",
                agent_id,
                content,
                row["version"],
                reason,
            )
        return CoreMemory(**dict(row))

    async def get_core_memory_history(
        self, agent_id: str, limit: int = 100
    ) -> list[CoreMemoryHistory]:
        limit = min(limit, MAX_LIMIT)
        rows = await self.db.fetch(
            "SELECT * FROM core_memory_history WHERE agent_id = $1 ORDER BY version LIMIT $2",
            agent_id,
            limit,
        )
        return [CoreMemoryHistory(**dict(r)) for r in rows]

    # ── Recall Memory ───────────────────────────────────────

    async def add_recall(self, memory: RecallMemoryCreate) -> RecallMemory:
        embedding_str = _format_embedding(memory.embedding)
        row = await self.db.fetchrow(
            """INSERT INTO recall_memory
               (agent_id, summary, embedding, event_type, participants,
                transcript_id, importance_score)
               VALUES ($1, $2, $3::vector, $4, $5, $6, $7)
               RETURNING *""",
            memory.agent_id,
            memory.summary,
            embedding_str,
            memory.event_type,
            memory.participants,
            memory.transcript_id,
            memory.importance_score,
        )
        return _row_to_recall(row)

    async def search_recall(
        self, agent_id: str, embedding: list[float], limit: int = 10
    ) -> list[RecallMemory]:
        limit = min(limit, MAX_LIMIT)
        embedding_str = _format_embedding(embedding)
        rows = await self.db.fetch(
            """SELECT * FROM recall_memory
               WHERE agent_id = $1
               ORDER BY embedding <=> $2::vector
               LIMIT $3""",
            agent_id,
            embedding_str,
            limit,
        )
        return [_row_to_recall(r) for r in rows]

    async def increment_recalled_count(self, memory_id: int) -> None:
        await self.db.execute(
            "UPDATE recall_memory SET recalled_count = recalled_count + 1 WHERE id = $1",
            memory_id,
        )

    # ── Conversation Buffer ─────────────────────────────────

    async def add_buffer_entry(self, entry: ConversationBufferCreate) -> ConversationBuffer:
        row = await self.db.fetchrow(
            """INSERT INTO conversation_buffer (agent_id, role, speaker, content)
               VALUES ($1, $2, $3, $4)
               RETURNING *""",
            entry.agent_id,
            entry.role,
            entry.speaker,
            entry.content,
        )
        return ConversationBuffer(**dict(row))

    async def get_buffer(self, agent_id: str, limit: int = 50) -> list[ConversationBuffer]:
        limit = min(limit, MAX_LIMIT)
        rows = await self.db.fetch(
            """SELECT * FROM conversation_buffer
               WHERE agent_id = $1
               ORDER BY created_at DESC
               LIMIT $2""",
            agent_id,
            limit,
        )
        return [ConversationBuffer(**dict(r)) for r in rows]

    async def clear_buffer(self, agent_id: str) -> None:
        await self.db.execute(
            "DELETE FROM conversation_buffer WHERE agent_id = $1", agent_id
        )
