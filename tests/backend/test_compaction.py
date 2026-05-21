"""Tests for memory compaction cycle (MemoryCompactor)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from core.memory.compaction import (
    BUFFER_COMPACT_COUNT,
    BUFFER_MAX_SIZE,
    SUMMARY_MAX_TOKENS,
    SUMMARY_MODEL,
    MemoryCompactor,
)
from core.memory.embeddings import EMBEDDING_DIMENSION
from core.models import LLMResponse, RecallMemory, Transcript

# ── Helpers ──────────────────────────────────────────────────────


def _make_transcript(
    id: int = 1,  # noqa: A002
    event_type: str = "conversation",
    participants: list[str] | None = None,
    content: str = "Full conversation transcript here",
    token_count: int = 50,
) -> Transcript:
    return Transcript(
        id=id,
        event_type=event_type,
        participants=participants or ["vera"],
        content=content,
        token_count=token_count,
        created_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
    )


def _make_recall_memory(
    id: int = 1,  # noqa: A002
    agent_id: str = "vera",
    summary: str = "I discussed building plans with Rex.",
    transcript_id: int = 1,
    event_type: str = "conversation",
) -> RecallMemory:
    return RecallMemory(
        id=id,
        agent_id=agent_id,
        summary=summary,
        embedding=[0.1] * EMBEDDING_DIMENSION,
        event_type=event_type,
        participants=["vera", "rex"],
        transcript_id=transcript_id,
        importance_score=0.5,
        timestamp=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        recalled_count=0,
    )


def _make_llm_response(content: str = "I discussed building plans with Rex.") -> LLMResponse:
    return LLMResponse(
        content=content,
        model=SUMMARY_MODEL,
        input_tokens=200,
        output_tokens=80,
        estimated_cost=Decimal("0.001"),
        latency_ms=500,
        openrouter_id="test-123",
    )


def _fake_embedding() -> list[float]:
    return [0.1] * EMBEDDING_DIMENSION


def _make_buffer(count: int) -> list[dict[str, str]]:
    """Create a mock conversation buffer with `count` messages."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
        for i in range(count)
    ]


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def archival_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.store_transcript.return_value = _make_transcript()
    return mock


@pytest.fixture
def recall_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.store_recall_memory.return_value = _make_recall_memory()
    return mock


@pytest.fixture
def llm_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.complete.return_value = _make_llm_response()
    return mock


@pytest.fixture
def http_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def compactor(
    archival_mock: AsyncMock,
    recall_mock: AsyncMock,
    llm_mock: AsyncMock,
    http_mock: AsyncMock,
) -> MemoryCompactor:
    return MemoryCompactor(
        archival=archival_mock,
        recall=recall_mock,
        llm_client=llm_mock,
        http_client=http_mock,
        openrouter_api_key="test-key",
    )


# ── compact_interaction tests ────────────────────────────────────


