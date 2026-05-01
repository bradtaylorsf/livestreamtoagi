"""Repository for core_memory, core_memory_history, recall_memory, conversation_buffer."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from core.models import (
    ConversationBuffer,
    ConversationBufferCreate,
    CoreMemory,
    CoreMemoryHistory,
    JournalEntry,
    JournalEntryCreate,
    RecallMemory,
    RecallMemoryCreate,
    SelfModificationProposal,
    SelfModificationProposalCreate,
)

if TYPE_CHECKING:
    import uuid as _uuid
    from datetime import datetime

    import asyncpg

    from core.database import Database


MAX_LIMIT = 500

def _sim_filter(param_num: int) -> str:
    """Return SQL fragment for simulation_id filtering."""
    return f"simulation_id = ${param_num}"


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

    async def get_core_memory(
        self, agent_id: str, simulation_id: _uuid.UUID | None = None
    ) -> CoreMemory | None:
        row = await self.db.fetchrow(
            f"SELECT * FROM core_memory WHERE agent_id = $1 AND {_sim_filter(2)}",
            agent_id,
            simulation_id,
        )
        return CoreMemory(**dict(row)) if row else None

    async def upsert_core_memory(
        self,
        agent_id: str,
        content: str,
        token_count: int,
        reason: str | None = None,
        simulation_id: _uuid.UUID | None = None,
    ) -> CoreMemory:
        """Atomically upsert core memory and insert history record."""
        async with self.db.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO core_memory (agent_id, content, token_count, version, simulation_id)
                       VALUES ($1, $2, $3, 1, $4)
                       ON CONFLICT (agent_id, simulation_id)
                       DO UPDATE
                       SET content = $2,
                           token_count = $3,
                           version = core_memory.version + 1,
                           last_updated = NOW()
                       RETURNING *""",
                agent_id,
                content,
                token_count,
                simulation_id,
            )
            await conn.execute(
                """INSERT INTO core_memory_history
                       (agent_id, content, version, change_reason, simulation_id)
                       VALUES ($1, $2, $3, $4, $5)""",
                agent_id,
                content,
                row["version"],
                reason,
                simulation_id,
            )
        return CoreMemory(**dict(row))

    async def get_core_memory_history(
        self, agent_id: str, limit: int = 100, simulation_id: _uuid.UUID | None = None
    ) -> list[CoreMemoryHistory]:
        limit = min(limit, MAX_LIMIT)
        rows = await self.db.fetch(
            f"""SELECT * FROM core_memory_history
                WHERE agent_id = $1 AND {_sim_filter(3)}
                ORDER BY version LIMIT $2""",
            agent_id,
            limit,
            simulation_id,
        )
        return [CoreMemoryHistory(**dict(r)) for r in rows]

    # ── Recall Memory ───────────────────────────────────────

    async def add_recall(self, memory: RecallMemoryCreate) -> RecallMemory:
        embedding_str = _format_embedding(memory.embedding)
        row = await self.db.fetchrow(
            """INSERT INTO recall_memory
               (agent_id, summary, embedding, event_type, participants,
                transcript_id, importance_score, simulation_id)
               VALUES ($1, $2, $3::vector, $4, $5, $6, $7, $8)
               RETURNING *""",
            memory.agent_id,
            memory.summary,
            embedding_str,
            memory.event_type,
            memory.participants,
            memory.transcript_id,
            memory.importance_score,
            memory.simulation_id,
        )
        return _row_to_recall(row)

    async def search_recall(
        self,
        agent_id: str,
        embedding: list[float],
        limit: int = 10,
        simulation_id: _uuid.UUID | None = None,
    ) -> list[RecallMemory]:
        limit = min(limit, MAX_LIMIT)
        embedding_str = _format_embedding(embedding)
        rows = await self.db.fetch(
            f"""SELECT * FROM recall_memory
               WHERE agent_id = $1 AND {_sim_filter(4)}
               ORDER BY embedding <=> $2::vector
               LIMIT $3""",
            agent_id,
            embedding_str,
            limit,
            simulation_id,
        )
        return [_row_to_recall(r) for r in rows]

    async def increment_recalled_count(
        self, memory_id: int, simulation_id: _uuid.UUID | None = None
    ) -> None:
        await self.db.execute(
            "UPDATE recall_memory SET recalled_count = recalled_count + 1"
            f" WHERE id = $1 AND {_sim_filter(2)}",
            memory_id,
            simulation_id,
        )

    # ── Conversation Buffer ─────────────────────────────────

    async def add_buffer_entry(self, entry: ConversationBufferCreate) -> ConversationBuffer:
        row = await self.db.fetchrow(
            """INSERT INTO conversation_buffer (agent_id, role, speaker, content, simulation_id)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING *""",
            entry.agent_id,
            entry.role,
            entry.speaker,
            entry.content,
            entry.simulation_id,
        )
        return ConversationBuffer(**dict(row))

    async def get_buffer(
        self, agent_id: str, limit: int = 50, simulation_id: _uuid.UUID | None = None
    ) -> list[ConversationBuffer]:
        limit = min(limit, MAX_LIMIT)
        rows = await self.db.fetch(
            f"""SELECT * FROM conversation_buffer
               WHERE agent_id = $1 AND {_sim_filter(3)}
               ORDER BY created_at DESC
               LIMIT $2""",
            agent_id,
            limit,
            simulation_id,
        )
        return [ConversationBuffer(**dict(r)) for r in rows]

    async def clear_buffer(
        self, agent_id: str, simulation_id: _uuid.UUID | None = None
    ) -> None:
        await self.db.execute(
            f"DELETE FROM conversation_buffer WHERE agent_id = $1 AND {_sim_filter(2)}",
            agent_id,
            simulation_id,
        )

    # ── Recall Memory (time-based) ─────────────────────────────

    async def get_recent_recall_memories(
        self,
        agent_id: str,
        since: datetime,
        *,
        limit: int = 20,
        simulation_id: _uuid.UUID | None = None,
    ) -> list[RecallMemory]:
        """Fetch Tier 2 recall memories created after `since`.

        Capped at `limit` (default 20) most recent to prevent reflection
        prompts from growing unboundedly and truncating LLM responses.
        """
        rows = await self.db.fetch(
            f"""SELECT * FROM recall_memory
               WHERE agent_id = $1 AND timestamp >= $2 AND {_sim_filter(4)}
               ORDER BY timestamp DESC
               LIMIT $3""",
            agent_id,
            since,
            limit,
            simulation_id,
        )
        return [_row_to_recall(r) for r in rows]

    async def update_importance_score(
        self, memory_id: int, importance_score: float, simulation_id: _uuid.UUID | None = None
    ) -> None:
        """Update the importance score of a recall memory."""
        await self.db.execute(
            f"UPDATE recall_memory SET importance_score = $1 WHERE id = $2 AND {_sim_filter(3)}",
            importance_score,
            memory_id,
            simulation_id,
        )

    # ── Journal Entries ────────────────────────────────────────

    async def create_journal_entry(self, entry: JournalEntryCreate) -> JournalEntry:
        row = await self.db.fetchrow(
            """INSERT INTO journal_entries
               (agent_id, reflection_type, content, token_count, image_url, simulation_id)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            entry.agent_id,
            entry.reflection_type,
            entry.content,
            entry.token_count,
            entry.image_url,
            entry.simulation_id,
        )
        return JournalEntry(**dict(row))

    async def update_journal_entry_image(
        self, entry_id: int, image_url: str, simulation_id: _uuid.UUID | None = None
    ) -> None:
        """Set the image_url on an existing journal entry."""
        await self.db.execute(
            f"UPDATE journal_entries SET image_url = $1 WHERE id = $2 AND {_sim_filter(3)}",
            image_url,
            entry_id,
            simulation_id,
        )

    async def get_journal_entries(
        self,
        agent_id: str,
        limit: int = 20,
        offset: int = 0,
        simulation_id: _uuid.UUID | None = None,
    ) -> tuple[list[JournalEntry], int]:
        """Return paginated journal entries with total count.

        When ``simulation_id`` is None, returns entries from every simulation
        (including the live one).
        """
        limit = min(limit, MAX_LIMIT)
        if simulation_id is None:
            count = await self.db.fetchval(
                "SELECT COUNT(*) FROM journal_entries WHERE agent_id = $1",
                agent_id,
            )
            rows = await self.db.fetch(
                """SELECT * FROM journal_entries
                   WHERE agent_id = $1
                   ORDER BY created_at DESC
                   LIMIT $2 OFFSET $3""",
                agent_id,
                limit,
                offset,
            )
        else:
            count = await self.db.fetchval(
                f"SELECT COUNT(*) FROM journal_entries WHERE agent_id = $1 AND {_sim_filter(2)}",
                agent_id,
                simulation_id,
            )
            rows = await self.db.fetch(
                f"""SELECT * FROM journal_entries
                   WHERE agent_id = $1 AND {_sim_filter(4)}
                   ORDER BY created_at DESC
                   LIMIT $2 OFFSET $3""",
                agent_id,
                limit,
                offset,
                simulation_id,
            )
        return [JournalEntry(**dict(r)) for r in rows], count or 0

    async def get_recent_journal_entries(
        self,
        agent_id: str,
        limit: int = 10,
        simulation_id: _uuid.UUID | None = None,
    ) -> list[JournalEntry]:
        """Return most recent journal entries (for dream recombination)."""
        rows = await self.db.fetch(
            f"""SELECT * FROM journal_entries
               WHERE agent_id = $1 AND {_sim_filter(3)}
               ORDER BY created_at DESC
               LIMIT $2""",
            agent_id,
            limit,
            simulation_id,
        )
        return [JournalEntry(**dict(r)) for r in rows]

    async def get_recent_journal_entries_by_type(
        self,
        agent_id: str,
        reflection_type: str,
        limit: int = 1,
        simulation_id: _uuid.UUID | None = None,
    ) -> list[JournalEntry]:
        """Return most recent journal entries filtered by reflection_type."""
        rows = await self.db.fetch(
            f"""SELECT * FROM journal_entries
               WHERE agent_id = $1 AND reflection_type = $2 AND {_sim_filter(4)}
               ORDER BY created_at DESC
               LIMIT $3""",
            agent_id,
            reflection_type,
            limit,
            simulation_id,
        )
        return [JournalEntry(**dict(r)) for r in rows]

    async def search_recall_memories_by_keyword(
        self,
        agent_id: str,
        keyword: str,
        *,
        limit: int = 50,
        offset: int = 0,
        simulation_id: _uuid.UUID | None = None,
    ) -> tuple[list[RecallMemory], int]:
        """Text search recall memories using ILIKE (pg_trgm if available)."""
        limit = min(limit, MAX_LIMIT)
        pattern = f"%{keyword}%"
        count = await self.db.fetchval(
            f"""SELECT COUNT(*) FROM recall_memory
                WHERE agent_id = $1 AND summary ILIKE $2 AND {_sim_filter(3)}""",
            agent_id,
            pattern,
            simulation_id,
        )
        rows = await self.db.fetch(
            f"""SELECT * FROM recall_memory
               WHERE agent_id = $1 AND summary ILIKE $2 AND {_sim_filter(5)}
               ORDER BY timestamp DESC
               LIMIT $3 OFFSET $4""",
            agent_id,
            pattern,
            limit,
            offset,
            simulation_id,
        )
        return [_row_to_recall(r) for r in rows], count or 0

    async def get_recall_memories_paginated(
        self,
        agent_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        simulation_id: _uuid.UUID | None = None,
    ) -> tuple[list[RecallMemory], int]:
        """Return paginated recall memories for an agent."""
        limit = min(limit, MAX_LIMIT)
        count = await self.db.fetchval(
            f"SELECT COUNT(*) FROM recall_memory WHERE agent_id = $1 AND {_sim_filter(2)}",
            agent_id,
            simulation_id,
        )
        rows = await self.db.fetch(
            f"""SELECT * FROM recall_memory
               WHERE agent_id = $1 AND {_sim_filter(4)}
               ORDER BY timestamp DESC
               LIMIT $2 OFFSET $3""",
            agent_id,
            limit,
            offset,
            simulation_id,
        )
        return [_row_to_recall(r) for r in rows], count or 0

    # ── Self-Modification Proposals ────────────────────────────

    async def create_proposal(
        self, proposal: SelfModificationProposalCreate
    ) -> SelfModificationProposal:
        row = await self.db.fetchrow(
            """INSERT INTO self_modification_proposals
               (agent_id, proposal_type, description, reasoning,
                file, new_content, impact_notes, status, simulation_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'queued_for_review', $8)
               RETURNING *""",
            proposal.agent_id,
            proposal.proposal_type,
            proposal.description,
            proposal.reasoning,
            proposal.file,
            proposal.new_content,
            proposal.impact_notes,
            proposal.simulation_id,
        )
        return SelfModificationProposal(**dict(row))

    async def get_proposals(
        self,
        agent_id: str,
        status: str | None = None,
        simulation_id: _uuid.UUID | None = None,
    ) -> list[SelfModificationProposal]:
        if status:
            rows = await self.db.fetch(
                f"""SELECT * FROM self_modification_proposals
                   WHERE agent_id = $1 AND status = $2 AND {_sim_filter(3)}
                   ORDER BY created_at DESC""",
                agent_id,
                status,
                simulation_id,
            )
        else:
            rows = await self.db.fetch(
                f"""SELECT * FROM self_modification_proposals
                   WHERE agent_id = $1 AND {_sim_filter(2)}
                   ORDER BY created_at DESC""",
                agent_id,
                simulation_id,
            )
        return [SelfModificationProposal(**dict(r)) for r in rows]

    async def update_proposal_status(
        self, proposal_id: int, status: str, reviewed_by: str,
        simulation_id: _uuid.UUID | None = None,
    ) -> None:
        await self.db.execute(
            f"""UPDATE self_modification_proposals
               SET status = $1, reviewed_at = NOW(), reviewed_by = $2
               WHERE id = $3 AND {_sim_filter(4)}""",
            status,
            reviewed_by,
            proposal_id,
            simulation_id,
        )

    async def get_evolution_log(
        self, agent_id: str, limit: int = 10, simulation_id: _uuid.UUID | None = None
    ) -> list[SelfModificationProposal]:
        """Fetch proposals for a specific agent, ordered by most recent first."""
        limit = min(limit, MAX_LIMIT)
        rows = await self.db.fetch(
            f"""SELECT * FROM self_modification_proposals
               WHERE agent_id = $1 AND {_sim_filter(3)}
               ORDER BY created_at DESC
               LIMIT $2""",
            agent_id,
            limit,
            simulation_id,
        )
        return [SelfModificationProposal(**dict(r)) for r in rows]

    async def check_and_auto_approve(
        self, auto_approval_enabled: bool = False,
        simulation_id: _uuid.UUID | None = None,
    ) -> int:
        """Auto-approve proposals older than 4 hours when enabled.

        Returns the number of proposals auto-approved.
        """
        if not auto_approval_enabled:
            return 0
        result = await self.db.execute(
            f"""UPDATE self_modification_proposals
               SET status = 'auto_approved',
                   reviewed_at = NOW(),
                   reviewed_by = 'system:auto_approve'
               WHERE status = 'queued_for_review'
                 AND created_at < NOW() - INTERVAL '4 hours'
                 AND {_sim_filter(1)}""",
            simulation_id,
        )
        # asyncpg execute returns status string like "UPDATE N"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0
