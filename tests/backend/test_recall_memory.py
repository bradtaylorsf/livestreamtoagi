"""Tests for Tier 2 recall memory system (RecallMemoryManager + embeddings)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from core.memory.embeddings import EMBEDDING_DIMENSION, EMBEDDING_MODEL
from core.memory.recall_memory import (
    CANDIDATE_MULTIPLIER,
    RecallMemoryManager,
    _cosine_similarity,
    _format_memories,
    _score_candidates,
)
from core.models import RecallMemory, RecallMemoryCreate

# ── Helpers ──────────────────────────────────────────────────────


def _make_recall_memory(
    id: int = 1,  # noqa: A002
    agent_id: str = "vera",
    summary: str = "Had a conversation about building plans",
    embedding: list[float] | None = None,
    event_type: str | None = "conversation",
    participants: list[str] | None = None,
    transcript_id: int | None = 42,
    importance_score: float = 0.5,
    timestamp: datetime | None = None,
    recalled_count: int = 0,
) -> RecallMemory:
    if embedding is None:
        embedding = [0.0] * EMBEDDING_DIMENSION
    if timestamp is None:
        timestamp = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    return RecallMemory(
        id=id,
        agent_id=agent_id,
        summary=summary,
        embedding=embedding,
        event_type=event_type,
        participants=participants,
        transcript_id=transcript_id,
        importance_score=importance_score,
        timestamp=timestamp,
        recalled_count=recalled_count,
    )


def _unit_vector(dim: int, total: int = EMBEDDING_DIMENSION) -> list[float]:
    """Create a unit vector with 1.0 at position `dim`, 0.0 elsewhere."""
    v = [0.0] * total
    v[dim] = 1.0
    return v


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.add_recall = AsyncMock()
    repo.search_recall = AsyncMock(return_value=[])
    repo.increment_recalled_count = AsyncMock()
    return repo


@pytest.fixture
def mock_embedding_fn() -> AsyncMock:
    fn = AsyncMock(return_value=[0.0] * EMBEDDING_DIMENSION)
    return fn


@pytest.fixture
def manager(mock_repo: AsyncMock, mock_embedding_fn: AsyncMock) -> RecallMemoryManager:
    return RecallMemoryManager(mock_repo, mock_embedding_fn)


# ── store_recall_memory ──────────────────────────────────────────


class TestStoreRecallMemory:
    async def test_calls_repo_with_correct_model(
        self, manager: RecallMemoryManager, mock_repo: AsyncMock
    ) -> None:
        embedding = _unit_vector(0)
        mock_repo.add_recall.return_value = _make_recall_memory(embedding=embedding)

        await manager.store_recall_memory(
            agent_id="vera",
            summary="Discussed building plans with Rex",
            embedding=embedding,
            transcript_id=42,
            event_type="conversation",
            participants=["vera", "rex"],
            importance_score=0.8,
        )

        mock_repo.add_recall.assert_called_once()
        create_arg: RecallMemoryCreate = mock_repo.add_recall.call_args[0][0]
        assert create_arg.agent_id == "vera"
        assert create_arg.summary == "Discussed building plans with Rex"
        assert create_arg.event_type == "conversation"
        assert create_arg.participants == ["vera", "rex"]
        assert create_arg.transcript_id == 42
        assert create_arg.importance_score == 0.8

    async def test_default_importance_score(
        self, manager: RecallMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.add_recall.return_value = _make_recall_memory()

        await manager.store_recall_memory(
            agent_id="vera",
            summary="A memory",
            embedding=[0.0] * EMBEDDING_DIMENSION,
        )

        create_arg: RecallMemoryCreate = mock_repo.add_recall.call_args[0][0]
        assert create_arg.importance_score == 0.5


# ── retrieve_recall_memories ─────────────────────────────────────


class TestRetrieveRecallMemories:
    async def test_returns_empty_string_when_no_memories(
        self, manager: RecallMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.search_recall.return_value = []

        result = await manager.retrieve_recall_memories("vera", "any query")
        assert result == ""

    async def test_generates_embedding_for_query(
        self,
        manager: RecallMemoryManager,
        mock_embedding_fn: AsyncMock,
        mock_repo: AsyncMock,
    ) -> None:
        mock_repo.search_recall.return_value = []

        await manager.retrieve_recall_memories("vera", "What did we discuss?")

        mock_embedding_fn.assert_called_once_with("What did we discuss?")

    async def test_overfetches_candidates(
        self, manager: RecallMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.search_recall.return_value = []

        await manager.retrieve_recall_memories("vera", "query", limit=3)

        _, kwargs = mock_repo.search_recall.call_args
        assert kwargs.get("limit") == 3 * CANDIDATE_MULTIPLIER or \
            mock_repo.search_recall.call_args[0][2] == 3 * CANDIDATE_MULTIPLIER

    async def test_scoring_formula(
        self,
        manager: RecallMemoryManager,
        mock_repo: AsyncMock,
        mock_embedding_fn: AsyncMock,
    ) -> None:
        """Verify 70% similarity + 30% recency produces correct ranking."""
        query_vec = _unit_vector(0)
        mock_embedding_fn.return_value = query_vec

        # Memory A: high similarity (same direction), old
        # Memory B: low similarity (orthogonal), new
        mem_a = _make_recall_memory(
            id=1,
            summary="Highly relevant but old",
            embedding=_unit_vector(0),  # cosine_sim = 1.0
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),  # oldest
        )
        mem_b = _make_recall_memory(
            id=2,
            summary="Not relevant but recent",
            embedding=_unit_vector(1),  # cosine_sim = 0.0
            timestamp=datetime(2026, 4, 1, tzinfo=UTC),  # newest
        )

        mock_repo.search_recall.return_value = [mem_a, mem_b]

        result = await manager.retrieve_recall_memories("vera", "query", limit=2)

        # Score A: 1.0 * 0.7 + 0.0 * 0.3 = 0.70 (oldest, recency=0)
        # Score B: 0.0 * 0.7 + 1.0 * 0.3 = 0.30 (newest, recency=1)
        # A should rank first
        assert "Highly relevant but old" in result
        lines = result.split("\n")
        # First memory line should be A
        memory_lines = [line for line in lines if line.startswith("- ")]
        assert "Highly relevant but old" in memory_lines[0]
        assert "Not relevant but recent" in memory_lines[1]

    async def test_recalled_count_incremented(
        self,
        manager: RecallMemoryManager,
        mock_repo: AsyncMock,
        mock_embedding_fn: AsyncMock,
    ) -> None:
        mock_embedding_fn.return_value = _unit_vector(0)
        mem1 = _make_recall_memory(id=10, embedding=_unit_vector(0))
        mem2 = _make_recall_memory(id=20, embedding=_unit_vector(0))
        mock_repo.search_recall.return_value = [mem1, mem2]

        await manager.retrieve_recall_memories("vera", "query", limit=2)

        assert mock_repo.increment_recalled_count.call_count == 2
        called_ids = {
            call.args[0] for call in mock_repo.increment_recalled_count.call_args_list
        }
        assert called_ids == {10, 20}

    async def test_respects_limit(
        self,
        manager: RecallMemoryManager,
        mock_repo: AsyncMock,
        mock_embedding_fn: AsyncMock,
    ) -> None:
        mock_embedding_fn.return_value = _unit_vector(0)
        memories = [
            _make_recall_memory(id=i, embedding=_unit_vector(0))
            for i in range(5)
        ]
        mock_repo.search_recall.return_value = memories

        result = await manager.retrieve_recall_memories("vera", "query", limit=2)

        # Should only format 2 memories
        memory_lines = [line for line in result.split("\n") if line.startswith("- ")]
        assert len(memory_lines) == 2
        assert mock_repo.increment_recalled_count.call_count == 2


# ── Output format ────────────────────────────────────────────────


class TestOutputFormat:
    def test_format_matches_spec(self) -> None:
        memories = [
            _make_recall_memory(
                event_type="conversation",
                summary="Discussed budget concerns with Sentinel",
                transcript_id=42,
            ),
            _make_recall_memory(
                event_type="building",
                summary="Built pixel art renderer v2",
                transcript_id=99,
            ),
        ]

        result = _format_memories(memories)

        assert result.startswith("## Relevant memories")
        assert "- [conversation] Discussed budget concerns with Sentinel" in result
        assert "  (Full transcript available: transcript_42)" in result
        assert "- [building] Built pixel art renderer v2" in result
        assert "  (Full transcript available: transcript_99)" in result

    def test_format_without_transcript_id(self) -> None:
        memories = [_make_recall_memory(transcript_id=None)]

        result = _format_memories(memories)

        assert "transcript" not in result.split("\n")[-1]

    def test_format_without_event_type(self) -> None:
        memories = [_make_recall_memory(event_type=None)]

        result = _format_memories(memories)

        assert "[memory]" in result


# ── Scoring helpers ──────────────────────────────────────────────


class TestCosineSimiarity:
    def test_identical_vectors(self) -> None:
        v = _unit_vector(0)
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert _cosine_similarity(_unit_vector(0), _unit_vector(1)) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        v = _unit_vector(0)
        neg_v = [-x for x in v]
        assert _cosine_similarity(v, neg_v) == pytest.approx(-1.0)

    def test_zero_vector(self) -> None:
        zero = [0.0] * EMBEDDING_DIMENSION
        assert _cosine_similarity(zero, _unit_vector(0)) == 0.0


class TestScoreCandidates:
    def test_blended_score_values(self) -> None:
        query = _unit_vector(0)

        oldest = datetime(2026, 1, 1, tzinfo=UTC)
        newest = datetime(2026, 4, 1, tzinfo=UTC)

        candidates = [
            _make_recall_memory(id=1, embedding=_unit_vector(0), timestamp=oldest),
            _make_recall_memory(id=2, embedding=_unit_vector(1), timestamp=newest),
        ]

        scored = _score_candidates(candidates, query)
        scores = {m.id: s for m, s in scored}

        # ID 1: sim=1.0, recency=0.0 → 0.7
        assert scores[1] == pytest.approx(0.7)
        # ID 2: sim=0.0, recency=1.0 → 0.3
        assert scores[2] == pytest.approx(0.3)

    def test_single_candidate_gets_recency_one(self) -> None:
        query = _unit_vector(0)
        candidates = [
            _make_recall_memory(
                id=1,
                embedding=_unit_vector(0),
                timestamp=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        ]

        scored = _score_candidates(candidates, query)
        _, score = scored[0]

        # sim=1.0, recency=1.0 (single item → time_range=0 → recency=1.0)
        assert score == pytest.approx(1.0)


# ── Embeddings module ────────────────────────────────────────────


class TestEmbeddingsConfig:
    def test_dimension_is_1536(self) -> None:
        assert EMBEDDING_DIMENSION == 1536

    def test_model_name(self) -> None:
        assert "embedding" in EMBEDDING_MODEL.lower()


# ── Integration test (requires real database) ────────────────────


@pytest.mark.integration
class TestRecallMemoryIntegration:
    """Full store → retrieve cycle against real pgvector.

    Run with: pytest -m integration (requires Docker services).
    """

    async def test_store_and_retrieve_cycle(self) -> None:
        pytest.skip("Requires running Docker services — run with pytest -m integration")
