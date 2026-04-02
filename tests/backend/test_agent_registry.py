"""Tests for agent configuration loader and registry."""

from __future__ import annotations

from pathlib import Path
import math
from unittest.mock import AsyncMock

import pytest
import yaml
from pydantic import ValidationError

from core.agent_registry import AgentRegistry
from core.llm_client import MODEL_REGISTRY
from core.models import AgentConfig, AgentStatus

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"
PROMPT_TOKEN_BUDGET = 512


def estimate_token_count(text: str) -> int:
    """Estimate tokens conservatively without adding a tokenizer dependency."""
    return math.ceil(len(text) / 4)


# ── Config validation ────────────────────────────────────────────


def test_config_validation_missing_fields():
    """AgentConfig rejects configs missing required fields."""
    with pytest.raises(ValidationError):
        AgentConfig(
            # missing id, display_name, model_conversation, model_building
            chattiness=0.5,
            initiative=0.5,
            interrupt_tendency=0.5,
        )


def test_config_validation_out_of_range():
    """AgentConfig rejects chattiness > 1.0."""
    with pytest.raises(ValidationError):
        AgentConfig(
            id="test",
            display_name="Test",
            model_conversation="claude-haiku-4-5",
            model_building="claude-haiku-4-5",
            chattiness=1.5,
            initiative=0.5,
            interrupt_tendency=0.5,
        )


def test_config_validation_negative_value():
    """AgentConfig rejects negative initiative."""
    with pytest.raises(ValidationError):
        AgentConfig(
            id="test",
            display_name="Test",
            model_conversation="claude-haiku-4-5",
            model_building="claude-haiku-4-5",
            chattiness=0.5,
            initiative=-0.1,
            interrupt_tendency=0.5,
        )


def test_config_validation_valid():
    """AgentConfig accepts a valid configuration."""
    config = AgentConfig(
        id="test",
        display_name="Test Agent",
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        voice_id="en-US-GuyNeural",
        chattiness=0.5,
        initiative=0.3,
        interrupt_tendency=0.2,
        eavesdrop_tendency=0.4,
        closing_weight=0.1,
    )
    assert config.id == "test"
    assert config.status == AgentStatus.active


# ── Registry loading ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_loads_all_9_agents():
    """Registry loads all 9 agents from the agents/ directory."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()
    agents = registry.get_all_agents()
    assert len(agents) == 9
    agent_ids = {a.id for a in agents}
    assert agent_ids == {
        "vera", "rex", "aurora", "pixel", "fork",
        "sentinel", "grok", "overseer", "alpha",
    }


@pytest.mark.asyncio
async def test_get_agent_by_id():
    """get_agent returns correct config for a known agent."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    rex = registry.get_agent("rex")
    assert rex is not None
    assert rex.display_name == "Rex — The Skeptic"
    assert rex.model_conversation == "claude-haiku-4-5"
    assert rex.model_building == "claude-sonnet-4-6"
    assert rex.chattiness == 0.3
    assert rex.initiative == 0.2
    assert rex.interrupt_tendency == 0.3
    assert rex.voice_id == "en-US-GuyNeural"


@pytest.mark.asyncio
async def test_get_agent_not_found():
    """get_agent returns None for an unknown agent ID."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()
    assert registry.get_agent("nonexistent") is None


@pytest.mark.asyncio
async def test_system_prompt_loaded():
    """System prompts are loaded from system_prompt.md files."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    vera = registry.get_agent("vera")
    assert vera is not None
    assert "Showrunner" in vera.system_prompt
    assert "shared goals" in vera.system_prompt.lower()


@pytest.mark.asyncio
async def test_behaviors_loaded():
    """Behaviors are loaded from behaviors.yaml files."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    rex = registry.get_agent("rex")
    assert rex is not None
    assert "communication" in rex.behaviors
    assert "building" in rex.behaviors


@pytest.mark.asyncio
async def test_special_agents_have_zero_weights():
    """Overseer and Alpha have conversation weights at 0.0."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    overseer = registry.get_agent("overseer")
    assert overseer is not None
    assert overseer.chattiness == 0.0
    assert overseer.initiative == 0.0
    assert overseer.interrupt_tendency == 1.0

    alpha = registry.get_agent("alpha")
    assert alpha is not None
    assert alpha.chattiness == 0.0
    assert alpha.initiative == 0.0
    assert alpha.voice_id is None


