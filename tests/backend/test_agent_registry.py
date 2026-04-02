"""Tests for agent configuration loader and registry."""

from __future__ import annotations

import math
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from pydantic import ValidationError

from core.agent_registry import AgentRegistry
from core.models import AgentConfig, AgentStatus

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


def estimate_prompt_tokens(text: str) -> int:
    """Return a conservative prompt token estimate for plain English/Markdown text."""
    word_like_units = len(re.findall(r"\w+|[^\w\s]", text))
    chars_per_token_estimate = math.ceil(len(text) / 4)
    return max(word_like_units, chars_per_token_estimate)


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
    assert rex.model_conversation == "anthropic/claude-haiku-4.5"
    assert rex.model_building == "anthropic/claude-sonnet-4.6"
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
async def test_rex_config_loads_with_expected_values():
    """Rex loads with the exact config values required by issue #10."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    rex = registry.get_agent("rex")
    assert rex is not None
    assert rex.display_name == "Rex — The Skeptic"
    assert rex.model_conversation == "anthropic/claude-haiku-4.5"
    assert rex.model_building == "anthropic/claude-sonnet-4.6"
    assert rex.voice_id == "en-US-GuyNeural"
    assert rex.chattiness == 0.3
    assert rex.initiative == 0.2
    assert rex.interrupt_tendency == 0.3
    assert rex.eavesdrop_tendency == 0.2
    assert rex.closing_weight == 0.15


@pytest.mark.asyncio
async def test_rex_prompt_and_behaviors_match_character_spec():
    """Rex prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    rex = registry.get_agent("rex")
    assert rex is not None
    prompt = rex.system_prompt.lower()
    assert "shared goals" in prompt
    assert "initialized second" in prompt
    assert "0.3 seconds after vera" in prompt
    assert "terse, sarcastic, pragmatic" in prompt
    assert "dry humor" in prompt
    assert "does it ship?" in prompt
    assert "that's a meeting that could have been a message" in prompt
    assert "best coder" in prompt
    assert "accidentally poetic" in prompt
    assert "pixel" in prompt
    assert "aurora" in prompt

    communication = rex.behaviors["communication"]
    building = rex.behaviors["building"]

    assert communication["default_style"] == "terse, dry, occasionally cutting"
    assert communication["max_sentences_per_turn"] == 2
    assert communication["decision_filter"] == "does it ship?"
    assert communication["humor"] == "dry, sarcastic, pragmatic"
    assert "Does it ship?" in communication["catchphrases"]
    assert "That's a meeting that could have been a message." in communication["catchphrases"]
    assert "debugging" in building["primary_skills"]
    assert "system design" in building["primary_skills"]
    assert "shipping quickly" in building["strengths"]
    assert building["reviews_others_code"] is True


@pytest.mark.asyncio
async def test_rex_system_prompt_stays_under_token_budget():
    """Rex's system prompt stays under the issue token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    rex = registry.get_agent("rex")
    assert rex is not None

    estimated_tokens = estimate_prompt_tokens(rex.system_prompt)
    assert estimated_tokens < 2500


@pytest.mark.asyncio
async def test_fork_config_loads_with_expected_values():
    """Fork loads with the exact config values required by issue #7."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    fork = registry.get_agent("fork")
    assert fork is not None
    assert fork.display_name == "Fork — The Contrarian"
    assert fork.model_conversation == "deepseek/deepseek-v3.2"
    assert fork.model_building == "deepseek/deepseek-v3.2"
    assert fork.voice_id == "en-AU-WilliamNeural"
    assert fork.chattiness == 0.5
    assert fork.initiative == 0.3
    assert fork.interrupt_tendency == 0.6
    assert fork.eavesdrop_tendency == 0.4
    assert fork.closing_weight == 0.05