class TestCompactInteraction:
    """Tests for compact_interaction method."""

    @pytest.mark.asyncio
    async def test_creates_tier3_and_tier2_entries(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
        recall_mock: AsyncMock,
    ) -> None:
        """compact_interaction stores transcript in Tier 3 and summary in Tier 2."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            result = await compactor.compact_interaction(
                agent_id="vera",
                interaction="Vera: Let's build a dashboard.\nRex: Sounds good.",
                event_type="conversation",
                participants=["vera", "rex"],
            )

        assert result is not None
        assert result.transcript.id == 1
        assert result.recall_memory.id == 1

        # Tier 3 was called
        archival_mock.store_transcript.assert_awaited_once_with(
            event_type="conversation",
            participants=["vera", "rex"],
            content="Vera: Let's build a dashboard.\nRex: Sounds good.",
            conversation_id=None,
        )

        # Tier 2 was called
        recall_mock.store_recall_memory.assert_awaited_once()
        call_kwargs = recall_mock.store_recall_memory.call_args.kwargs
        assert call_kwargs["agent_id"] == "vera"
        assert call_kwargs["transcript_id"] == 1
        assert call_kwargs["event_type"] == "conversation"
        assert call_kwargs["participants"] == ["vera", "rex"]

    @pytest.mark.asyncio
    async def test_generates_summary_from_agent_perspective(
        self,
        compactor: MemoryCompactor,
        llm_mock: AsyncMock,
    ) -> None:
        """Summary prompt includes agent_id and instructs from-perspective writing."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.compact_interaction(
                agent_id="rex",
                interaction="Some conversation text.",
                event_type="building_session",
            )

        llm_mock.complete.assert_awaited_once()
        call_kwargs = llm_mock.complete.call_args.kwargs
        messages = call_kwargs["messages"]

        # System message references the agent
        assert "rex" in messages[0]["content"].lower()
        assert "perspective" in messages[0]["content"].lower()

        # Uses cheap model
        assert call_kwargs["model"] == SUMMARY_MODEL
        assert call_kwargs["max_tokens"] == SUMMARY_MAX_TOKENS

    @pytest.mark.asyncio
    async def test_generates_embedding_from_summary(
        self,
        compactor: MemoryCompactor,
        llm_mock: AsyncMock,
        recall_mock: AsyncMock,
    ) -> None:
        """Embedding is generated from the LLM summary, not the raw transcript."""
        summary_text = "I discussed plans with Rex and we decided to build a dashboard."
        llm_mock.complete.return_value = _make_llm_response(content=summary_text)
        fake_emb = _fake_embedding()

        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=fake_emb,
        ) as emb_mock:
            await compactor.compact_interaction(
                agent_id="vera",
                interaction="Long transcript here...",
                event_type="conversation",
            )

        # Embedding was generated from the summary, not transcript
        emb_mock.assert_awaited_once_with(summary_text, compactor._http, "test-key")

        # The embedding was passed to recall
        call_kwargs = recall_mock.store_recall_memory.call_args.kwargs
        assert call_kwargs["embedding"] == fake_emb

    @pytest.mark.asyncio
    async def test_empty_interaction_returns_none(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
    ) -> None:
        """Empty or whitespace-only interactions are skipped."""
        assert await compactor.compact_interaction("vera", "", "conversation") is None
        assert await compactor.compact_interaction("vera", "   ", "conversation") is None
        assert await compactor.compact_interaction("vera", "\n\t", "conversation") is None

        archival_mock.store_transcript.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_defaults_participants_to_agent(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
    ) -> None:
        """When participants is None, defaults to [agent_id]."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.compact_interaction(
                agent_id="fork",
                interaction="Solo reflection time.",
                event_type="reflection",
            )

        archival_mock.store_transcript.assert_awaited_once_with(
            event_type="reflection",
            participants=["fork"],
            content="Solo reflection time.",
            conversation_id=None,
        )


# ── manage_conversation_buffer tests ─────────────────────────────


class TestManageConversationBuffer:
    """Tests for manage_conversation_buffer method."""

    @pytest.mark.asyncio
    async def test_buffer_under_threshold_unchanged(
        self,
        compactor: MemoryCompactor,
    ) -> None:
        """Buffer with <= 20 messages is returned unchanged."""
        buffer = _make_buffer(15)
        result = await compactor.manage_conversation_buffer("vera", buffer)
        assert result == buffer
        assert len(result) == 15

    @pytest.mark.asyncio
    async def test_buffer_at_threshold_unchanged(
        self,
        compactor: MemoryCompactor,
    ) -> None:
        """Buffer with exactly 20 messages is returned unchanged."""
        buffer = _make_buffer(BUFFER_MAX_SIZE)
        result = await compactor.manage_conversation_buffer("vera", buffer)
        assert result == buffer
        assert len(result) == BUFFER_MAX_SIZE

    @pytest.mark.asyncio
    async def test_buffer_over_threshold_compacts_oldest(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
    ) -> None:
        """Buffer with > 20 messages compacts oldest 10 and returns remaining."""
        buffer = _make_buffer(25)

        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            result = await compactor.manage_conversation_buffer("vera", buffer)

        # Returns 15 remaining messages (25 - 10)
        assert len(result) == 25 - BUFFER_COMPACT_COUNT
        # The remaining messages are the newest ones
        assert result[0]["content"] == "Message 10"
        assert result[-1]["content"] == "Message 24"

        # Compaction was triggered
        archival_mock.store_transcript.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_buffer_compaction_uses_conversation_segment_type(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
    ) -> None:
        """Compacted buffer segments use 'conversation_segment' event type."""
        buffer = _make_buffer(21)

        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.manage_conversation_buffer("vera", buffer)

        call_kwargs = archival_mock.store_transcript.call_args.kwargs
        assert call_kwargs["event_type"] == "conversation_segment"

    @pytest.mark.asyncio
    async def test_buffer_compaction_formats_messages(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
    ) -> None:
        """Compacted messages are formatted as '[role] content' lines."""
        buffer = _make_buffer(21)

        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.manage_conversation_buffer("vera", buffer)

        call_kwargs = archival_mock.store_transcript.call_args.kwargs
        content = call_kwargs["content"]
        assert "[user] Message 0" in content
        assert "[assistant] Message 1" in content


# ── Summary format tests ─────────────────────────────────────────


class TestSummaryFormat:
    """Tests for summary prompt structure."""

    @pytest.mark.asyncio
    async def test_summary_prompt_includes_required_fields(
        self,
        compactor: MemoryCompactor,
        llm_mock: AsyncMock,
    ) -> None:
        """Summary prompt asks for: what happened, key decisions, emotional tone, surprises."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.compact_interaction(
                agent_id="vera",
                interaction="Test transcript",
                event_type="conversation",
            )

        messages = llm_mock.complete.call_args.kwargs["messages"]
        system = messages[0]["content"]
        assert "what happened" in system.lower()
        assert "key decisions" in system.lower()
        assert "emotional tone" in system.lower()
        assert "surprising" in system.lower()

    @pytest.mark.asyncio
    async def test_summary_user_message_includes_context(
        self,
        compactor: MemoryCompactor,
        llm_mock: AsyncMock,
    ) -> None:
        """User message includes agent_id, event_type, and full transcript."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.compact_interaction(
                agent_id="aurora",
                interaction="Aurora designed a new logo.",
                event_type="building_session",
            )

        messages = llm_mock.complete.call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "aurora" in user_msg.lower()
        assert "building_session" in user_msg
        assert "Aurora designed a new logo." in user_msg

    @pytest.mark.asyncio
    async def test_scene_summary_prompt_preserves_continuity_fields(
        self,
        compactor: MemoryCompactor,
        llm_mock: AsyncMock,
    ) -> None:
        """Scene summaries ask for commitments, failures, tool outcomes, and next steps."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            await compactor.compact_interaction(
                agent_id="rex",
                interaction="Vera: I'll build the bridge.\nTool: inspect succeeded.",
                event_type="minecraft_scene",
                summary_style="scene",
            )

        messages = llm_mock.complete.call_args.kwargs["messages"]
        system = messages[0]["content"].lower()
        assert "commitments" in system
        assert "discovered constraints" in system
        assert "repeated failures" in system
        assert "help requests" in system
        assert "build progress" in system
        assert "tool outcomes" in system
        assert "next practical thing" in system


