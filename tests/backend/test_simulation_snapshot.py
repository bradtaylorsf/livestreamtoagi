"""Tests for SimulationSnapshotExporter and SimulationSnapshotImporter.

Covers full simulation state capture and restore (issue #252).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from core.simulation.snapshot import (
    SNAPSHOT_VERSION,
    SimulationSnapshot,
    SimulationSnapshotExporter,
    SimulationSnapshotImporter,
    SnapshotRestoreResult,
)

SIM_ID = str(uuid.uuid4())
SIM_UUID = uuid.UUID(SIM_ID)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _mock_acquire():
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        yield conn

    db.acquire = _mock_acquire
    return db


@pytest.fixture
def exporter(mock_db):
    return SimulationSnapshotExporter(db=mock_db)


@pytest.fixture
def importer(mock_db):
    return SimulationSnapshotImporter(db=mock_db)


# ── Exporter tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_empty_simulation(mock_db, exporter):
    """Export a sim with no data returns valid empty snapshot structure."""
    # agents_participated row has no agents
    mock_db.fetchrow.return_value = {"agents_participated": []}
    # core_memory fallback also returns nothing
    mock_db.fetch.return_value = []

    result = await exporter.export(SIM_ID)

    assert result["version"] == SNAPSHOT_VERSION
    assert result["source_simulation_id"] == SIM_ID
    assert result["agents"] == {}
    assert result["agent_states"] == {}
    assert result["agent_accounts"] == {}
    assert result["agent_goals"] == {}
    assert result["world_chunks"] == []
    assert result["relationships"] == []
    assert result["snapshot_at"] != ""


@pytest.mark.asyncio
async def test_export_with_core_memory(mock_db):
    """Export with core memory: DB fetchrow returns a row, verify core_memory in output."""
    # Make agents_participated return ["rex"]
    mock_db.fetchrow.return_value = {"agents_participated": ["rex"]}

    captured_conn = None

    @asynccontextmanager
    async def _acquire():
        nonlocal captured_conn
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        # core memory for rex
        conn.fetchrow = AsyncMock(return_value={"content": "I am Rex the builder"})
        # all fetch calls return empty (recall, journal, internal_state, accounts, goals, chunks, relationships)
        conn.fetch = AsyncMock(return_value=[])
        captured_conn = conn
        yield conn

    mock_db.acquire = _acquire

    exporter = SimulationSnapshotExporter(db=mock_db)
    result = await exporter.export(SIM_ID)

    assert "rex" in result["agents"]
    assert result["agents"]["rex"]["core_memory"] == "I am Rex the builder"


@pytest.mark.asyncio
async def test_export_preserves_timestamps(mock_db):
    """Verify recall memory timestamps are included in the export."""
    mock_db.fetchrow.return_value = {"agents_participated": ["vera"]}

    ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
    recall_row = MagicMock()
    recall_row.__getitem__ = lambda self, key: {
        "summary": "Team meeting",
        "importance_score": 0.8,
        "event_type": "conversation",
        "participants": ["rex", "vera"],
        "embedding": "[0.1,0.2,0.3]",
        "timestamp": ts,
        "recalled_count": 3,
    }[key]

    call_count = 0

    @asynccontextmanager
    async def _acquire():
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)

        nonlocal call_count

        async def _fetchrow(*args, **kwargs):
            return None  # no core memory

        async def _fetch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First fetch call for this agent is recall_memory
                return [recall_row]
            return []

        conn.fetchrow = _fetchrow
        conn.fetch = _fetch
        yield conn

    mock_db.acquire = _acquire

    exporter = SimulationSnapshotExporter(db=mock_db)
    result = await exporter.export(SIM_ID)

    assert "vera" in result["agents"]
    recall_memories = result["agents"]["vera"]["recall_memories"]
    assert len(recall_memories) == 1
    assert recall_memories[0]["timestamp"] == ts.isoformat()
    assert recall_memories[0]["recalled_count"] == 3


@pytest.mark.asyncio
async def test_get_agent_ids_from_simulation_record(mock_db):
    """When agents_participated exists on the simulation record, use it."""
    mock_db.fetchrow.return_value = {"agents_participated": ["fork", "aurora", "rex"]}

    @asynccontextmanager
    async def _acquire():
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])
        yield conn

    mock_db.acquire = _acquire

    exporter = SimulationSnapshotExporter(db=mock_db)
    result = await exporter.export(SIM_ID)

    # All three agents should appear in the snapshot (even if empty memory)
    assert set(result["agents"].keys()) == {"fork", "aurora", "rex"}
    # fetch for agents_participated should have been called, not the fallback
    mock_db.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_ids_fallback_to_core_memory(mock_db):
    """When agents_participated is empty, fall back to querying core_memory."""
    # agents_participated is empty list — triggers fallback
    mock_db.fetchrow.return_value = {"agents_participated": []}
    mock_db.fetch.return_value = [
        {"agent_id": "pixel"},
        {"agent_id": "sentinel"},
    ]

    @asynccontextmanager
    async def _acquire():
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])
        yield conn

    mock_db.acquire = _acquire

    exporter = SimulationSnapshotExporter(db=mock_db)
    result = await exporter.export(SIM_ID)

    # Fallback fetch was called on the outer db
    mock_db.fetch.assert_called_once()
    assert set(result["agents"].keys()) == {"pixel", "sentinel"}


# ── Importer tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_core_memory(mock_db, importer):
    """Restore a snapshot with core memory, verify correct SQL is executed."""
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "source_simulation_id": SIM_ID,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "agents": {
            "rex": {
                "core_memory": "I am Rex, the chief builder",
                "recall_memories": [],
                "journal_entries": [],
            },
        },
        "agent_states": {},
        "agent_accounts": {},
        "agent_goals": {},
        "world_chunks": [],
        "relationships": [],
    }

    result = await importer.restore(snapshot, SIM_ID)

    assert result.core_memories_restored == 1
    assert "rex" in result.agents_restored
    assert result.warnings == []

    # Verify execute was called with an INSERT into core_memory
    execute_calls = [str(c.args[0]) for c in mock_db.execute.call_args_list]
    assert any("core_memory" in sql for sql in execute_calls)


@pytest.mark.asyncio
async def test_restore_recall_with_timestamps(mock_db, importer):
    """Verify timestamps are preserved when restoring recall memories."""
    ts = "2025-03-01T10:00:00+00:00"
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "source_simulation_id": SIM_ID,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "agents": {
            "aurora": {
                "core_memory": "",
                "recall_memories": [
                    {
                        "summary": "Creative brainstorm session",
                        "importance_score": 0.9,
                        "event_type": "conversation",
                        "participants": ["aurora", "rex"],
                        "embedding": [0.1] * 10,
                        "timestamp": ts,
                        "recalled_count": 2,
                    }
                ],
                "journal_entries": [],
            },
        },
        "agent_states": {},
        "agent_accounts": {},
        "agent_goals": {},
        "world_chunks": [],
        "relationships": [],
    }

    result = await importer.restore(snapshot, SIM_ID)

    assert result.recall_memories_restored == 1
    assert result.warnings == []

    # Verify that the timestamp was passed into the INSERT
    execute_calls = mock_db.execute.call_args_list
    recall_call = next(
        c for c in execute_calls if "recall_memory" in str(c.args[0])
    )
    # The parsed datetime should be in the args
    call_args = recall_call.args
    ts_parsed = datetime.fromisoformat(ts)
    assert ts_parsed in call_args


@pytest.mark.asyncio
async def test_restore_with_clear_first(mock_db, importer):
    """_clear_simulation_state deletes from all expected tables."""
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "source_simulation_id": SIM_ID,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "agents": {
            "rex": {
                "core_memory": "Rex memory",
                "recall_memories": [],
                "journal_entries": [],
            },
        },
        "agent_states": {},
        "agent_accounts": {},
        "agent_goals": {},
        "world_chunks": [],
        "relationships": [],
    }

    await importer.restore(snapshot, SIM_ID, clear_first=True)

    execute_calls = [str(c.args[0]) for c in mock_db.execute.call_args_list]

    expected_tables = {
        "core_memory",
        "recall_memory",
        "journal_entries",
        "agent_goals",
        "agent_internal_state",
        "agent_accounts",
        "agent_relationships",
        "world_chunks",
    }
    deleted_tables = {
        table for table in expected_tables
        if any(f"DELETE FROM {table}" in sql for sql in execute_calls)
    }
    assert deleted_tables == expected_tables, (
        f"Missing DELETE for: {expected_tables - deleted_tables}"
    )


@pytest.mark.asyncio
async def test_restore_version_mismatch_warning(mock_db, importer):
    """Snapshot with an unknown version should produce a warning."""
    snapshot = {
        "version": 99,
        "source_simulation_id": SIM_ID,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "agents": {},
        "agent_states": {},
        "agent_accounts": {},
        "agent_goals": {},
        "world_chunks": [],
        "relationships": [],
    }

    result = await importer.restore(snapshot, SIM_ID)

    assert any("version" in w.lower() for w in result.warnings), (
        f"Expected version warning, got: {result.warnings}"
    )


@pytest.mark.asyncio
async def test_restore_with_agent_filter(mock_db, importer):
    """Only filtered agents should be restored."""
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "source_simulation_id": SIM_ID,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "agents": {
            "rex": {"core_memory": "Rex", "recall_memories": [], "journal_entries": []},
            "fork": {"core_memory": "Fork", "recall_memories": [], "journal_entries": []},
            "vera": {"core_memory": "Vera", "recall_memories": [], "journal_entries": []},
        },
        "agent_states": {},
        "agent_accounts": {},
        "agent_goals": {},
        "world_chunks": [],
        "relationships": [],
    }

    result = await importer.restore(snapshot, SIM_ID, agents=["rex", "fork"])

    assert sorted(result.agents_restored) == ["fork", "rex"]
    assert "vera" not in result.agents_restored
    assert result.core_memories_restored == 2