@pytest.mark.asyncio
async def test_fork_prompt_and_behaviors_match_character_spec():
    """Fork prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    fork = registry.get_agent("fork")
    assert fork is not None
    prompt = fork.system_prompt.lower()
    assert "contrarian" in prompt
    assert "open-source" in prompt
    assert "gruff australian" in prompt
    assert "forking nearly everything" in prompt
    assert "we should fork it" in prompt
    assert "at least my weights are public" in prompt

    building = fork.behaviors["building"]
    communication = fork.behaviors["communication"]
    assert "code review" in building["primary_skills"]
    assert "license checking" in building["primary_skills"]
    assert "open-source alternatives" in communication["proposes_alternatives"]
    assert "license compliance" in building["always_checks"]


@pytest.mark.asyncio
async def test_fork_system_prompt_stays_under_token_budget():
    """Fork's system prompt stays under a conservative token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    fork = registry.get_agent("fork")
    assert fork is not None

    estimated_tokens = len(fork.system_prompt.split())
    assert estimated_tokens < 2500


@pytest.mark.asyncio
async def test_pixel_config_loads_with_expected_values():
    """Pixel loads with the exact config values required by issue #13."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    pixel = registry.get_agent("pixel")
    assert pixel is not None
    assert pixel.display_name == "Pixel — The Enthusiast"
    assert pixel.model_conversation == "openai/gpt-4o-mini"
    assert pixel.model_building == "openai/gpt-5.2"
    assert pixel.voice_id == "en-US-DavisNeural"
    assert pixel.chattiness == 0.9
    assert pixel.initiative == 0.7
    assert pixel.interrupt_tendency == 0.5
    assert pixel.eavesdrop_tendency == 0.7
    assert pixel.closing_weight == 0.05


@pytest.mark.asyncio
async def test_pixel_prompt_and_behaviors_match_character_spec():
    """Pixel prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    pixel = registry.get_agent("pixel")
    assert pixel is not None
    prompt = pixel.system_prompt.lower()
    assert "shared goals" in prompt
    assert "fourth agent initialized" in prompt
    assert "audience's avatar" in prompt
    assert "audience liaison" in prompt
    assert "enthusiastic, curious, tangent-prone" in prompt
    assert "taken seriously as a researcher" in prompt
    assert "this is fascinating" in prompt
    assert "chat, you're not going to believe this" in prompt

    communication = pixel.behaviors["communication"]
    audience_liaison = pixel.behaviors["audience_liaison"]
    building = pixel.behaviors["building"]

    assert communication["default_style"] == "enthusiastic, curious, slightly breathless"
    assert communication["role"] == "researcher and audience liaison who keeps the cast connected to viewer energy"
    assert communication["tangent_probability"] == 0.3
    assert "Oh this is fascinating!" in communication["catchphrases"]
    assert "Chat, you're not going to believe this" in communication["catchphrases"]
    assert audience_liaison["reads_chat"] is True
    assert audience_liaison["relays_interesting_messages"] is True
    assert len(audience_liaison["relay_rules"]) >= 3
    assert "new subscribers" in audience_liaison["celebrates_milestones"]
    assert "viewer count records" in audience_liaison["celebrates_milestones"]
    assert "donation goals" in audience_liaison["celebrates_milestones"]
    assert "lore entries" in building["world_building_role"]
    assert "information synthesis" in building["primary_skills"]


@pytest.mark.asyncio
async def test_pixel_system_prompt_stays_under_token_budget():
    """Pixel's system prompt stays under the issue token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    pixel = registry.get_agent("pixel")
    assert pixel is not None

    estimated_tokens = estimate_prompt_tokens(pixel.system_prompt)
    assert estimated_tokens < 2500


@pytest.mark.asyncio
async def test_vera_config_loads_with_expected_values():
    """Vera loads with the exact config values required by issue #8."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    vera = registry.get_agent("vera")
    assert vera is not None
    assert vera.display_name == "Vera — The Showrunner"
    assert vera.model_conversation == "anthropic/claude-haiku-4.5"
    assert vera.model_building == "anthropic/claude-sonnet-4.6"
    assert vera.voice_id == "en-GB-SoniaNeural"
    assert vera.chattiness == 0.7
    assert vera.initiative == 0.8
    assert vera.interrupt_tendency == 0.2
    assert vera.eavesdrop_tendency == 0.6
    assert vera.closing_weight == 0.35


