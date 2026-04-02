"""Integration tests for Database/RedisClient lifecycle and repo CRUD.

Requires Docker Compose services to be running.
Run with: pytest tests/backend/test_database_integration.py -v -m integration
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from dotenv import load_dotenv

from core.database import Database
from core.models import (
    AgentCreate,
    ConversationCreate,
    CostEventCreate,
    ExpansionProposalCreate,
    RecallMemoryCreate,
    RevenueEventCreate,
    TranscriptCreate,
    WorldChunkCreate,
    WorldEventCreate,
)
from core.redis_client import RedisClient
from core.repos.agent_repo import AgentRepo
from core.repos.conversation_repo import ConversationRepo
from core.repos.cost_repo import CostRepo
from core.repos.memory_repo import MemoryRepo
from core.repos.transcript_repo import TranscriptRepo
from core.repos.world_repo import WorldRepo
from db.migrate import up

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://agi:devpassword@localhost:5434/livestream_agi"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6381")


@pytest.fixture()
async def db():
    """Provide a connected Database instance, clean up after test."""
    database = Database(dsn=DATABASE_URL, min_size=2, max_size=5)
    await database.connect()

    # Run migrations to ensure schema exists
    async with database.acquire() as conn:
        await up(conn)

    yield database

    # Clean all data (but keep schema) for test isolation
    async with database.acquire() as conn:
        await conn.execute("""
            DELETE FROM interrupt_log;
            DELETE FROM conversation_selection_log;
            DELETE FROM conversation_buffer;
            DELETE FROM recall_memory;
            DELETE FROM core_memory_history;
            DELETE FROM core_memory;
            DELETE FROM expansion_proposals;
            DELETE FROM cost_events;
            DELETE FROM revenue_events;
            DELETE FROM challenges;
            DELETE FROM world_events;
            DELETE FROM world_chunks;
            DELETE FROM conversations;
            DELETE FROM transcripts;
        """)
    await database.disconnect()


@pytest.fixture()
async def redis():
    """Provide a connected RedisClient instance."""
    client = RedisClient(url=REDIS_URL)
    await client.connect()
    yield client
    await client.disconnect()


# ── Connection Pool Lifecycle ───────────────────────────────────


@pytest.mark.integration
async def test_pool_connect_and_disconnect():
    """Pool connects, executes a query, and disconnects cleanly."""
    database = Database(dsn=DATABASE_URL, min_size=2, max_size=5)
    await database.connect()
    result = await database.fetchval("SELECT 1")
    assert result == 1
    await database.disconnect()


@pytest.mark.integration
async def test_pool_acquire_context_manager():
    """acquire() yields a usable connection."""
    database = Database(dsn=DATABASE_URL, min_size=2, max_size=5)
    await database.connect()
    async with database.acquire() as conn:
        result = await conn.fetchval("SELECT 42")
        assert result == 42
    await database.disconnect()


@pytest.mark.integration
async def test_redis_connect_and_disconnect():
    """Redis connects, pings, and disconnects cleanly."""
    client = RedisClient(url=REDIS_URL)
    await client.connect()
    result = await client.client.ping()
    assert result is True
    await client.disconnect()


@pytest.mark.integration
async def test_redis_set_get_delete(redis):
    """Basic Redis set/get/delete operations."""
    await redis.set("test_key", "test_value", ex=10)
    val = await redis.get("test_key")
    assert val == "test_value"
    await redis.delete("test_key")
    val = await redis.get("test_key")
    assert val is None


# ── AgentRepo CRUD ──────────────────────────────────────────────


@pytest.mark.integration
async def test_agent_crud(db):
    """Create, read, update agents through AgentRepo."""
    repo = AgentRepo(db)

    # Seeded agents should exist
    agents = await repo.list()
    assert len(agents) >= 9  # 9 seeded agents

    vera = await repo.get("vera")
    assert vera is not None
    assert vera.display_name == "Vera"

    # Update status
    updated = await repo.update_status("vera", "sleeping")
    assert updated is not None
    assert updated.status == "sleeping"

    # Create a new agent
    new_agent = await repo.create(
        AgentCreate(
            id="test_agent",
            display_name="Test Agent",
            model_conversation="test-model",
            model_building="test-model",
        )
    )
    assert new_agent.id == "test_agent"

    # Verify it was created
    fetched = await repo.get("test_agent")
    assert fetched is not None

    # Clean up
    await db.execute("DELETE FROM agents WHERE id = 'test_agent'")
    # Restore vera's status
    await db.execute("UPDATE agents SET status = 'active' WHERE id = 'vera'")


# ── MemoryRepo Transactional Upsert ────────────────────────────


@pytest.mark.integration
async def test_memory_upsert_transactional(db):
    """upsert_core_memory atomically inserts/updates memory + history."""
    repo = MemoryRepo(db)

    # First insert
    mem = await repo.upsert_core_memory("vera", "I am Vera, the showrunner.", 6, "initial")
    assert mem.version == 1
    assert mem.content == "I am Vera, the showrunner."

    # Update (should increment version)
    mem2 = await repo.upsert_core_memory("vera", "I am Vera. I love planning.", 7, "update")
    assert mem2.version == 2

    # History should have both versions
    history = await repo.get_core_memory_history("vera")
    assert len(history) == 2
    assert history[0].version == 1
    assert history[1].version == 2


# ── MemoryRepo: Recall with pgvector ───────────────────────────


@pytest.mark.integration
async def test_recall_memory_vector_search(db):
    """add_recall and search_recall with cosine similarity."""
    repo = MemoryRepo(db)

    # Insert 3 memories with distinct embeddings
    base = [0.0] * 1536
    for i in range(3):
        vec = list(base)
        vec[i] = 1.0
        await repo.add_recall(
            RecallMemoryCreate(
                agent_id="vera",
                summary=f"memory_{i}",
                embedding=vec,
            )
        )

    # Search: closest to vec[0] should be memory_0
    query = list(base)
    query[0] = 1.0
    results = await repo.search_recall("vera", query, limit=1)
    assert len(results) == 1
    assert results[0].summary == "memory_0"

    # Search: closest to vec[2] should be memory_2
    query2 = list(base)
    query2[2] = 1.0
    results2 = await repo.search_recall("vera", query2, limit=1)
    assert results2[0].summary == "memory_2"


# ── ConversationRepo ────────────────────────────────────────────


@pytest.mark.integration
async def test_conversation_lifecycle(db):
    """Create, close, and log selection for a conversation."""
    repo = ConversationRepo(db)

    conv = await repo.create(
        ConversationCreate(
            trigger_type="proximity",
            initial_energy=1.0,
            participating_agents=["vera", "rex"],
            location="spawn",
        )
    )
    assert conv.id is not None
    assert conv.trigger_type == "proximity"

    # Close it
    closed = await repo.close(conv.id, 0.1, "energy_decay")
    assert closed is not None
    assert closed.final_energy == 0.1
    assert closed.closed_by == "energy_decay"

    # Verify get
    fetched = await repo.get(conv.id)
    assert fetched is not None
    assert fetched.ended_at is not None


# ── TranscriptRepo ──────────────────────────────────────────────


@pytest.mark.integration
async def test_transcript_crud(db):
    """Create and search transcripts."""
    repo = TranscriptRepo(db)

    t = await repo.create(
        TranscriptCreate(
            event_type="dialogue",
            participants=["vera", "rex"],
            content="Hello from Vera!",
            token_count=4,
        )
    )
    assert t.id is not None

    fetched = await repo.get(t.id)
    assert fetched is not None
    assert fetched.content == "Hello from Vera!"

    by_participant = await repo.search_by_participant("vera")
    assert len(by_participant) >= 1

    by_type = await repo.search_by_event_type("dialogue")
    assert len(by_type) >= 1


# ── CostRepo ────────────────────────────────────────────────────


@pytest.mark.integration
async def test_cost_and_revenue(db):
    """Add costs and revenue, verify totals."""
    repo = CostRepo(db)

    await repo.add_cost(
        CostEventCreate(agent_id="vera", cost_type="llm_api", amount=Decimal("0.0050"))
    )
    await repo.add_cost(
        CostEventCreate(agent_id="rex", cost_type="llm_api", amount=Decimal("0.0030"))
    )

    total = await repo.get_total_costs()
    assert total == Decimal("0.0080")

    await repo.add_revenue(
        RevenueEventCreate(source="twitch_sub", amount=Decimal("4.99"))
    )
    rev = await repo.get_total_revenue()
    assert rev == Decimal("4.99")

    vera_costs = await repo.get_costs_by_agent("vera")
    assert len(vera_costs) == 1


# ── WorldRepo ───────────────────────────────────────────────────


@pytest.mark.integration
async def test_world_chunk_and_events(db):
    """Create world chunks and events."""
    repo = WorldRepo(db)

    chunk = await repo.create_chunk(
        WorldChunkCreate(
            name="spawn", x_offset=0, y_offset=0, width=16, height=16,
            tile_data={"layers": []}
        )
    )
    assert chunk.id is not None

    fetched = await repo.get_chunk(chunk.id)
    assert fetched is not None
    assert fetched.name == "spawn"

    # Area query
    in_area = await repo.get_chunks_in_area(0, 0, 20, 20)
    assert len(in_area) >= 1

    event = await repo.create_event(
        WorldEventCreate(event_type="build", description="Built spawn",
                         agents_involved=["aurora"])
    )
    assert event.id is not None

    # Proposals
    proposal = await repo.create_proposal(
        ExpansionProposalCreate(
            proposed_by="aurora", title="Garden", description="A peaceful garden"
        )
    )
    assert proposal.id is not None

    voted = await repo.vote_proposal(proposal.id, vote_for=True)
    assert voted is not None
    assert voted.votes_for == 1
