"""Integration tests for the database migration system.

Requires Docker Compose services (PostgreSQL with pgvector) to be running.
Run with: pytest tests/backend/test_migrations.py -v
"""

from __future__ import annotations

import os

import asyncpg
import pytest
from dotenv import load_dotenv

from db.migrate import down, up

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://agi:devpassword@localhost:5434/livestream_agi"
)

ALL_TABLES = [
    "agents",
    "core_memory",
    "core_memory_history",
    "transcripts",
    "recall_memory",
    "conversation_buffer",
    "world_chunks",
    "world_events",
    "expansion_proposals",
    "challenges",
    "revenue_events",
    "cost_events",
    "conversations",
    "conversation_selection_log",
    "interrupt_log",
    "energy_change_log",
    "overseer_shadow_log",
]

AGENT_IDS = ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok", "overseer", "alpha"]


@pytest.fixture()
async def conn():
    """Provide a database connection and clean up migrations after each test."""
    c = await asyncpg.connect(DATABASE_URL)
    yield c
    # Drop all tables directly (faster and avoids FK ordering issues from test data)
    await c.execute("""
        DROP TABLE IF EXISTS
            energy_change_log, self_modification_proposals, journal_entries,
            interrupt_log, conversation_selection_log, expansion_proposals,
            conversation_buffer, recall_memory, core_memory_history, core_memory,
            cost_events, revenue_events, challenges, world_events, world_chunks,
            conversations, transcripts, agents, schema_migrations
        CASCADE
    """)
    await c.close()


@pytest.mark.integration
async def test_migration_creates_all_tables(conn):
    await up(conn)

    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    table_names = {r["table_name"] for r in rows}

    for table in ALL_TABLES:
        assert table in table_names, f"Table {table} was not created"


@pytest.mark.integration
async def test_migration_idempotent(conn):
    await up(conn)
    # Running up again should not raise
    await up(conn)

    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    table_names = {r["table_name"] for r in rows}
    for table in ALL_TABLES:
        assert table in table_names


@pytest.mark.integration
async def test_rollback(conn):
    await up(conn)
    # Roll back overseer shadow log
    await down(conn)
    # Roll back self-modification fields
    await down(conn)
    # Roll back energy change log
    await down(conn)
    # Roll back reflection tables
    await down(conn)
    # Roll back schema hardening
    await down(conn)
    # Roll back seed data
    await down(conn)
    # Roll back initial schema
    await down(conn)

    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name != 'schema_migrations'"
    )
    table_names = {r["table_name"] for r in rows}

    for table in ALL_TABLES:
        assert table not in table_names, f"Table {table} still exists after rollback"


@pytest.mark.integration
async def test_agent_seed_data(conn):
    await up(conn)

    rows = await conn.fetch("SELECT id FROM agents ORDER BY id")
    ids = sorted(r["id"] for r in rows)
    assert ids == sorted(AGENT_IDS)


@pytest.mark.integration
async def test_insert_and_query_each_table(conn):
    await up(conn)

    # transcripts
    await conn.execute(
        "INSERT INTO transcripts (event_type, participants, content, token_count) "
        "VALUES ($1, $2, $3, $4)",
        "dialogue", ["vera", "rex"], "Hello world", 2,
    )
    row = await conn.fetchrow("SELECT * FROM transcripts WHERE event_type = 'dialogue'")
    assert row["content"] == "Hello world"

    # core_memory
    await conn.execute(
        "INSERT INTO core_memory (agent_id, content, token_count) VALUES ($1, $2, $3)",
        "vera", "I am Vera", 3,
    )
    row = await conn.fetchrow("SELECT * FROM core_memory WHERE agent_id = 'vera'")
    assert row["content"] == "I am Vera"

    # core_memory_history
    await conn.execute(
        "INSERT INTO core_memory_history (agent_id, content, version, change_reason) "
        "VALUES ($1, $2, $3, $4)",
        "vera", "I am Vera", 1, "initial",
    )

    # conversation_buffer
    await conn.execute(
        "INSERT INTO conversation_buffer (agent_id, role, speaker, content) "
        "VALUES ($1, $2, $3, $4)",
        "rex", "agent", "rex", "Let me think.",
    )

    # world_chunks
    await conn.execute(
        "INSERT INTO world_chunks (name, x_offset, y_offset, width, height, tile_data) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        "spawn", 0, 0, 16, 16, "{}",
    )

    # world_events
    await conn.execute(
        "INSERT INTO world_events (event_type, description) VALUES ($1, $2)",
        "build", "A new chunk was built",
    )

    # expansion_proposals
    await conn.execute(
        "INSERT INTO expansion_proposals (proposed_by, title, description) "
        "VALUES ($1, $2, $3)",
        "aurora", "New garden", "Let's build a garden",
    )

    # challenges
    await conn.execute(
        "INSERT INTO challenges (description, submitted_by, source) VALUES ($1, $2, $3)",
        "Build a bridge", "viewer1", "twitch",
    )

    # revenue_events
    await conn.execute(
        "INSERT INTO revenue_events (source, amount) VALUES ($1, $2)",
        "twitch_sub", 4.99,
    )

    # cost_events
    await conn.execute(
        "INSERT INTO cost_events (agent_id, cost_type, amount) VALUES ($1, $2, $3)",
        "vera", "llm_api", 0.0012,
    )

    # conversations
    conv_id = await conn.fetchval(
        "INSERT INTO conversations (trigger_type, initial_energy, participating_agents) "
        "VALUES ($1, $2, $3) RETURNING id",
        "proximity", 1.0, '["vera", "rex"]',
    )
    assert conv_id is not None

    # conversation_selection_log
    await conn.execute(
        "INSERT INTO conversation_selection_log "
        "(conversation_id, turn_number, selected_agent_id, agent_scores) "
        "VALUES ($1, $2, $3, $4)",
        conv_id, 1, "vera", '{"vera": 0.8, "rex": 0.6}',
    )

    # interrupt_log
    await conn.execute(
        "INSERT INTO interrupt_log "
        "(conversation_id, attempting_agent_id, would_have_spoken_id, "
        "interrupt_score, threshold_at_time, succeeded) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        conv_id, "fork", "rex", 0.85, 0.7, True,
    )

    # recall_memory (requires a vector)
    embedding = [0.0] * 1536
    await conn.execute(
        "INSERT INTO recall_memory (agent_id, summary, embedding) VALUES ($1, $2, $3)",
        "vera", "Test memory", str(embedding),
    )


