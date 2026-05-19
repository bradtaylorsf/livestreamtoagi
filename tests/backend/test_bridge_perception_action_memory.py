"""Tests for bridge perception/action event memory consumers (issue #552, E5-4)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from core.bridge.consumers import (
    format_action_result,
    format_observations,
    register_memory_consumer,
    unregister_memory_consumer,
)
from core.event_bus import EventType, event_bus
from core.memory.archival_memory import ArchivalMemoryManager
from core.memory.compaction import MemoryCompactor
from core.memory.embeddings import generate_deterministic_embedding
from core.memory.recall_memory import RecallMemoryManager
from core.memory.token_counter import TokenCounter
from core.models import RecallMemory, RecallMemoryCreate, Transcript, TranscriptCreate

EMBEDDING_DIMENSION = 8


class FakeCompactor:
    def __init__(self, *, raise_on_compact: bool = False) -> None:
        self.raise_on_compact = raise_on_compact
        self.calls: list[dict[str, Any]] = []

    async def compact_interaction(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        participants: list[str] | None = None,
        conversation_id: object | None = None,
    ) -> object:
        self.calls.append(
            {
                "agent_id": agent_id,
                "interaction": interaction,
                "event_type": event_type,
                "participants": participants,
                "conversation_id": conversation_id,
            }
        )
        if self.raise_on_compact:
            raise RuntimeError("memory unavailable")
        return object()


class InMemoryTranscriptRepo:
    def __init__(self) -> None:
        self.transcripts: list[Transcript] = []

    async def create(self, create: TranscriptCreate) -> Transcript:
        transcript = Transcript(
            id=len(self.transcripts) + 1,
            event_type=create.event_type,
            participants=create.participants,
            content=create.content,
            token_count=create.token_count,
        )
        self.transcripts.append(transcript)
        return transcript

    async def get(self, transcript_id: int) -> Transcript | None:
        return next((t for t in self.transcripts if t.id == transcript_id), None)

    async def search_by_participant(self, agent_id: str, limit: int) -> list[Transcript]:
        return [t for t in self.transcripts if agent_id in t.participants][:limit]

    async def search_by_event_type(self, event_type: str, limit: int) -> list[Transcript]:
        return [t for t in self.transcripts if t.event_type == event_type][:limit]


class InMemoryRecallRepo:
    def __init__(self) -> None:
        self.memories: list[RecallMemory] = []

    async def add_recall(self, create: RecallMemoryCreate) -> RecallMemory:
        memory = RecallMemory(
            id=len(self.memories) + 1,
            agent_id=create.agent_id,
            summary=create.summary,
            embedding=create.embedding,
            event_type=create.event_type,
            participants=create.participants,
            transcript_id=create.transcript_id,
            importance_score=create.importance_score,
            timestamp=datetime.now(UTC),
            simulation_id=create.simulation_id,
        )
        self.memories.append(memory)
        return memory

    async def search_recall(
        self,
        agent_id: str,
        _embedding: list[float],
        limit: int,
        simulation_id: object | None = None,
    ) -> list[RecallMemory]:
        return [
            m
            for m in self.memories
            if m.agent_id == agent_id
            and (simulation_id is None or m.simulation_id == simulation_id)
        ][:limit]

    async def increment_recalled_count(
        self,
        memory_id: int,
        simulation_id: object | None = None,
    ) -> None:
        for memory in self.memories:
            if memory.id == memory_id and (
                simulation_id is None or memory.simulation_id == simulation_id
            ):
                memory.recalled_count += 1


class FakeLLMClient:
    async def complete(self, *args: object, **kwargs: object) -> object:
        return SimpleNamespace(content="Rex observed action act-7 succeed: placed 10 blocks.")


async def deterministic_embedding(text: str) -> list[float]:
    return generate_deterministic_embedding(text, EMBEDDING_DIMENSION)


@pytest.fixture(autouse=True)
def cleanup_consumer() -> Iterator[None]:
    unregister_memory_consumer(event_bus)
    try:
        yield
    finally:
        unregister_memory_consumer(event_bus)


def test_format_observations_is_deterministic() -> None:
    assert format_observations([{"z": 3, "type": "block", "x": 1, "y": 2}]) == (
        'Perception report:\n- {"type": "block", "x": 1, "y": 2, "z": 3}'
    )


def test_format_action_result_omits_blank_detail() -> None:
    assert format_action_result("act-7", "success", "  ") == (
        "Action result:\n- action_id: act-7\n- status: success"
    )


async def test_perception_event_compacts_to_existing_memory_path() -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_PERCEPTION,
        {
            "trace_id": "trace-1",
            "request_id": "req-1",
            "agent_id": "vera",
            "run_id": "run-1",
            "simulation_id": "sim-1",
            "observations": [
                {"z": 3, "type": "block", "x": 1, "y": 2},
                {"type": "entity", "distance": 2},
            ],
        },
    )

    assert compactor.calls == [
        {
            "agent_id": "vera",
            "interaction": (
                'Perception report:\n- {"type": "block", "x": 1, "y": 2, "z": 3}\n'
                '- {"distance": 2, "type": "entity"}'
            ),
            "event_type": "bridge_perception",
            "participants": ["vera"],
            "conversation_id": None,
        }
    ]


async def test_action_result_event_compacts_to_existing_memory_path() -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {
            "trace_id": "trace-2",
            "request_id": "req-2",
            "agent_id": "rex",
            "run_id": "run-1",
            "simulation_id": "sim-1",
            "action_id": "act-7",
            "status": "success",
            "detail": "placed 10 blocks",
        },
    )

    assert compactor.calls == [
        {
            "agent_id": "rex",
            "interaction": (
                "Action result:\n"
                "- action_id: act-7\n"
                "- status: success\n"
                "- detail: placed 10 blocks"
            ),
            "event_type": "bridge_action_result",
            "participants": ["rex"],
            "conversation_id": None,
        }
    ]


async def test_action_result_event_creates_retrievable_recall_with_embedding() -> None:
    transcript_repo = InMemoryTranscriptRepo()
    recall_repo = InMemoryRecallRepo()
    recall = RecallMemoryManager(recall_repo, embedding_fn=deterministic_embedding)
    archival = ArchivalMemoryManager(transcript_repo, TokenCounter())
    compactor = MemoryCompactor(
        archival=archival,
        recall=recall,
        llm_client=FakeLLMClient(),
        http_client=object(),
        openrouter_api_key="",
        embedding_fn=deterministic_embedding,
    )
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {
            "agent_id": "rex",
            "action_id": "act-7",
            "status": "success",
            "detail": "placed 10 blocks",
        },
    )

    assert len(transcript_repo.transcripts) == 1
    assert len(recall_repo.memories) == 1
    memory = recall_repo.memories[0]
    assert memory.event_type == "bridge_action_result"
    assert memory.participants == ["rex"]
    assert memory.transcript_id == transcript_repo.transcripts[0].id
    assert memory.embedding == generate_deterministic_embedding(
        memory.summary,
        EMBEDDING_DIMENSION,
    )

    formatted = await recall.retrieve_recall_memories("rex", "what action succeeded", limit=1)

    assert "[bridge_action_result]" in formatted
    assert "placed 10 blocks" in formatted


async def test_empty_perception_observations_are_noop() -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_PERCEPTION,
        {"agent_id": "vera", "observations": []},
    )

    assert compactor.calls == []


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (EventType.BRIDGE_PERCEPTION, {"observations": [{"type": "block"}]}),
        (
            EventType.BRIDGE_ACTION_RESULT,
            {"action_id": "act-7", "status": "success", "detail": "placed 10 blocks"},
        ),
    ],
)
async def test_missing_agent_id_is_noop(event_type: EventType, data: dict[str, Any]) -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(event_type, data)

    assert compactor.calls == []


async def test_compactor_exceptions_are_logged_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    compactor = FakeCompactor(raise_on_compact=True)
    simulation_errors: list[dict[str, Any]] = []

    async def on_simulation_error(event: dict[str, Any]) -> None:
        simulation_errors.append(event)

    event_bus.on(EventType.SIMULATION_ERROR, on_simulation_error)
    register_memory_consumer(event_bus, compactor)
    try:
        with caplog.at_level(
            logging.ERROR,
            logger="core.bridge.consumers.perception_action_memory",
        ):
            await event_bus.emit(
                EventType.BRIDGE_ACTION_RESULT,
                {
                    "agent_id": "pixel",
                    "action_id": "act-8",
                    "status": "failure",
                    "detail": "path blocked",
                },
            )
    finally:
        event_bus.off(EventType.SIMULATION_ERROR, on_simulation_error)

    assert len(compactor.calls) == 1
    assert simulation_errors == []
    assert "Failed to compact bridge_action_result memory" in caplog.text


async def test_unregister_memory_consumer_removes_callbacks() -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)
    unregister_memory_consumer(event_bus)

    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {
            "agent_id": "sentinel",
            "action_id": "act-9",
            "status": "partial",
            "detail": "budget check pending",
        },
    )

    assert compactor.calls == []
