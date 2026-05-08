"""Tests for agent_energy_log persistence and the /energy-timeline endpoint."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.conversation.selection_logger import SelectionLogger
from core.models import AgentEnergyLogCreate, LoggingConfig
from core.repos.conversation_repo import ConversationRepo

# ── Models ─────────────────────────────────────────────────────


def test_agent_energy_log_create_model():
    sim_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    entry = AgentEnergyLogCreate(
        simulation_id=sim_id,
        agent_id="vera",
        conversation_id=conv_id,
        turn_number=3,
        energy=42.0,
    )
    assert entry.simulation_id == sim_id
    assert entry.agent_id == "vera"
    assert entry.energy == 42.0


# ── ConversationRepo.log_agent_energy_bulk ─────────────────────


@pytest.mark.asyncio
async def test_log_agent_energy_bulk_executes_with_records():
    mock_conn = AsyncMock()
    mock_db = MagicMock()

    class _CtxMgr:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    mock_db.acquire = MagicMock(return_value=_CtxMgr())
    repo = ConversationRepo(mock_db)

    sim_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    entries = [
        AgentEnergyLogCreate(
            simulation_id=sim_id,
            agent_id=aid,
            conversation_id=conv_id,
            turn_number=1,
            energy=50.0,
        )
        for aid in ("vera", "rex", "fork")
    ]
    written = await repo.log_agent_energy_bulk(entries)
    assert written == 3
    assert mock_conn.executemany.await_count == 1
    sql, records = mock_conn.executemany.await_args.args
    assert "INSERT INTO agent_energy_log" in sql
    assert "ON CONFLICT" in sql
    assert len(records) == 3


@pytest.mark.asyncio
async def test_log_agent_energy_bulk_empty_is_noop():
    mock_db = MagicMock()
    repo = ConversationRepo(mock_db)
    written = await repo.log_agent_energy_bulk([])
    assert written == 0
    mock_db.acquire.assert_not_called()


# ── ConversationRepo.get_energy_timeline ───────────────────────


@pytest.mark.asyncio
async def test_get_energy_timeline_groups_by_agent():
    sim_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    ts1 = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    ts2 = datetime(2026, 5, 1, 10, 0, 5, tzinfo=UTC)

    async def fetch(query, *args):
        return [
            {
                "agent_id": "vera",
                "conversation_id": conv_id,
                "turn_number": 0,
                "energy": 50.0,
                "timestamp": ts1,
            },
            {
                "agent_id": "vera",
                "conversation_id": conv_id,
                "turn_number": 1,
                "energy": 48.0,
                "timestamp": ts2,
            },
            {
                "agent_id": "rex",
                "conversation_id": conv_id,
                "turn_number": 0,
                "energy": 50.0,
                "timestamp": ts1,
            },
        ]

    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(side_effect=fetch)
    repo = ConversationRepo(mock_db)

    timeline = await repo.get_energy_timeline(sim_id)
    assert set(timeline.keys()) == {"vera", "rex"}
    vera_points = timeline["vera"]
    assert len(vera_points) == 2
    assert vera_points[0]["t"] == ts1.isoformat()
    assert vera_points[0]["energy"] == 50.0
    assert vera_points[0]["turn"] == 0
    assert vera_points[0]["conversation_id"] == str(conv_id)
    assert vera_points[1]["energy"] == 48.0


@pytest.mark.asyncio
async def test_get_energy_timeline_filters_by_agent_id():
    sim_id = uuid.uuid4()
    seen_args: dict = {}

    async def fetch(query, *args):
        seen_args["query"] = query
        seen_args["args"] = args
        return []

    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(side_effect=fetch)
    repo = ConversationRepo(mock_db)

    await repo.get_energy_timeline(sim_id, agent_id="vera")
    assert "AND agent_id = $2" in seen_args["query"]
    assert seen_args["args"] == (sim_id, "vera")


# ── SelectionLogger.log_agent_energy ───────────────────────────


@pytest.mark.asyncio
async def test_log_agent_energy_writes_one_row_per_agent():
    repo = AsyncMock(spec=ConversationRepo)
    cfg = LoggingConfig(
        log_every_selection=True,
        log_energy_changes=True,
        retention_days=14,
    )
    logger = SelectionLogger(repo, cfg, simulation_id=uuid.uuid4())

    sim_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    await logger.log_agent_energy(
        conversation_id=conv_id,
        turn_number=3,
        simulation_id=sim_id,
        agent_energies={"vera": 60.0, "rex": 60.0, "fork": 60.0},
    )
    repo.log_agent_energy_bulk.assert_awaited_once()
    entries = repo.log_agent_energy_bulk.await_args.args[0]
    assert len(entries) == 3
    assert {e.agent_id for e in entries} == {"vera", "rex", "fork"}
    assert all(e.simulation_id == sim_id for e in entries)
    assert all(e.conversation_id == conv_id for e in entries)
    assert all(e.turn_number == 3 for e in entries)
    assert all(e.energy == 60.0 for e in entries)


@pytest.mark.asyncio
async def test_log_agent_energy_empty_is_noop():
    repo = AsyncMock(spec=ConversationRepo)
    cfg = LoggingConfig(
        log_every_selection=True,
        log_energy_changes=True,
        retention_days=14,
    )
    logger = SelectionLogger(repo, cfg, simulation_id=uuid.uuid4())
    await logger.log_agent_energy(
        conversation_id=uuid.uuid4(),
        turn_number=0,
        simulation_id=uuid.uuid4(),
        agent_energies={},
    )
    repo.log_agent_energy_bulk.assert_not_called()


# ── Performance smoke: timeline grouping over many points ──────


@pytest.mark.asyncio
async def test_get_energy_timeline_groups_1000_rows_quickly():
    """A 7-day sim with 1000 turns spread across agents should be cheap to
    transform into the response dict — the test isolates the Python work
    (DB time is held at zero by mocking)."""
    sim_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    ts = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(1000):
        rows.append(
            {
                "agent_id": ("vera", "rex", "fork", "aurora", "pixel")[i % 5],
                "conversation_id": conv_id,
                "turn_number": i,
                "energy": 50.0 + (i % 20),
                "timestamp": ts,
            }
        )

    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(return_value=rows)
    repo = ConversationRepo(mock_db)

    start = time.perf_counter()
    timeline = await repo.get_energy_timeline(sim_id)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 500.0, f"timeline grouping took {elapsed_ms:.1f}ms"
    assert sum(len(v) for v in timeline.values()) == 1000
