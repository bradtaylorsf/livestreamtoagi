"""Tests for the MemoryBackend protocol seam."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from core.memory.backend import DefaultMemoryBackend, MemoryBackend, select_memory_backend
from core.models import RecallMemory, Transcript

SIMULATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class RecordingRecallBackend:
    def __init__(self) -> None:
        self.store_calls: list[dict[str, Any]] = []
        self.retrieve_calls: list[tuple[str, str, int, uuid.UUID | None]] = []

    async def store_recall_memory(
        self,
        agent_id: str,
        summary: str,
        embedding: list[float],
        transcript_id: int | None = None,
        event_type: str | None = None,
        participants: list[str] | None = None,
        importance_score: float = 0.5,
        simulation_id: uuid.UUID | None = None,
    ) -> RecallMemory:
        self.store_calls.append(
            {
                "agent_id": agent_id,
                "summary": summary,
                "embedding": embedding,
                "transcript_id": transcript_id,
                "event_type": event_type,
                "participants": participants,
                "importance_score": importance_score,
                "simulation_id": simulation_id,
            }
        )
        return RecallMemory(
            id=1,
            agent_id=agent_id,
            summary=summary,
            embedding=embedding,
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
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        self.retrieve_calls.append((agent_id, query_text, limit, simulation_id))
        return "## Relevant memories\n- [event] Vera remembered the bridge."


class RecordingArchivalBackend:
    def __init__(self) -> None:
        self.store_calls: list[tuple[str, list[str], str, object | None]] = []
        self.full_transcript_calls: list[int] = []
        self.agent_calls: list[tuple[str, int]] = []
        self.type_calls: list[tuple[str, int]] = []
        self.transcript = Transcript(
            id=7,
            event_type="event",
            participants=["vera", "rex"],
            content="Vera and Rex tested the bridge.",
            token_count=7,
        )

    async def store_transcript(
        self,
        event_type: str,
        participants: list[str],
        content: str,
        conversation_id: object | None = None,
    ) -> Transcript:
        self.store_calls.append((event_type, participants, content, conversation_id))
        return self.transcript.model_copy(
            update={
                "event_type": event_type,
                "participants": participants,
                "content": content,
            }
        )

    async def retrieve_full_transcript(self, transcript_id: int) -> Transcript | None:
        self.full_transcript_calls.append(transcript_id)
        return self.transcript

    async def get_transcripts_by_agent(self, agent_id: str, limit: int = 100) -> list[Transcript]:
        self.agent_calls.append((agent_id, limit))
        return [self.transcript]

    async def get_transcripts_by_type(self, event_type: str, limit: int = 100) -> list[Transcript]:
        self.type_calls.append((event_type, limit))
        return [self.transcript]


async def test_default_backend_satisfies_memory_backend_protocol_and_delegates() -> None:
    recall = RecordingRecallBackend()
    archival = RecordingArchivalBackend()
    backend = DefaultMemoryBackend(recall, archival)

    assert isinstance(backend, MemoryBackend)
    assert backend.recall_memory is recall
    assert backend.archival_memory is archival

    stored_recall = await backend.store_recall_memory(
        "vera",
        "Vera remembered the bridge.",
        [0.1, 0.2, 0.3],
        transcript_id=7,
        event_type="event",
        participants=["vera", "rex"],
        importance_score=0.8,
        simulation_id=SIMULATION_ID,
    )
    retrieved = await backend.retrieve_recall_memories(
        "vera",
        "bridge",
        limit=2,
        simulation_id=SIMULATION_ID,
    )
    stored_transcript = await backend.store_transcript(
        "event",
        ["vera", "rex"],
        "Vera and Rex tested the bridge.",
        conversation_id="conversation-1",
    )
    full_transcript = await backend.retrieve_full_transcript(7)
    by_agent = await backend.get_transcripts_by_agent("vera", limit=5)
    by_type = await backend.get_transcripts_by_type("event", limit=6)

    assert stored_recall.agent_id == "vera"
    assert retrieved.startswith("## Relevant memories")
    assert stored_transcript.content == "Vera and Rex tested the bridge."
    assert full_transcript == archival.transcript
    assert by_agent == [archival.transcript]
    assert by_type == [archival.transcript]
    assert recall.store_calls == [
        {
            "agent_id": "vera",
            "summary": "Vera remembered the bridge.",
            "embedding": [0.1, 0.2, 0.3],
            "transcript_id": 7,
            "event_type": "event",
            "participants": ["vera", "rex"],
            "importance_score": 0.8,
            "simulation_id": SIMULATION_ID,
        }
    ]
    assert recall.retrieve_calls == [("vera", "bridge", 2, SIMULATION_ID)]
    assert archival.store_calls == [
        ("event", ["vera", "rex"], "Vera and Rex tested the bridge.", "conversation-1")
    ]
    assert archival.full_transcript_calls == [7]
    assert archival.agent_calls == [("vera", 5)]
    assert archival.type_calls == [("event", 6)]


def test_select_memory_backend_uses_default_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)

    backend = select_memory_backend(RecordingRecallBackend(), RecordingArchivalBackend())

    assert isinstance(backend, DefaultMemoryBackend)
    assert isinstance(backend, MemoryBackend)


def test_select_memory_backend_accepts_default_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_BACKEND", " default ")

    backend = select_memory_backend(RecordingRecallBackend(), RecordingArchivalBackend())

    assert isinstance(backend, DefaultMemoryBackend)


def test_select_memory_backend_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown MEMORY_BACKEND 'answer-engine'"):
        select_memory_backend(
            RecordingRecallBackend(),
            RecordingArchivalBackend(),
            name="answer-engine",
        )
