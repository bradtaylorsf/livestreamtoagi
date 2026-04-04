"""Tests for the relationship tracker and relationship repo."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import EvolutionEvent, Relationship, RelationshipCreate, RelationshipUpdate
from core.repos.relationship_repo import RelationshipRepo
from core.social.relationship_tracker import (
    RelationshipTracker,
    _estimate_sentiment_from_text,
    _parse_json_response,
)


# ── Model tests ────────────────────────────────────────────────


def test_relationship_model():
    rel = Relationship(
        id=uuid.uuid4(),
        simulation_id=uuid.uuid4(),
        agent_id="rex",
        target_agent_id="fork",
        sentiment_score=Decimal("0.5"),
        trust_score=Decimal("0.7"),
        interaction_count=3,
    )
    assert rel.agent_id == "rex"
    assert rel.target_agent_id == "fork"
    assert rel.sentiment_score == Decimal("0.5")


def test_evolution_event_model():
    event = EvolutionEvent(
        timestamp="2026-01-05T10:00:00+00:00",
        event="conversation_update: trusts rex more",
        sentiment_before=0.3,
        sentiment_after=0.5,
    )
    assert event.event == "conversation_update: trusts rex more"
    assert event.sentiment_after == 0.5


def test_relationship_create_model():
    sim_id = uuid.uuid4()
    create = RelationshipCreate(
        simulation_id=sim_id,
        agent_id="vera",
        target_agent_id="rex",
        sentiment_score=Decimal("0.2"),
    )
    assert create.agent_id == "vera"
    assert create.sentiment_score == Decimal("0.2")


def test_relationship_update_model():
    update = RelationshipUpdate(sentiment_score=Decimal("0.8"), trust_score=Decimal("0.9"))
    assert update.sentiment_score == Decimal("0.8")
    assert update.interaction_count is None


# ── Sentiment estimation tests ─────────────────────────────────


def test_estimate_sentiment_positive():
    score = _estimate_sentiment_from_text("Trusted partner and close ally")
    assert score > 0


def test_estimate_sentiment_negative():
    score = _estimate_sentiment_from_text("Constant conflict and disagreement")
    assert score < 0


def test_estimate_sentiment_neutral():
    score = _estimate_sentiment_from_text("Not yet established")
    assert score == 0.0


def test_estimate_sentiment_mixed():
    score = _estimate_sentiment_from_text("Respected but sometimes frustrating")
    # Has both positive and negative, result depends on counts
    assert isinstance(score, float)


# ── JSON parsing tests ─────────────────────────────────────────


def test_parse_json_response_clean():
    result = _parse_json_response('{"relationships": []}')
    assert result == {"relationships": []}


def test_parse_json_response_with_fences():
    result = _parse_json_response('```json\n{"relationships": []}\n```')
    assert result == {"relationships": []}


def test_parse_json_response_invalid():
    result = _parse_json_response("not json at all")
    assert result == {}


# ── RelationshipTracker tests ──────────────────────────────────


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock()
    return llm


@pytest.fixture
def mock_repo():
    repo = AsyncMock(spec=RelationshipRepo)
    repo.increment_interaction = AsyncMock(return_value=Relationship(
        id=uuid.uuid4(),
        simulation_id=uuid.uuid4(),
        agent_id="rex",
        target_agent_id="fork",
        interaction_count=1,
    ))
    repo.get = AsyncMock(return_value=None)
    repo.upsert = AsyncMock(return_value=Relationship(
        id=uuid.uuid4(),
        simulation_id=uuid.uuid4(),
        agent_id="rex",
        target_agent_id="fork",
    ))
    repo.append_evolution_event = AsyncMock()
    return repo


@pytest.fixture
def mock_clock():
    clock = MagicMock()
    clock.now.return_value = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
    return clock


@pytest.fixture
def tracker(mock_llm, mock_repo, mock_clock):
    sim_id = uuid.uuid4()
    return RelationshipTracker(
        llm_client=mock_llm,
        relationship_repo=mock_repo,
        simulation_id=sim_id,
        clock=mock_clock,
    )


@pytest.mark.asyncio
async def test_update_after_conversation_increments_interactions(tracker, mock_repo, mock_llm):
    """Interaction counts should be incremented for all participant pairs."""
    mock_llm.complete.return_value = MagicMock(
        content='{"relationships": []}',
    )

    history = [
        {"speaker": "rex", "content": "Let's build something."},
        {"speaker": "fork", "content": "I disagree with that approach."},
    ]
    await tracker.update_after_conversation(history, ["rex", "fork"])

    # 2 agents = 2 increment calls (rex->fork and fork->rex)
    assert mock_repo.increment_interaction.call_count == 2


@pytest.mark.asyncio
async def test_update_after_conversation_skips_single_participant(tracker, mock_repo):
    """Single-participant conversations should be skipped."""
    await tracker.update_after_conversation([], ["rex"])
    mock_repo.increment_interaction.assert_not_called()


@pytest.mark.asyncio
async def test_update_after_conversation_extracts_sentiment(tracker, mock_repo, mock_llm):
    """LLM should be called to extract sentiment from conversation."""
    mock_llm.complete.return_value = MagicMock(
        content='{"relationships": [{"from": "rex", "to": "fork", "sentiment": 0.5, "trust": 0.7, "summary": "respects fork"}]}',
    )
    mock_repo.get.return_value = None

    history = [
        {"speaker": "rex", "content": "Good point, Fork."},
        {"speaker": "fork", "content": "Thanks, Rex."},
    ]
    await tracker.update_after_conversation(history, ["rex", "fork"])

    # LLM should be called for sentiment extraction
    mock_llm.complete.assert_called_once()
    # Upsert should be called with extracted sentiment
    mock_repo.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_update_after_conversation_handles_llm_failure(tracker, mock_repo, mock_llm):
    """LLM failure should not prevent interaction count updates."""
    mock_llm.complete.side_effect = Exception("LLM timeout")

    history = [
        {"speaker": "rex", "content": "Hello"},
        {"speaker": "fork", "content": "Hi"},
    ]
    # Should not raise
    await tracker.update_after_conversation(history, ["rex", "fork"])

    # Interaction counts should still be updated
    assert mock_repo.increment_interaction.call_count == 2


@pytest.mark.asyncio
async def test_update_from_reflection_parses_relationships(tracker, mock_repo):
    """Reflection updates should parse relationship section from core memory."""
    mock_repo.get.return_value = Relationship(
        id=uuid.uuid4(),
        simulation_id=tracker._simulation_id,
        agent_id="rex",
        target_agent_id="fork",
        sentiment_score=Decimal("0.2"),
        interaction_count=5,
    )

    core_memory = """## My Core Memory
