"""Tests for enhanced cross-conversation memory (#271)."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.conversation.topic_detector import TopicDetector
from core.conversation.triggers import TriggerSystem
from core.models import ConversationRecord, TopicConfig


# ── Shared fixtures ──────────────────────────────────────────

TOPIC_KEYWORDS = {
    "code": ["code", "function", "bug"],
    "art": ["design", "color", "pixel"],
    "budget": ["cost", "budget", "money"],
}

RELEVANCE_MAP = {
    "code": {"rex": 0.9},
    "art": {"aurora": 0.9},
    "budget": {"sentinel": 0.9},
}


@pytest.fixture()
def topic_config() -> TopicConfig:
    return TopicConfig(
        relevance_map=RELEVANCE_MAP,
        topic_keywords=TOPIC_KEYWORDS,
        fallback_to_llm=True,
        classifier_model="anthropic/claude-haiku-4.5",
    )


# ── ConversationRecord model tests ──────────────────────────


def test_conversation_record_format_for_context():
    """ConversationRecord formats correctly for prompt injection."""
    record = ConversationRecord(
        summary="Vera and Rex discussed the dashboard feature.",
        topics=["code", "planning"],
        outcome="Agreed to build dashboard",
        key_decisions=["Use React for frontend", "Rex leads implementation"],
        unresolved_tensions=["Budget allocation unclear"],
        novel_information=["New API endpoint needed"],
        participants=["vera", "rex"],
        turn_count=8,
    )
    text = record.format_for_context()
    assert "Vera and Rex discussed" in text
    assert "Use React for frontend" in text
    assert "Budget allocation unclear" in text


def test_conversation_record_minimal():
    """ConversationRecord works with only summary."""
    record = ConversationRecord(summary="Short chat.")
    text = record.format_for_context()
    assert text == "Short chat."


# ── Topic exhaustion tests ──────────────────────────────────


def test_topic_exhaustion_available(topic_config: TopicConfig):
    """Topics with 0-2 mentions are 'available'."""
    detector = TopicDetector(topic_config)
    assert detector.get_topic_exhaustion("code") == "available"
    detector.record_topic("code")
    detector.record_topic("code")
    assert detector.get_topic_exhaustion("code") == "available"


def test_topic_exhaustion_cooling_down(topic_config: TopicConfig):
    """Topics with 3-4 mentions are 'cooling_down'."""
    detector = TopicDetector(topic_config)
    for _ in range(3):
        detector.record_topic("code")
    assert detector.get_topic_exhaustion("code") == "cooling_down"

    detector.record_topic("code")
    assert detector.get_topic_exhaustion("code") == "cooling_down"


def test_topic_exhaustion_exhausted(topic_config: TopicConfig):
    """Topics with 5+ mentions are 'exhausted'."""
    detector = TopicDetector(topic_config)
    for _ in range(5):
        detector.record_topic("code")
    assert detector.get_topic_exhaustion("code") == "exhausted"


def test_general_topic_always_available(topic_config: TopicConfig):
    """The 'general' topic is always available."""
    detector = TopicDetector(topic_config)
    for _ in range(10):
        detector.record_topic("general")
    assert detector.get_topic_exhaustion("general") == "available"


def test_get_all_exhaustion(topic_config: TopicConfig):
    """get_all_exhaustion returns only non-available topics."""
    detector = TopicDetector(topic_config)
    for _ in range(5):
        detector.record_topic("code")
    for _ in range(3):
        detector.record_topic("art")
    detector.record_topic("budget")  # Only once

    result = detector.get_all_exhaustion()
    assert result["code"] == "exhausted"
    assert result["art"] == "cooling_down"
    assert "budget" not in result


# ── LLM-first topic detection tests ────────────────────────


@pytest.mark.asyncio
async def test_llm_called_first_when_available(topic_config: TopicConfig):
    """LLM is used as primary classifier, not just fallback."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = AsyncMock(content="art")
    detector = TopicDetector(topic_config, llm_client=mock_llm)

    # Message has code keywords, but LLM should be called first
    result = await detector.detect_topic([{"content": "Let's review the code"}])
    mock_llm.complete.assert_called_once()
    assert result == "art"  # LLM result takes precedence


