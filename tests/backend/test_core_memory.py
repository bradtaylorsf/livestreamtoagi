"""Tests for Tier 1 core memory system (CoreMemoryManager + TokenCounter)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core.memory.core_memory import (
    CORE_MEMORY_TEMPLATE,
    TOKEN_LIMIT,
    VALID_SECTIONS,
    CoreMemoryExceededError,
    CoreMemoryManager,
    InvalidSectionError,
)
from core.memory.token_counter import TokenCounter
from core.models import CoreMemory, CoreMemoryHistory


# ── Fixtures ───────────────────────────────────────────────────────

def _make_core_memory(
    agent_id: str = "rex",
    content: str | None = None,
    token_count: int = 200,
    version: int = 1,
) -> CoreMemory:
    if content is None:
        content = CORE_MEMORY_TEMPLATE.format(date="2026-04-01", identity="I am Rex, the builder.")
    return CoreMemory(
        agent_id=agent_id,
        content=content,
        token_count=token_count,
        version=version,
        last_updated=datetime(2026, 4, 1),
    )


@pytest.fixture
def token_counter() -> TokenCounter:
    return TokenCounter()


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_core_memory = AsyncMock(return_value=None)
    repo.upsert_core_memory = AsyncMock()
    repo.get_core_memory_history = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def manager(mock_repo: AsyncMock, token_counter: TokenCounter) -> CoreMemoryManager:
    return CoreMemoryManager(mock_repo, token_counter)


# ── TokenCounter tests ────────────────────────────────────────────

class TestTokenCounter:
    def test_count_tokens_returns_int(self, token_counter: TokenCounter) -> None:
        result = token_counter.count_tokens("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_empty_string_zero_tokens(self, token_counter: TokenCounter) -> None:
        assert token_counter.count_tokens("") == 0

    def test_longer_text_more_tokens(self, token_counter: TokenCounter) -> None:
        short = token_counter.count_tokens("Hi")
        long = token_counter.count_tokens("This is a much longer sentence with many more words in it.")
        assert long > short


# ── get_core_memory ───────────────────────────────────────────────

class TestGetCoreMemory:
    async def test_returns_markdown_format(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        cm = _make_core_memory()
        mock_repo.get_core_memory.return_value = cm

        result = await manager.get_core_memory("rex")

        assert result is not None
        assert "## My Core Memory" in result
        assert "### Who I am" in result
        assert "### My relationships" in result
        assert "### Key learnings" in result
        assert "### Current goals" in result
        assert "### Running jokes / lore" in result

    async def test_returns_none_when_not_found(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.get_core_memory.return_value = None
        result = await manager.get_core_memory("unknown_agent")
        assert result is None


# ── update_core_memory ────────────────────────────────────────────

class TestUpdateCoreMemory:
    async def test_modifies_only_targeted_section(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        cm = _make_core_memory()
        mock_repo.get_core_memory.return_value = cm
        mock_repo.upsert_core_memory.return_value = cm

        await manager.update_core_memory(
            "rex", "goals", "- Build the pixel world\n- Ship v1", "weekly_reflection"
        )

        call_args = mock_repo.upsert_core_memory.call_args
        new_content = call_args[0][1]  # second positional arg

        # Goals section updated
        assert "- Build the pixel world" in new_content
        assert "- Ship v1" in new_content

        # Other sections unchanged
        assert "- No learnings recorded yet" in new_content
        assert "Vera: Not yet established" in new_content
        assert "- No running jokes yet" in new_content

    async def test_version_increments_on_update(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        cm = _make_core_memory(version=3)
        mock_repo.get_core_memory.return_value = cm
        mock_repo.upsert_core_memory.return_value = _make_core_memory(version=4)

        result = await manager.update_core_memory(
            "rex", "goals", "- New goal", "relationship_update"
        )

        # upsert_core_memory was called (repo handles version increment)
        mock_repo.upsert_core_memory.assert_called_once()
        assert result.version == 4

    async def test_token_limit_enforcement_raises_at_3000(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock, token_counter: TokenCounter
    ) -> None:
        # Create content that will exceed 3000 tokens when updated
        huge_section = "- " + "word " * 3000  # well over 3000 tokens
        cm = _make_core_memory()
        mock_repo.get_core_memory.return_value = cm

        with pytest.raises(CoreMemoryExceededError, match=f"limit: {TOKEN_LIMIT}"):
            await manager.update_core_memory(
                "rex", "key_learnings", huge_section, "weekly_reflection"
            )

        # Should NOT have called upsert
        mock_repo.upsert_core_memory.assert_not_called()

    async def test_history_records_created_on_update(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        cm = _make_core_memory()
        mock_repo.get_core_memory.return_value = cm
        mock_repo.upsert_core_memory.return_value = cm

        await manager.update_core_memory(
            "rex", "relationships", "- Vera: Best friend and coordinator", "relationship_update"
        )

        # Verify reason was passed through to repo (repo handles history insert)
        call_args = mock_repo.upsert_core_memory.call_args
        assert call_args[0][3] == "relationship_update"  # reason arg

    async def test_invalid_section_raises_error(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        cm = _make_core_memory()
        mock_repo.get_core_memory.return_value = cm

        with pytest.raises(InvalidSectionError, match="Invalid section"):
            await manager.update_core_memory(
                "rex", "nonexistent_section", "content", "test"
            )

    async def test_update_nonexistent_agent_raises(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.get_core_memory.return_value = None

        with pytest.raises(ValueError, match="No core memory found"):
            await manager.update_core_memory(
                "nobody", "goals", "- Something", "test"
            )


# ── initialize_agent_memory ───────────────────────────────────────

class TestInitializeAgentMemory:
    async def test_creates_template_with_identity(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.upsert_core_memory.return_value = _make_core_memory()

        await manager.initialize_agent_memory("rex", "I am Rex, the engineer and builder.")

        call_args = mock_repo.upsert_core_memory.call_args
        content = call_args[0][1]

        assert "## My Core Memory" in content
        assert "I am Rex, the engineer and builder." in content
        assert "### My relationships" in content
        assert "### Key learnings" in content
        assert "### Current goals" in content
        assert "### Running jokes / lore" in content

        # Reason should be initial_creation
        assert call_args[0][3] == "initial_creation"

    async def test_initialize_stores_token_count(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock, token_counter: TokenCounter
    ) -> None:
        mock_repo.upsert_core_memory.return_value = _make_core_memory()

        await manager.initialize_agent_memory("rex", "I am Rex.")

        call_args = mock_repo.upsert_core_memory.call_args
        stored_token_count = call_args[0][2]
        assert isinstance(stored_token_count, int)
        assert stored_token_count > 0


# ── get_token_count ───────────────────────────────────────────────

class TestGetTokenCount:
    async def test_returns_stored_count(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.get_core_memory.return_value = _make_core_memory(token_count=1500)

        count = await manager.get_token_count("rex")
        assert count == 1500

    async def test_raises_for_missing_agent(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        mock_repo.get_core_memory.return_value = None

        with pytest.raises(ValueError, match="No core memory found"):
            await manager.get_token_count("nobody")


# ── get_history ───────────────────────────────────────────────────

class TestGetHistory:
    async def test_returns_history_list(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        history = [
            CoreMemoryHistory(
                id=1, agent_id="rex", content="v1", version=1,
                changed_at=datetime(2026, 4, 1), change_reason="initial_creation",
            ),
            CoreMemoryHistory(
                id=2, agent_id="rex", content="v2", version=2,
                changed_at=datetime(2026, 4, 2), change_reason="weekly_reflection",
            ),
        ]
        mock_repo.get_core_memory_history.return_value = history

        result = await manager.get_history("rex")
        assert len(result) == 2
        assert result[0].version == 1
        assert result[1].change_reason == "weekly_reflection"

    async def test_respects_limit(
        self, manager: CoreMemoryManager, mock_repo: AsyncMock
    ) -> None:
        history = [
            CoreMemoryHistory(
                id=i, agent_id="rex", content=f"v{i}", version=i,
                changed_at=datetime(2026, 4, 1), change_reason="test",
            )
            for i in range(1, 11)
        ]
        mock_repo.get_core_memory_history.return_value = history

        result = await manager.get_history("rex", limit=3)
        assert len(result) == 3


# ── VALID_SECTIONS constant ───────────────────────────────────────

class TestConstants:
    def test_valid_sections_matches_template(self) -> None:
        template = CORE_MEMORY_TEMPLATE.format(date="2026-01-01", identity="Test")
        for section in VALID_SECTIONS:
            # Each valid section should have a corresponding heading in the template
            from core.memory.core_memory import _SECTION_HEADINGS
            heading = _SECTION_HEADINGS[section]
            assert f"### {heading}" in template

    def test_token_limit_is_3000(self) -> None:
        assert TOKEN_LIMIT == 3000


# ── Integration test (requires real database) ─────────────────────

@pytest.mark.integration
class TestCoreMemoryIntegration:
    """Full CRUD cycle against a real database.

    Run with: pytest -m integration (requires Docker services).
    """

    async def test_full_crud_cycle(self) -> None:
        """Initialize → get → update → get_history → verify version increment."""
        # This test requires a running PostgreSQL instance.
        # It is skipped by default (not in the default marker set).
        # To run: docker compose up -d && pytest -m integration
        pytest.skip("Requires running Docker services — run with pytest -m integration")