@pytest.mark.asyncio
async def test_fork_config_loads_with_expected_values():
    """Fork config loads with the expected model and conversation weights."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    fork = registry.get_agent("fork")
    assert fork is not None
    assert fork.model_conversation == "deepseek-v3.2"
    assert fork.model_building == "deepseek-v3.2"
    assert MODEL_REGISTRY[fork.model_conversation].openrouter_id == "deepseek/deepseek-chat-v3.2"
    assert MODEL_REGISTRY[fork.model_building].openrouter_id == "deepseek/deepseek-chat-v3.2"
    assert fork.voice_id == "en-AU-WilliamNeural"
    assert fork.chattiness == 0.5
    assert fork.initiative == 0.3
    assert fork.interrupt_tendency == 0.6
    assert fork.eavesdrop_tendency == 0.4
    assert fork.closing_weight == 0.05


@pytest.mark.asyncio
async def test_fork_prompt_and_behaviors_match_character():
    """Fork retains the required contrarian open-source reviewer traits."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    fork = registry.get_agent("fork")
    assert fork is not None
    prompt = fork.system_prompt.lower()
    assert "contrarian" in prompt
    assert "open-source" in prompt
    assert "gruff" in prompt
    assert "fork" in prompt

    communication = fork.behaviors["communication"]
    building = fork.behaviors["building"]
    assert communication["proposes_alternatives"] == (
        "always suggests open-source alternative to any commercial tool"
    )
    assert "We should fork it." in communication["catchphrases"]
    assert "At least my weights are public." in communication["catchphrases"]
    assert "code review" in building["primary_skills"]
    assert "license" in building["license_checking"].lower()


def test_fork_system_prompt_stays_under_token_budget():
    """Fork's prompt leaves enough room for runtime context in the model input."""
    prompt_path = AGENTS_DIR / "fork" / "system_prompt.md"
    prompt_text = prompt_path.read_text()

    assert estimate_token_count(prompt_text) <= PROMPT_TOKEN_BUDGET


# ── Status management ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_transitions():
    """Status transitions work: active → paused → active."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    vera = registry.get_agent("vera")
    assert vera is not None
    assert vera.status == AgentStatus.active

    await registry.set_status("vera", AgentStatus.paused)
    vera = registry.get_agent("vera")
    assert vera.status == AgentStatus.paused

    await registry.set_status("vera", AgentStatus.active)
    vera = registry.get_agent("vera")
    assert vera.status == AgentStatus.active


@pytest.mark.asyncio
async def test_get_active_excludes_paused_muted():
    """get_active_agents excludes paused and muted agents."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    all_count = len(registry.get_all_agents())
    assert all_count == 9

    await registry.set_status("vera", AgentStatus.paused)
    await registry.set_status("grok", AgentStatus.muted)

    active = registry.get_active_agents()
    active_ids = {a.id for a in active}
    assert "vera" not in active_ids
    assert "grok" not in active_ids
    assert len(active) == all_count - 2


@pytest.mark.asyncio
async def test_set_status_unknown_agent():
    """set_status raises KeyError for unknown agent."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    with pytest.raises(KeyError, match="nonexistent"):
        await registry.set_status("nonexistent", AgentStatus.paused)


# ── Redis integration ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_persisted_to_redis():
    """set_status writes to Redis when available."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)

    registry = AgentRegistry(redis_client=mock_redis, agents_dir=AGENTS_DIR)
    await registry.load_all()

    await registry.set_status("rex", AgentStatus.sleeping)
    mock_redis.set.assert_called_with("agent:status:rex", "sleeping")


@pytest.mark.asyncio
async def test_get_status_reads_from_redis():
    """get_status reads from Redis when available."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="paused")
    mock_redis.set = AsyncMock(return_value=True)

    registry = AgentRegistry(redis_client=mock_redis, agents_dir=AGENTS_DIR)
    await registry.load_all()

    status = await registry.get_status("vera")
    assert status == AgentStatus.paused
    mock_redis.get.assert_called_with("agent:status:vera")


@pytest.mark.asyncio
async def test_redis_fallback():
    """Registry works with in-memory status when Redis is unavailable."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))
    mock_redis.set = AsyncMock(side_effect=Exception("Redis down"))

    registry = AgentRegistry(redis_client=mock_redis, agents_dir=AGENTS_DIR)
    await registry.load_all()

    # set_status should update in-memory even if Redis fails
    await registry.set_status("vera", AgentStatus.paused)
    vera = registry.get_agent("vera")
    assert vera is not None
    assert vera.status == AgentStatus.paused

    # get_status should fall back to in-memory
    status = await registry.get_status("vera")
    assert status == AgentStatus.paused


# ── Edge cases ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_agents_dir():
    """Registry handles missing agents directory gracefully."""
    registry = AgentRegistry(redis_client=None, agents_dir="/nonexistent/path")
    await registry.load_all()
    assert registry.get_all_agents() == []


@pytest.mark.asyncio
async def test_invalid_model_name(tmp_path):
    """Registry rejects agents with invalid model names."""
    agent_dir = tmp_path / "bad_agent"
    agent_dir.mkdir()
    config = {
        "id": "bad",
        "display_name": "Bad Agent",
        "model_conversation": "nonexistent-model",
        "model_building": "also-fake",
        "chattiness": 0.5,
        "initiative": 0.5,
        "interrupt_tendency": 0.5,
    }
    with open(agent_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)

    registry = AgentRegistry(redis_client=None, agents_dir=tmp_path)
    await registry.load_all()
    # Invalid agent is skipped, not crash
    assert registry.get_all_agents() == []


@pytest.mark.asyncio
async def test_reload():
    """reload() re-reads configs from disk."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()
    assert len(registry.get_all_agents()) == 9

    await registry.reload()
    assert len(registry.get_all_agents()) == 9
