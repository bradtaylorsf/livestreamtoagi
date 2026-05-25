"""Tests for bridge perception/action event memory consumers (issue #552, E5-4)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Iterator
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
from core.embodiment.build_feedback import BUILD_FEEDBACK_ARTIFACT_TYPE
from core.event_bus import EventType, event_bus
from core.memory.archival_memory import ArchivalMemoryManager
from core.memory.compaction import MemoryCompactor
from core.memory.embeddings import generate_deterministic_embedding
from core.memory.recall_memory import RecallMemoryManager
from core.memory.token_counter import TokenCounter
from core.models import RecallMemory, RecallMemoryCreate, Transcript, TranscriptCreate

EMBEDDING_DIMENSION = 8


class FakeCompactor:
    def __init__(
        self,
        *,
        raise_on_compact: bool = False,
        release_event: asyncio.Event | None = None,
    ) -> None:
        self.raise_on_compact = raise_on_compact
        self.release_event = release_event
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
        if self.release_event is not None:
            await self.release_event.wait()
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


class FakeArtifactRepo:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def save_artifact(self, artifact: object) -> object:
        self.saved.append(artifact)
        return artifact


async def deterministic_embedding(text: str) -> list[float]:
    return generate_deterministic_embedding(text, EMBEDDING_DIMENSION)


async def _wait_for(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting for background memory consumer")


@pytest.fixture(autouse=True)
def cleanup_consumer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("CONVERSATION_MODE", raising=False)
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

    await _wait_for(lambda: len(compactor.calls) == 1)
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


async def test_capitalized_agent_id_is_compacted_lowercase() -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_PERCEPTION,
        {
            "trace_id": "trace-1",
            "request_id": "req-1",
            "agent_id": "Alpha",
            "run_id": "run-1",
            "simulation_id": "sim-1",
            "observations": [{"type": "block", "x": 1, "y": 64, "z": 1}],
        },
    )

    await _wait_for(lambda: len(compactor.calls) == 1)
    assert compactor.calls[0]["agent_id"] == "alpha"
    assert compactor.calls[0]["participants"] == ["alpha"]


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

    await _wait_for(lambda: len(compactor.calls) == 1)
    assert compactor.calls == [
        {
            "agent_id": "rex",
            "interaction": (
                "Action result:\n- action_id: act-7\n- status: success\n- detail: placed 10 blocks"
            ),
            "event_type": "bridge_action_result",
            "participants": ["rex"],
            "conversation_id": None,
        }
    ]


async def test_build_action_and_next_perception_produce_feedback_memory_and_artifact() -> None:
    compactor = FakeCompactor()
    artifact_repo = FakeArtifactRepo()
    sim_id = uuid.uuid4()
    feedback_events: list[dict[str, Any]] = []

    async def on_feedback(event: dict[str, Any]) -> None:
        feedback_events.append(event)

    event_bus.on(EventType.BUILD_FEEDBACK, on_feedback)
    register_memory_consumer(event_bus, compactor, artifact_repo=artifact_repo)
    try:
        await event_bus.emit(
            EventType.BRIDGE_ACTION_RESULT,
            {
                "trace_id": "trace-build-1",
                "request_id": "req-build-1",
                "agent_id": "rex",
                "run_id": "run-1",
                "simulation_id": str(sim_id),
                "action_id": "build-plan-7",
                "status": "partial",
                "outcome_class": "partial",
                "detail": (
                    "buildFromPlan partial: intended=2; present=1; missing=1; completion=0.5"
                ),
                "goal": "Build a two-block marker",
            },
        )
        await event_bus.emit(
            EventType.BRIDGE_PERCEPTION,
            {
                "trace_id": "trace-build-2",
                "request_id": "req-build-2",
                "agent_id": "rex",
                "run_id": "run-1",
                "simulation_id": str(sim_id),
                "observations": [
                    {
                        "type": "structure",
                        "action_id": "build-plan-7",
                        "metric": {
                            "intended_count": 2,
                            "blocks_present": 1,
                            "blocks_missing": 1,
                            "completion_ratio": 0.5,
                        },
                    }
                ],
            },
        )

        await _wait_for(
            lambda: any(call["event_type"] == "build_feedback" for call in compactor.calls)
        )
        await _wait_for(lambda: len(artifact_repo.saved) == 1)
        await _wait_for(lambda: len(feedback_events) == 1)
    finally:
        event_bus.off(EventType.BUILD_FEEDBACK, on_feedback)

    feedback_call = next(call for call in compactor.calls if call["event_type"] == "build_feedback")
    assert feedback_call["agent_id"] == "rex"
    assert "Repair missing intended block or step" in feedback_call["interaction"]
    assert "suggested_next_step" in feedback_call["interaction"]

    artifact = artifact_repo.saved[0]
    assert artifact.simulation_id == sim_id
    assert artifact.agent_id == "rex"
    assert artifact.artifact_type == BUILD_FEEDBACK_ARTIFACT_TYPE
    assert artifact.tool_output["classification"] == "needs_repair"
    assert artifact.tool_output["missing"]["count"] == 1

    assert feedback_events[0]["data"]["attempt_id"] == "build-plan-7"
    assert feedback_events[0]["data"]["suggested_next_step"].startswith("Repair missing")


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

    await _wait_for(lambda: len(recall_repo.memories) == 1)
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


async def test_director_v2_skips_legacy_per_event_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {
            "agent_id": "rex",
            "action_id": "act-director-v2",
            "status": "success",
            "detail": "movement event should be handled by scene memory",
        },
    )

    await asyncio.sleep(0)
    assert compactor.calls == []


async def test_empty_perception_observations_are_noop() -> None:
    compactor = FakeCompactor()
    register_memory_consumer(event_bus, compactor)

    await event_bus.emit(
        EventType.BRIDGE_PERCEPTION,
        {"agent_id": "vera", "observations": []},
    )

    await asyncio.sleep(0)
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

    await asyncio.sleep(0)
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
            await _wait_for(lambda: len(compactor.calls) == 1)
    finally:
        event_bus.off(EventType.SIMULATION_ERROR, on_simulation_error)

    assert len(compactor.calls) == 1
    assert simulation_errors == []
    assert "Failed to compact bridge_action_result memory" in caplog.text


async def test_registered_consumer_does_not_block_bridge_ack() -> None:
    release = asyncio.Event()
    compactor = FakeCompactor(release_event=release)
    register_memory_consumer(event_bus, compactor)

    started = time.monotonic()
    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {
            "agent_id": "grok",
            "action_id": "act-fast-ack",
            "status": "success",
            "detail": "moved before memory finished",
        },
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    await _wait_for(lambda: len(compactor.calls) == 1)
    release.set()


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