### Who I am
I am Rex, the engineer.
### My relationships
- Fork: Trusted code review partner and close ally
- Vera: Respected project manager
### My goals
- Build great things
"""
    await tracker.update_from_reflection("rex", None, core_memory)

    # Should have updated fork and vera relationships
    assert mock_repo.upsert.call_count >= 1


@pytest.mark.asyncio
async def test_update_from_reflection_skips_without_core_memory(tracker, mock_repo):
    """No-op if core memory text is empty."""
    await tracker.update_from_reflection("rex", None, None)
    mock_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_get_relationship(tracker, mock_repo):
    expected = Relationship(
        id=uuid.uuid4(),
        simulation_id=tracker._simulation_id,
        agent_id="rex",
        target_agent_id="fork",
    )
    mock_repo.get.return_value = expected

    result = await tracker.get_relationship("rex", "fork")
    assert result == expected


@pytest.mark.asyncio
async def test_get_social_graph(tracker, mock_repo):
    mock_repo.get_social_graph.return_value = []
    result = await tracker.get_social_graph()
    assert result == []


@pytest.mark.asyncio
async def test_get_evolution(tracker, mock_repo):
    mock_repo.get_evolution.return_value = [
        {"timestamp": "2026-01-05T10:00:00", "event": "test"}
    ]
    result = await tracker.get_evolution("rex", "fork")
    assert len(result) == 1


@pytest.mark.asyncio
async def test_three_participant_conversation(tracker, mock_repo, mock_llm):
    """Three participants should produce 6 interaction increments (3 pairs, bidirectional)."""
    mock_llm.complete.return_value = MagicMock(content='{"relationships": []}')

    history = [
        {"speaker": "rex", "content": "Hi all"},
        {"speaker": "fork", "content": "Hello"},
        {"speaker": "vera", "content": "Good morning"},
    ]
    await tracker.update_after_conversation(history, ["rex", "fork", "vera"])

    # 3 agents = 3 pairs * 2 directions = 6 increment calls
    assert mock_repo.increment_interaction.call_count == 6