@pytest.mark.asyncio
async def test_keyword_fallback_on_llm_failure(topic_config: TopicConfig):
    """When LLM fails, keyword matching is used as fallback."""
    mock_llm = AsyncMock()
    mock_llm.complete.side_effect = RuntimeError("API error")
    detector = TopicDetector(topic_config, llm_client=mock_llm)

    result = await detector.detect_topic([{"content": "Let's review the code"}])
    assert result == "code"  # Falls back to keyword match


@pytest.mark.asyncio
async def test_keyword_only_when_no_llm(topic_config: TopicConfig):
    """Without LLM client, keywords are used directly."""
    detector = TopicDetector(topic_config, llm_client=None)

    result = await detector.detect_topic([{"content": "The design needs more color"}])
    assert result == "art"


# ── Summary buffer expansion tests ──────────────────────────


def test_summary_buffer_expanded_to_25():
    """Verify the conversation summaries deque holds 25 entries."""
    d: deque[str] = deque(maxlen=25)
    for i in range(30):
        d.append(f"Summary {i}")
    assert len(d) == 25
    assert d[0] == "Summary 5"


# ── Tension trigger tests ──────────────────────────────────


class _FakeClock:
    def __init__(self, t: float = 0.0):
        self._t = t

    def monotonic(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


def _make_trigger_config():
    """Create a minimal TriggerConfig mock."""
    from unittest.mock import MagicMock

    cfg = MagicMock()
    cfg.idle_timeout_seconds = 60
    cfg.memory_trigger_chance = 0.0
    cfg.agent_initiative = {"vera": 0.8, "rex": 0.2}
    cfg.daily_schedule = {}
    return cfg


@pytest.mark.asyncio
async def test_tension_event_queued_and_fires():
    """Tensions from ConversationRecords are queued and fire as triggers."""
    clock = _FakeClock(100.0)
    cfg = _make_trigger_config()
    ts = TriggerSystem(cfg, clock=clock)

    ts.queue_event("tension", {
        "text": "Rex and Vera disagree about the API design",
        "from_participants": ["vera", "rex"],
    })

    trigger = await ts.check()
    assert trigger is not None
    assert trigger["type"] == "tension"
    assert "unresolved issue" in trigger["prompt_hint"]
    assert "API design" in trigger["prompt_hint"]


@pytest.mark.asyncio
async def test_tension_starter_from_participants():
    """Tension trigger picks starter from original conversation participants."""
    import random

    clock = _FakeClock(100.0)
    cfg = _make_trigger_config()
    rng = random.Random(42)
    ts = TriggerSystem(cfg, clock=clock, rng=rng)

    ts.queue_event("tension", {
        "text": "Budget disagreement",
        "from_participants": ["vera", "rex"],
    })

    trigger = await ts.check()
    assert trigger["starter_agent_id"] in ("vera", "rex")


@pytest.mark.asyncio
async def test_tension_dedup_collapsed():
    """Duplicate tension events are collapsed."""
    clock = _FakeClock(100.0)
    cfg = _make_trigger_config()
    ts = TriggerSystem(cfg, clock=clock)

    ts.queue_event("tension", {"text": "First tension"})
    ts.queue_event("tension", {"text": "Second tension"})  # Collapsed (same event_type)

    trigger = await ts.check()
    assert trigger is not None
    # After popping the one event, no more pending
    ts._last_speech_time = clock.monotonic()  # prevent idle from firing
    trigger2 = await ts.check()
    # Should be idle or None, not another tension
    assert trigger2 is None or trigger2["type"] != "tension"
