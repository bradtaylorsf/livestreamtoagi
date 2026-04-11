"""Tests for the alliance system (#274)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.social.alliances import (
    MAX_ALLIANCES_PER_AGENT,
    Alliance,
    AllianceManager,
    AllianceProposal,
)


# ── AllianceManager Tests ────────────────────────────────────────


class TestAllianceManager:
    """Tests for alliance proposal, voting, and management."""

    def _make_repo(self) -> AsyncMock:
        """Create a mock AllianceRepo."""
        repo = AsyncMock()
        repo.get_agent_alliances.return_value = []
        repo.get_active_alliances.return_value = []
        repo.get_members.return_value = []
        repo.db = AsyncMock()
        return repo

    @pytest.mark.asyncio
    async def test_propose_alliance(self) -> None:
        repo = self._make_repo()
        repo.create_proposal.return_value = {
            "id": "00000000-0000-0000-0000-000000000001",
            "proposer": "rex",
            "alliance_name": "Builders Guild",
            "purpose": "Build cool stuff",
            "invitees": ["fork", "aurora"],
            "votes": {},
            "status": "pending",
        }

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.propose_alliance(
            proposer_id="rex",
            name="Builders Guild",
            invitees=["fork", "aurora"],
            purpose="Build cool stuff",
        )

        assert result is not None
        assert isinstance(result, AllianceProposal)
        assert result.alliance_name == "Builders Guild"
        assert result.invitees == ["fork", "aurora"]

    @pytest.mark.asyncio
    async def test_propose_blocked_when_max_alliances(self) -> None:
        repo = self._make_repo()
        repo.get_agent_alliances.return_value = [
            {"id": "a1"}, {"id": "a2"},
        ]

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.propose_alliance(
            proposer_id="rex",
            name="Third Alliance",
            invitees=["fork"],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_vote_on_proposal_still_pending(self) -> None:
        repo = self._make_repo()
        repo.vote_on_proposal.return_value = {
            "id": "00000000-0000-0000-0000-000000000001",
            "proposer": "rex",
            "alliance_name": "Builders",
            "purpose": "",
            "invitees": ["fork", "aurora"],
            "votes": {"fork": True},  # aurora hasn't voted yet
            "status": "pending",
        }

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.vote_on_proposal("00000000-0000-0000-0000-000000000001", "fork", True)

        assert isinstance(result, AllianceProposal)
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_vote_forms_alliance_on_majority_accept(self) -> None:
        repo = self._make_repo()
        repo.vote_on_proposal.return_value = {
            "id": "00000000-0000-0000-0000-000000000001",
            "proposer": "rex",
            "alliance_name": "Builders",
            "purpose": "Build stuff",
            "invitees": ["fork", "aurora"],
            "votes": {"fork": True, "aurora": True},
            "status": "pending",
        }
        repo.create_alliance.return_value = {
            "id": "00000000-0000-0000-0000-000000000002",
            "name": "Builders",
            "founded_by": "rex",
            "purpose": "Build stuff",
        }

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.vote_on_proposal("00000000-0000-0000-0000-000000000001", "aurora", True)

        assert isinstance(result, Alliance)
        assert result.name == "Builders"
        assert "rex" in result.members
        # Both accepting invitees should be members
        assert "fork" in result.members
        assert "aurora" in result.members

    @pytest.mark.asyncio
    async def test_vote_rejects_on_majority_no(self) -> None:
        repo = self._make_repo()
        repo.vote_on_proposal.return_value = {
            "id": "00000000-0000-0000-0000-000000000001",
            "proposer": "rex",
            "alliance_name": "Builders",
            "purpose": "",
            "invitees": ["fork", "aurora"],
            "votes": {"fork": False, "aurora": False},
            "status": "pending",
        }

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.vote_on_proposal("00000000-0000-0000-0000-000000000001", "aurora", False)

        assert isinstance(result, AllianceProposal)
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_leave_alliance(self) -> None:
        repo = self._make_repo()
        repo.get_members.return_value = ["fork", "aurora"]  # 2 left after rex leaves

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.leave_alliance("rex", "00000000-0000-0000-0000-000000000002")
        assert result is True
        repo.remove_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_dissolves_when_under_two(self) -> None:
        repo = self._make_repo()
        repo.get_members.return_value = ["aurora"]  # Only 1 left

        mgr = AllianceManager(alliance_repo=repo)
        await mgr.leave_alliance("rex", "00000000-0000-0000-0000-000000000002")
        repo.dissolve_alliance.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_alliance_context_empty(self) -> None:
        repo = self._make_repo()
        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.get_alliance_context("rex")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_alliance_context_with_alliances(self) -> None:
        repo = self._make_repo()
        repo.get_agent_alliances.return_value = [
            {"id": "a1", "name": "Builders Guild", "purpose": "Build cool stuff"},
        ]
        repo.get_members.return_value = ["rex", "fork"]

        mgr = AllianceManager(alliance_repo=repo)
        result = await mgr.get_alliance_context("rex")
        assert "Builders Guild" in result
        assert "fork" in result

    @pytest.mark.asyncio
    async def test_no_repo_returns_empty(self) -> None:
        mgr = AllianceManager()
        assert await mgr.propose_alliance("rex", "Test", ["fork"]) is None
        assert await mgr.get_alliance_context("rex") == ""
        assert await mgr.get_active_alliances() == []


# ── Speaker Selector Alliance Integration ────────────────────────


class TestSpeakerSelectorAllianceIntegration:
    """Tests for alliance effects on speaker selection."""

    def _make_config(self) -> MagicMock:
        config = MagicMock()
        config.selection_weights = MagicMock(
            time_since_spoke=0.3,
            topic_relevance=0.3,
            chattiness=0.15,
            adjacency_fit=0.15,
            random_jitter=0.1,
        )
        config.interrupts = MagicMock(enabled=False)
        config.topics = MagicMock(relevance_map={})
        config.adjacency = {}
        return config

    def test_set_alliance_pairs(self) -> None:
        from core.conversation.speaker_selector import SpeakerSelector
        config = self._make_config()
        selector = SpeakerSelector(config)
        pairs = {frozenset({"rex", "fork"})}
        selector.set_alliance_pairs(pairs)
        assert selector._alliance_pairs == pairs

    def test_alliance_boost_applied(self) -> None:
        from core.conversation.speaker_selector import SpeakerSelector
        from core.models import AgentConfig

        config = self._make_config()
        selector = SpeakerSelector(config)
        selector.set_alliance_pairs({frozenset({"rex", "fork"})})

        # Create two agents: fork (ally of rex) and aurora (not ally)
        fork = AgentConfig(
            id="fork", display_name="Fork", model_conversation="test",
            model_building="test", chattiness=0.5, initiative=0.5,
            interrupt_tendency=0.3,
        )
        aurora = AgentConfig(
            id="aurora", display_name="Aurora", model_conversation="test",
            model_building="test", chattiness=0.5, initiative=0.5,
            interrupt_tendency=0.3,
        )

        history = [{"speaker": "rex", "content": "Hello", "timestamp": "2024-01-01T00:00:00Z"}]

        # Run selection multiple times to check score direction
        fork_scores = []
        aurora_scores = []
        for _ in range(50):
            result = selector.select(history, [fork, aurora], energy=10.0)
            fork_scores.append(result.scores.get("fork", 0))
            aurora_scores.append(result.scores.get("aurora", 0))

        # Fork (ally) should have higher average score than Aurora
        avg_fork = sum(fork_scores) / len(fork_scores)
        avg_aurora = sum(aurora_scores) / len(aurora_scores)
        # The alliance boost is +0.1, so fork should average higher
        assert avg_fork > avg_aurora


# ── Core Memory Alliance Section ─────────────────────────────────


class TestCoreMemoryAllianceSection:
    """Tests for the alliance section in core memory."""

    def test_alliances_in_valid_sections(self) -> None:
        from core.memory.core_memory import VALID_SECTIONS
        assert "alliances" in VALID_SECTIONS

    def test_alliances_heading_exists(self) -> None:
        from core.memory.core_memory import _SECTION_HEADINGS
        assert "alliances" in _SECTION_HEADINGS
        assert _SECTION_HEADINGS["alliances"] == "My alliances"

    def test_template_includes_alliances(self) -> None:
        from core.memory.core_memory import CORE_MEMORY_TEMPLATE
        assert "My alliances" in CORE_MEMORY_TEMPLATE


# ── Social Tools Tests ───────────────────────────────────────────


class TestSocialTools:
    """Tests for alliance-related agent tools."""

    @pytest.mark.asyncio
    async def test_propose_alliance_tool(self) -> None:
        from tools.social_tools import ProposeAllianceTool

        mgr = AsyncMock()
        mgr.propose_alliance.return_value = AllianceProposal(
            id="p1", proposer="rex", alliance_name="Builders",
            invitees=["fork"], purpose="Build",
        )

        tool = ProposeAllianceTool(alliance_manager=mgr, agent_id="rex")
        result = await tool.execute(
            alliance_name="Builders",
            invitees=["fork"],
            purpose="Build",
        )
        assert result["status"] == "proposed"
        assert result["proposal_id"] == "p1"

    @pytest.mark.asyncio
    async def test_vote_alliance_tool_forms_alliance(self) -> None:
        from tools.social_tools import VoteAllianceTool

        mgr = AsyncMock()
        mgr.vote_on_proposal.return_value = Alliance(
            id="a1", name="Builders", members=["rex", "fork"],
            founded_by="rex", purpose="Build",
        )

        tool = VoteAllianceTool(alliance_manager=mgr, agent_id="fork")
        proposal_uuid = "00000000-0000-0000-0000-000000000001"
        result = await tool.execute(proposal_id=proposal_uuid, accept="yes")
        assert result["status"] == "alliance_formed"
        assert "rex" in result["members"]

    @pytest.mark.asyncio
    async def test_leave_alliance_tool(self) -> None:
        from tools.social_tools import LeaveAllianceTool

        mgr = AsyncMock()
        mgr.leave_alliance.return_value = True

        tool = LeaveAllianceTool(alliance_manager=mgr, agent_id="rex")
        result = await tool.execute(alliance_id="a1")
        assert result["status"] == "left"

    @pytest.mark.asyncio
    async def test_view_alliances_tool(self) -> None:
        from tools.social_tools import ViewAlliancesTool

        mgr = AsyncMock()
        mgr.get_active_alliances.return_value = [
            Alliance(id="a1", name="Builders", members=["rex", "fork"],
                     founded_by="rex", purpose="Build"),
        ]

        tool = ViewAlliancesTool(alliance_manager=mgr, agent_id="rex")
        result = await tool.execute()
        assert result["status"] == "ok"
        assert len(result["alliances"]) == 1
        assert result["alliances"][0]["name"] == "Builders"

    @pytest.mark.asyncio
    async def test_tool_without_manager(self) -> None:
        from tools.social_tools import ProposeAllianceTool

        tool = ProposeAllianceTool(agent_id="rex")
        result = await tool.execute(
            alliance_name="Test", invitees=["fork"], purpose="Test",
        )
        assert result["status"] == "error"
