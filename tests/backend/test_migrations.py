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
    "TEST_DATABASE_URL", "postgresql://agi:devpassword@localhost:5434/livestream_agi_test"
)

# Well-known live simulation UUID (seeded by migration 035)
_LIVE_SIM_ID = "00000000-0000-0000-0000-000000000001"

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
    "management_shadow_log",
    "artifacts",
    "simulations",
    "eval_runs",
    "eval_results",
    "agent_internal_state",
    "agent_accounts",
    "agent_goals",
    "agent_relationships",
    "journal_entries",
    "self_modification_proposals",
    "alliances",
    "alliance_members",
    "alliance_proposals",
    "phase_assertions",
    "evolution_cycles",
    "character_applications",
    "character_departures",
    "agent_transactions",
]


def _discover_agent_ids() -> list[str]:
    """Discover agent IDs from the agents/ directory."""
    from pathlib import Path

    agents_dir = Path(__file__).resolve().parent.parent.parent / "agents"
    return sorted(
        d.name
        for d in agents_dir.iterdir()
        if d.is_dir() and (d / "config.yaml").exists() and d.name != "template"
    )


AGENT_IDS = _discover_agent_ids()


@pytest.fixture()
async def conn():
    """Provide a database connection and clean up migrations after each test."""
    c = await asyncpg.connect(DATABASE_URL)
    yield c
    # Drop all tables directly (faster and avoids FK ordering issues from test data)
    await c.execute("""
        DROP TABLE IF EXISTS
            eval_results, eval_runs, eval_analyses, agent_internal_state,
            energy_change_log, self_modification_proposals, journal_entries,
            interrupt_log, conversation_selection_log, expansion_proposals,
            conversation_buffer, recall_memory, core_memory_history, core_memory,
            cost_events, revenue_events, challenges, world_events, world_chunks,
            artifacts, management_shadow_log, agent_goals, agent_relationships,
            phase_assertions, versioned_agent_configs, evolution_cycles,
            prompt_logs, agent_accounts, agent_transactions,
            character_applications, character_departures,
            alliance_proposals, alliances, challenge_votes,
            model_versions,
            simulations, conversations, transcripts, agents, schema_migrations
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
    # Roll back all migrations in reverse order
    # Get current version to know how many times to call down()
    row = await conn.fetchrow("SELECT MAX(version) as v FROM schema_migrations")
    num_migrations = row["v"] if row and row["v"] else 0
    for _ in range(num_migrations):
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
        "dialogue",
        ["vera", "rex"],
        "Hello world",
        2,
    )
    row = await conn.fetchrow("SELECT * FROM transcripts WHERE event_type = 'dialogue'")
    assert row["content"] == "Hello world"

    # core_memory
    await conn.execute(
        "INSERT INTO core_memory (agent_id, content, token_count, simulation_id) VALUES ($1, $2, $3, $4)",
        "vera",
        "I am Vera",
        3,
        _LIVE_SIM_ID,
    )
    row = await conn.fetchrow("SELECT * FROM core_memory WHERE agent_id = 'vera'")
    assert row["content"] == "I am Vera"

    # core_memory_history
    await conn.execute(
        "INSERT INTO core_memory_history (agent_id, content, version, change_reason, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5)",
        "vera",
        "I am Vera",
        1,
        "initial",
        _LIVE_SIM_ID,
    )

    # conversation_buffer
    await conn.execute(
        "INSERT INTO conversation_buffer (agent_id, role, speaker, content, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5)",
        "rex",
        "agent",
        "rex",
        "Let me think.",
        _LIVE_SIM_ID,
    )

    # world_chunks
    await conn.execute(
        "INSERT INTO world_chunks (name, x_offset, y_offset, width, height, tile_data, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        "spawn",
        0,
        0,
        16,
        16,
        "{}",
        _LIVE_SIM_ID,
    )

    # world_events
    await conn.execute(
        "INSERT INTO world_events (event_type, description, simulation_id) VALUES ($1, $2, $3)",
        "build",
        "A new chunk was built",
        _LIVE_SIM_ID,
    )

    # expansion_proposals
    await conn.execute(
        "INSERT INTO expansion_proposals (proposed_by, title, description, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "aurora",
        "New garden",
        "Let's build a garden",
        _LIVE_SIM_ID,
    )

    # challenges
    await conn.execute(
        "INSERT INTO challenges (description, submitted_by, source, simulation_id) VALUES ($1, $2, $3, $4)",
        "Build a bridge",
        "viewer1",
        "twitch",
        _LIVE_SIM_ID,
    )

    # revenue_events
    await conn.execute(
        "INSERT INTO revenue_events (source, amount, simulation_id) VALUES ($1, $2, $3)",
        "twitch_sub",
        4.99,
        _LIVE_SIM_ID,
    )

    # cost_events
    await conn.execute(
        "INSERT INTO cost_events (agent_id, cost_type, amount, simulation_id) VALUES ($1, $2, $3, $4)",
        "vera",
        "llm_api",
        0.0012,
        _LIVE_SIM_ID,
    )

    # conversations
    conv_id = await conn.fetchval(
        "INSERT INTO conversations (trigger_type, initial_energy, participating_agents, simulation_id) "
        "VALUES ($1, $2, $3, $4) RETURNING id",
        "proximity",
        1.0,
        '["vera", "rex"]',
        _LIVE_SIM_ID,
    )
    assert conv_id is not None

    # conversation_selection_log
    await conn.execute(
        "INSERT INTO conversation_selection_log "
        "(conversation_id, turn_number, selected_agent_id, agent_scores, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5)",
        conv_id,
        1,
        "vera",
        '{"vera": 0.8, "rex": 0.6}',
        _LIVE_SIM_ID,
    )

    # interrupt_log
    await conn.execute(
        "INSERT INTO interrupt_log "
        "(conversation_id, attempting_agent_id, would_have_spoken_id, "
        "interrupt_score, threshold_at_time, succeeded, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        conv_id,
        "fork",
        "rex",
        0.85,
        0.7,
        True,
        _LIVE_SIM_ID,
    )

    # recall_memory (requires a vector)
    embedding = [0.0] * 1536
    await conn.execute(
        "INSERT INTO recall_memory (agent_id, summary, embedding, simulation_id) VALUES ($1, $2, $3, $4)",
        "vera",
        "Test memory",
        str(embedding),
        _LIVE_SIM_ID,
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
            "INSERT INTO recall_memory (agent_id, summary, embedding, simulation_id) VALUES ($1, $2, $3, $4)",
            "vera",
            f"memory_{i}",
            str(v),
            _LIVE_SIM_ID,
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
            "INSERT INTO core_memory (agent_id, content, token_count, simulation_id) VALUES ($1, $2, $3, $4)",
            "nonexistent_agent",
            "should fail",
            1,
            _LIVE_SIM_ID,
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
        "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = 'idx_recall_embedding'"
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
        "INSERT INTO core_memory (agent_id, content, token_count, simulation_id) "
        "VALUES ('test_uc', 'memory1', 100, $1)",
        _LIVE_SIM_ID,
    )

    # Second insert with same agent_id + simulation_id should fail on unique constraint
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            "INSERT INTO core_memory (agent_id, content, token_count, simulation_id) "
            "VALUES ('test_uc', 'memory2', 200, $1)",
            _LIVE_SIM_ID,
        )


@pytest.mark.integration
async def test_cross_simulation_isolation(conn):
    """The same agent can exist in two simulations simultaneously without data leakage.

    Verifies the core correctness property of simulation-scoped memory:
    - core_memory rows for 'vera' in sim1 and sim2 are independent.
    - recall_memory rows for 'vera' in sim1 and sim2 are independent.
    - Querying by simulation_id returns exactly the row for that simulation.
    """
    await up(conn)

    sim2_id = "00000000-0000-0000-0000-000000000002"

    # ── Arrange ──────────────────────────────────────────────────────────────

    # Create a second simulation row (sim1 / _LIVE_SIM_ID is seeded by migration 035)
    await conn.execute(
        "INSERT INTO simulations (id, name, description, config, status, agents_participated) "
        "VALUES ($1, $2, $3, $4::jsonb, $5, $6)",
        sim2_id,
        "Test Simulation 2",
        "Second simulation for isolation testing",
        '{"mode": "eval"}',
        "running",
        [],
    )

    # Insert core_memory for 'vera' in sim1
    await conn.execute(
        "INSERT INTO core_memory (agent_id, content, token_count, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "vera",
        "Vera's core memory in sim1",
        5,
        _LIVE_SIM_ID,
    )

    # Insert core_memory for 'vera' in sim2
    await conn.execute(
        "INSERT INTO core_memory (agent_id, content, token_count, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "vera",
        "Vera's core memory in sim2",
        6,
        sim2_id,
    )

    # Insert recall_memory for 'vera' in sim1
    embedding_sim1 = [0.1] * 1536
    embedding_sim1[0] = 1.0
    await conn.execute(
        "INSERT INTO recall_memory (agent_id, summary, embedding, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "vera",
        "Vera's recall in sim1",
        str(embedding_sim1),
        _LIVE_SIM_ID,
    )

    # Insert recall_memory for 'vera' in sim2
    embedding_sim2 = [0.2] * 1536
    embedding_sim2[0] = 0.5
    await conn.execute(
        "INSERT INTO recall_memory (agent_id, summary, embedding, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "vera",
        "Vera's recall in sim2",
        str(embedding_sim2),
        sim2_id,
    )

    # ── Act & Assert: core_memory isolation ──────────────────────────────────

    sim1_core_rows = await conn.fetch(
        "SELECT content FROM core_memory WHERE agent_id = 'vera' AND simulation_id = $1",
        _LIVE_SIM_ID,
    )
    sim2_core_rows = await conn.fetch(
        "SELECT content FROM core_memory WHERE agent_id = 'vera' AND simulation_id = $1",
        sim2_id,
    )

    assert len(sim1_core_rows) == 1, (
        f"Expected 1 core_memory row for vera in sim1, got {len(sim1_core_rows)}"
    )
    assert len(sim2_core_rows) == 1, (
        f"Expected 1 core_memory row for vera in sim2, got {len(sim2_core_rows)}"
    )

    # Verify content is distinct — no cross-contamination
    sim1_content = sim1_core_rows[0]["content"]
    sim2_content = sim2_core_rows[0]["content"]
    assert sim1_content != sim2_content, (
        "core_memory content should differ across simulations, but got the same value"
    )
    assert sim1_content == "Vera's core memory in sim1"
    assert sim2_content == "Vera's core memory in sim2"

    # ── Act & Assert: recall_memory isolation ─────────────────────────────────

    sim1_recall_rows = await conn.fetch(
        "SELECT summary FROM recall_memory WHERE agent_id = 'vera' AND simulation_id = $1",
        _LIVE_SIM_ID,
    )
    sim2_recall_rows = await conn.fetch(
        "SELECT summary FROM recall_memory WHERE agent_id = 'vera' AND simulation_id = $1",
        sim2_id,
    )

    assert len(sim1_recall_rows) == 1, (
        f"Expected 1 recall_memory row for vera in sim1, got {len(sim1_recall_rows)}"
    )
    assert len(sim2_recall_rows) == 1, (
        f"Expected 1 recall_memory row for vera in sim2, got {len(sim2_recall_rows)}"
    )

    sim1_summary = sim1_recall_rows[0]["summary"]
    sim2_summary = sim2_recall_rows[0]["summary"]
    assert sim1_summary != sim2_summary, (
        "recall_memory summaries should differ across simulations, but got the same value"
    )
    assert sim1_summary == "Vera's recall in sim1"
    assert sim2_summary == "Vera's recall in sim2"

    # ── Act & Assert: journal_entries isolation ──────────────────────────────

    await conn.execute(
        "INSERT INTO journal_entries (agent_id, reflection_type, content, token_count, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5)",
        "vera", "6hour", "Journal in sim1", 5, _LIVE_SIM_ID,
    )
    await conn.execute(
        "INSERT INTO journal_entries (agent_id, reflection_type, content, token_count, simulation_id) "
        "VALUES ($1, $2, $3, $4, $5)",
        "vera", "6hour", "Journal in sim2", 5, sim2_id,
    )

    sim1_journals = await conn.fetch(
        "SELECT content FROM journal_entries WHERE agent_id = 'vera' AND simulation_id = $1",
        _LIVE_SIM_ID,
    )
    sim2_journals = await conn.fetch(
        "SELECT content FROM journal_entries WHERE agent_id = 'vera' AND simulation_id = $1",
        sim2_id,
    )
    assert len(sim1_journals) == 1
    assert len(sim2_journals) == 1
    assert sim1_journals[0]["content"] == "Journal in sim1"
    assert sim2_journals[0]["content"] == "Journal in sim2"

    # ── Act & Assert: agent_goals isolation ──────────────────────────────────

    await conn.execute(
        "INSERT INTO agent_goals (agent_id, goal, priority, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "vera", "Goal in sim1", 1, _LIVE_SIM_ID,
    )
    await conn.execute(
        "INSERT INTO agent_goals (agent_id, goal, priority, simulation_id) "
        "VALUES ($1, $2, $3, $4)",
        "vera", "Goal in sim2", 1, sim2_id,
    )

    sim1_goals = await conn.fetch(
        "SELECT goal FROM agent_goals WHERE agent_id = 'vera' AND simulation_id = $1",
        _LIVE_SIM_ID,
    )
    sim2_goals = await conn.fetch(
        "SELECT goal FROM agent_goals WHERE agent_id = 'vera' AND simulation_id = $1",
        sim2_id,
    )
    assert len(sim1_goals) == 1
    assert len(sim2_goals) == 1
    assert sim1_goals[0]["goal"] == "Goal in sim1"
    assert sim2_goals[0]["goal"] == "Goal in sim2"

    # ── Act & Assert: world_events isolation ─────────────────────────────────

    await conn.execute(
        "INSERT INTO world_events (event_type, description, simulation_id) "
        "VALUES ($1, $2, $3)",
        "test", "Event in sim1", _LIVE_SIM_ID,
    )
    await conn.execute(
        "INSERT INTO world_events (event_type, description, simulation_id) "
        "VALUES ($1, $2, $3)",
        "test", "Event in sim2", sim2_id,
    )

    sim1_events = await conn.fetch(
        "SELECT description FROM world_events WHERE simulation_id = $1",
        _LIVE_SIM_ID,
    )
    sim2_events = await conn.fetch(
        "SELECT description FROM world_events WHERE simulation_id = $1",
        sim2_id,
    )
    assert len(sim1_events) == 1
    assert len(sim2_events) == 1
    assert sim1_events[0]["description"] == "Event in sim1"
    assert sim2_events[0]["description"] == "Event in sim2"

    # ── Act & Assert: challenges isolation ────────────────────────────────────

    await conn.execute(
        "INSERT INTO challenges (description, simulation_id) VALUES ($1, $2)",
        "Challenge in sim1", _LIVE_SIM_ID,
    )
    await conn.execute(
        "INSERT INTO challenges (description, simulation_id) VALUES ($1, $2)",
        "Challenge in sim2", sim2_id,
    )

    sim1_ch = await conn.fetch(
        "SELECT description FROM challenges WHERE simulation_id = $1",
        _LIVE_SIM_ID,
    )
    sim2_ch = await conn.fetch(
        "SELECT description FROM challenges WHERE simulation_id = $1",
        sim2_id,
    )
    assert len(sim1_ch) == 1
    assert len(sim2_ch) == 1
    assert sim1_ch[0]["description"] == "Challenge in sim1"
    assert sim2_ch[0]["description"] == "Challenge in sim2"


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
