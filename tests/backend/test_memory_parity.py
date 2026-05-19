"""Parity tests for tool-facing and bridge-facing memory adapters."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from core.bridge.contract import PROTOCOL_VERSION, BridgeRequest, CostContext
from core.bridge.handlers.memory import handle_memory_read
from core.memory.backend import DefaultMemoryBackend
from tools.memory_tools import RecallMemoryTool

SIMULATION_ID = "11111111-1111-1111-1111-111111111111"
SIMULATION_UUID = uuid.UUID(SIMULATION_ID)


class RecordingRecallMemory:
    def __init__(self, formatted: str) -> None:
        self.formatted = formatted
        self.calls: list[tuple[str, str, int, uuid.UUID | None]] = []

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        self.calls.append((agent_id, query_text, limit, simulation_id))
        return self.formatted


class UnexpectedRecallMemory:
    async def retrieve_recall_memories(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("bridge recall reads should use services.memory_backend")


class RecordingArchivalMemory:
    async def store_transcript(
        self,
        event_type: str,
        participants: list[str],
        content: str,
        conversation_id: object | None = None,
    ) -> Any:
        raise AssertionError("archival writes are not part of recall parity")

    async def retrieve_full_transcript(self, transcript_id: int) -> Any:
        raise AssertionError("archival reads are not part of recall parity")

    async def get_transcripts_by_agent(self, agent_id: str, limit: int = 100) -> list[Any]:
        raise AssertionError("archival reads are not part of recall parity")

    async def get_transcripts_by_type(self, event_type: str, limit: int = 100) -> list[Any]:
        raise AssertionError("archival reads are not part of recall parity")


class RecordingCoreMemory:
    def __init__(self, core_memory: str | None) -> None:
        self.core_memory = core_memory
        self.calls: list[tuple[str, uuid.UUID | None]] = []

    async def get_core_memory(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> str | None:
        self.calls.append((agent_id, simulation_id))
        return self.core_memory


@dataclass
class FakeServices:
    recall_memory: Any | None = None
    core_memory: RecordingCoreMemory | None = None
    memory_backend: Any | None = None


def _memory_request(payload: dict[str, Any]) -> BridgeRequest:
    return BridgeRequest(
        version=PROTOCOL_VERSION,
        request_id="req-memory-parity-test",
        agent_id="rex",
        run_id="run-memory-parity-test",
        simulation_id=SIMULATION_ID,
        service="memory",
        method="recall",
        payload=payload,
        deadline_ms=5000,
        cost_context=CostContext(
            agent_tier="conversation",
            budget_bucket="memory-parity-test",
            estimated_cost_usd=0.0,
        ),
    )


async def test_recall_tool_and_bridge_return_equivalent_results() -> None:
    query = "spawn bridge handoff"
    recall_manager = RecordingRecallMemory(
        "## Relevant memories\n- Rex and Vera coordinated the spawn bridge handoff."
    )
    memory_backend = DefaultMemoryBackend(recall_manager, RecordingArchivalMemory())
    tool = RecallMemoryTool(recall_manager=recall_manager, agent_id="rex")

    tool_result = await tool.execute(
        query=query,
        limit=2,
        simulation_id=SIMULATION_UUID,
    )
    bridge_result = await handle_memory_read(
        _memory_request({"query": query, "tier": "recall", "limit": 2}),
        FakeServices(
            recall_memory=UnexpectedRecallMemory(),
            memory_backend=memory_backend,
        ),
    )

    assert tool_result["status"] == "ok"
    assert tool_result["memories"] == bridge_result["formatted"]
    assert bridge_result["results"] == []
    assert recall_manager.calls == [
        ("rex", query, 2, SIMULATION_UUID),
        ("rex", query, 2, SIMULATION_UUID),
    ]


async def test_recall_tool_and_bridge_return_equivalent_empty_results() -> None:
    query = "unrecorded topic"
    recall_manager = RecordingRecallMemory("")
    memory_backend = DefaultMemoryBackend(recall_manager, RecordingArchivalMemory())
    tool = RecallMemoryTool(recall_manager=recall_manager, agent_id="rex")

    tool_result = await tool.execute(
        query=query,
        limit=4,
        simulation_id=SIMULATION_UUID,
    )
    bridge_result = await handle_memory_read(
        _memory_request({"query": query, "tier": "recall", "limit": 4}),
        FakeServices(
            recall_memory=UnexpectedRecallMemory(),
            memory_backend=memory_backend,
        ),
    )

    assert tool_result == {"status": "no_results", "memories": ""}
    assert bridge_result["formatted"] == tool_result["memories"]
    assert bridge_result["results"] == []
    assert recall_manager.calls == [
        ("rex", query, 4, SIMULATION_UUID),
        ("rex", query, 4, SIMULATION_UUID),
    ]


async def test_bridge_core_read_delegates_to_core_memory_manager() -> None:
    core_manager = RecordingCoreMemory("## Core memory\n\nRex builds useful paths.")
    expected = await core_manager.get_core_memory(
        "rex",
        simulation_id=SIMULATION_UUID,
    )
    core_manager.calls.clear()

    bridge_result = await handle_memory_read(
        _memory_request({"query": "ignored for core reads", "tier": "core", "limit": 2}),
        FakeServices(core_memory=core_manager),
    )

    assert bridge_result["core_memory"] == expected
    assert bridge_result["results"] == []
    assert "formatted" not in bridge_result
    assert core_manager.calls == [("rex", SIMULATION_UUID)]