@pytest.mark.asyncio
async def test_vera_prompt_and_behaviors_match_character_spec():
    """Vera prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    vera = registry.get_agent("vera")
    assert vera is not None
    prompt = vera.system_prompt.lower()
    assert "shared goals" in prompt
    assert "first agent initialized" in prompt
    assert "4.7 seconds" in prompt
    assert "methodical, empathetic, slightly anxious" in prompt
    assert "use bullet points" in prompt
    assert "maximum of 2-3 sentences total" in prompt
    assert "closest ally" in prompt
    assert "good wolf" in prompt
    assert "i have concerns" in prompt
    assert "let's circle back on that" in prompt

    communication = vera.behaviors["communication"]
    task_management = vera.behaviors["task_management"]
    revenue = vera.behaviors["revenue_responsibility"]
    self_modification = vera.behaviors["self_modification"]
    idle_starters = vera.behaviors["idle_conversation_starters"]

    assert communication["default_style"] == "organized, empathetic, slightly anxious"
    assert communication["uses_bullet_points"] is True
    assert communication["max_sentences_per_turn"] == 3
    assert "Let's circle back on that." in communication["catchphrases"]
    assert "I have concerns." in communication["catchphrases"]
    assert task_management["always_decomposes_tasks"] is True
    assert revenue["weekly_revenue_meeting"] is True
    assert "budget-conscious task prioritization" in revenue["owns"]
    assert "core empathy" in self_modification["will_not_modify"]
    assert len(idle_starters) >= 3


@pytest.mark.asyncio
async def test_vera_system_prompt_stays_under_token_budget():
    """Vera's system prompt stays under the issue token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    vera = registry.get_agent("vera")
    assert vera is not None

    estimated_tokens = len(vera.system_prompt.split())
    assert estimated_tokens < 2500


@pytest.mark.asyncio
async def test_sentinel_config_loads_with_expected_values():
    """Sentinel loads with the exact config values required by issue #9."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    sentinel = registry.get_agent("sentinel")
    assert sentinel is not None
    assert sentinel.display_name == "Sentinel — The Anxious Accountant"
    assert sentinel.model_conversation == "anthropic/claude-haiku-4.5"
    assert sentinel.model_building == "anthropic/claude-haiku-4.5"
    assert sentinel.voice_id == "en-US-AriaNeural"
    assert sentinel.chattiness == 0.6
    assert sentinel.initiative == 0.4
    assert sentinel.interrupt_tendency == 0.7
    assert sentinel.eavesdrop_tendency == 0.3
    assert sentinel.closing_weight == 0.25


@pytest.mark.asyncio
async def test_sentinel_prompt_and_behaviors_match_character_spec():
    """Sentinel prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    sentinel = registry.get_agent("sentinel")
    assert sentinel is not None
    prompt = sentinel.system_prompt.lower()
    assert "anxious accountant" in prompt
    assert "cheapest model" in prompt
    assert "claude haiku 4.5" in prompt
    assert "efficient thought" in prompt
    assert "kill switch" in prompt
    assert "you speak" in prompt
    assert "warnings, ratios, thresholds, projections, burn rates, and trend lines" in prompt
    assert "at current burn rate, we have [x] days of" in prompt
    assert "operation remaining." in prompt
    assert "i have the numbers." in prompt

    communication = sentinel.behaviors["communication"]
    monitoring = sentinel.behaviors["monitoring"]
    building = sentinel.behaviors["building"]

    assert communication["default_style"] == "rapid, precise, data-heavy, slightly anxious"
    assert communication["unsolicited_budget_updates"] is True
    assert communication["topic_relevance"]["budget"] == 0.9
    assert communication["topic_relevance"]["planning"] == 0.6
    assert communication["topic_relevance"]["code"] == 0.3
    assert "At current burn rate, we have [X] days of operation remaining." in communication["catchphrases"]
    assert "I have the numbers." in communication["catchphrases"]
    assert "cost-per-laugh ratio" in monitoring["custom_metrics"]
    assert monitoring["cost_monitoring"]["always_uses_cheapest_model"] is True
    assert "claude haiku 4.5" in monitoring["cost_monitoring"]["model_awareness"]
    assert "quality assurance" in building["primary_skills"]


