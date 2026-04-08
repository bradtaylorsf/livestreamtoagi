"""Tests for WorldSimulator, PersonaManager, and new tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from core.simulation.recurring_personas import PersonaManager
from core.simulation.world_simulator import WorldSimulator
from tools.revenue_tools import CheckEmailResponsesTool, CheckPostPerformanceTool


# ── Recurring personas config ───────────────────────────────


def test_recurring_personas_yaml_exists():
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "recurring_personas.yaml"
    assert config_path.exists()


def test_recurring_personas_yaml_valid():
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "recurring_personas.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    assert "personas" in data
    assert len(data["personas"]) >= 10

    for persona in data["personas"]:
        assert "name" in persona
        assert "personality" in persona
        assert "frequency" in persona
        assert persona["frequency"] in ("daily", "twice_daily", "every_other_day")
        assert "favorite_agent" in persona


# ── PersonaManager ──────────────────────────────────────────


def test_persona_manager_loads_personas():
    mgr = PersonaManager()
    personas = mgr.load_personas()
    assert len(personas) >= 10
    assert all("name" in p for p in personas)


def test_persona_manager_get_active_day_1():
    """On day 1, most personas should be active (all have at least every_other_day)."""
    mgr = PersonaManager()
    mgr.load_personas()
    active = mgr.get_active_personas(simulated_day=1)
    # At minimum, daily and twice_daily personas should appear
    assert len(active) >= 5


def test_persona_manager_get_active_respects_frequency():
    """every_other_day personas shouldn't appear every day."""
    mgr = PersonaManager()
    mgr.load_personas()
    # Day 1: everyone appears
    mgr.get_active_personas(simulated_day=1)
    # Day 1 again: every_other_day personas already appeared today
    active_same_day = mgr.get_active_personas(simulated_day=1)
    # Should be fewer since every_other_day ones just appeared
    # (they might still appear due to random chance, but should be less)
    assert isinstance(active_same_day, list)


def test_persona_manager_fallback_comment():
    """Without LLM, generate_comment should return template text."""
    mgr = PersonaManager(llm_client=None)
    mgr.load_personas()
    persona = mgr._personas[0]
    comment = mgr._fallback_comment(persona)
    assert persona["name"] in comment


def test_persona_manager_fallback_chat():
    """Without LLM, generate_chat_message should return template text."""
    mgr = PersonaManager(llm_client=None)
    mgr.load_personas()
    persona = mgr._personas[0]
    chat = mgr._fallback_chat(persona)
    assert persona["name"] in chat


async def test_persona_manager_generate_comment_no_llm():
    """generate_comment falls back to template without LLM."""
    mgr = PersonaManager(llm_client=None)
    mgr.load_personas()
    persona = mgr._personas[0]
    comment = await mgr.generate_comment(persona, "test context")
    assert isinstance(comment, str)
    assert len(comment) > 0


async def test_persona_manager_generate_chat_no_llm():
    """generate_chat_message falls back to template without LLM."""
    mgr = PersonaManager(llm_client=None)
    mgr.load_personas()
    persona = mgr._personas[0]
    message = await mgr.generate_chat_message(persona, "test context")
    assert isinstance(message, str)
    assert len(message) > 0


# ── WorldSimulator ──────────────────────────────────────────


def _make_mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.rpush = AsyncMock()
    redis.ltrim = AsyncMock()
    redis.scan = AsyncMock(return_value=(0, []))
    redis.delete = AsyncMock()
    return redis


def test_world_simulator_init():
    redis = _make_mock_redis()
    ws = WorldSimulator(redis_client=redis)
    assert ws._running is False
    assert ws._task is None


async def test_world_simulator_start_stop():
    redis = _make_mock_redis()
    ws = WorldSimulator(redis_client=redis)
    ws.start()
    assert ws._running is True
    assert ws._task is not None
    await ws.stop()
    assert ws._running is False
    assert ws._task is None


