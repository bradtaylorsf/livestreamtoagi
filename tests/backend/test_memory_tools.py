"""Tests for memory tools: recall_memory, retrieve_transcript, update_core_memory."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core.memory.core_memory import (
    VALID_SECTIONS,
    CoreMemoryExceededError,
    InvalidSectionError,
)
from core.models import CoreMemory, Transcript
from tools import (
    BaseTool,
    RecallMemoryTool,
    RetrieveTranscriptTool,
    UpdateCoreMemoryTool,
    get_memory_tools,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def recall_manager() -> AsyncMock:
    manager = AsyncMock()
    manager.retrieve_recall_memories = AsyncMock(return_value="")
    return manager


@pytest.fixture
def archival_manager() -> AsyncMock:
    manager = AsyncMock()
    manager.retrieve_full_transcript = AsyncMock(return_value=None)
    return manager


@pytest.fixture
def core_manager() -> AsyncMock:
    manager = AsyncMock()
    manager.update_core_memory = AsyncMock()
    return manager


@pytest.fixture
def recall_tool(recall_manager: AsyncMock) -> RecallMemoryTool:
    return RecallMemoryTool(recall_manager=recall_manager, agent_id="rex")


@pytest.fixture
def transcript_tool(archival_manager: AsyncMock) -> RetrieveTranscriptTool:
    return RetrieveTranscriptTool(archival_manager=archival_manager)


@pytest.fixture
def core_tool(core_manager: AsyncMock) -> UpdateCoreMemoryTool:
    return UpdateCoreMemoryTool(core_manager=core_manager, agent_id="rex")


# ── BaseTool interface conformance ────────────────────────────────


class TestToolInterface:
    def test_recall_memory_has_required_attrs(self, recall_tool: RecallMemoryTool) -> None:
        assert isinstance(recall_tool, BaseTool)
        assert recall_tool.name == "recall_memory"
        assert isinstance(recall_tool.description, str)
        assert "query" in recall_tool.parameters

    def test_retrieve_transcript_has_required_attrs(
        self, transcript_tool: RetrieveTranscriptTool
    ) -> None:
        assert isinstance(transcript_tool, BaseTool)
        assert transcript_tool.name == "retrieve_transcript"
        assert isinstance(transcript_tool.description, str)
        assert "transcript_id" in transcript_tool.parameters

    def test_update_core_memory_has_required_attrs(
        self, core_tool: UpdateCoreMemoryTool
    ) -> None:
        assert isinstance(core_tool, BaseTool)
        assert core_tool.name == "update_core_memory"
        assert isinstance(core_tool.description, str)
        assert "section" in core_tool.parameters
        assert "content" in core_tool.parameters


# ── RecallMemoryTool ──────────────────────────────────────────────


class TestRecallMemory:
    async def test_returns_formatted_summaries(
        self, recall_tool: RecallMemoryTool, recall_manager: AsyncMock
    ) -> None:
        formatted = (
            "## Relevant memories\n"
            "- [conversation] Rex discussed architecture with Vera\n"
            "  (Full transcript available: transcript_42)"
        )
        recall_manager.retrieve_recall_memories.return_value = formatted

        result = await recall_tool.execute(query="architecture discussion")

        assert result["status"] == "ok"
        assert "transcript_42" in result["memories"]
        assert "architecture" in result["memories"]
        recall_manager.retrieve_recall_memories.assert_called_once_with(
            "rex", "architecture discussion", limit=3
        )

    async def test_returns_no_results_when_empty(
        self, recall_tool: RecallMemoryTool, recall_manager: AsyncMock
    ) -> None:
        recall_manager.retrieve_recall_memories.return_value = ""

        result = await recall_tool.execute(query="nonexistent topic")

        assert result["status"] == "no_results"
        assert result["memories"] == ""

    async def test_respects_custom_limit(
        self, recall_tool: RecallMemoryTool, recall_manager: AsyncMock
    ) -> None:
        recall_manager.retrieve_recall_memories.return_value = "## Relevant memories\n- result"

        await recall_tool.execute(query="test", limit=5)

        recall_manager.retrieve_recall_memories.assert_called_once_with(
            "rex", "test", limit=5
        )

    async def test_defaults_limit_to_3(
        self, recall_tool: RecallMemoryTool, recall_manager: AsyncMock
    ) -> None:
        recall_manager.retrieve_recall_memories.return_value = "## Relevant memories\n- result"

        await recall_tool.execute(query="test")

        recall_manager.retrieve_recall_memories.assert_called_once_with(
            "rex", "test", limit=3
        )


# ── RetrieveTranscriptTool ────────────────────────────────────────


class TestRetrieveTranscript:
    async def test_returns_full_text(
        self, transcript_tool: RetrieveTranscriptTool, archival_manager: AsyncMock
    ) -> None:
        transcript = Transcript(
            id=42,
            event_type="conversation",
            participants=["rex", "vera"],
            content="Rex: Let's discuss the architecture.\nVera: Sounds good.",
            token_count=25,
            created_at=datetime(2026, 4, 1),
        )
        archival_manager.retrieve_full_transcript.return_value = transcript

        result = await transcript_tool.execute(transcript_id=42)

        assert result["status"] == "ok"
        assert result["transcript_id"] == 42
        assert result["content"] == transcript.content
        assert result["token_count"] == 25
        assert result["participants"] == ["rex", "vera"]
        archival_manager.retrieve_full_transcript.assert_called_once_with(42)

    async def test_returns_not_found_for_missing_transcript(
        self, transcript_tool: RetrieveTranscriptTool, archival_manager: AsyncMock
    ) -> None:
        archival_manager.retrieve_full_transcript.return_value = None

        result = await transcript_tool.execute(transcript_id=999)

        assert result["status"] == "not_found"
        assert "999" in result["error"]


# ── UpdateCoreMemoryTool ──────────────────────────────────────────


class TestUpdateCoreMemory:
    async def test_updates_section_successfully(
        self, core_tool: UpdateCoreMemoryTool, core_manager: AsyncMock
    ) -> None:
        core_manager.update_core_memory.return_value = CoreMemory(
            agent_id="rex",
            content="updated content",
            token_count=250,
            version=2,
            last_updated=datetime(2026, 4, 1),
        )

        result = await core_tool.execute(
            section="goals", content="- Build the library module"
        )

        assert result["status"] == "updated"
        assert result["token_count"] == 250
        assert result["version"] == 2
        core_manager.update_core_memory.assert_called_once_with(
            agent_id="rex",
            section="goals",
            content="- Build the library module",
            reason="tool_update by rex",
        )

    async def test_validates_section_names(
        self, core_tool: UpdateCoreMemoryTool, core_manager: AsyncMock
    ) -> None:
        core_manager.update_core_memory.side_effect = InvalidSectionError(
            "Invalid section 'invalid_section'. Must be one of: "
            f"{sorted(VALID_SECTIONS)}"
        )

        result = await core_tool.execute(
            section="invalid_section", content="anything"
        )

        assert result["status"] == "error"
        assert "Invalid section" in result["error"]

    async def test_enforces_token_limit(
        self, core_tool: UpdateCoreMemoryTool, core_manager: AsyncMock
    ) -> None:
        core_manager.update_core_memory.side_effect = CoreMemoryExceededError(
            "Update would result in 3500 tokens (limit: 3000)"
        )

        result = await core_tool.execute(
            section="key_learnings", content="x " * 2000
        )

        assert result["status"] == "error"
        assert "3000" in result["error"]

    async def test_defaults_agent_target_to_self(
        self, core_tool: UpdateCoreMemoryTool, core_manager: AsyncMock
    ) -> None:
        core_manager.update_core_memory.return_value = CoreMemory(
            agent_id="rex",
            content="content",
            token_count=100,
            version=1,
            last_updated=datetime(2026, 4, 1),
        )

        await core_tool.execute(section="goals", content="test")

        core_manager.update_core_memory.assert_called_once_with(
            agent_id="rex",
            section="goals",
            content="test",
            reason="tool_update by rex",
        )

    async def test_allows_targeting_another_agent(
        self, core_tool: UpdateCoreMemoryTool, core_manager: AsyncMock
    ) -> None:
        core_manager.update_core_memory.return_value = CoreMemory(
            agent_id="vera",
            content="content",
            token_count=100,
            version=1,
            last_updated=datetime(2026, 4, 1),
        )

        await core_tool.execute(
            section="relationships", content="- Rex: good collaborator", agent_target="vera"
        )

        core_manager.update_core_memory.assert_called_once_with(
            agent_id="vera",
            section="relationships",
            content="- Rex: good collaborator",
            reason="tool_update by rex",
        )


# ── get_memory_tools factory ──────────────────────────────────────


class TestGetMemoryTools:
    def test_returns_all_three_tools(
        self,
        recall_manager: AsyncMock,
        archival_manager: AsyncMock,
        core_manager: AsyncMock,
    ) -> None:
        tools = get_memory_tools(
            recall_manager=recall_manager,
            archival_manager=archival_manager,
            core_manager=core_manager,
            agent_id="vera",
        )

        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"recall_memory", "retrieve_transcript", "update_core_memory"}
        for tool in tools:
            assert isinstance(tool, BaseTool)
