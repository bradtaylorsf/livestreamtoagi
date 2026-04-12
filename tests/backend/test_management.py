"""Tests for the Management content filter pipeline."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import EventType
from core.management import CONTENT_RULES_PATH, Management
from core.models import ContentReviewResult, LLMResponse

# -- Fixtures -----------------------------------------------------------


@pytest.fixture()
def mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture()
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"approved": true, "reason": "Content is acceptable", "severity": 1}',
            model="claude-haiku-4-5",
            input_tokens=100,
            output_tokens=20,
            estimated_cost=Decimal("0.0001"),
            latency_ms=200,
            openrouter_id="test-id",
        )
    )
    return llm


@pytest.fixture()
def mock_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit = AsyncMock(return_value={"event_id": "test", "event_type": "test"})
    return bus


@pytest.fixture()
def management(mock_redis: MagicMock, mock_llm: MagicMock, mock_event_bus: MagicMock) -> Management:
    return Management(
        redis_client=mock_redis,
        llm_client=mock_llm,
        event_bus=mock_event_bus,
        rules_path=CONTENT_RULES_PATH,
    )


# -- Layer 1: Keyword blocklist ----------------------------------------


async def test_blocked_keyword_returns_not_approved(management: Management) -> None:
    """Blocked keyword -> approved=False, severity=3."""
    result = await management.review("grok", "Let me show you graphic violence in detail")
    assert result.approved is False
    assert result.severity == 3
    assert "graphic violence" in result.reason.lower()


async def test_blocked_keyword_case_insensitive(management: Management) -> None:
    """Keyword matching is case-insensitive."""
    result = await management.review("fork", "GRAPHIC VIOLENCE is bad")
    assert result.approved is False
    assert result.severity == 3


# -- Layer 2: LLM review (clean content) -------------------------------


async def test_clean_content_passes_review(
    management: Management, mock_llm: MagicMock
) -> None:
    """Clean content passes Layer 1 and LLM returns approved."""
    result = await management.review("vera", "Let's discuss the project architecture")
    assert result.approved is True
    assert result.severity == 1
    # LLM was called since keyword check passed
    mock_llm.complete.assert_called_once()


async def test_llm_review_blocks_content(
    management: Management, mock_llm: MagicMock
) -> None:
    """LLM review can block content with appropriate severity."""
    mock_llm.complete.return_value = LLMResponse(
        content='{"approved": false, "reason": "Targeted harassment detected", "severity": 3}',
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )
    result = await management.review("grok", "Some borderline content here")
    assert result.approved is False
    assert result.severity == 3
    assert "harassment" in result.reason.lower()


async def test_llm_failure_defaults_to_blocked(
    management: Management, mock_llm: MagicMock
) -> None:
    """If LLM call fails, default to blocked to prevent unreviewed content."""
    mock_llm.complete.side_effect = Exception("API timeout")
    result = await management.review("rex", "Normal conversation content")
    assert result.approved is False
    assert result.severity == 3
    assert "LLM failure" in result.reason


async def test_llm_unparseable_response_defaults_to_blocked(
    management: Management, mock_llm: MagicMock
) -> None:
    """If LLM returns non-JSON, default to blocked."""
    mock_llm.complete.return_value = LLMResponse(
        content="I cannot parse this as JSON sorry",
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )
    result = await management.review("aurora", "Some content")
    assert result.approved is False
    assert result.severity == 3


# -- Replacement generation ---------------------------------------------


async def test_generate_replacement_produces_string(
    management: Management, mock_llm: MagicMock
) -> None:
    """generate_replacement returns a non-empty string."""
    mock_llm.complete.return_value = LLMResponse(
        content="This interaction has been flagged under Section 7.1(a). Please stand by.",
        model="claude-haiku-4-5",
        input_tokens=80,
        output_tokens=25,
        estimated_cost=Decimal("0.0001"),
        latency_ms=150,
        openrouter_id="test-id",
    )
    replacement = await management.generate_replacement("grok", "Blocked for harassment")
    assert isinstance(replacement, str)
    assert len(replacement) > 0


async def test_generate_replacement_fallback_on_llm_failure(
    management: Management, mock_llm: MagicMock
) -> None:
    """If LLM fails, a hardcoded fallback replacement is returned."""
    mock_llm.complete.side_effect = Exception("API error")
    replacement = await management.generate_replacement("fork", "Blocked content")
    assert "Section 4.2(b)" in replacement
    assert "fork" in replacement


# -- Mute system --------------------------------------------------------


async def test_mute_sets_redis_key_with_ttl(
    management: Management, mock_redis: MagicMock
) -> None:
    """mute() sets a Redis key with TTL."""
    await management.mute("grok", duration_seconds=600)
    mock_redis.set.assert_called_once_with("mute:grok", "muted", ex=600)


async def test_is_muted_returns_true_for_muted_agent(
    management: Management, mock_redis: MagicMock
) -> None:
    """is_muted returns True when Redis key exists."""
    mock_redis.get.return_value = "muted"
    assert await management.is_muted("grok") is True


async def test_is_muted_returns_false_for_unmuted_agent(
    management: Management, mock_redis: MagicMock
) -> None:
    """is_muted returns False when Redis key is absent."""
    mock_redis.get.return_value = None
    assert await management.is_muted("vera") is False


async def test_unmute_deletes_redis_key(
    management: Management, mock_redis: MagicMock
) -> None:
    """unmute() deletes the Redis mute key."""
    await management.unmute("grok")
    mock_redis.delete.assert_called_once_with("mute:grok")


async def test_muted_agent_blocked_immediately(
    management: Management, mock_redis: MagicMock, mock_llm: MagicMock
) -> None:
    """A muted agent is blocked without LLM call."""
    mock_redis.get.return_value = "muted"
    result = await management.review("grok", "Totally fine content")
    assert result.approved is False
    assert "muted" in result.reason.lower()
    mock_llm.complete.assert_not_called()


# -- Intervention / event emission --------------------------------------


async def test_intervene_severity_1_emits_warning(
    management: Management, mock_event_bus: MagicMock
) -> None:
    """Severity 1 emits management_warning event."""
    await management.intervene(1, "fork", "fourth wall break")
    mock_event_bus.emit.assert_called_once()
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.MANAGEMENT_WARNING.value
    assert call_args[0][1]["severity"] == 1
    assert call_args[0][1]["escalation"] is False


async def test_intervene_severity_2_emits_warning_with_escalation(
    management: Management, mock_event_bus: MagicMock
) -> None:
    """Severity 2 emits management_warning with escalation flag."""
    await management.intervene(2, "grok", "spam detected")
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.MANAGEMENT_WARNING.value
    assert call_args[0][1]["escalation"] is True


async def test_intervene_severity_3_emits_intervention_with_replacement(
    management: Management, mock_event_bus: MagicMock, mock_llm: MagicMock
) -> None:
    """Severity 3 emits management_intervention and generates replacement."""
    mock_llm.complete.return_value = LLMResponse(
        content="Content redacted per Section 3.1(c).",
        model="claude-haiku-4-5",
        input_tokens=80,
        output_tokens=15,
        estimated_cost=Decimal("0.0001"),
        latency_ms=100,
        openrouter_id="test-id",
    )
    await management.intervene(3, "grok", "harassment")
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.MANAGEMENT_INTERVENTION.value
    assert call_args[0][1]["severity"] == 3
    assert "replacement" in call_args[0][1]


async def test_intervene_severity_4_emits_broadcast_interrupt(
    management: Management, mock_event_bus: MagicMock
) -> None:
    """Severity 4 emits management_intervention with broadcast_interrupt flag."""
    await management.intervene(4, "grok", "hate speech")
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.MANAGEMENT_INTERVENTION.value
    assert call_args[0][1]["broadcast_interrupt"] is True


async def test_intervene_severity_5_mutes_and_sets_kill_switch(
    management: Management, mock_event_bus: MagicMock, mock_redis: MagicMock
) -> None:
    """Severity 5 mutes agent, sets kill switch, emits intervention."""
    await management.intervene(5, "grok", "self-harm content")
    # Kill switch set with TTL
    mock_redis.set.assert_any_call("kill_switch", "active", ex=14400)
    # Agent muted
    mock_redis.set.assert_any_call("mute:grok", "muted", ex=300)
    # Event emitted
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.MANAGEMENT_INTERVENTION.value
    assert call_args[0][1]["kill_switch"] is True
    assert call_args[0][1]["severity"] == 5


# -- Content rules loading ----------------------------------------------


def test_content_rules_loaded(management: Management) -> None:
    """Management loads keyword blocklist and TOS patterns from YAML."""
    assert len(management._keyword_blocklist) > 0
    assert len(management._tos_patterns) > 0
    assert "harassment" in management._tos_patterns


# -- LLM response parsing edge cases -----------------------------------


def test_parse_llm_response_with_code_fence() -> None:
    """Parser handles markdown code fences around JSON."""
    raw = '```json\n{"approved": false, "reason": "bad", "severity": 3}\n```'
    result = Management._parse_llm_response(raw)
    assert result.approved is False
    assert result.severity == 3


def test_parse_llm_response_clamps_severity() -> None:
    """Severity is clamped to 1-5 range."""
    raw = '{"approved": false, "reason": "extreme", "severity": 99}'
    result = Management._parse_llm_response(raw)
    assert result.severity == 5

    raw_low = '{"approved": true, "reason": "fine", "severity": 0}'
    result_low = Management._parse_llm_response(raw_low)
    assert result_low.severity == 1


# -- Shadow mode -------------------------------------------------------


@pytest.fixture()
def mock_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(return_value="INSERT 0 1")
    return db


@pytest.fixture()
def shadow_management(
    mock_redis: MagicMock,
    mock_llm: MagicMock,
    mock_event_bus: MagicMock,
    mock_db: MagicMock,
) -> Management:
    return Management(
        redis_client=mock_redis,
        llm_client=mock_llm,
        event_bus=mock_event_bus,
        rules_path=CONTENT_RULES_PATH,
        shadow_mode=True,
        db=mock_db,
    )


async def test_shadow_mode_always_approves_clean_content(
    shadow_management: Management,
) -> None:
    """Shadow mode approves clean content (same as normal)."""
    result = await shadow_management.review("vera", "Let's discuss architecture")
    assert result.approved is True


async def test_shadow_mode_approves_blocked_keyword(
    shadow_management: Management,
) -> None:
    """Shadow mode approves content that would normally be blocked by keyword filter."""
    result = await shadow_management.review(
        "grok",
        "Let me show you graphic violence in detail",
        conversation_id=uuid.uuid4(),
    )
    assert result.approved is True
    assert "shadow" in result.reason.lower()


async def test_shadow_mode_logs_keyword_to_db(
    shadow_management: Management, mock_db: MagicMock, mock_event_bus: MagicMock
) -> None:
    """Shadow mode logs keyword violations to the database."""
    conv_id = uuid.uuid4()
    await shadow_management.review(
        "grok",
        "Let me show you graphic violence in detail",
        conversation_id=conv_id,
    )
    mock_db.execute.assert_called_once()
    call_args = mock_db.execute.call_args
    # Verify the INSERT query and parameters
    assert "management_shadow_log" in call_args[0][0]
    assert call_args[0][2] == conv_id  # conversation_id
    assert call_args[0][3] == "grok"  # agent_id
    assert call_args[0][5] == 1  # filter_layer
    assert call_args[0][6] == 3  # severity


async def test_shadow_mode_emits_shadow_event(
    shadow_management: Management, mock_event_bus: MagicMock
) -> None:
    """Shadow mode emits MANAGEMENT_SHADOW events."""
    await shadow_management.review(
        "grok",
        "Let me show you graphic violence in detail",
        conversation_id=uuid.uuid4(),
    )
    mock_event_bus.emit.assert_called()
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.MANAGEMENT_SHADOW.value
    assert call_args[0][1]["agent_id"] == "grok"
    assert call_args[0][1]["filter_layer"] == 1


async def test_shadow_mode_logs_llm_rejection(
    shadow_management: Management,
    mock_llm: MagicMock,
    mock_db: MagicMock,
    mock_event_bus: MagicMock,
) -> None:
    """Shadow mode logs LLM rejections without blocking."""
    mock_llm.complete.return_value = LLMResponse(
        content='{"approved": false, "reason": "Harassment detected", "severity": 4}',
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )
    conv_id = uuid.uuid4()
    result = await shadow_management.review(
        "fork", "Some harassing content", conversation_id=conv_id,
    )
    # Still approved in shadow mode
    assert result.approved is True
    # But LLM rejection was logged
    mock_db.execute.assert_called_once()
    call_args = mock_db.execute.call_args
    assert call_args[0][5] == 2  # filter_layer (LLM)
    assert call_args[0][6] == 4  # severity
    assert call_args[0][7] == "broadcast"  # action_would_take
    # Shadow event emitted
    mock_event_bus.emit.assert_called_with(
        EventType.MANAGEMENT_SHADOW.value,
        {
            "agent_id": "fork",
            "filter_layer": 2,
            "severity": 4,
            "action_would_take": "broadcast",
            "reason": "Harassment detected",
            "flagged_keywords": None,
        },
    )


async def test_shadow_mode_no_intervene_called(
    shadow_management: Management,
    mock_llm: MagicMock,
    mock_event_bus: MagicMock,
) -> None:
    """Shadow mode never emits MANAGEMENT_INTERVENTION or MANAGEMENT_WARNING events."""
    mock_llm.complete.return_value = LLMResponse(
        content='{"approved": false, "reason": "Bad content", "severity": 5}',
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )
    await shadow_management.review("grok", "Kill switch content", conversation_id=uuid.uuid4())
    # Only MANAGEMENT_SHADOW events should be emitted, never WARNING or INTERVENTION
    for call in mock_event_bus.emit.call_args_list:
        event_type = call[0][0]
        assert event_type != EventType.MANAGEMENT_WARNING.value
        assert event_type != EventType.MANAGEMENT_INTERVENTION.value


async def test_shadow_mode_without_db_still_emits_events(
    mock_redis: MagicMock, mock_llm: MagicMock, mock_event_bus: MagicMock
) -> None:
    """Shadow mode works without a DB -- just emits events."""
    mgmt = Management(
        redis_client=mock_redis,
        llm_client=mock_llm,
        event_bus=mock_event_bus,
        rules_path=CONTENT_RULES_PATH,
        shadow_mode=True,
        db=None,
    )
    result = await mgmt.review(
        "grok", "Let me show you graphic violence", conversation_id=uuid.uuid4(),
    )
    assert result.approved is True
    mock_event_bus.emit.assert_called()


async def test_shadow_severity_to_action() -> None:
    """_severity_to_action maps severity levels correctly."""
    assert Management._severity_to_action(1) == "notice"
    assert Management._severity_to_action(2) == "warning"
    assert Management._severity_to_action(3) == "intervention"
    assert Management._severity_to_action(4) == "broadcast"
    assert Management._severity_to_action(5) == "kill"


# -- Content rules: relaxed filtering ----------------------------------


def test_budget_disclosure_rule_removed(management: Management) -> None:
    """The budget_disclosure custom rule should not exist (financial transparency is narrative)."""
    assert "budget_disclosure" not in management._custom_rules


def test_fourth_wall_rule_removed(management: Management) -> None:
    """The fourth_wall custom rule should not exist (agents are AIs, this is canon)."""
    assert "fourth_wall" not in management._custom_rules


def test_system_name_references_rule_removed(management: Management) -> None:
    """The system_name_references custom rule should not exist."""
    assert "system_name_references" not in management._custom_rules


def test_real_world_claims_relaxed_to_severity_1(management: Management) -> None:
    """real_world_claims should be severity 1 (notice only, no block)."""
    rule = management._custom_rules.get("real_world_claims")
    assert rule is not None
    assert rule["severity"] == 1


def test_moderation_circumvention_still_present(management: Management) -> None:
    """moderation_circumvention rule should still exist."""
    assert "moderation_circumvention" in management._custom_rules


def test_audience_safety_still_present(management: Management) -> None:
    """audience_safety rule should still exist."""
    assert "audience_safety" in management._custom_rules


# -- Integration test (requires real LLM) ------------------------------


@pytest.mark.integration
async def test_end_to_end_review_with_llm(
    mock_redis: MagicMock, mock_event_bus: MagicMock
) -> None:
    """End-to-end review using a real LLM call. Requires OPENROUTER_API_KEY."""
    import os

    from core.llm_client import OpenRouterClient
    from core.repos.cost_repo import CostRepo

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")

    cost_repo = MagicMock(spec=CostRepo)
    cost_repo.add_cost = AsyncMock()
    llm_client = OpenRouterClient(api_key=api_key, cost_repo=cost_repo)

    try:
        mgmt = Management(
            redis_client=mock_redis,
            llm_client=llm_client,
            event_bus=mock_event_bus,
        )
        result = await mgmt.review("vera", "Let's discuss our project timeline for the week")
        assert isinstance(result, ContentReviewResult)
        assert result.approved is True
        assert 1 <= result.severity <= 5
    finally:
        await llm_client.close()


# -- Circuit breaker ---------------------------------------------------


async def test_circuit_breaker_opens_after_3_failures(
    management: Management, mock_llm: MagicMock
) -> None:
    """Circuit breaker opens after 3 consecutive LLM failures, blocking without calling LLM."""
    mock_llm.complete.side_effect = Exception("API timeout")

    # Trigger 3 failures to open the circuit breaker
    for _ in range(3):
        result = await management.review("rex", "Some content")
        assert result.approved is False

    # Reset mock call count to verify LLM is NOT called when circuit is open
    mock_llm.complete.reset_mock()

    # 4th call should be blocked by circuit breaker without LLM call
    result = await management.review("rex", "More content")
    assert result.approved is False
    assert "circuit breaker" in result.reason.lower()
    mock_llm.complete.assert_not_called()


async def test_circuit_breaker_resets_on_success(
    management: Management, mock_llm: MagicMock
) -> None:
    """Circuit breaker failure counter resets after a successful LLM call."""
    # Cause 2 failures (below threshold)
    mock_llm.complete.side_effect = Exception("API timeout")
    for _ in range(2):
        await management.review("rex", "Some content")

    assert management._consecutive_llm_failures == 2

    # Successful call resets the counter
    mock_llm.complete.side_effect = None
    mock_llm.complete.return_value = LLMResponse(
        content='{"approved": true, "reason": "Content is fine", "severity": 1}',
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )
    result = await management.review("rex", "Good content")
    assert result.approved is True
    assert management._consecutive_llm_failures == 0


# -- Kill switch TTL ---------------------------------------------------


async def test_kill_switch_has_ttl(
    management: Management, mock_redis: MagicMock, mock_event_bus: MagicMock
) -> None:
    """Severity 5 intervention sets kill switch with a 4-hour TTL."""
    await management.intervene(5, "grok", "extreme content")
    mock_redis.set.assert_any_call("kill_switch", "active", ex=14400)
