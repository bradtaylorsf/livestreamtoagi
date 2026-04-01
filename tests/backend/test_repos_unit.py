"""Unit tests for repository classes using a mock Database."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from core.models import (
    AgentCreate,
    ChallengeCreate,
    ConversationBufferCreate,
    ConversationCreate,
    CostEventCreate,
    ExpansionProposalCreate,
    InterruptLogCreate,
    SelectionLogCreate,
    TranscriptCreate,
    WorldChunkCreate,
    WorldEventCreate,
)
from core.repos.agent_repo import AgentRepo
from core.repos.conversation_repo import ConversationRepo
from core.repos.cost_repo import CostRepo
from core.repos.memory_repo import MemoryRepo
from core.repos.transcript_repo import TranscriptRepo
from core.repos.world_repo import WorldRepo


def make_mock_db():
    """Create a mock Database with async convenience methods."""
    db = MagicMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value="INSERT 0 1")
    # For acquire() context manager
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock()

    # transaction() must return a sync object that supports async-with
    class FakeTransaction:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    mock_conn.transaction = MagicMock(return_value=FakeTransaction())

    class AcquireCM:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    db.acquire = MagicMock(return_value=AcquireCM())
    db._mock_conn = mock_conn
    return db


def make_agent_row():
    return {
        "id": "vera",
        "display_name": "Vera",
        "model_conversation": "claude-haiku",
        "model_building": "claude-sonnet",
        "voice_id": "en-GB-SoniaNeural",
        "status": "active",
        "created_at": datetime(2024, 1, 1),
    }


# ── AgentRepo ───────────────────────────────────────────────────


async def test_agent_get_returns_agent():
    db = make_mock_db()
    db.fetchrow.return_value = make_agent_row()
    repo = AgentRepo(db)
    agent = await repo.get("vera")
    assert agent is not None
    assert agent.id == "vera"
    assert agent.display_name == "Vera"
    db.fetchrow.assert_called_once()


async def test_agent_get_returns_none():
    db = make_mock_db()
    db.fetchrow.return_value = None
    repo = AgentRepo(db)
    assert await repo.get("nonexistent") is None


async def test_agent_list_all():
    db = make_mock_db()
    db.fetch.return_value = [make_agent_row()]
    repo = AgentRepo(db)
    agents = await repo.list()
    assert len(agents) == 1
    assert agents[0].id == "vera"


async def test_agent_list_by_status():
    db = make_mock_db()
    db.fetch.return_value = [make_agent_row()]
    repo = AgentRepo(db)
    agents = await repo.list(status="active")
    assert len(agents) == 1
    # Verify the status filter was passed
    call_args = db.fetch.call_args
    assert "active" in call_args[0]


async def test_agent_create():
    db = make_mock_db()
    db.fetchrow.return_value = make_agent_row()
    repo = AgentRepo(db)
    agent = await repo.create(
        AgentCreate(
            id="vera",
            display_name="Vera",
            model_conversation="claude-haiku",
            model_building="claude-sonnet",
        )
    )
    assert agent.id == "vera"


async def test_agent_update_status():
    db = make_mock_db()
    row = make_agent_row()
    row["status"] = "idle"
    db.fetchrow.return_value = row
    repo = AgentRepo(db)
    agent = await repo.update_status("vera", "idle")
    assert agent is not None
    assert agent.status == "idle"


# ── TranscriptRepo ──────────────────────────────────────────────


def make_transcript_row():
    return {
        "id": 1,
        "event_type": "dialogue",
        "participants": ["vera", "rex"],
        "content": "Hello",
        "token_count": 5,
        "created_at": datetime(2024, 1, 1),
    }


async def test_transcript_create():
    db = make_mock_db()
    db.fetchrow.return_value = make_transcript_row()
    repo = TranscriptRepo(db)
    t = await repo.create(
        TranscriptCreate(event_type="dialogue", participants=["vera", "rex"],
                         content="Hello", token_count=5)
    )
    assert t.id == 1
    assert t.participants == ["vera", "rex"]


async def test_transcript_get():
    db = make_mock_db()
    db.fetchrow.return_value = make_transcript_row()
    repo = TranscriptRepo(db)
    t = await repo.get(1)
    assert t is not None
    assert t.content == "Hello"


async def test_transcript_search_by_participant():
    db = make_mock_db()
    db.fetch.return_value = [make_transcript_row()]
    repo = TranscriptRepo(db)
    results = await repo.search_by_participant("vera")
    assert len(results) == 1


async def test_transcript_search_by_event_type():
    db = make_mock_db()
    db.fetch.return_value = [make_transcript_row()]
    repo = TranscriptRepo(db)
    results = await repo.search_by_event_type("dialogue")
    assert len(results) == 1


# ── ConversationRepo ────────────────────────────────────────────


def make_conversation_row():
    return {
        "id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        "started_at": datetime(2024, 1, 1),
        "ended_at": None,
        "trigger_type": "proximity",
        "trigger_details": None,
        "initial_energy": 1.0,
        "final_energy": None,
        "turn_count": 0,
        "participating_agents": ["vera", "rex"],
        "topics_discussed": None,
        "closed_by": None,
        "location": "spawn",
        "audience_events_during": 0,
        "config_hash": None,
    }


async def test_conversation_create_without_id():
    db = make_mock_db()
    db.fetchrow.return_value = make_conversation_row()
    repo = ConversationRepo(db)
    conv = await repo.create(
        ConversationCreate(
            trigger_type="proximity",
            initial_energy=1.0,
            participating_agents=["vera", "rex"],
        )
    )
    assert conv.trigger_type == "proximity"


async def test_conversation_create_with_id():
    db = make_mock_db()
    db.fetchrow.return_value = make_conversation_row()
    repo = ConversationRepo(db)
    conv_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    conv = await repo.create(
        ConversationCreate(
            id=conv_id,
            trigger_type="proximity",
            initial_energy=1.0,
            participating_agents=["vera", "rex"],
        )
    )
    assert conv.id == conv_id


async def test_conversation_close():
    db = make_mock_db()
    row = make_conversation_row()
    row["ended_at"] = datetime(2024, 1, 1)
    row["final_energy"] = 0.2
    row["closed_by"] = "energy_decay"
    db.fetchrow.return_value = row
    repo = ConversationRepo(db)
    conv = await repo.close(row["id"], 0.2, "energy_decay")
    assert conv is not None
    assert conv.final_energy == 0.2


async def test_conversation_log_selection():
    db = make_mock_db()
    repo = ConversationRepo(db)
    await repo.log_selection(
        SelectionLogCreate(
            conversation_id=uuid.uuid4(),
            turn_number=1,
            selected_agent_id="vera",
            agent_scores={"vera": 0.8},
        )
    )
    db.execute.assert_called_once()


async def test_conversation_log_interrupt():
    db = make_mock_db()
    repo = ConversationRepo(db)
    await repo.log_interrupt(
        InterruptLogCreate(
            conversation_id=uuid.uuid4(),
            attempting_agent_id="fork",
            would_have_spoken_id="rex",
            interrupt_score=0.85,
            threshold_at_time=0.7,
            succeeded=True,
        )
    )
    db.execute.assert_called_once()


# ── MemoryRepo ──────────────────────────────────────────────────


async def test_memory_get_core_memory():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "agent_id": "vera",
        "content": "I am organized",
        "token_count": 3,
        "last_updated": datetime(2024, 1, 1),
        "version": 1,
    }
    repo = MemoryRepo(db)
    mem = await repo.get_core_memory("vera")
    assert mem is not None
    assert mem.content == "I am organized"


async def test_memory_upsert_core_memory():
    db = make_mock_db()
    db._mock_conn.fetchrow.return_value = {
        "agent_id": "vera",
        "content": "Updated",
        "token_count": 10,
        "last_updated": datetime(2024, 1, 1),
        "version": 2,
    }
    repo = MemoryRepo(db)
    mem = await repo.upsert_core_memory("vera", "Updated", 10, "test reason")
    assert mem.version == 2
    assert mem.content == "Updated"


async def test_memory_add_buffer_entry():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "agent_id": "rex",
        "role": "agent",
        "speaker": "rex",
        "content": "Hmm.",
        "created_at": datetime(2024, 1, 1),
    }
    repo = MemoryRepo(db)
    entry = await repo.add_buffer_entry(
        ConversationBufferCreate(agent_id="rex", role="agent", speaker="rex", content="Hmm.")
    )
    assert entry.content == "Hmm."


async def test_memory_clear_buffer():
    db = make_mock_db()
    repo = MemoryRepo(db)
    await repo.clear_buffer("rex")
    db.execute.assert_called_once()


# ── CostRepo ────────────────────────────────────────────────────


async def test_cost_add_cost():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "agent_id": "vera",
        "cost_type": "llm_api",
        "amount": Decimal("0.0012"),
        "details": None,
        "created_at": datetime(2024, 1, 1),
    }
    repo = CostRepo(db)
    cost = await repo.add_cost(
        CostEventCreate(agent_id="vera", cost_type="llm_api", amount=Decimal("0.0012"))
    )
    assert cost.amount == Decimal("0.0012")


async def test_cost_get_total_costs():
    db = make_mock_db()
    db.fetchval.return_value = Decimal("10.50")
    repo = CostRepo(db)
    total = await repo.get_total_costs()
    assert total == Decimal("10.50")


async def test_cost_get_total_revenue():
    db = make_mock_db()
    db.fetchval.return_value = Decimal("100.00")
    repo = CostRepo(db)
    total = await repo.get_total_revenue()
    assert total == Decimal("100.00")


async def test_cost_create_challenge():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "description": "Build a bridge",
        "submitted_by": "viewer1",
        "source": "twitch",
        "status": "pending",
        "assigned_agents": None,
        "result": None,
        "cost_estimate": None,
        "actual_cost": None,
        "created_at": datetime(2024, 1, 1),
        "completed_at": None,
    }
    repo = CostRepo(db)
    ch = await repo.create_challenge(
        ChallengeCreate(description="Build a bridge", submitted_by="viewer1", source="twitch")
    )
    assert ch.description == "Build a bridge"


# ── WorldRepo ───────────────────────────────────────────────────


async def test_world_create_chunk():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "name": "spawn",
        "x_offset": 0,
        "y_offset": 0,
        "width": 16,
        "height": 16,
        "tile_data": {"layers": []},
        "objects": [],
        "built_by": ["aurora"],
        "built_date": datetime(2024, 1, 1),
        "description": "Spawn area",
        "proposal_votes": None,
        "tileset_url": None,
    }
    repo = WorldRepo(db)
    chunk = await repo.create_chunk(
        WorldChunkCreate(
            name="spawn", x_offset=0, y_offset=0, width=16, height=16,
            tile_data={"layers": []}, built_by=["aurora"], description="Spawn area",
        )
    )
    assert chunk.name == "spawn"


async def test_world_create_event():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "event_type": "build",
        "description": "New chunk",
        "agents_involved": ["aurora"],
        "audience_participation": False,
        "created_at": datetime(2024, 1, 1),
    }
    repo = WorldRepo(db)
    event = await repo.create_event(
        WorldEventCreate(event_type="build", description="New chunk",
                         agents_involved=["aurora"])
    )
    assert event.event_type == "build"


async def test_world_create_proposal():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "proposed_by": "aurora",
        "title": "Garden",
        "description": "Build a garden",
        "status": "proposed",
        "votes_for": 0,
        "votes_against": 0,
        "created_at": datetime(2024, 1, 1),
    }
    repo = WorldRepo(db)
    proposal = await repo.create_proposal(
        ExpansionProposalCreate(
            proposed_by="aurora", title="Garden", description="Build a garden"
        )
    )
    assert proposal.title == "Garden"


async def test_world_vote_proposal():
    db = make_mock_db()
    db.fetchrow.return_value = {
        "id": 1,
        "proposed_by": "aurora",
        "title": "Garden",
        "description": "Build a garden",
        "status": "proposed",
        "votes_for": 1,
        "votes_against": 0,
        "created_at": datetime(2024, 1, 1),
    }
    repo = WorldRepo(db)
    proposal = await repo.vote_proposal(1, vote_for=True)
    assert proposal is not None
    assert proposal.votes_for == 1
