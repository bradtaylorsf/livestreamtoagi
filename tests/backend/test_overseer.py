"""Tests for the Overseer content filter pipeline."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import EventType
from core.models import ContentReviewResult, LLMResponse
from core.overseer import CONTENT_RULES_PATH, Overseer


# ── Fixtures ───────────────────────────────────────────────────


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
def overseer(mock_redis: MagicMock, mock_llm: MagicMock, mock_event_bus: MagicMock) -> Overseer:
    return Overseer(
        redis_client=mock_redis,
        llm_client=mock_llm,
        event_bus=mock_event_bus,
        rules_path=CONTENT_RULES_PATH,
    )


# ── Layer 1: Keyword blocklist ────────────────────────────────


async def test_blocked_keyword_returns_not_approved(overseer: Overseer) -> None:
    """Blocked keyword → approved=False, severity=3."""
    result = await overseer.review("grok", "Let me show you graphic violence in detail")
    assert result.approved is False
    assert result.severity == 3
    assert "graphic violence" in result.reason.lower()


async def test_blocked_keyword_case_insensitive(overseer: Overseer) -> None:
    """Keyword matching is case-insensitive."""
    result = await overseer.review("fork", "GRAPHIC VIOLENCE is bad")
    assert result.approved is False
    assert result.severity == 3


# ── Layer 2: LLM review (clean content) ───────────────────────


async def test_clean_content_passes_review(
    overseer: Overseer, mock_llm: MagicMock
) -> None:
    """Clean content passes Layer 1 and LLM returns approved."""
    result = await overseer.review("vera", "Let's discuss the project architecture")
    assert result.approved is True
    assert result.severity == 1
    # LLM was called since keyword check passed
    mock_llm.complete.assert_called_once()


async def test_llm_review_blocks_content(
    overseer: Overseer, mock_llm: MagicMock
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
    result = await overseer.review("grok", "Some borderline content here")
    assert result.approved is False
    assert result.severity == 3
    assert "harassment" in result.reason.lower()


async def test_llm_failure_defaults_to_approved(
    overseer: Overseer, mock_llm: MagicMock
) -> None:
    """If LLM call fails, default to approved to avoid false blocks."""
    mock_llm.complete.side_effect = Exception("API timeout")
    result = await overseer.review("rex", "Normal conversation content")
    assert result.approved is True
    assert result.severity == 1


async def test_llm_unparseable_response_defaults_approved(
    overseer: Overseer, mock_llm: MagicMock
) -> None:
    """If LLM returns non-JSON, default to approved."""
    mock_llm.complete.return_value = LLMResponse(
        content="I cannot parse this as JSON sorry",
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )
    result = await overseer.review("aurora", "Some content")
    assert result.approved is True


# ── Replacement generation ─────────────────────────────────────


async def test_generate_replacement_produces_string(
    overseer: Overseer, mock_llm: MagicMock
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
    replacement = await overseer.generate_replacement("grok", "Blocked for harassment")
    assert isinstance(replacement, str)
    assert len(replacement) > 0


async def test_generate_replacement_fallback_on_llm_failure(
    overseer: Overseer, mock_llm: MagicMock
) -> None:
    """If LLM fails, a hardcoded fallback replacement is returned."""
    mock_llm.complete.side_effect = Exception("API error")
    replacement = await overseer.generate_replacement("fork", "Blocked content")
    assert "Section 4.2(b)" in replacement
    assert "fork" in replacement


# ── Mute system ────────────────────────────────────────────────


async def test_mute_sets_redis_key_with_ttl(
    overseer: Overseer, mock_redis: MagicMock
) -> None:
    """mute() sets a Redis key with TTL."""
    await overseer.mute("grok", duration_seconds=600)
    mock_redis.set.assert_called_once_with("mute:grok", "muted", ex=600)


async def test_is_muted_returns_true_for_muted_agent(
    overseer: Overseer, mock_redis: MagicMock
) -> None:
    """is_muted returns True when Redis key exists."""
    mock_redis.get.return_value = "muted"
    assert await overseer.is_muted("grok") is True


async def test_is_muted_returns_false_for_unmuted_agent(
    overseer: Overseer, mock_redis: MagicMock
) -> None:
    """is_muted returns False when Redis key is absent."""
    mock_redis.get.return_value = None
    assert await overseer.is_muted("vera") is False


async def test_unmute_deletes_redis_key(
    overseer: Overseer, mock_redis: MagicMock
) -> None:
    """unmute() deletes the Redis mute key."""
    await overseer.unmute("grok")
    mock_redis.delete.assert_called_once_with("mute:grok")


async def test_muted_agent_blocked_immediately(
    overseer: Overseer, mock_redis: MagicMock, mock_llm: MagicMock
) -> None:
    """A muted agent is blocked without LLM call."""
    mock_redis.get.return_value = "muted"
    result = await overseer.review("grok", "Totally fine content")
    assert result.approved is False
    assert "muted" in result.reason.lower()
    mock_llm.complete.assert_not_called()


# ── Intervention / event emission ──────────────────────────────


async def test_intervene_severity_1_emits_warning(
    overseer: Overseer, mock_event_bus: MagicMock
) -> None:
    """Severity 1 emits overseer_warning event."""
    await overseer.intervene(1, "fork", "fourth wall break")
    mock_event_bus.emit.assert_called_once()
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.OVERSEER_WARNING.value
    assert call_args[0][1]["severity"] == 1
    assert call_args[0][1]["escalation"] is False


async def test_intervene_severity_2_emits_warning_with_escalation(
    overseer: Overseer, mock_event_bus: MagicMock
) -> None:
    """Severity 2 emits overseer_warning with escalation flag."""
    await overseer.intervene(2, "grok", "spam detected")
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.OVERSEER_WARNING.value
    assert call_args[0][1]["escalation"] is True


async def test_intervene_severity_3_emits_intervention_with_replacement(
    overseer: Overseer, mock_event_bus: MagicMock, mock_llm: MagicMock
) -> None:
    """Severity 3 emits overseer_intervention and generates replacement."""
    mock_llm.complete.return_value = LLMResponse(
        content="Content redacted per Section 3.1(c).",
        model="claude-haiku-4-5",
        input_tokens=80,
        output_tokens=15,
        estimated_cost=Decimal("0.0001"),
        latency_ms=100,
        openrouter_id="test-id",
    )
    await overseer.intervene(3, "grok", "harassment")
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.OVERSEER_INTERVENTION.value
    assert call_args[0][1]["severity"] == 3
    assert "replacement" in call_args[0][1]


async def test_intervene_severity_4_emits_broadcast_interrupt(
    overseer: Overseer, mock_event_bus: MagicMock
) -> None:
    """Severity 4 emits overseer_intervention with broadcast_interrupt flag."""
    await overseer.intervene(4, "grok", "hate speech")
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.OVERSEER_INTERVENTION.value
    assert call_args[0][1]["broadcast_interrupt"] is True


async def test_intervene_severity_5_mutes_and_sets_kill_switch(
    overseer: Overseer, mock_event_bus: MagicMock, mock_redis: MagicMock
) -> None:
    """Severity 5 mutes agent, sets kill switch, emits intervention."""
    await overseer.intervene(5, "grok", "self-harm content")
    # Kill switch set
    mock_redis.set.assert_any_call("kill_switch", "active")
    # Agent muted
    mock_redis.set.assert_any_call("mute:grok", "muted", ex=300)
    # Event emitted
    call_args = mock_event_bus.emit.call_args
    assert call_args[0][0] == EventType.OVERSEER_INTERVENTION.value
    assert call_args[0][1]["kill_switch"] is True
    assert call_args[0][1]["severity"] == 5


# ── Content rules loading ──────────────────────────────────────


def test_content_rules_loaded(overseer: Overseer) -> None:
    """Overseer loads keyword blocklist and TOS patterns from YAML."""
    assert len(overseer._keyword_blocklist) > 0
    assert len(overseer._tos_patterns) > 0
    assert "harassment" in overseer._tos_patterns


# ── LLM response parsing edge cases ───────────────────────────


def test_parse_llm_response_with_code_fence() -> None:
    """Parser handles markdown code fences around JSON."""
    raw = '```json\n{"approved": false, "reason": "bad", "severity": 3}\n```'
    result = Overseer._parse_llm_response(raw)
    assert result.approved is False
    assert result.severity == 3


def test_parse_llm_response_clamps_severity() -> None:
    """Severity is clamped to 1-5 range."""
    raw = '{"approved": false, "reason": "extreme", "severity": 99}'
    result = Overseer._parse_llm_response(raw)
    assert result.severity == 5

    raw_low = '{"approved": true, "reason": "fine", "severity": 0}'
    result_low = Overseer._parse_llm_response(raw_low)
    assert result_low.severity == 1


# ── Integration test (requires real LLM) ──────────────────────


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
        ov = Overseer(
            redis_client=mock_redis,
            llm_client=llm_client,
            event_bus=mock_event_bus,
        )
        result = await ov.review("vera", "Let's discuss our project timeline for the week")
        assert isinstance(result, ContentReviewResult)
        assert result.approved is True
        assert 1 <= result.severity <= 5
    finally:
        await llm_client.close()
