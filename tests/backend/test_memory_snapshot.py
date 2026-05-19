"""Tests for memory snapshot export and import."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.memory.snapshot import (
    SNAPSHOT_VERSION,
    AgentSnapshot,
    MemorySnapshot,
    MemorySnapshotImporter,
    RestoreResult,
)
from core.models import CoreMemory, JournalEntry, RecallMemory

# ── Schema model tests ─────────────────────────────────────────


def test_memory_snapshot_defaults():
    snap = MemorySnapshot()
    assert snap.version == SNAPSHOT_VERSION
    assert snap.agents == {}
    assert snap.relationships == []


def test_agent_snapshot_defaults():
    agent = AgentSnapshot()
    assert agent.core_memory == ""
    assert agent.recall_memories == []
    assert agent.journal_entries == []


def test_memory_snapshot_round_trip():
    snap = MemorySnapshot(
        version=1,
        source_simulation_id="test-id",
        agents={
            "rex": AgentSnapshot(
                core_memory="I am Rex",
                recall_memories=[{"summary": "test", "importance_score": 0.5}],
            ),
        },
        relationships=[
            {"agent": "rex", "target": "fork", "sentiment": 0.5},
        ],
    )
    data = snap.model_dump()
    restored = MemorySnapshot(**data)
    assert restored.agents["rex"].core_memory == "I am Rex"
    assert len(restored.relationships) == 1


def test_restore_result_defaults():
    result = RestoreResult()
    assert result.agents_restored == []
    assert result.core_memories_restored == 0
    assert result.warnings == []


# ── Pre-built snapshot file tests ──────────────────────────────


SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "snapshots"


@pytest.mark.parametrize("filename", ["day3_normal.json", "conflict.json", "mature.json"])
def test_prebuilt_snapshot_is_valid(filename):
    """Pre-built snapshot files should be valid JSON matching the schema."""
    path = SNAPSHOT_DIR / filename
    assert path.exists(), f"Snapshot {filename} not found"

    data = json.loads(path.read_text())
    snap = MemorySnapshot(**data)
    assert snap.version == SNAPSHOT_VERSION
    assert len(snap.agents) > 0


def test_day3_normal_has_expected_agents():
    data = json.loads((SNAPSHOT_DIR / "day3_normal.json").read_text())
    snap = MemorySnapshot(**data)
    assert "vera" in snap.agents
    assert "rex" in snap.agents
    assert "fork" in snap.agents


def test_conflict_snapshot_has_negative_sentiment():
    data = json.loads((SNAPSHOT_DIR / "conflict.json").read_text())
    snap = MemorySnapshot(**data)
    # At least one relationship should have negative sentiment
    negative = [r for r in snap.relationships if r.get("sentiment", 0) < 0]
    assert len(negative) > 0


def test_mature_snapshot_has_high_trust():
    data = json.loads((SNAPSHOT_DIR / "mature.json").read_text())
    snap = MemorySnapshot(**data)
    # At least one relationship should have high trust
    high_trust = [r for r in snap.relationships if r.get("trust", 0) >= 0.8]
    assert len(high_trust) > 0


# ── Importer tests ─────────────────────────────────────────────


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_memory_repo():
    repo = AsyncMock()
    repo.get_core_memory = AsyncMock(return_value=None)
    repo.upsert_core_memory = AsyncMock(return_value=CoreMemory(
        agent_id="rex",
        content="test",
        token_count=5,
    ))
    repo.add_recall = AsyncMock(return_value=RecallMemory(
        id=1,
        agent_id="rex",
        summary="test",
        embedding=[0.1] * 1536,
    ))
    repo.create_journal_entry = AsyncMock(return_value=JournalEntry(
        id=1,
        agent_id="rex",
        reflection_type="6hour",
        content="test",
        token_count=5,
    ))
    return repo


@pytest.fixture
def mock_core_memory_mgr():
    mgr = AsyncMock()
    mgr.get_core_memory = AsyncMock(return_value=None)
    mgr.initialize_agent_memory = AsyncMock()
    return mgr


@pytest.fixture
def mock_recall_memory_mgr():
    return AsyncMock()


@pytest.fixture
def mock_relationship_repo():
    repo = AsyncMock()
    repo.upsert = AsyncMock()
    return repo


@pytest.fixture
def importer(mock_db, mock_memory_repo, mock_core_memory_mgr, mock_recall_memory_mgr, mock_relationship_repo):
    return MemorySnapshotImporter(
        db=mock_db,
        memory_repo=mock_memory_repo,
        core_memory_mgr=mock_core_memory_mgr,
        recall_memory_mgr=mock_recall_memory_mgr,
        relationship_repo=mock_relationship_repo,
    )


@pytest.mark.asyncio
async def test_restore_core_memory(importer, mock_core_memory_mgr, mock_memory_repo):
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {
                "core_memory": "I am Rex the builder",
                "recall_memories": [],
                "journal_entries": [],
            },
        },
        "relationships": [],
    }
    result = await importer.restore(snapshot)
    assert result.core_memories_restored == 1
    assert "rex" in result.agents_restored
    mock_core_memory_mgr.initialize_agent_memory.assert_not_called()
    mock_memory_repo.upsert_core_memory.assert_called_once()
    call = mock_memory_repo.upsert_core_memory.await_args
    assert call.args[:3] == ("rex", "I am Rex the builder", 6)
    assert call.kwargs["reason"] == "snapshot_restore"


@pytest.mark.asyncio
async def test_restore_upserts_core_memory(importer, mock_memory_repo):
    """Core-memory restore preserves the snapshot text through an upsert."""
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {
                "core_memory": "Updated Rex memory",
                "recall_memories": [],
                "journal_entries": [],
            },
        },
        "relationships": [],
    }
    result = await importer.restore(snapshot)
    assert result.core_memories_restored == 1
    mock_memory_repo.upsert_core_memory.assert_called_once()


@pytest.mark.asyncio
async def test_restore_recall_memories_with_embeddings(importer, mock_memory_repo):
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {
                "core_memory": "",
                "recall_memories": [
                    {
                        "summary": "Built a new feature",
                        "importance_score": 0.7,
                        "event_type": "conversation",
                        "embedding": [0.1] * 1536,
                    },
                ],
                "journal_entries": [],
            },
        },
        "relationships": [],
    }
    result = await importer.restore(snapshot)
    assert result.recall_memories_restored == 1


@pytest.mark.asyncio
async def test_restore_skips_recall_without_embedding(importer):
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {
                "core_memory": "",
                "recall_memories": [
                    {"summary": "No embedding", "importance_score": 0.5},
                ],
                "journal_entries": [],
            },
        },
        "relationships": [],
    }
    result = await importer.restore(snapshot)
    assert result.recall_memories_restored == 0
    assert len(result.warnings) > 0


@pytest.mark.asyncio
async def test_restore_journal_entries(importer, mock_memory_repo):
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {
                "core_memory": "",
                "recall_memories": [],
                "journal_entries": [
                    {"reflection_type": "6hour", "content": "Day 3 journal", "token_count": 10},
                ],
            },
        },
        "relationships": [],
    }
    result = await importer.restore(snapshot)
    assert result.journal_entries_restored == 1


@pytest.mark.asyncio
async def test_restore_relationships(importer, mock_relationship_repo):
    sim_id = str(uuid.uuid4())
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {"core_memory": "", "recall_memories": [], "journal_entries": []},
        },
        "relationships": [
            {"agent": "rex", "target": "fork", "sentiment": 0.5, "trust": 0.7, "interaction_count": 10},
        ],
    }
    result = await importer.restore(snapshot, simulation_id=sim_id)
    assert result.relationships_restored == 1
    mock_relationship_repo.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_restore_filters_agents(importer):
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {"core_memory": "Rex", "recall_memories": [], "journal_entries": []},
            "fork": {"core_memory": "Fork", "recall_memories": [], "journal_entries": []},
            "vera": {"core_memory": "Vera", "recall_memories": [], "journal_entries": []},
        },
        "relationships": [],
    }
    result = await importer.restore(snapshot, agents=["rex", "fork"])
    assert sorted(result.agents_restored) == ["fork", "rex"]
    assert result.core_memories_restored == 2


@pytest.mark.asyncio
async def test_restore_clear_first(importer, mock_db):
    snapshot = {
        "version": 1,
        "agents": {
            "rex": {"core_memory": "Rex", "recall_memories": [], "journal_entries": []},
        },
        "relationships": [],
    }
    await importer.restore(snapshot, clear_first=True)
    # Should have called execute to delete recall and journal entries
    assert mock_db.execute.call_count >= 2


@pytest.mark.asyncio
async def test_restore_warns_on_version_mismatch(importer):
    snapshot = {
        "version": 99,
        "agents": {},
        "relationships": [],
    }
    result = await importer.restore(snapshot)
    assert any("version" in w.lower() for w in result.warnings)
