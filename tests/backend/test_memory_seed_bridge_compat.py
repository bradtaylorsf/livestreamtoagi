"""Compatibility coverage for memory_seed and bridge core-memory reads."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.bridge import contract as c
from core.bridge.server import BRIDGE_TOKEN_ENV, BRIDGE_WS_PATH, bridge_router
from core.memory.core_memory import CORE_MEMORY_TEMPLATE
from core.memory.memory_seed import MemorySeedApplier
from core.models import AgentConfig, CoreMemory, MemorySeedConfig

TOKEN = "test-memory-seed-bridge-secret"  # noqa: S105 - test-only shared secret
SEED_FILE = Path("scenarios/seeds/blank-slate.json")
BLANK_SLATE_AGENT_IDS = (
    "vera",
    "rex",
    "aurora",
    "pixel",
    "fork",
    "sentinel",
    "grok",
)


class InMemoryCoreMemoryStore:
    """Shared fake for CoreMemoryManager and MemoryRepo core-memory methods."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, uuid.UUID | None], CoreMemory] = {}

    async def get_core_memory(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> str | None:
        record = self.records.get((agent_id, simulation_id))
        return record.content if record else None

    async def initialize_agent_memory(
        self,
        agent_id: str,
        identity: str,
        simulation_id: uuid.UUID | None = None,
    ) -> CoreMemory:
        content = CORE_MEMORY_TEMPLATE.format(date="2026-05-19", identity=identity)
        return await self.upsert_core_memory(
            agent_id,
            content,
            self._count_tokens(content),
            "initial_creation",
            simulation_id=simulation_id,
        )

    async def upsert_core_memory(
        self,
        agent_id: str,
        content: str,
        token_count: int,
        reason: str,
        simulation_id: uuid.UUID | None = None,
    ) -> CoreMemory:
        record = CoreMemory(
            agent_id=agent_id,
            content=content,
            token_count=token_count,
            simulation_id=simulation_id,
        )
        self.records[(agent_id, simulation_id)] = record
        return record

    @staticmethod
    def _count_tokens(content: str) -> int:
        return max(1, int(len(content.split()) * 1.3))


class FakeRecallMemory:
    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        return ""


@dataclass
class FakeServices:
    core_memory: InMemoryCoreMemoryStore
    recall_memory: FakeRecallMemory


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    return TOKEN


def _make_agent(agent_id: str) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.title(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=0.5,
        initiative=0.5,
        interrupt_tendency=0.1,
    )


def _memory_request(
    *,
    agent_id: str,
    simulation_id: uuid.UUID,
    request_id: str = "req-memory-seed-bridge",
) -> dict[str, Any]:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id=request_id,
        agent_id=agent_id,
        run_id="run-memory-seed-bridge",
        simulation_id=str(simulation_id),
        service="memory",
        method="recall",
        payload={"query": "ignored for core reads", "tier": "core"},
        deadline_ms=5000,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="memory-seed-bridge-test",
            estimated_cost_usd=0.0,
        ),
    ).model_dump()


def _client(services: FakeServices) -> TestClient:
    app = FastAPI()
    app.include_router(bridge_router)
    app.state.services = services
    return TestClient(app)


def _send_memory_request(client: TestClient, request: dict[str, Any]) -> c.BridgeResponse:
    with client.websocket_connect(
        BRIDGE_WS_PATH,
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as ws:
        ws.send_json(request)
        raw_response = ws.receive_json()
    return c.BridgeResponse.model_validate(raw_response)


def test_blank_slate_seed_core_memory_is_visible_through_bridge(token_env: str) -> None:
    seed_data = json.loads(SEED_FILE.read_text())
    expected_vera_memory = seed_data["agents"]["vera"]["core_memory"]
    target_simulation_id = uuid.uuid4()
    other_simulation_id = uuid.uuid4()
    core_memory = InMemoryCoreMemoryStore()
    registry = MagicMock()
    registry.get_all_agents = MagicMock(
        return_value=[_make_agent(agent_id) for agent_id in BLANK_SLATE_AGENT_IDS]
    )
    applier = MemorySeedApplier(
        db=AsyncMock(),
        memory_repo=core_memory,
        core_memory_mgr=core_memory,
        recall_memory_mgr=FakeRecallMemory(),
        agent_registry=registry,
    )

    result = asyncio.run(
        applier.apply(
            MemorySeedConfig(mode="custom", custom_file=str(SEED_FILE)),
            target_simulation_id,
        )
    )

    assert result.core_memories_restored == len(BLANK_SLATE_AGENT_IDS)
    assert sorted(result.agents_restored) == sorted(BLANK_SLATE_AGENT_IDS)

    services = FakeServices(core_memory=core_memory, recall_memory=FakeRecallMemory())
    response = _send_memory_request(
        _client(services),
        _memory_request(agent_id="vera", simulation_id=target_simulation_id),
    )

    assert response.ok is True
    payload = c.validate_response(response, service="memory", method="recall")
    assert isinstance(payload, c.MemoryRecallResponse)
    assert payload.results == []
    assert payload.formatted is None
    assert payload.core_memory == expected_vera_memory
    assert payload.core_memory.startswith("I am Vera. I just woke up")

    scoped_response = _send_memory_request(
        _client(services),
        _memory_request(
            agent_id="vera",
            simulation_id=other_simulation_id,
            request_id="req-memory-seed-bridge-other-sim",
        ),
    )

    assert scoped_response.ok is True
    scoped_payload = c.validate_response(scoped_response, service="memory", method="recall")
    assert isinstance(scoped_payload, c.MemoryRecallResponse)
    assert scoped_payload.core_memory is None
