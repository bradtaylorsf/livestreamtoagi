"""Tests for tools/character_tools.py — ProposeCharacterTool, VoteCharacterTool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.character_tools import ProposeCharacterTool, VoteCharacterTool


# ── ProposeCharacterTool ─────────────────────────────────────


class TestProposeCharacterTool:
    def _make_tool(
        self, spawner: AsyncMock | None = None, agent_id: str = "aurora",
    ) -> ProposeCharacterTool:
        return ProposeCharacterTool(spawner=spawner, agent_id=agent_id)

    async def test_happy_path_returns_proposed(self) -> None:
        saved = MagicMock(id="app-1", role="Diplomat")
        saved.name = "spark"
        spawner = MagicMock()
        spawner.can_add_character.return_value = True
        spawner.submit_application = AsyncMock(return_value=saved)

        tool = self._make_tool(spawner=spawner, agent_id="aurora")
        result = await tool.execute(
            character_name="spark",
            role="Diplomat",
            personality_sketch="Friendly and persuasive.",
        )

        assert result["status"] == "proposed"
        assert result["application_id"] == "app-1"
        assert result["character_name"] == "spark"
        assert result["role"] == "Diplomat"

    async def test_no_spawner_returns_error(self) -> None:
        tool = self._make_tool(spawner=None)
        result = await tool.execute(
            character_name="spark", role="Diplomat",
            personality_sketch="Friendly.",
        )
        assert result["status"] == "error"
        assert "not available" in result["reason"]

    async def test_cast_full_returns_error(self) -> None:
        spawner = MagicMock()
        spawner.can_add_character.return_value = False

        tool = self._make_tool(spawner=spawner)
        result = await tool.execute(
            character_name="spark", role="Diplomat",
            personality_sketch="Friendly.",
        )
        assert result["status"] == "error"
        assert "full" in result["reason"].lower()

    async def test_submit_returns_none(self) -> None:
        spawner = MagicMock()
        spawner.can_add_character.return_value = True
        spawner.submit_application = AsyncMock(return_value=None)

        tool = self._make_tool(spawner=spawner)
        result = await tool.execute(
            character_name="spark", role="Diplomat",
            personality_sketch="Friendly.",
        )
        assert result["status"] == "error"
        assert "save" in result["reason"].lower() or "failed" in result["reason"].lower()

    async def test_passes_simulation_id(self) -> None:
        saved = MagicMock(id="app-2", role="Engineer")
        saved.name = "blaze"
        spawner = MagicMock()
        spawner.can_add_character.return_value = True
        spawner.submit_application = AsyncMock(return_value=saved)

        tool = self._make_tool(spawner=spawner)
        await tool.execute(
            character_name="blaze", role="Engineer",
            personality_sketch="Bold.", simulation_id="sim-99",
        )

        call_kwargs = spawner.submit_application.call_args
        assert call_kwargs.kwargs["simulation_id"] == "sim-99"


# ── VoteCharacterTool ────────────────────────────────────────


class TestVoteCharacterTool:
    def _make_tool(
        self, voting_manager: AsyncMock | None = None, agent_id: str = "rex",
    ) -> VoteCharacterTool:
        return VoteCharacterTool(voting_manager=voting_manager, agent_id=agent_id)

    async def test_yes_vote_records(self) -> None:
        mgr = AsyncMock()
        tool = self._make_tool(voting_manager=mgr, agent_id="rex")

        valid_uuid = "00000000-0000-0000-0000-000000000001"
        result = await tool.execute(
            application_id=valid_uuid, vote="yes", reasoning="Great fit!",
        )

        assert result["status"] == "voted"
        assert result["vote"] == "yes"
        mgr.record_agent_vote.assert_called_once_with(
            application_id=valid_uuid,
            agent_id="rex",
            vote=True,
            reasoning="Great fit!",
        )

    async def test_no_vote_records(self) -> None:
        mgr = AsyncMock()
        tool = self._make_tool(voting_manager=mgr)

        valid_uuid = "00000000-0000-0000-0000-000000000002"
        result = await tool.execute(
            application_id=valid_uuid, vote="no", reasoning="Not convinced.",
        )

        assert result["status"] == "voted"
        assert result["vote"] == "no"
        mgr.record_agent_vote.assert_called_once()
        assert mgr.record_agent_vote.call_args.kwargs["vote"] is False

    async def test_no_voting_manager_returns_error(self) -> None:
        tool = self._make_tool(voting_manager=None)
        result = await tool.execute(
            application_id="some-id", vote="yes", reasoning="Why not",
        )
        assert result["status"] == "error"
        assert "not available" in result["reason"]

    async def test_invalid_uuid_returns_error(self) -> None:
        mgr = AsyncMock()
        tool = self._make_tool(voting_manager=mgr)

        result = await tool.execute(
            application_id="not-a-uuid", vote="yes", reasoning="Sure",
        )
        assert result["status"] == "error"
        assert "UUID" in result["reason"]
        mgr.record_agent_vote.assert_not_called()

    async def test_missing_reasoning_defaults_to_empty(self) -> None:
        mgr = AsyncMock()
        tool = self._make_tool(voting_manager=mgr)

        valid_uuid = "00000000-0000-0000-0000-000000000003"
        await tool.execute(application_id=valid_uuid, vote="yes")

        assert mgr.record_agent_vote.call_args.kwargs["reasoning"] == ""