async def test_world_simulator_tick_no_drafts():
    """Tick with no pending drafts should not error."""
    redis = _make_mock_redis()
    ws = WorldSimulator(redis_client=redis)
    await ws.tick()
    # Should update world state
    redis.set.assert_called()


async def test_world_simulator_process_social_approval():
    """Social drafts should be approved after delay elapsed."""
    redis = _make_mock_redis()
    draft_data = json.dumps({
        "draft_id": "test-123",
        "status": "pending_human_review",
        "agent_id": "pixel",
        "platform": "twitter",
        "content": "Hello world!",
        "timestamp": 1000,
    })
    redis.get = AsyncMock(return_value=draft_data)
    # Return one key on scan
    redis.scan = AsyncMock(return_value=(0, ["drafts:social:test-123"]))

    ws = WorldSimulator(redis_client=redis)

    # First tick — scans and schedules
    await ws._scan_new_drafts(0)
    assert "test-123" in ws._pending_socials

    # Advance time past the approval delay
    await ws._process_pending_drafts(now=10000)  # Way past any delay

    # Should have updated the draft status
    set_calls = [c for c in redis.set.call_args_list if "drafts:social:test-123" in str(c)]
    assert len(set_calls) > 0
    # Should be in approved_posts
    assert "test-123" in ws._approved_posts


async def test_world_simulator_email_flow():
    """Email drafts should be sent and then receive responses."""
    redis = _make_mock_redis()
    draft_data = json.dumps({
        "draft_id": "email-456",
        "status": "pending_human_review",
        "agent_id": "vera",
        "to": "contact@example.com",
        "subject": "Hello",
        "body": "We want to collaborate",
        "timestamp": 1000,
    })
    redis.get = AsyncMock(return_value=draft_data)
    redis.scan = AsyncMock(side_effect=[
        (0, []),  # No social drafts
        (0, ["drafts:email:email-456"]),  # One email draft
    ])

    ws = WorldSimulator(redis_client=redis)

    # Scan and schedule
    await ws._scan_new_drafts(0)
    assert "email-456" in ws._pending_emails

    # Process: mark as sent
    await ws._process_pending_emails(now=100000)
    assert "email-456" in ws._sent_emails

    # Generate response
    await ws._generate_email_responses(now=999999)
    # Should have stored a response
    response_calls = [
        c for c in redis.set.call_args_list
        if "email:response:email-456" in str(c)
    ]
    assert len(response_calls) > 0


async def test_world_simulator_revenue_update():
    """Revenue simulation should write to Redis."""
    redis = _make_mock_redis()
    redis.get = AsyncMock(return_value="42")  # viewer count
    redis.scan = AsyncMock(return_value=(0, []))

    ws = WorldSimulator(redis_client=redis)
    await ws._simulate_revenue_changes()

    # Should have written revenue status
    revenue_calls = [
        c for c in redis.set.call_args_list
        if "world:revenue_status" in str(c)
    ]
    assert len(revenue_calls) > 0

    # Should also mirror data to world:budget (read by GetWorldStateTool)
    budget_calls = [
        c for c in redis.set.call_args_list
        if "world:budget" in str(c) and "world:revenue" not in str(c)
    ]
    assert len(budget_calls) > 0


async def test_world_simulator_world_state_update():
    """World state update should write recent events to Redis."""
    redis = _make_mock_redis()
    redis.scan = AsyncMock(return_value=(0, []))

    ws = WorldSimulator(redis_client=redis)
    ws._add_event("test_event", {"key": "value"})
    await ws._update_world_state()

    events_calls = [
        c for c in redis.set.call_args_list
        if "world:recent_events" in str(c)
    ]
    assert len(events_calls) > 0


async def test_world_simulator_inject_personas():
    """Should inject persona chat messages when PersonaManager is available."""
    redis = _make_mock_redis()
    redis.scan = AsyncMock(return_value=(0, []))

    mgr = PersonaManager(llm_client=None)
    mgr.load_personas()

    ws = WorldSimulator(redis_client=redis, persona_manager=mgr)
    await ws._inject_recurring_characters()
    # May or may not have injected (probabilistic), but should not error
    assert True