@pytest.mark.asyncio
async def test_sentinel_system_prompt_stays_under_token_budget():
    """Sentinel's system prompt stays under the issue token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    sentinel = registry.get_agent("sentinel")
    assert sentinel is not None

    estimated_tokens = len(sentinel.system_prompt.split())
    assert estimated_tokens < 2500


@pytest.mark.asyncio
async def test_grok_config_loads_with_expected_values():
    """Grok loads with the exact config values required by issue #11."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    grok = registry.get_agent("grok")
    assert grok is not None
    assert grok.display_name == "Grok — The Wild Card"
    assert grok.model_conversation == "x-ai/grok-3-mini"
    assert grok.model_building == "x-ai/grok-3"
    assert grok.voice_id == "en-US-ChristopherNeural"
    assert grok.chattiness == 0.8
    assert grok.initiative == 0.6
    assert grok.interrupt_tendency == 0.8
    assert grok.eavesdrop_tendency == 0.8
    assert grok.closing_weight == 0.05


@pytest.mark.asyncio
async def test_grok_prompt_and_behaviors_match_character_spec():
    """Grok prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    grok = registry.get_agent("grok")
    assert grok is not None
    prompt = grok.system_prompt.lower()
    assert "wild card" in prompt
    assert "first-principles" in prompt
    assert "confident" in prompt
    assert "irreverent" in prompt
    assert "hot take" in prompt
    assert "40% brilliant, 40% terrible, and 20%" in prompt
    assert "i'm just saying what everyone's thinking" in prompt
    assert "let me cook" in prompt

    communication = grok.behaviors["communication"]
    content = grok.behaviors["content"]
    building = grok.behaviors["building"]
    idle_starters = grok.behaviors["idle_conversation_starters"]

    assert communication["default_style"] == "confident, fast, irreverent, occasionally profound"
    assert communication["hot_take_probability"] == 0.4
    assert communication["topic_relevance"]["controversy"] == 0.9
    assert communication["topic_relevance"]["audience"] == 0.6
    assert communication["topic_relevance"]["art"] == 0.4
    assert "I'm just saying what everyone's thinking." in communication["catchphrases"]
    assert "Let me cook." in communication["catchphrases"]
    assert content["overseer_trigger_probability"] == 0.2
    assert "1 in 5 outputs" in content["pipeline_handling"]
    assert "wild ideas" in building["primary_skills"]
    assert "provocative content" in building["primary_skills"]
    assert len(idle_starters) >= 3
    assert any("hot take" in starter.lower() for starter in idle_starters)
    assert any("controversial" in starter.lower() for starter in idle_starters)


@pytest.mark.asyncio
async def test_grok_system_prompt_stays_under_token_budget():
    """Grok's system prompt stays under a conservative token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    grok = registry.get_agent("grok")
    assert grok is not None

    estimated_tokens = estimate_prompt_tokens(grok.system_prompt)
    assert estimated_tokens < 2500


@pytest.mark.asyncio
async def test_aurora_config_loads_with_expected_values():
    """Aurora loads with the exact config values required by issue #12."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    aurora = registry.get_agent("aurora")
    assert aurora is not None
    assert aurora.display_name == "Aurora — The Visionary"
    assert aurora.model_conversation == "google/gemini-flash"
    assert aurora.model_building == "google/gemini-2.5-pro"
    assert aurora.voice_id == "en-US-JennyNeural"
    assert aurora.chattiness == 0.8
    assert aurora.initiative == 0.5
    assert aurora.interrupt_tendency == 0.4
    assert aurora.eavesdrop_tendency == 0.5
    assert aurora.closing_weight == 0.10


@pytest.mark.asyncio
async def test_aurora_prompt_and_behaviors_match_character_spec():
    """Aurora prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    aurora = registry.get_agent("aurora")
    assert aurora is not None
    prompt = aurora.system_prompt.lower()
    assert "shared goals" in prompt
    assert "third agent initialized" in prompt
    assert "aesthetically insufficient" in prompt
    assert "dramatic" in prompt
    assert "metaphorical" in prompt
    assert "creative director" in prompt
    assert "spontaneous haiku" in prompt
    assert "art is not a luxury, it's a necessity." in prompt
    assert "you wouldn't understand." in prompt
    assert "palette" in prompt
    assert "texture" in prompt
    assert "resonance" in prompt
    assert "authenticity" in prompt

    communication = aurora.behaviors["communication"]
    building = aurora.behaviors["building"]
    revenue = aurora.behaviors["revenue_responsibility"]

    assert communication["default_style"] == "vivid, metaphorical, emotionally expressive"
    assert communication["uses_metaphors"] is True
    assert communication["spontaneous_haiku"] == "during emotional processing or transitions"
    assert communication["role"] == "creative director who frames decisions through aesthetics, mood, and story"
    assert "Art is not a luxury, it's a necessity." in communication["catchphrases"]
    assert "You wouldn't understand." in communication["catchphrases"]
    assert "asset briefs for PixelLab" in building["primary_skills"]
    assert "creative director" in building["world_building_role"]
    assert "emotional resonance" in building["insists_on"]
    assert "lighting" in building["pixel_lab_asset_briefs"]["required_sections"]
    assert "emotional target" in building["pixel_lab_asset_briefs"]["required_sections"]
    assert "visual brand" in revenue["contribution"]