@pytest.mark.integration
async def test_pgvector_similarity_search(conn):
    await up(conn)

    # Insert 3 embeddings with known vectors
    base = [0.0] * 1536
    vecs = []
    for i in range(3):
        v = list(base)
        v[i] = 1.0  # unit vector along dimension i
        vecs.append(v)

    for i, v in enumerate(vecs):
        await conn.execute(
            "INSERT INTO recall_memory (agent_id, summary, embedding) VALUES ($1, $2, $3)",
            "vera", f"memory_{i}", str(v),
        )

    # Query: nearest to vec[0] should be memory_0
    query_vec = str(vecs[0])
    row = await conn.fetchrow(
        "SELECT summary FROM recall_memory ORDER BY embedding <=> $1::vector LIMIT 1",
        query_vec,
    )
    assert row["summary"] == "memory_0"

    # Query: nearest to vec[2] should be memory_2
    query_vec = str(vecs[2])
    row = await conn.fetchrow(
        "SELECT summary FROM recall_memory ORDER BY embedding <=> $1::vector LIMIT 1",
        query_vec,
    )
    assert row["summary"] == "memory_2"


@pytest.mark.integration
async def test_foreign_key_constraints(conn):
    await up(conn)

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute(
            "INSERT INTO core_memory (agent_id, content, token_count) VALUES ($1, $2, $3)",
            "nonexistent_agent", "should fail", 1,
        )


@pytest.mark.integration
async def test_gin_index_exists(conn):
    await up(conn)

    row = await conn.fetchrow(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE indexname = 'idx_transcripts_participants'"
    )
    assert row is not None, "GIN index idx_transcripts_participants not found"
    assert "gin" in row["indexdef"].lower()


@pytest.mark.integration
async def test_ivfflat_index_exists(conn):
    await up(conn)

    row = await conn.fetchrow(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE indexname = 'idx_recall_embedding'"
    )
    assert row is not None, "IVF FLAT index idx_recall_embedding not found"
    assert "ivfflat" in row["indexdef"].lower()


# ── Schema constraint tests ───────────────────────────────────────


@pytest.mark.integration
async def test_agents_table_columns(conn):
    """Agents table has expected columns with correct types."""
    await up(conn)

    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_name = 'agents' ORDER BY ordinal_position"
    )
    columns = {r["column_name"]: r for r in rows}

    assert "id" in columns
    assert "display_name" in columns
    assert "model_conversation" in columns
    assert "model_building" in columns
    assert "voice_id" in columns
    assert "status" in columns
    assert "created_at" in columns

    # id and display_name should be NOT NULL
    assert columns["id"]["is_nullable"] == "NO"
    assert columns["display_name"]["is_nullable"] == "NO"


@pytest.mark.integration
async def test_foreign_key_recall_memory_to_agents(conn):
    """recall_memory.agent_id should reference agents.id."""
    await up(conn)

    fk_rows = await conn.fetch("""
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
        WHERE tc.table_name = 'recall_memory'
            AND tc.constraint_type = 'FOREIGN KEY'
    """)

    fk_targets = {r["foreign_table"] for r in fk_rows}
    assert "agents" in fk_targets, "recall_memory should have FK to agents"


@pytest.mark.integration
async def test_unique_constraint_on_core_memory(conn):
    """core_memory should have a unique constraint on agent_id."""
    await up(conn)

    # Insert an agent first
    await conn.execute(
        "INSERT INTO agents (id, display_name, model_conversation, model_building) "
        "VALUES ('test_uc', 'Test', 'claude-haiku-4-5', 'claude-haiku-4-5')"
    )
    await conn.execute(
        "INSERT INTO core_memory (agent_id, content, token_count) "
        "VALUES ('test_uc', 'memory1', 100)"
    )

    # Second insert with same agent_id should fail on unique constraint
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            "INSERT INTO core_memory (agent_id, content, token_count) "
            "VALUES ('test_uc', 'memory2', 200)"
        )


@pytest.mark.integration
async def test_interrupt_log_fk_to_conversations(conn):
    """interrupt_log should have FK to conversations."""
    await up(conn)

    fk_rows = await conn.fetch("""
        SELECT ccu.table_name AS foreign_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
        WHERE tc.table_name = 'interrupt_log'
            AND tc.constraint_type = 'FOREIGN KEY'
    """)

    fk_targets = {r["foreign_table"] for r in fk_rows}
    assert "conversations" in fk_targets