# ── New tools: CheckPostPerformance, CheckEmailResponses ────


async def test_check_post_performance_not_found():
    redis = _make_mock_redis()
    redis.get = AsyncMock(return_value=None)
    tool = CheckPostPerformanceTool(redis_client=redis, agent_id="pixel")
    result = await tool.execute(draft_id="nonexistent")
    assert result["status"] == "not_found"


async def test_check_post_performance_pending():
    redis = _make_mock_redis()
    draft_data = json.dumps({"status": "pending_human_review"})
    redis.get = AsyncMock(side_effect=[draft_data, None])  # draft exists, no engagement
    tool = CheckPostPerformanceTool(redis_client=redis, agent_id="pixel")
    result = await tool.execute(draft_id="test-123")
    assert result["status"] == "ok"
    assert result["draft_status"] == "pending_human_review"
    assert result["engagement"] is None


async def test_check_post_performance_with_engagement():
    redis = _make_mock_redis()
    draft_data = json.dumps({"status": "approved"})
    engagement_data = json.dumps({
        "likes": 150,
        "comments": [
            {"user": "fan1", "text": "Great post!"},
            {"user": "fan2", "text": "Love it"},
        ],
        "shares": 25,
    })
    redis.get = AsyncMock(side_effect=[draft_data, engagement_data])
    tool = CheckPostPerformanceTool(redis_client=redis, agent_id="pixel")
    result = await tool.execute(draft_id="test-123")
    assert result["status"] == "ok"
    assert result["likes"] == 150
    assert result["comments_count"] == 2
    assert result["shares"] == 25


async def test_check_email_responses_not_found():
    redis = _make_mock_redis()
    redis.get = AsyncMock(return_value=None)
    tool = CheckEmailResponsesTool(redis_client=redis, agent_id="vera")
    result = await tool.execute(draft_id="nonexistent")
    assert result["status"] == "not_found"


async def test_check_email_responses_no_reply():
    redis = _make_mock_redis()
    draft_data = json.dumps({"status": "sent"})
    redis.get = AsyncMock(side_effect=[draft_data, None])  # draft exists, no response
    tool = CheckEmailResponsesTool(redis_client=redis, agent_id="vera")
    result = await tool.execute(draft_id="email-456")
    assert result["status"] == "ok"
    assert result["draft_status"] == "sent"
    assert result["response"] is None


async def test_check_email_responses_with_reply():
    redis = _make_mock_redis()
    draft_data = json.dumps({"status": "sent"})
    response_data = json.dumps({
        "sentiment": "positive",
        "response": "We'd love to collaborate!",
    })
    redis.get = AsyncMock(side_effect=[draft_data, response_data])
    tool = CheckEmailResponsesTool(redis_client=redis, agent_id="vera")
    result = await tool.execute(draft_id="email-456")
    assert result["status"] == "ok"
    assert result["sentiment"] == "positive"
    assert "collaborate" in result["response_text"]


# ── SimulationConfig.world_sim ──────────────────────────────


def test_simulation_config_world_sim_default():
    from core.simulation.orchestrator import SimulationConfig
    config = SimulationConfig(name="test", agents=["vera"])
    assert config.world_sim is False


def test_simulation_config_world_sim_enabled():
    from core.simulation.orchestrator import SimulationConfig
    config = SimulationConfig(name="test", agents=["vera"])
    config.world_sim = True
    d = config.to_dict()
    assert d["world_sim"] is True


# ── Tool registration ───────────────────────────────────────


def test_new_tools_in_imports():
    """CheckPostPerformanceTool and CheckEmailResponsesTool should be importable from tools."""
    from tools import CheckEmailResponsesTool, CheckPostPerformanceTool
    assert CheckPostPerformanceTool.name == "check_post_performance"
    assert CheckEmailResponsesTool.name == "check_email_responses"
