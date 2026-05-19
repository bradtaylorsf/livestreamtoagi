"""Tests for the bridge memory read/write paths (issues #549/#550, E5-1/E5-2)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.bridge import contract as c
from core.bridge.server import (
    BRIDGE_TOKEN_ENV,
    BRIDGE_WS_PATH,
    ERR_MEMORY_SERVICE_UNAVAILABLE,
    bridge_router,
)
from core.memory.compaction import CompactionResult
from core.models import RecallMemory, Transcript

TOKEN = "test-bridge-memory-secret"  # noqa: S105 - test-only shared secret
SIMULATION_ID = "11111111-1111-1111-1111-111111111111"
SIMULATION_UUID = uuid.UUID(SIMULATION_ID)


class FakeCoreMemory:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.calls: list[tuple[str, uuid.UUID | None]] = []

    async def get_core_memory(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> str | None:
        self.calls.append((agent_id, simulation_id))
        return self.value


class FakeRecallMemory:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls: list[tuple[str, str, int, uuid.UUID | None]] = []

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        self.calls.append((agent_id, query_text, limit, simulation_id))
        return self.value


class FakeCompactor:
    def __init__(self, embedding: list[float] | None = None) -> None:
        self.embedding = embedding or [0.125, 0.25, 0.5]
        self.calls: list[dict[str, Any]] = []
        self.transcripts: list[Transcript] = []
        self.recall_memories: list[RecallMemory] = []

    async def compact_interaction(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        participants: list[str] | None = None,
        conversation_id: object | None = None,
    ) -> CompactionResult | None:
        self.calls.append(
            {
                "agent_id": agent_id,
                "interaction": interaction,
                "event_type": event_type,
                "participants": participants,
                "conversation_id": conversation_id,
            }
        )
        if not interaction or not interaction.strip():
            return None

        stored_participants = participants or [agent_id]
        transcript = Transcript(
            id=len(self.transcripts) + 1,
            event_type=event_type,
            participants=stored_participants,
            content=interaction,
            token_count=len(interaction.split()),
        )
        recall_memory = RecallMemory(
            id=len(self.recall_memories) + 1,
            agent_id=agent_id,
            summary=f"{agent_id}:{event_type}:{interaction}",
            embedding=list(self.embedding),
            event_type=event_type,
            participants=stored_participants,
            transcript_id=transcript.id,
        )
        self.transcripts.append(transcript)
        self.recall_memories.append(recall_memory)
        return CompactionResult(transcript=transcript, recall_memory=recall_memory)


@dataclass
class FakeServices:
    core_memory: FakeCoreMemory | None
    recall_memory: FakeRecallMemory | None
    compactor: FakeCompactor | None = None


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    return TOKEN


def _client(services: Any | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(bridge_router)
    if services is not None:
        app.state.services = services
    return TestClient(app)


def _memory_request(payload: dict[str, Any], simulation_id: str = SIMULATION_ID) -> dict[str, Any]:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id="req-memory-read-test",
        agent_id="vera",
        run_id="run-memory-read-test",
        simulation_id=simulation_id,
        service="memory",
        method="recall",
        payload=payload,
        deadline_ms=5000,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="bridge-memory-test",
            estimated_cost_usd=0.0,
        ),
    ).model_dump()


def _memory_write_request(payload: dict[str, Any]) -> dict[str, Any]:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id="req-memory-write-test",
        agent_id="vera",
        run_id="run-memory-write-test",
        simulation_id=SIMULATION_ID,
        service="memory",
        method="write",
        payload=payload,
        deadline_ms=5000,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="bridge-memory-test",
            estimated_cost_usd=0.0,
        ),
    ).model_dump()


def _send_memory_request(client: TestClient, request: dict[str, Any]) -> c.BridgeResponse:
    with client.websocket_connect(
        BRIDGE_WS_PATH,
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as ws:
        ws.send_json(request)
        raw_response = ws.receive_json()
    return c.BridgeResponse.model_validate(raw_response)


def test_bridge_recall_read_matches_direct_manager_call(token_env: str) -> None:
    services = FakeServices(
        core_memory=FakeCoreMemory("## Core memory"),
        recall_memory=FakeRecallMemory("## Relevant memories\n- [build] Rex built a bridge"),
    )
    query = "what did rex build yesterday"
    expected = asyncio.run(
        services.recall_memory.retrieve_recall_memories(
            "vera",
            query,
            limit=2,
            simulation_id=SIMULATION_UUID,
        )
    )
    services.recall_memory.calls.clear()

    request = _memory_request({"query": query, "tier": "recall", "limit": 2})
    response = _send_memory_request(_client(services), request)

    assert response.ok is True
    payload = c.validate_response(response, service="memory", method="recall")
    assert isinstance(payload, c.MemoryRecallResponse)
    assert payload.results == []
    assert payload.formatted == expected
    assert payload.core_memory is None
    assert services.recall_memory.calls == [("vera", query, 2, SIMULATION_UUID)]
    assert services.core_memory.calls == []


def test_bridge_core_read_matches_direct_manager_call(token_env: str) -> None:
    services = FakeServices(
        core_memory=FakeCoreMemory("## My Core Memory\n\n### Who I am\nVera"),
        recall_memory=FakeRecallMemory("## Relevant memories"),
    )
    expected = asyncio.run(
        services.core_memory.get_core_memory("vera", simulation_id=SIMULATION_UUID)
    )
    services.core_memory.calls.clear()

    request = _memory_request({"query": "ignored for core reads", "tier": "core", "limit": 2})
    response = _send_memory_request(_client(services), request)

    assert response.ok is True
    payload = c.validate_response(response, service="memory", method="recall")
    assert isinstance(payload, c.MemoryRecallResponse)
    assert payload.results == []
    assert payload.formatted is None
    assert payload.core_memory == expected
    assert services.core_memory.calls == [("vera", SIMULATION_UUID)]
    assert services.recall_memory.calls == []


def test_bridge_memory_read_without_services_is_contract_valid_error(token_env: str) -> None:
    request = _memory_request({"query": "anything", "tier": "recall"})
    response = _send_memory_request(_client(), request)

    assert response.ok is False
    assert response.payload is None
    assert response.error is not None
    assert response.error.code == ERR_MEMORY_SERVICE_UNAVAILABLE
    assert response.retryable is True
    c.validate_response(response, service="memory", method="recall")


def test_bridge_memory_read_malformed_simulation_id_uses_unscoped_manager_call(
    token_env: str,
) -> None:
    services = FakeServices(
        core_memory=FakeCoreMemory("## Core memory"),
        recall_memory=FakeRecallMemory("## Relevant memories"),
    )
    request = _memory_request(
        {"query": "anything", "tier": "core"},
        simulation_id="not-a-uuid",
    )

    response = _send_memory_request(_client(services), request)

    assert response.ok is True
    assert services.core_memory.calls == [("vera", None)]


def test_bridge_memory_write_matches_direct_compactor_call(token_env: str) -> None:
    payload = {
        "content": "Rex finished the spawn bridge and Vera logged the handoff.",
        "kind": "event",
        "metadata": {
            "participants": ["vera", "rex"],
            "conversation_id": "22222222-2222-2222-2222-222222222222",
        },
    }
    direct_compactor = FakeCompactor()
    expected = asyncio.run(
        direct_compactor.compact_interaction(
            agent_id="vera",
            interaction=payload["content"],
            event_type=payload["kind"],
            participants=payload["metadata"]["participants"],
            conversation_id=payload["metadata"]["conversation_id"],
        )
    )
    assert expected is not None

    bridge_compactor = FakeCompactor()
    services = FakeServices(core_memory=None, recall_memory=None, compactor=bridge_compactor)
    request = _memory_write_request(payload)
    response = _send_memory_request(_client(services), request)

    assert response.ok is True
    parsed = c.validate_response(response, service="memory", method="write")
    assert isinstance(parsed, c.MemoryWriteResponse)
    assert parsed.memory_id == str(expected.recall_memory.id)
    assert bridge_compactor.calls == direct_compactor.calls
    assert [t.model_dump() for t in bridge_compactor.transcripts] == [
        t.model_dump() for t in direct_compactor.transcripts
    ]
    assert [m.model_dump() for m in bridge_compactor.recall_memories] == [
        m.model_dump() for m in direct_compactor.recall_memories
    ]


def test_bridge_memory_write_is_idempotent_on_request_id(token_env: str) -> None:
    compactor = FakeCompactor()
    services = FakeServices(core_memory=None, recall_memory=None, compactor=compactor)
    request = _memory_write_request(
        {
            "content": "Rex finished the spawn bridge and Vera logged the handoff.",
            "kind": "event",
        }
    )
    client = _client(services)

    first_response = _send_memory_request(client, request)
    second_response = _send_memory_request(client, request)

    first_payload = c.validate_response(first_response, service="memory", method="write")
    second_payload = c.validate_response(second_response, service="memory", method="write")
    assert isinstance(first_payload, c.MemoryWriteResponse)
    assert isinstance(second_payload, c.MemoryWriteResponse)
    assert first_payload.memory_id == second_payload.memory_id == "1"
    assert len(compactor.calls) == 1
    assert len(compactor.transcripts) == 1
    assert len(compactor.recall_memories) == 1


@pytest.mark.parametrize("missing", ["services", "compactor"])
def test_bridge_memory_write_without_services_or_compactor_is_contract_valid_error(
    token_env: str,
    missing: str,
) -> None:
    services = None
    if missing == "compactor":
        services = FakeServices(
            core_memory=FakeCoreMemory("## Core memory"),
            recall_memory=FakeRecallMemory("## Relevant memories"),
            compactor=None,
        )
    request = _memory_write_request({"content": "Remember this event", "kind": "event"})
    response = _send_memory_request(_client(services), request)

    assert response.ok is False
    assert response.payload is None
    assert response.error is not None
    assert response.error.code == ERR_MEMORY_SERVICE_UNAVAILABLE
    assert response.retryable is True
    c.validate_response(response, service="memory", method="write")


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "event"},
        {"content": "", "kind": "event"},
        {"content": "Bridge event", "kind": "banter"},
    ],
)
def test_bridge_memory_write_payload_validation_rejects_missing_empty_or_bad_kind(
    token_env: str,
    payload: dict[str, Any],
) -> None:
    compactor = FakeCompactor()
    services = FakeServices(core_memory=None, recall_memory=None, compactor=compactor)
    response = _send_memory_request(_client(services), _memory_write_request(payload))

    assert response.ok is False
    assert response.payload is None
    assert response.error is not None
    assert response.error.code == c.ERR_INVALID_PAYLOAD
    assert compactor.calls == []
    c.validate_response(response, service="memory", method="write")


def test_bridge_memory_write_whitespace_content_returns_contract_valid_error(
    token_env: str,
) -> None:
    compactor = FakeCompactor()
    services = FakeServices(core_memory=None, recall_memory=None, compactor=compactor)
    response = _send_memory_request(
        _client(services),
        _memory_write_request({"content": "   ", "kind": "event"}),
    )

    assert response.ok is False
    assert response.payload is None
    assert response.error is not None
    assert response.error.code == c.ERR_INVALID_PAYLOAD
    assert compactor.calls == [
        {
            "agent_id": "vera",
            "interaction": "   ",
            "event_type": "event",
            "participants": ["vera"],
            "conversation_id": None,
        }
    ]
    assert compactor.transcripts == []
    assert compactor.recall_memories == []
    c.validate_response(response, service="memory", method="write")