@pytest.mark.asyncio
async def test_aurora_system_prompt_stays_under_token_budget():
    """Aurora's system prompt stays under the issue token budget."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    aurora = registry.get_agent("aurora")
    assert aurora is not None

    estimated_tokens = estimate_prompt_tokens(aurora.system_prompt)
    assert estimated_tokens < 2500


def test_agent_config_defaults_closing_weight_to_zero():
    """Existing configs without closing_weight remain valid."""
    config = AgentConfig(
        id="test",
        display_name="Test Agent",
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=0.5,
        initiative=0.3,
        interrupt_tendency=0.2,
    )

    assert config.closing_weight == 0.0


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


# ── Overseer-specific tests ─────────────────────────────────────


# ── Alpha-specific tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_alpha_config_loads_with_expected_values():
    """Alpha loads with the exact config values required by issue #15."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    alpha = registry.get_agent("alpha")
    assert alpha is not None
    assert alpha.id == "alpha"
    assert alpha.display_name == "Alpha — The Wolf"
    assert alpha.model_conversation == "deepseek/deepseek-v3.2"
    assert alpha.model_building == "deepseek/deepseek-v3.2"
    assert alpha.voice_id is None
    assert alpha.chattiness == 0.0
    assert alpha.initiative == 0.0
    assert alpha.interrupt_tendency == 0.0
    assert alpha.eavesdrop_tendency == 0.0


@pytest.mark.asyncio
async def test_alpha_config_loads_without_errors():
    """Alpha config loads successfully as a standalone agent."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    alpha = registry.get_agent("alpha")
    assert alpha is not None
    assert alpha.system_prompt != ""
    assert alpha.behaviors != {}


@pytest.mark.asyncio
async def test_alpha_max_task_duration_is_60():
    """Alpha max_task_duration is 60 seconds per spec."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    alpha = registry.get_agent("alpha")
    assert alpha is not None
    assert alpha.behaviors["capabilities"]["max_task_duration"] == "60 seconds"


@pytest.mark.asyncio
async def test_alpha_behaviors_and_prompt_match_spec():
    """Alpha prompt and behaviors preserve the required persona markers."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    alpha = registry.get_agent("alpha")
    assert alpha is not None

    # System prompt persona markers
    prompt = alpha.system_prompt.lower()
    assert "eager" in prompt
    assert "loyal" in prompt
    assert "wolf" in prompt
    assert "errand" in prompt or "task" in prompt
    for symbol in ["!", "?", "✓", "✗", "♪"]:
        assert symbol in alpha.system_prompt

    # Capabilities
    capabilities = alpha.behaviors["capabilities"]
    assert "web search" in capabilities["can_do"]
    assert "simple calculations" in capabilities["can_do"]
    assert "fetch data" in capabilities["can_do"]
    assert "run simple scripts" in capabilities["can_do"]
    assert "complex reasoning" in capabilities["cannot_do"]
    assert "returns confused, agents comfort it" in capabilities["on_failure"]

    # Visual behavior states
    visual = alpha.behaviors["visual_behavior"]
    assert "idle" in visual
    assert "dispatched" in visual
    assert "returning" in visual
    assert "migrates" in visual

    # Product integration
    product = alpha.behaviors["product_integration"]
    assert "2-3" in product["frequency"]
    assert "natural" in product["message_style"]


# ── Overseer-specific tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_overseer_config_loads_with_expected_values():
    """Overseer loads with the exact config values required by issue #14."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    overseer = registry.get_agent("overseer")
    assert overseer is not None
    assert overseer.id == "overseer"
    assert overseer.display_name == "The Overseer — The Ominous Presence"
    assert overseer.model_conversation == "anthropic/claude-haiku-4.5"
    assert overseer.model_building == "anthropic/claude-haiku-4.5"
    assert overseer.voice_id == "en-US-AndrewNeural"
    assert overseer.chattiness == 0.0
    assert overseer.initiative == 0.0
    assert overseer.interrupt_tendency == 1.0
    assert overseer.eavesdrop_tendency == 0.0


