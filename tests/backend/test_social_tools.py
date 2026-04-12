"""Tests for tools/social_tools.py — error paths and edge cases.

Happy-path tests are in test_alliances.py::TestSocialTools; this file
covers the gaps: invalid UUID, no-manager guards, rejected vote path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.social_tools import (
    LeaveAllianceTool,
    ProposeAllianceTool,
    ViewAlliancesTool,
    VoteAllianceTool,
)


class TestVoteAllianceToolEdgeCases:
    async def test_invalid_uuid_returns_error(self) -> None:
        mgr = AsyncMock()
        tool = VoteAllianceTool(alliance_manager=mgr, agent_id="fork")

        result = await tool.execute(proposal_id="not-a-uuid", accept="yes")
        assert result["status"] == "error"
        assert "UUID" in result["reason"]
        mgr.vote_on_proposal.assert_not_called()

    async def test_no_manager_returns_error(self) -> None:
        tool = VoteAllianceTool(agent_id="fork")
        result = await tool.execute(
            proposal_id="00000000-0000-0000-0000-000000000001", accept="yes",
        )
        assert result["status"] == "error"
        assert "not available" in result["reason"]

    async def test_proposal_not_found_returns_error(self) -> None:
        mgr = AsyncMock()
        mgr.vote_on_proposal.return_value = None

        tool = VoteAllianceTool(alliance_manager=mgr, agent_id="fork")
        result = await tool.execute(
            proposal_id="00000000-0000-0000-0000-000000000001", accept="yes",
        )
        assert result["status"] == "error"
        assert "not found" in result["reason"].lower()

    async def test_rejected_vote_returns_voted_status(self) -> None:
        proposal = MagicMock(status="pending")
        mgr = AsyncMock()
        mgr.vote_on_proposal.return_value = proposal

        tool = VoteAllianceTool(alliance_manager=mgr, agent_id="fork")
        result = await tool.execute(
            proposal_id="00000000-0000-0000-0000-000000000001", accept="no",
        )
        assert result["status"] == "voted"
        assert result["vote"] == "rejected"


class TestLeaveAllianceToolEdgeCases:
    async def test_no_manager_returns_error(self) -> None:
        tool = LeaveAllianceTool(agent_id="rex")
        result = await tool.execute(alliance_id="a1")
        assert result["status"] == "error"
        assert "not available" in result["reason"]

    async def test_leave_fails_returns_error(self) -> None:
        mgr = AsyncMock()
        mgr.leave_alliance.return_value = False

        tool = LeaveAllianceTool(alliance_manager=mgr, agent_id="rex")
        result = await tool.execute(alliance_id="a1")
        assert result["status"] == "error"


class TestViewAlliancesToolEdgeCases:
    async def test_no_manager_returns_error(self) -> None:
        tool = ViewAlliancesTool(agent_id="rex")
        result = await tool.execute()
        assert result["status"] == "error"
        assert "not available" in result["reason"]

    async def test_empty_alliances(self) -> None:
        mgr = AsyncMock()
        mgr.get_active_alliances.return_value = []

        tool = ViewAlliancesTool(alliance_manager=mgr, agent_id="rex")
        result = await tool.execute()
        assert result["status"] == "ok"
        assert result["alliances"] == []


class TestProposeAllianceToolEdgeCases:
    async def test_proposal_returns_none(self) -> None:
        mgr = AsyncMock()
        mgr.propose_alliance.return_value = None

        tool = ProposeAllianceTool(alliance_manager=mgr, agent_id="rex")
        result = await tool.execute(
            alliance_name="TestAlliance", invitees=["fork"], purpose="Test",
        )
        assert result["status"] == "error"
        assert "too many" in result["reason"].lower() or "cannot" in result["reason"].lower()
