"""ArchivalMemoryManager — Tier 3 archival memory (transcript storage)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import TranscriptCreate

if TYPE_CHECKING:
    from core.memory.token_counter import TokenCounter
    from core.models import Transcript
    from core.repos.transcript_repo import TranscriptRepo


class ArchivalMemoryManager:
    """Manages Tier 3 archival memory: immutable full-text transcript storage.

    Transcripts are never updated or deleted — this tier provides ground truth
    for when agents need full detail from a recall memory reference.
    """

    def __init__(
        self,
        transcript_repo: TranscriptRepo,
        token_counter: TokenCounter,
    ) -> None:
        self._repo = transcript_repo
        self._token_counter = token_counter

    async def store_transcript(
        self,
        event_type: str,
        participants: list[str],
        content: str,
        conversation_id: object | None = None,
    ) -> Transcript:
        """Store a full transcript with automatically calculated token count."""
        token_count = self._token_counter.count_tokens(content)
        create = TranscriptCreate(
            event_type=event_type,
            participants=participants,
            content=content,
            token_count=token_count,
            conversation_id=conversation_id,
        )
        return await self._repo.create(create)

    async def retrieve_full_transcript(
        self, transcript_id: int
    ) -> Transcript | None:
        """Retrieve a complete transcript by ID."""
        return await self._repo.get(transcript_id)

    async def get_transcripts_by_agent(
        self, agent_id: str, limit: int = 100
    ) -> list[Transcript]:
        """Get transcripts where the given agent participated."""
        return await self._repo.search_by_participant(agent_id, limit)

    async def get_transcripts_by_type(
        self, event_type: str, limit: int = 100
    ) -> list[Transcript]:
        """Get transcripts filtered by event type."""
        return await self._repo.search_by_event_type(event_type, limit)