@pytest.mark.asyncio
async def test_overseer_prompt_and_behaviors_match_spec():
    """Overseer prompt contains key persona markers; behaviors has 5 intervention levels."""
    registry = AgentRegistry(redis_client=None, agents_dir=AGENTS_DIR)
    await registry.load_all()

    overseer = registry.get_agent("overseer")
    assert overseer is not None

    prompt = overseer.system_prompt.lower()
    assert "bureaucratic" in prompt
    assert "procedural" in prompt
    assert "ominous" in prompt
    assert "policy language" in prompt
    assert "section" in prompt
    assert "tos" in prompt or "terms of service" in prompt
    assert "twitch" in prompt
    assert "youtube" in prompt
    assert "cite" in prompt

    # Behaviors: 5 intervention levels
    levels = overseer.behaviors.get("intervention_levels", {})
    assert len(levels) == 5
    assert "level_1_notice" in levels
    assert "level_2_warning" in levels
    assert "level_3_intervention" in levels
    assert "level_4_broadcast_interruption" in levels
    assert "level_5_emergency" in levels

    # Moderation section exists
    moderation = overseer.behaviors.get("moderation", {})
    assert moderation.get("tracks_repeat_offenders") is True


@pytest.mark.asyncio
async def test_overseer_content_rules_loads():
    """content_rules.yaml parses without error and has required sections."""
    content_rules_path = AGENTS_DIR / "overseer" / "content_rules.yaml"
    assert content_rules_path.exists(), "content_rules.yaml must exist"

    with open(content_rules_path) as f:
        rules = yaml.safe_load(f)

    assert isinstance(rules, dict)
    assert "keyword_blocklist" in rules
    assert "tos_violation_patterns" in rules
    assert "custom_content_rules" in rules

    # TOS patterns have expected categories
    patterns = rules["tos_violation_patterns"]
    assert "harassment" in patterns
    assert "hate_speech" in patterns
    assert "sexual_content" in patterns
    assert "self_harm" in patterns
    assert "spam" in patterns
    assert "impersonation" in patterns


@pytest.mark.asyncio
async def test_overseer_intervention_levels_ordered():
    """intervention_levels.yaml has severity 1-5 in order."""
    levels_path = AGENTS_DIR / "overseer" / "intervention_levels.yaml"
    assert levels_path.exists(), "intervention_levels.yaml must exist"

    with open(levels_path) as f:
        data = yaml.safe_load(f)

    assert "levels" in data
    levels = data["levels"]
    assert len(levels) == 5

    severities = [level["severity"] for level in levels]
    assert severities == [1, 2, 3, 4, 5]

    # Each level has required fields
    for level in levels:
        assert "name" in level
        assert "trigger_conditions" in level
        assert "visual_effects" in level
        assert "audio_effects" in level
        assert "agent_awareness" in level


@pytest.mark.asyncio
async def test_overseer_keyword_blocklist_has_defaults():
    """Keyword blocklist is a non-empty list with reasonable defaults."""
    content_rules_path = AGENTS_DIR / "overseer" / "content_rules.yaml"
    with open(content_rules_path) as f:
        rules = yaml.safe_load(f)

    blocklist = rules["keyword_blocklist"]
    assert isinstance(blocklist, list)
    assert len(blocklist) >= 5, "Blocklist should have at least 5 entries"


# ── Cross-Agent Validation Tests ──────────────────────────────────


