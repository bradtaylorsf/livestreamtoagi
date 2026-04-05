"""Tests for DB-backed versioned agent config (#238)."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import (
    ActiveConfig,
    AgentConfig,
    AgentPromptVersion,
    AgentStatus,
    ConversationParamVersion,
)


# ── Model tests ──────────────────────────────────────────────


class TestAgentPromptVersionModel:
    def test_create(self) -> None:
        v = AgentPromptVersion(
            id=uuid.uuid4(),
            agent_id="rex",
            version=1,
            system_prompt="You are Rex.",
            behaviors={"style": "sarcastic"},
            config_params={"chattiness": 0.4},
            source="seed",
        )
        assert v.agent_id == "rex"
        assert v.version == 1
        assert v.config_params["chattiness"] == 0.4
        assert v.source == "seed"

    def test_defaults(self) -> None:
        v = AgentPromptVersion(
            id=uuid.uuid4(),
            agent_id="vera",
            version=1,
            system_prompt="test",
            source="manual",
        )
        assert v.behaviors == {}
        assert v.config_params == {}
        assert v.eval_run_id is None


class TestConversationParamVersionModel:
    def test_create(self) -> None:
        v = ConversationParamVersion(
            id=uuid.uuid4(),
            version=1,
            params={"selection_weights": {"time_since_spoke": 0.3}},
            source="seed",
        )
        assert v.version == 1
        assert v.params["selection_weights"]["time_since_spoke"] == 0.3


class TestActiveConfigModel:
    def test_create(self) -> None:
        ac = ActiveConfig(
            agent_id="rex",
            prompt_version=2,
            conversation_param_version=1,
        )
        assert ac.agent_id == "rex"
        assert ac.prompt_version == 2


# ── AgentRegistry DB loading tests ───────────────────────────


class TestAgentRegistryDBLoading:
    @pytest.mark.asyncio
    async def test_load_from_db_with_no_repo(self) -> None:
        """Registry without config_repo should fall back to YAML."""
        from core.agent_registry import AgentRegistry

        registry = AgentRegistry(redis_client=None, agents_dir="agents")
        # load_all should not raise even without DB
        await registry.load_all()
        # Should have loaded from YAML
        agents = registry.get_all_agents()
        assert len(agents) > 0

    @pytest.mark.asyncio
    async def test_load_from_db_builds_agent_config(self) -> None:
        """Registry should build AgentConfig from DB prompt versions."""
        from core.agent_registry import AgentRegistry

        mock_repo = AsyncMock()
        mock_repo.get_all_active_configs.return_value = [
            ActiveConfig(agent_id="rex", prompt_version=1, conversation_param_version=1),
        ]
        mock_repo.get_prompt_version.return_value = AgentPromptVersion(
            id=uuid.uuid4(),
            agent_id="rex",
            version=1,
            system_prompt="You are Rex the engineer.",
            behaviors={"style": "dry"},
            config_params={
                "display_name": "Rex",
                "model_conversation": "claude-haiku-4-5",
                "model_building": "claude-sonnet-4-6",
                "chattiness": 0.4,
                "initiative": 0.6,
                "interrupt_tendency": 0.2,
                "voice_id": "en-US-GuyNeural",
            },
            source="seed",
        )

        registry = AgentRegistry(
            redis_client=None,
            agents_dir="nonexistent_dir",
            config_version_repo=mock_repo,
        )
        await registry.load_all()

        agent = registry.get_agent("rex")
        assert agent is not None
        assert agent.display_name == "Rex"
        assert agent.chattiness == 0.4
        assert agent.system_prompt == "You are Rex the engineer."
        assert agent.behaviors == {"style": "dry"}

    @pytest.mark.asyncio
    async def test_yaml_fallback_when_db_empty(self) -> None:
        """Agents not in DB should still load from YAML."""
        from core.agent_registry import AgentRegistry

        mock_repo = AsyncMock()
        mock_repo.get_all_active_configs.return_value = []

        registry = AgentRegistry(
            redis_client=None,
            agents_dir="agents",
            config_version_repo=mock_repo,
        )
        await registry.load_all()

        # Should have fallen back to YAML
        agents = registry.get_all_agents()
        assert len(agents) > 0

    @pytest.mark.asyncio
    async def test_reload_agent_from_db(self) -> None:
        """reload_agent should hot-swap a single agent's config."""
        from core.agent_registry import AgentRegistry

        mock_repo = AsyncMock()
        mock_repo.get_active_config.return_value = ActiveConfig(
            agent_id="rex", prompt_version=2, conversation_param_version=1,
        )
        mock_repo.get_prompt_version.return_value = AgentPromptVersion(
            id=uuid.uuid4(),
            agent_id="rex",
            version=2,
            system_prompt="Updated Rex prompt.",
            behaviors={},
            config_params={
                "display_name": "Rex v2",
                "model_conversation": "claude-haiku-4-5",
                "model_building": "claude-sonnet-4-6",
                "chattiness": 0.3,
                "initiative": 0.7,
                "interrupt_tendency": 0.1,
            },
            source="eval_loop",
        )

        registry = AgentRegistry(
            redis_client=None,
            agents_dir="agents",
            config_version_repo=mock_repo,
        )
        await registry.load_all()

        # Verify rex loaded from YAML first
        original = registry.get_agent("rex")
        assert original is not None

        # Reload from DB
        await registry.reload_agent("rex")
        updated = registry.get_agent("rex")
        assert updated is not None
        assert updated.display_name == "Rex v2"
        assert updated.chattiness == 0.3
        assert updated.system_prompt == "Updated Rex prompt."


# ── ConfigLoader DB loading tests ────────────────────────────


class TestConfigLoaderDB:
    @pytest.mark.asyncio
    async def test_load_from_db_returns_none_without_repo(self) -> None:
        from core.config_loader import ConfigLoader

        loader = ConfigLoader()
        result = await loader.load_from_db()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_from_db_returns_none_when_no_version(self) -> None:
        from core.config_loader import ConfigLoader

        mock_repo = AsyncMock()
        mock_repo.get_active_conversation_params.return_value = None

        loader = ConfigLoader(config_version_repo=mock_repo)
        result = await loader.load_from_db()
        assert result is None


# ── ConfigVersionRepo tests (unit) ───────────────────────────


class TestConfigVersionRepo:
    @pytest.mark.asyncio
    async def test_get_active_prompt_not_found(self) -> None:
        from core.repos.config_version_repo import ConfigVersionRepo

        mock_db = AsyncMock()
        mock_db.fetchrow.return_value = None
        repo = ConfigVersionRepo(mock_db)
        result = await repo.get_active_prompt("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_rollback_nonexistent_version_raises(self) -> None:
        from core.repos.config_version_repo import ConfigVersionRepo

        mock_db = AsyncMock()
        mock_db.fetchval.return_value = None
        repo = ConfigVersionRepo(mock_db)
        with pytest.raises(ValueError, match="Version 99 not found"):
            await repo.rollback_prompt("rex", 99)

    @pytest.mark.asyncio
    async def test_rollback_conversation_nonexistent_raises(self) -> None:
        from core.repos.config_version_repo import ConfigVersionRepo

        mock_db = AsyncMock()
        mock_db.fetchval.return_value = None
        repo = ConfigVersionRepo(mock_db)
        with pytest.raises(ValueError, match="version 99 not found"):
            await repo.rollback_conversation_params(99)
