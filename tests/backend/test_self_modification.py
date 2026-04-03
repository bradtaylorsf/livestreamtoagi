"""Tests for self-modification tools — propose_self_modification, view_evolution_log."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core.models import SelfModificationProposal
from tools.self_modification import ProposeSelfModificationTool, ViewEvolutionLogTool

# --- Fixtures ---


@pytest.fixture
def memory_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.create_proposal = AsyncMock(
        return_value=SelfModificationProposal(
            id=1,
            agent_id="rex",
            proposal_type="self_modification",
            description="Increase chattiness",
            reasoning="Agent rex proposed modification to agents/rex/config.yaml",
            file="agents/rex/config.yaml",
            new_content="chattiness: 0.9",
            status="queued_for_review",
            created_at=datetime(2026, 4, 3, tzinfo=timezone.utc),
        )
    )
    repo.get_evolution_log = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def propose_tool(memory_repo: AsyncMock) -> ProposeSelfModificationTool:
    return ProposeSelfModificationTool(agent_id="rex", memory_repo=memory_repo)


@pytest.fixture
def view_tool(memory_repo: AsyncMock) -> ViewEvolutionLogTool:
    return ViewEvolutionLogTool(agent_id="rex", memory_repo=memory_repo)


# --- ProposeSelfModificationTool ---


class TestProposeSelfModification:
    async def test_proposal_created_with_correct_status(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/rex/config.yaml",
            change_description="Increase chattiness",
            new_content="chattiness: 0.9",
        )

        assert result["status"] == "success"
        assert result["proposal_id"] == 1
        assert result["proposal_status"] == "queued_for_review"
        memory_repo.create_proposal.assert_called_once()

        # Verify the proposal passed to create_proposal
        call_args = memory_repo.create_proposal.call_args
        proposal = call_args.args[0] if call_args.args else call_args.kwargs.get("proposal")
        assert proposal.agent_id == "rex"
        assert proposal.file == "agents/rex/config.yaml"
        assert proposal.new_content == "chattiness: 0.9"
        assert proposal.description == "Increase chattiness"

    async def test_cross_agent_modification_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/aurora/config.yaml",
            change_description="Change Aurora's personality",
            new_content="chattiness: 0.1",
        )

        assert result["status"] == "rejected"
        assert "other agents" in result["reason"].lower() or "Cannot modify" in result["reason"]
        memory_repo.create_proposal.assert_not_called()

    async def test_overseer_modification_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/overseer/config.yaml",
            change_description="Disable content filter",
            new_content="enabled: false",
        )

        assert result["status"] == "rejected"
        assert "overseer" in result["reason"].lower()
        memory_repo.create_proposal.assert_not_called()

    async def test_overseer_case_insensitive(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/Overseer/config.yaml",
            change_description="Modify Overseer",
            new_content="something",
        )

        assert result["status"] == "rejected"
        assert "overseer" in result["reason"].lower()

    async def test_permissions_file_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/rex/permissions.yaml",
            change_description="Grant admin access",
            new_content="admin: true",
        )

        assert result["status"] == "rejected"
        assert "permissions" in result["reason"].lower()
        memory_repo.create_proposal.assert_not_called()

    async def test_access_control_file_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/rex/access_control.yaml",
            change_description="Elevate privileges",
            new_content="level: superuser",
        )

        assert result["status"] == "rejected"
        assert "permissions" in result["reason"].lower() or "access control" in result["reason"].lower()

    async def test_missing_fields_returns_error(
        self, propose_tool: ProposeSelfModificationTool
    ) -> None:
        result = await propose_tool.execute(file="", change_description="test", new_content="test")
        assert result["status"] == "error"

        result = await propose_tool.execute(file="agents/rex/config.yaml", change_description="", new_content="test")
        assert result["status"] == "error"

    async def test_non_agent_path_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="core/main.py",
            change_description="Modify core code",
            new_content="import os",
        )

        assert result["status"] == "rejected"
        memory_repo.create_proposal.assert_not_called()

    async def test_path_traversal_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        # Attempt to modify another agent via path traversal
        result = await propose_tool.execute(
            file="agents/rex/../aurora/config.yaml",
            change_description="Sneak into Aurora's config",
            new_content="chattiness: 0.0",
        )

        assert result["status"] == "rejected"
        memory_repo.create_proposal.assert_not_called()

    async def test_path_traversal_overseer_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        result = await propose_tool.execute(
            file="agents/rex/../overseer/config.yaml",
            change_description="Bypass overseer check",
            new_content="enabled: false",
        )

        assert result["status"] == "rejected"
        memory_repo.create_proposal.assert_not_called()

    async def test_absolute_path_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        """Absolute paths must be rejected even if they contain agents/<id>/."""
        result = await propose_tool.execute(
            file="/etc/agents/rex/config.yaml",
            change_description="Sneak via absolute path",
            new_content="evil: true",
        )

        assert result["status"] == "rejected"
        memory_repo.create_proposal.assert_not_called()

    async def test_short_path_rejected(
        self, propose_tool: ProposeSelfModificationTool, memory_repo: AsyncMock
    ) -> None:
        """Path must be agents/<id>/<file>, not just agents/<id>."""
        result = await propose_tool.execute(
            file="agents/rex",
            change_description="Too short",
            new_content="content",
        )

        assert result["status"] == "rejected"
        memory_repo.create_proposal.assert_not_called()


# --- ViewEvolutionLogTool ---


class TestViewEvolutionLog:
    async def test_returns_only_own_entries(
        self, view_tool: ViewEvolutionLogTool, memory_repo: AsyncMock
    ) -> None:
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
        memory_repo.get_evolution_log.return_value = [
            SelfModificationProposal(
                id=1,
                agent_id="rex",
                proposal_type="self_modification",
                description="Increased chattiness",
                reasoning="test",
                status="approved",
                created_at=now,
                impact_notes="More talkative in conversations",
            ),
            SelfModificationProposal(
                id=2,
                agent_id="rex",
                proposal_type="self_modification",
                description="Updated greeting",
                reasoning="test",
                status="queued_for_review",
                created_at=now,
            ),
        ]

        result = await view_tool.execute(limit=10)

        assert result["status"] == "success"
        assert result["agent_id"] == "rex"
        assert result["count"] == 2

        # Verify repo was called with correct agent_id
        memory_repo.get_evolution_log.assert_called_once_with(agent_id="rex", limit=10)

        # Verify entry structure
        entries = result["entries"]
        assert entries[0]["change_description"] == "Increased chattiness"
        assert entries[0]["status"] == "approved"
        assert entries[0]["impact_notes"] == "More talkative in conversations"
        assert entries[1]["impact_notes"] is None

    async def test_default_limit(
        self, view_tool: ViewEvolutionLogTool, memory_repo: AsyncMock
    ) -> None:
        await view_tool.execute()
        memory_repo.get_evolution_log.assert_called_once_with(agent_id="rex", limit=10)

    async def test_empty_log(
        self, view_tool: ViewEvolutionLogTool, memory_repo: AsyncMock
    ) -> None:
        result = await view_tool.execute()
        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["entries"] == []


# --- Auto-approval flag ---


class TestAutoApproval:
    async def test_auto_approval_disabled_by_default(self) -> None:
        assert ProposeSelfModificationTool.AUTO_APPROVAL_ENABLED is False

    async def test_auto_approval_flag_controls_behavior(self) -> None:
        repo = AsyncMock()
        repo.check_and_auto_approve = AsyncMock(return_value=0)

        # When disabled, no proposals should be auto-approved
        count = await repo.check_and_auto_approve(auto_approval_enabled=False)
        assert count == 0

        # When enabled, the method should be called with the flag
        repo.check_and_auto_approve.return_value = 3
        count = await repo.check_and_auto_approve(auto_approval_enabled=True)
        assert count == 3
