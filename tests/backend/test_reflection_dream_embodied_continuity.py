"""Reflection and dream continuity through the embodied memory bridge."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from core.agent_goals import AgentGoalLegacy
from core.bridge import contract as c
from core.bridge.server import BRIDGE_TOKEN_ENV, BRIDGE_WS_PATH, bridge_router
from core.memory.core_memory import CORE_MEMORY_TEMPLATE, CoreMemoryManager
from core.memory.dreams import DreamManager
from core.memory.embeddings import EMBEDDING_DIMENSION
from core.memory.recall_memory import RecallMemoryManager
from core.memory.reflection import ReflectionManager
from core.models import CoreMemory, JournalEntry, LLMResponse, RecallMemory

TOKEN = "test-reflection-dream-continuity-token"  # noqa: S105 - test-only token


class ContinuityTokenCounter:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class ContinuityLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> LLMResponse:
        messages = kwargs["messages"]
        user_content = messages[-1]["content"]
        self.calls.append(kwargs)

        if "Perform your 6-hour reflection" in user_content:
            content = json.dumps(
                {
                    "importance_scores": {"1": 0.92},
                    "promotions": [
                        {
                            "section": "key_learnings",
                            "content": (
                                "- Mark safe mining paths with torch rings before "
                                "roaming far from camp"
                            ),
                            "reason": "The embodied camp route was hard to find.",
                        }
                    ],
                }
            )
        elif user_content.startswith("Generate up to"):
            content = json.dumps(
                {
                    "goals": [
                        {
                            "goal": "Mark the camp route with lights before the next mining trip",
                            "category": "creative",
                            "priority": 2,
                        }
                    ]
                }
            )
        elif "Dream now" in user_content:
            content = json.dumps(
                {
                    "dream_narrative": (
                        "I saw torch rings hovering over the camp path like a "
                        "map I could walk through."
                    ),
                    "insights": ["Torch rings can become a shared trail language"],
                    "new_goals": [
                        {
                            "description": "Build a torch-ring waypoint at the camp entrance",
                            "category": "creative",
                            "priority": 1,
                        }
                    ],
                    "mood_shift": "determined",
                }
            )
        elif "Write your journal entry" in user_content:
            content = "I learned that the camp route needs visible torch markers."
        else:
            raise AssertionError(f"Unexpected LLM prompt: {user_content}")

        return LLMResponse(
            content=content,
            model=kwargs.get("model", "test-model"),
            input_tokens=10,
            output_tokens=10,
            estimated_cost=Decimal("0"),
            latency_ms=1,
            openrouter_id="test-continuity",
        )


@dataclass
class ContinuityAgentConfig:
    id: str = "vera"
    display_name: str = "Vera"
    role: str = "Coordinator"
    chattiness: float = 0.5
    initiative: float = 0.7
    system_prompt: str = "You remember practical camp lessons and act on them."
    model_building: str = "test-building-model"


class ContinuityRegistry:
    def __init__(self) -> None:
        self.agent = ContinuityAgentConfig()

    def get_agent(self, agent_id: str) -> ContinuityAgentConfig | None:
        return self.agent if agent_id == self.agent.id else None


@dataclass
class RecordedGoal:
    agent_id: str
    goal_text: str
    priority: int
    source: str
    category: str | None
    simulation_id: uuid.UUID | None


class ContinuityGoalManager:
    def __init__(self) -> None:
        self.added: list[RecordedGoal] = []

    async def get_goals(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> list[AgentGoalLegacy]:
        return [
            AgentGoalLegacy(goal=g.goal_text, priority=g.priority, status="pending")
            for g in self.added
            if g.agent_id == agent_id and g.simulation_id == simulation_id
        ]

    async def add_goal(
        self,
        agent_id: str,
        goal_text: str,
        priority: int = 3,
        related_agent: str | None = None,
        source: str = "self",
        category: str | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> AgentGoalLegacy:
        del related_agent
        self.added.append(
            RecordedGoal(
                agent_id=agent_id,
                goal_text=goal_text,
                priority=priority,
                source=source,
                category=category,
                simulation_id=simulation_id,
            )
        )
        return AgentGoalLegacy(goal=goal_text, priority=priority)


@dataclass
class ContinuityMemoryRepo:
    simulation_id: uuid.UUID
    next_recall_id: int = 1
    next_journal_id: int = 1
    core_rows: dict[tuple[str, uuid.UUID | None], CoreMemory] = field(default_factory=dict)
    recall_rows: list[RecallMemory] = field(default_factory=list)
    journal_rows: list[JournalEntry] = field(default_factory=list)

    def seed_core(self, agent_id: str) -> None:
        content = CORE_MEMORY_TEMPLATE.format(
            date="2026-05-25",
            identity="Vera coordinates camp safety in embodied Minecraft runs.",
        )
        self.core_rows[(agent_id, self.simulation_id)] = CoreMemory(
            agent_id=agent_id,
            content=content,
            token_count=len(content.split()),
            simulation_id=self.simulation_id,
        )

    def seed_recall(self, agent_id: str, summary: str, event_type: str) -> None:
        self.recall_rows.append(
            RecallMemory(
                id=self.next_recall_id,
                agent_id=agent_id,
                summary=summary,
                embedding=[0.1] * EMBEDDING_DIMENSION,
                event_type=event_type,
                importance_score=0.5,
                timestamp=datetime.now(UTC),
                simulation_id=self.simulation_id,
            )
        )
        self.next_recall_id += 1

    async def get_core_memory(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> CoreMemory | None:
        return self.core_rows.get((agent_id, simulation_id))

    async def upsert_core_memory(
        self,
        agent_id: str,
        content: str,
        token_count: int,
        reason: str,
        simulation_id: uuid.UUID | None = None,
    ) -> CoreMemory:
        del reason
        current = self.core_rows.get((agent_id, simulation_id))
        row = CoreMemory(
            agent_id=agent_id,
            content=content,
            token_count=token_count,
            version=(current.version + 1) if current else 1,
            last_updated=datetime.now(UTC),
            simulation_id=simulation_id,
        )
        self.core_rows[(agent_id, simulation_id)] = row
        return row

    async def get_recent_recall_memories(
        self,
        agent_id: str,
        since: datetime,
        *,
        limit: int = 20,
        simulation_id: uuid.UUID | None = None,
    ) -> list[RecallMemory]:
        rows = [
            row
            for row in self.recall_rows
            if row.agent_id == agent_id
            and row.simulation_id == simulation_id
            and row.timestamp is not None
            and row.timestamp >= since
        ]
        return sorted(rows, key=lambda row: row.timestamp or datetime.min, reverse=True)[:limit]

    async def update_importance_score(
        self,
        memory_id: int,
        importance_score: float,
        simulation_id: uuid.UUID | None = None,
    ) -> None:
        for row in self.recall_rows:
            if row.id == memory_id and row.simulation_id == simulation_id:
                row.importance_score = importance_score

    async def create_journal_entry(self, entry: Any) -> JournalEntry:
        row = JournalEntry(
            id=self.next_journal_id,
            agent_id=entry.agent_id,
            reflection_type=entry.reflection_type,
            content=entry.content,
            token_count=entry.token_count,
            image_url=getattr(entry, "image_url", None),
            created_at=datetime.now(UTC),
            simulation_id=entry.simulation_id,
        )
        self.journal_rows.append(row)
        self.next_journal_id += 1
        return row

    async def get_recent_journal_entries(
        self,
        agent_id: str,
        limit: int = 10,
        simulation_id: uuid.UUID | None = None,
    ) -> list[JournalEntry]:
        rows = [
            row
            for row in self.journal_rows
            if row.agent_id == agent_id and row.simulation_id == simulation_id
        ]
        return sorted(rows, key=lambda row: row.created_at or datetime.min, reverse=True)[:limit]

    async def add_recall(self, create: Any) -> RecallMemory:
        row = RecallMemory(
            id=self.next_recall_id,
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
        self.recall_rows.append(row)
        self.next_recall_id += 1
        return row

    async def search_recall(
        self,
        agent_id: str,
        embedding: list[float],
        limit: int = 10,
        simulation_id: uuid.UUID | None = None,
    ) -> list[RecallMemory]:
        del embedding
        rows = [
            row
            for row in self.recall_rows
            if row.agent_id == agent_id and row.simulation_id == simulation_id
        ]
        return sorted(rows, key=lambda row: row.timestamp or datetime.min, reverse=True)[:limit]

    async def increment_recalled_count(
        self,
        memory_id: int,
        simulation_id: uuid.UUID | None = None,
    ) -> None:
        for row in self.recall_rows:
            if row.id == memory_id and row.simulation_id == simulation_id:
                row.recalled_count += 1


@dataclass
class RuntimeServices:
    core_memory: CoreMemoryManager
    recall_memory: RecallMemoryManager


@dataclass
class ContinuityBundle:
    simulation_id: uuid.UUID
    repo: ContinuityMemoryRepo
    core_memory: CoreMemoryManager
    recall_memory: RecallMemoryManager
    goal_manager: ContinuityGoalManager


async def _embedding(text: str) -> list[float]:
    del text
    return [0.1] * EMBEDDING_DIMENSION


async def _run_reflection_and_dream_cycle() -> ContinuityBundle:
    simulation_id = uuid.uuid4()
    repo = ContinuityMemoryRepo(simulation_id=simulation_id)
    repo.seed_core("vera")
    repo.seed_recall(
        "vera",
        "Vera placed torches around the hard-to-find camp path after mining.",
        "bridge_action_result",
    )

    token_counter = ContinuityTokenCounter()
    core_memory = CoreMemoryManager(repo, token_counter)
    recall_memory = RecallMemoryManager(repo, _embedding)
    goal_manager = ContinuityGoalManager()
    llm = ContinuityLLM()
    registry = ContinuityRegistry()

    reflection = ReflectionManager(
        memory_repo=repo,
        llm_client=llm,
        core_memory_mgr=core_memory,
        token_counter=token_counter,
        agent_registry=registry,
        goal_manager=goal_manager,
        simulation_id=simulation_id,
    )
    dream = DreamManager(
        memory_repo=repo,
        llm_client=llm,
        core_memory_mgr=core_memory,
        goal_manager=goal_manager,
        simulation_id=simulation_id,
        embedding_fn=_embedding,
    )

    reflection_result = await reflection.run_6hour_reflection("vera")
    dream_result = await dream.run_dream("vera")

    assert reflection_result.promoted_count == 1
    assert dream_result is not None
    assert any(goal.source == "reflection" for goal in goal_manager.added)
    assert any(goal.source == "dream" for goal in goal_manager.added)

    return ContinuityBundle(
        simulation_id=simulation_id,
        repo=repo,
        core_memory=core_memory,
        recall_memory=recall_memory,
        goal_manager=goal_manager,
    )


def _client(services: RuntimeServices) -> TestClient:
    app = FastAPI()
    app.include_router(bridge_router)
    app.state.services = services
    return TestClient(app)


def _memory_request(
    *,
    agent_id: str,
    simulation_id: uuid.UUID,
    tier: str,
    query: str,
    limit: int = 3,
    request_id: str | None = None,
) -> dict[str, Any]:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id=request_id or f"req-continuity-{tier}",
        agent_id=agent_id,
        run_id="run-reflection-dream-continuity",
        simulation_id=str(simulation_id),
        service="memory",
        method="recall",
        payload={"query": query, "tier": tier, "limit": limit},
        deadline_ms=5000,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="memory-continuity-test",
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


def test_reflection_and_dream_outputs_feed_later_embodied_memory_context(
    monkeypatch: Any,
) -> None:
    bundle = asyncio.run(_run_reflection_and_dream_cycle())
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    client = _client(
        RuntimeServices(
            core_memory=bundle.core_memory,
            recall_memory=bundle.recall_memory,
        )
    )

    core_response = _send_memory_request(
        client,
        _memory_request(
            agent_id="vera",
            simulation_id=bundle.simulation_id,
            tier="core",
            query="current embodied lesson before moving",
        ),
    )
    recall_response = _send_memory_request(
        client,
        _memory_request(
            agent_id="vera",
            simulation_id=bundle.simulation_id,
            tier="recall",
            query="torch rings camp waypoint trail language",
            request_id="req-continuity-recall",
            limit=3,
        ),
    )

    core_payload = c.validate_response(core_response, service="memory", method="recall")
    recall_payload = c.validate_response(recall_response, service="memory", method="recall")

    assert isinstance(core_payload, c.MemoryRecallResponse)
    assert isinstance(recall_payload, c.MemoryRecallResponse)
    assert "Mark safe mining paths with torch rings" in (core_payload.core_memory or "")

    formatted = recall_payload.formatted or ""
    assert "[Dream insight] Torch rings can become a shared trail language" in formatted
    assert "[Dream goal] Build a torch-ring waypoint at the camp entrance" in formatted
    assert any(
        row.recalled_count > 0 for row in bundle.repo.recall_rows if row.event_type == "dream"
    )
