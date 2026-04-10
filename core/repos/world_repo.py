"""Repository for world_chunks, world_events, expansion_proposals."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.models import (
    ExpansionProposal,
    ExpansionProposalCreate,
    WorldChunk,
    WorldChunkCreate,
    WorldEvent,
    WorldEventCreate,
)
from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import asyncpg
    import uuid as _uuid

    from core.database import Database


def _row_to_chunk(row: asyncpg.Record) -> WorldChunk:
    """Convert a record row, parsing any JSONB string fields."""
    d = dict(row)
    for key in ("tile_data", "objects", "proposal_votes"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
    return WorldChunk(**d)


class WorldRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── World Chunks ────────────────────────────────────────

    async def create_chunk(
        self, chunk: WorldChunkCreate, simulation_id: _uuid.UUID | None = None
    ) -> WorldChunk:
        row = await self.db.fetchrow(
            """INSERT INTO world_chunks
               (name, x_offset, y_offset, width, height, tile_data,
                objects, built_by, description, tileset_url, simulation_id)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11)
               RETURNING *""",
            chunk.name,
            chunk.x_offset,
            chunk.y_offset,
            chunk.width,
            chunk.height,
            serialize_jsonb(chunk.tile_data),
            serialize_jsonb(chunk.objects),
            chunk.built_by,
            chunk.description,
            chunk.tileset_url,
            chunk.simulation_id,
        )
        return _row_to_chunk(row)

    async def get_chunk(
        self, chunk_id: int, simulation_id: _uuid.UUID | None = None
    ) -> WorldChunk | None:
        if simulation_id is not None:
            row = await self.db.fetchrow(
                "SELECT * FROM world_chunks WHERE id = $1 AND simulation_id = $2",
                chunk_id,
                simulation_id,
            )
        else:
            row = await self.db.fetchrow(
                "SELECT * FROM world_chunks WHERE id = $1", chunk_id
            )
        return _row_to_chunk(row) if row else None

    async def get_chunks_in_area(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        simulation_id: _uuid.UUID | None = None,
    ) -> list[WorldChunk]:
        if simulation_id is not None:
            rows = await self.db.fetch(
                """SELECT * FROM world_chunks
                   WHERE x_offset < $1::int + $3::int
                     AND x_offset + world_chunks.width > $1::int
                     AND y_offset < $2::int + $4::int
                     AND y_offset + world_chunks.height > $2::int
                     AND simulation_id = $5""",
                x,
                y,
                width,
                height,
                simulation_id,
            )
        else:
            rows = await self.db.fetch(
                """SELECT * FROM world_chunks
                   WHERE x_offset < $1::int + $3::int
                     AND x_offset + world_chunks.width > $1::int
                     AND y_offset < $2::int + $4::int
                     AND y_offset + world_chunks.height > $2::int""",
                x,
                y,
                width,
                height,
            )
        return [_row_to_chunk(r) for r in rows]

    # ── World Events ────────────────────────────────────────

    async def create_event(
        self, event: WorldEventCreate, simulation_id: _uuid.UUID | None = None
    ) -> WorldEvent:
        row = await self.db.fetchrow(
            """INSERT INTO world_events
               (event_type, description, agents_involved, audience_participation,
                simulation_id)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING *""",
            event.event_type,
            event.description,
            event.agents_involved,
            event.audience_participation,
            event.simulation_id,
        )
        return WorldEvent(**dict(row))

    async def get_recent_events(
        self, hours: int = 24, simulation_id: _uuid.UUID | None = None
    ) -> list[WorldEvent]:
        """Get events from the last N hours for cooldown and history checks."""
        if simulation_id is not None:
            rows = await self.db.fetch(
                """SELECT * FROM world_events
                   WHERE created_at > NOW() - make_interval(hours => $1)
                     AND simulation_id = $2
                   ORDER BY created_at DESC""",
                hours,
                simulation_id,
            )
        else:
            rows = await self.db.fetch(
                """SELECT * FROM world_events
                   WHERE created_at > NOW() - make_interval(hours => $1)
                   ORDER BY created_at DESC""",
                hours,
            )
        return [WorldEvent(**dict(r)) for r in rows]

    async def get_event_count_since(
        self, since: str, simulation_id: _uuid.UUID | None = None
    ) -> int:
        """Count events since a given timestamp (ISO format or interval)."""
        if simulation_id is not None:
            count = await self.db.fetchval(
                """SELECT COUNT(*) FROM world_events
                   WHERE created_at > $1::timestamptz
                     AND simulation_id = $2""",
                since,
                simulation_id,
            )
        else:
            count = await self.db.fetchval(
                "SELECT COUNT(*) FROM world_events WHERE created_at > $1::timestamptz",
                since,
            )
        return count or 0

    # ── Expansion Proposals ─────────────────────────────────

    async def create_proposal(
        self, proposal: ExpansionProposalCreate, simulation_id: _uuid.UUID | None = None
    ) -> ExpansionProposal:
        row = await self.db.fetchrow(
            """INSERT INTO expansion_proposals
               (proposed_by, title, description, simulation_id)
               VALUES ($1, $2, $3, $4)
               RETURNING *""",
            proposal.proposed_by,
            proposal.title,
            proposal.description,
            proposal.simulation_id,
        )
        return ExpansionProposal(**dict(row))

    async def vote_proposal(
        self, proposal_id: int, vote_for: bool, simulation_id: _uuid.UUID | None = None
    ) -> ExpansionProposal | None:
        if vote_for:
            sql = """UPDATE expansion_proposals
                     SET votes_for = votes_for + 1
                     WHERE id = $1 RETURNING *"""
        else:
            sql = """UPDATE expansion_proposals
                     SET votes_against = votes_against + 1
                     WHERE id = $1 RETURNING *"""
        row = await self.db.fetchrow(sql, proposal_id)
        return ExpansionProposal(**dict(row)) if row else None
