"""Protocol seam for swappable recall and archival memory backends."""

from __future__ import annotations

import os
import uuid as _uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from core.models import RecallMemory, Transcript


@runtime_checkable
class RecallMemoryBackend(Protocol):
    """Recall-memory read/write surface used by bridge and tools."""

    async def store_recall_memory(
        self,
        agent_id: str,
        summary: str,
        embedding: list[float],
        transcript_id: int | None = None,
        event_type: str | None = None,
        participants: list[str] | None = None,
        importance_score: float = 0.5,
        simulation_id: _uuid.UUID | None = None,
    ) -> RecallMemory:
        """Store a new recall memory with its pre-computed embedding."""

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: _uuid.UUID | None = None,
    ) -> str:
        """Retrieve formatted recall memories for a query."""


@runtime_checkable
class ArchivalMemoryBackend(Protocol):
    """Archival-memory read/write surface used by bridge and tools."""

    async def store_transcript(
        self,
        event_type: str,
        participants: list[str],
        content: str,
        conversation_id: object | None = None,
    ) -> Transcript:
        """Store a full transcript."""

    async def retrieve_full_transcript(self, transcript_id: int) -> Transcript | None:
        """Retrieve a complete transcript by ID."""

    async def get_transcripts_by_agent(self, agent_id: str, limit: int = 100) -> list[Transcript]:
        """Get transcripts where the given agent participated."""

    async def get_transcripts_by_type(self, event_type: str, limit: int = 100) -> list[Transcript]:
        """Get transcripts filtered by event type."""


@runtime_checkable
class MemoryBackend(RecallMemoryBackend, ArchivalMemoryBackend, Protocol):
    """Composite recall and archival backend surface."""

    @property
    def recall_memory(self) -> RecallMemoryBackend:
        """Recall-memory backend implementation."""

    @property
    def archival_memory(self) -> ArchivalMemoryBackend:
        """Archival-memory backend implementation."""


class DefaultMemoryBackend:
    """Default backend that delegates to the existing memory managers."""

    def __init__(
        self,
        recall_memory: RecallMemoryBackend,
        archival_memory: ArchivalMemoryBackend,
    ) -> None:
        self._recall_memory = recall_memory
        self._archival_memory = archival_memory

    @property
    def recall_memory(self) -> RecallMemoryBackend:
        """Recall-memory manager backing this backend."""
        return self._recall_memory

    @property
    def archival_memory(self) -> ArchivalMemoryBackend:
        """Archival-memory manager backing this backend."""
        return self._archival_memory

    async def store_recall_memory(
        self,
        agent_id: str,
        summary: str,
        embedding: list[float],
        transcript_id: int | None = None,
        event_type: str | None = None,
        participants: list[str] | None = None,
        importance_score: float = 0.5,
        simulation_id: _uuid.UUID | None = None,
    ) -> RecallMemory:
        """Store a new recall memory through the wrapped recall manager."""
        return await self._recall_memory.store_recall_memory(
            agent_id,
            summary,
            embedding,
            transcript_id=transcript_id,
            event_type=event_type,
            participants=participants,
            importance_score=importance_score,
            simulation_id=simulation_id,
        )

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: _uuid.UUID | None = None,
    ) -> str:
        """Retrieve formatted recall memories through the wrapped recall manager."""
        return await self._recall_memory.retrieve_recall_memories(
            agent_id,
            query_text,
            limit=limit,
            simulation_id=simulation_id,
        )

    async def store_transcript(
        self,
        event_type: str,
        participants: list[str],
        content: str,
        conversation_id: object | None = None,
    ) -> Transcript:
        """Store a full transcript through the wrapped archival manager."""
        return await self._archival_memory.store_transcript(
            event_type,
            participants,
            content,
            conversation_id=conversation_id,
        )

    async def retrieve_full_transcript(self, transcript_id: int) -> Transcript | None:
        """Retrieve a transcript through the wrapped archival manager."""
        return await self._archival_memory.retrieve_full_transcript(transcript_id)

    async def get_transcripts_by_agent(self, agent_id: str, limit: int = 100) -> list[Transcript]:
        """Get transcripts by participant through the wrapped archival manager."""
        return await self._archival_memory.get_transcripts_by_agent(agent_id, limit=limit)

    async def get_transcripts_by_type(self, event_type: str, limit: int = 100) -> list[Transcript]:
        """Get transcripts by event type through the wrapped archival manager."""
        return await self._archival_memory.get_transcripts_by_type(event_type, limit=limit)


_BackendFactory = Callable[[RecallMemoryBackend, ArchivalMemoryBackend], MemoryBackend]
_BACKENDS: dict[str, _BackendFactory] = {"default": DefaultMemoryBackend}


def select_memory_backend(
    recall: RecallMemoryBackend,
    archival: ArchivalMemoryBackend,
    *,
    name: str | None = None,
) -> MemoryBackend:
    """Select the configured memory backend.

    ``default`` is the only registered provider in E5-8 and preserves current
    RecallMemoryManager/ArchivalMemoryManager behavior.
    """
    raw_name = name if name is not None else os.environ.get("MEMORY_BACKEND")
    backend_name = raw_name.strip().lower() if raw_name and raw_name.strip() else "default"
    factory = _BACKENDS.get(backend_name)
    if factory is None:
        raise ValueError(f"Unknown MEMORY_BACKEND '{backend_name}'. Use 'default'.")
    return factory(recall, archival)