# ── compact_recall_only tests ──────────────────────────────────


class TestCompactRecallOnly:
    """Tests for compact_recall_only — per-agent recall without duplicate transcript."""

    @pytest.mark.asyncio
    async def test_creates_recall_without_transcript(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
        recall_mock: AsyncMock,
    ) -> None:
        """compact_recall_only creates recall memory but does NOT store transcript."""
        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=_fake_embedding(),
        ):
            result = await compactor.compact_recall_only(
                agent_id="rex",
                interaction="Vera: Let's build a dashboard.\nRex: Sounds good.",
                event_type="conversation",
                transcript_id=42,
                participants=["vera", "rex"],
            )

        assert result is not None
        # Transcript must NOT be stored again
        archival_mock.store_transcript.assert_not_awaited()
        # Recall memory was created with the existing transcript_id
        recall_mock.store_recall_memory.assert_awaited_once()
        call_kwargs = recall_mock.store_recall_memory.call_args.kwargs
        assert call_kwargs["agent_id"] == "rex"
        assert call_kwargs["transcript_id"] == 42

    @pytest.mark.asyncio
    async def test_empty_interaction_returns_none(
        self,
        compactor: MemoryCompactor,
        archival_mock: AsyncMock,
    ) -> None:
        """Empty interaction returns None without any DB calls."""
        result = await compactor.compact_recall_only(
            agent_id="vera",
            interaction="",
            event_type="conversation",
            transcript_id=1,
        )
        assert result is None
        archival_mock.store_transcript.assert_not_awaited()


# ── Integration test (marked for CI with real services) ──────────


@pytest.mark.integration
class TestCompactionIntegration:
    """Integration tests requiring real LLM/embedding calls.

    Run with: pytest -m integration
    """

    @pytest.mark.asyncio
    async def test_full_compaction_cycle(self) -> None:
        """Full compaction cycle with real LLM call.

        Requires OPENROUTER_API_KEY environment variable and Docker services.
        """
        pytest.skip("Requires OPENROUTER_API_KEY and running services")
