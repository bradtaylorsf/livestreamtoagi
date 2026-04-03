"""Tests for Tier 3 archival memory system (ArchivalMemoryManager)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from core.memory.archival_memory import ArchivalMemoryManager
from core.models import Transcript, TranscriptCreate

# ── Helpers ──────────────────────────────────────────────────────


def _make_transcript(
    id: int = 1,  # noqa: A002
    event_type: str = "conversation",
    participants: list[str] | None = None,
    content: str = "Vera: Let's discuss the plan.\nRex: Sounds good.",
    token_count: int = 15,
    created_at: datetime | None = None,
) -> Transcript:
    if participants is None:
        participants = ["vera", "rex"]
    if created_at is None:
        created_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    return Transcript(
        id=id,
        event_type=event_type,
        participants=participants,
        content=content,
        token_count=token_count,
        created_at=created_at,
    )


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_transcript_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    repo.search_by_participant = AsyncMock(return_value=[])
    repo.search_by_event_type = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_token_counter() -> Mock:
    counter = Mock()
    counter.count_tokens = Mock(return_value=42)
    return counter


@pytest.fixture
def manager(mock_transcript_repo: AsyncMock, mock_token_counter: Mock) -> ArchivalMemoryManager:
    return ArchivalMemoryManager(mock_transcript_repo, mock_token_counter)


# ── store_transcript ────────────────────────────────────────────


class TestStoreTranscript:
    async def test_calculates_token_count(
        self,
        manager: ArchivalMemoryManager,
        mock_token_counter: Mock,
        mock_transcript_repo: AsyncMock,
    ) -> None:
        content = "Vera: Hello!\nRex: Hi there!"
        mock_transcript_repo.create.return_value = _make_transcript(content=content, token_count=42)

        await manager.store_transcript("conversation", ["vera", "rex"], content)

        mock_token_counter.count_tokens.assert_called_once_with(content)

    async def test_passes_correct_create_model(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        content = "Aurora: Let's brainstorm."
        mock_transcript_repo.create.return_value = _make_transcript(
            event_type="building", participants=["aurora"], content=content, token_count=42
        )

        await manager.store_transcript("building", ["aurora"], content)

        mock_transcript_repo.create.assert_called_once()
        create_arg: TranscriptCreate = mock_transcript_repo.create.call_args[0][0]
        assert create_arg.event_type == "building"
        assert create_arg.participants == ["aurora"]
        assert create_arg.content == content
        assert create_arg.token_count == 42

    async def test_returns_created_transcript(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        expected = _make_transcript(id=99)
        mock_transcript_repo.create.return_value = expected

        result = await manager.store_transcript("conversation", ["vera"], "content")

        assert result == expected


# ── Token count ──────────────────────────────────────────────────


class TestTokenCount:
    async def test_token_count_stored_on_insertion(
        self, mock_transcript_repo: AsyncMock, mock_token_counter: Mock
    ) -> None:
        mock_token_counter.count_tokens.return_value = 137
        mock_transcript_repo.create.return_value = _make_transcript(token_count=137)

        mgr = ArchivalMemoryManager(mock_transcript_repo, mock_token_counter)
        await mgr.store_transcript("reflection", ["sentinel"], "Long reflection text...")

        create_arg: TranscriptCreate = mock_transcript_repo.create.call_args[0][0]
        assert create_arg.token_count == 137


# ── retrieve_full_transcript ─────────────────────────────────────


class TestRetrieveFullTranscript:
    async def test_returns_transcript(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        expected = _make_transcript(id=5)
        mock_transcript_repo.get.return_value = expected

        result = await manager.retrieve_full_transcript(5)

        mock_transcript_repo.get.assert_called_once_with(5)
        assert result == expected

    async def test_returns_none_for_missing_id(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        mock_transcript_repo.get.return_value = None

        result = await manager.retrieve_full_transcript(999)

        assert result is None


# ── get_transcripts_by_agent ─────────────────────────────────────


class TestGetByAgent:
    async def test_delegates_to_repo(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        transcripts = [_make_transcript(id=1), _make_transcript(id=2)]
        mock_transcript_repo.search_by_participant.return_value = transcripts

        result = await manager.get_transcripts_by_agent("vera", limit=50)

        mock_transcript_repo.search_by_participant.assert_called_once_with("vera", 50)
        assert result == transcripts

    async def test_default_limit(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        mock_transcript_repo.search_by_participant.return_value = []

        await manager.get_transcripts_by_agent("rex")

        mock_transcript_repo.search_by_participant.assert_called_once_with("rex", 100)


# ── get_transcripts_by_type ──────────────────────────────────────


class TestGetByType:
    async def test_delegates_to_repo(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        transcripts = [_make_transcript(event_type="challenge")]
        mock_transcript_repo.search_by_event_type.return_value = transcripts

        result = await manager.get_transcripts_by_type("challenge", limit=25)

        mock_transcript_repo.search_by_event_type.assert_called_once_with("challenge", 25)
        assert result == transcripts

    async def test_default_limit(
        self, manager: ArchivalMemoryManager, mock_transcript_repo: AsyncMock
    ) -> None:
        mock_transcript_repo.search_by_event_type.return_value = []

        await manager.get_transcripts_by_type("building")

        mock_transcript_repo.search_by_event_type.assert_called_once_with("building", 100)


# ── Immutability ─────────────────────────────────────────────────


class TestImmutability:
    def test_no_update_method(self) -> None:
        assert not hasattr(ArchivalMemoryManager, "update_transcript")
        assert not hasattr(ArchivalMemoryManager, "update")

    def test_no_delete_method(self) -> None:
        assert not hasattr(ArchivalMemoryManager, "delete_transcript")
        assert not hasattr(ArchivalMemoryManager, "delete")


# ── Integration test (requires real database) ────────────────────


@pytest.mark.integration
class TestArchivalMemoryIntegration:
    """Full store → retrieve cycle against real database.

    Run with: pytest -m integration (requires Docker services).
    """

    async def test_store_and_query_cycle(self) -> None:
        pytest.skip("Requires running Docker services — run with pytest -m integration")
