"""Tests for the bridge memory read path (issue #549, E5-1)."""

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


@dataclass
class FakeServices:
    core_memory: FakeCoreMemory | None
    recall_memory: FakeRecallMemory | None


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
