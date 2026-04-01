"""Repository for the transcripts table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import Transcript, TranscriptCreate

if TYPE_CHECKING:
    from core.database import Database


def _row_to_transcript(row) -> Transcript:
    return Transcript(**dict(row))


class TranscriptRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, transcript: TranscriptCreate) -> Transcript:
        row = await self.db.fetchrow(
            """INSERT INTO transcripts (event_type, participants, content, token_count)
               VALUES ($1, $2, $3, $4)
               RETURNING *""",
            transcript.event_type,
            transcript.participants,
            transcript.content,
            transcript.token_count,
        )
        return _row_to_transcript(row)

    async def get(self, transcript_id: int) -> Transcript | None:
        row = await self.db.fetchrow(
            "SELECT * FROM transcripts WHERE id = $1", transcript_id
        )
        return _row_to_transcript(row) if row else None

    async def search_by_participant(
        self, agent_id: str, limit: int = 100
    ) -> list[Transcript]:
        rows = await self.db.fetch(
            """SELECT * FROM transcripts
               WHERE $1 = ANY(participants)
               ORDER BY created_at DESC
               LIMIT $2""",
            agent_id,
            limit,
        )
        return [_row_to_transcript(r) for r in rows]

    async def search_by_event_type(
        self, event_type: str, limit: int = 100
    ) -> list[Transcript]:
        rows = await self.db.fetch(
            """SELECT * FROM transcripts
               WHERE event_type = $1
               ORDER BY created_at DESC
               LIMIT $2""",
            event_type,
            limit,
        )
        return [_row_to_transcript(r) for r in rows]