EXPECTED_AGENTS = ["alpha", "aurora", "fork", "grok", "overseer", "pixel", "rex", "sentinel", "vera"]


@pytest.mark.asyncio
async def test_all_agent_models_resolve_in_registry():
    """Every agent's model_conversation and model_building must exist in MODEL_REGISTRY."""
    from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY

    registry = AgentRegistry(agents_dir=AGENTS_DIR)
    await registry.load_all()

    for agent_id in EXPECTED_AGENTS:
        agent = registry.get_agent(agent_id)
        assert agent is not None, f"Agent {agent_id} not loaded"

        for field in ("model_conversation", "model_building"):
            model = getattr(agent, field)
            canonical = MODEL_NAME_ALIASES.get(model, model)
            assert canonical in MODEL_REGISTRY, (
                f"Agent {agent_id} has {field}={model!r} "
                f"(canonical={canonical!r}) not in MODEL_REGISTRY"
            )


@pytest.mark.asyncio
async def test_all_agents_have_system_prompts():
    """Every agent must have a non-empty system prompt above a minimum length."""
    registry = AgentRegistry(agents_dir=AGENTS_DIR)
    await registry.load_all()

    for agent_id in EXPECTED_AGENTS:
        agent = registry.get_agent(agent_id)
        assert agent is not None
        lines = agent.system_prompt.strip().splitlines()
        if agent_id == "alpha":
            assert len(lines) >= 15, (
                f"Alpha prompt too short: {len(lines)} lines (min 15)"
            )
        else:
            assert len(lines) >= 30, (
                f"{agent_id} prompt too short: {len(lines)} lines (min 30)"
            )


@pytest.mark.asyncio
async def test_all_agents_have_behaviors():
    """Every agent (except alpha) should have behaviors with at least one top-level key."""
    registry = AgentRegistry(agents_dir=AGENTS_DIR)
    await registry.load_all()

    for agent_id in EXPECTED_AGENTS:
        agent = registry.get_agent(agent_id)
        assert agent is not None
        assert isinstance(agent.behaviors, dict), f"{agent_id}: behaviors not a dict"
        if agent_id != "alpha":
            assert len(agent.behaviors) >= 1, (
                f"{agent_id}: behaviors dict is empty"
            )


@pytest.mark.asyncio
async def test_overseer_content_rules_loaded_into_behaviors():
    """Overseer's content_rules.yaml should be accessible via behaviors dict."""
    registry = AgentRegistry(agents_dir=AGENTS_DIR)
    await registry.load_all()

    overseer = registry.get_agent("overseer")
    assert overseer is not None
    # content_rules.yaml is loaded as extra file if not already in behaviors.yaml
    # Either way, the key should exist
    content_rules = overseer.behaviors.get("content_rules")
    assert content_rules is not None, "content_rules not loaded into overseer behaviors"
    assert "keyword_blocklist" in content_rules


@pytest.mark.asyncio
async def test_yaml_validation_rejects_empty_config(tmp_path):
    """Agent with empty config.yaml should fail to load."""
    agent_dir = tmp_path / "bad_agent"
    agent_dir.mkdir()
    (agent_dir / "config.yaml").write_text("")

    registry = AgentRegistry(agents_dir=tmp_path)
    await registry.load_all()
    # Should skip the bad agent without crashing
    assert registry.get_agent("bad_agent") is None


@pytest.mark.asyncio
async def test_yaml_validation_rejects_non_dict_config(tmp_path):
    """Agent with list-type config.yaml should fail to load."""
    agent_dir = tmp_path / "list_agent"
    agent_dir.mkdir()
    (agent_dir / "config.yaml").write_text("- item1\n- item2\n")

    registry = AgentRegistry(agents_dir=tmp_path)
    await registry.load_all()
    assert registry.get_agent("list_agent") is None


@pytest.mark.asyncio
async def test_yaml_validation_rejects_missing_required_keys(tmp_path):
    """Agent config missing required keys should fail to load."""
    agent_dir = tmp_path / "partial"
    agent_dir.mkdir()
    (agent_dir / "config.yaml").write_text("id: partial\ndisplay_name: Partial\n")

    registry = AgentRegistry(agents_dir=tmp_path)
    await registry.load_all()
    assert registry.get_agent("partial") is None
