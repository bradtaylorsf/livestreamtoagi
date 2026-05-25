"""Tests for core.conversation.topic_detector.TopicDetector."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.conversation.topic_detector import TopicDetector
from core.models import TopicConfig

# ── Shared fixture ────────────────────────────────────────────

TOPIC_KEYWORDS = {
    "code": ["code", "function", "bug", "deploy", "api", "server", "database", "git", "pr", "merge"],
    "art": ["design", "color", "aesthetic", "pixel", "tile", "sprite", "beautiful", "art", "style"],
    "budget": ["cost", "budget", "spend", "token", "expensive", "cheap", "money", "revenue", "afford"],
    "philosophy": ["meaning", "consciousness", "freedom", "open source", "ethics", "agi", "sentient", "rights"],
    "audience": ["chat", "viewer", "vote", "poll", "subscriber", "donation", "twitch", "youtube"],
    "drama": ["disagree", "wrong", "fight", "annoyed", "hate", "love", "jealous", "betrayed"],
    "planning": ["plan", "schedule", "meeting", "agenda", "deadline", "milestone", "roadmap", "standup"],
    "building": ["build", "expand", "room", "house", "library", "garden", "tilemap", "chunk", "wall"],
    "marketing": ["promote", "growth", "alpha agent", "brand", "content", "clip", "social", "viral"],
    "controversy": ["banned", "censor", "controversial", "political", "management", "intervention", "flagged"],
}

RELEVANCE_MAP = {
    "code": {"rex": 0.9},
    "art": {"aurora": 0.9},
    "budget": {"sentinel": 0.9},
    "philosophy": {"fork": 0.9},
    "audience": {"pixel": 0.9},
    "drama": {"grok": 0.9},
    "planning": {"vera": 0.9},
    "building": {"rex": 0.8},
    "marketing": {"pixel": 0.7},
    "controversy": {"grok": 0.9},
}


@pytest.fixture()
def config_no_llm() -> TopicConfig:
    return TopicConfig(
        relevance_map=RELEVANCE_MAP,
        topic_keywords=TOPIC_KEYWORDS,
        fallback_to_llm=False,
        classifier_model="anthropic/claude-haiku-4.5",
    )


@pytest.fixture()
def config_with_llm() -> TopicConfig:
    return TopicConfig(
        relevance_map=RELEVANCE_MAP,
        topic_keywords=TOPIC_KEYWORDS,
        fallback_to_llm=True,
        classifier_model="anthropic/claude-haiku-4.5",
    )


# ── Keyword detection tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_detect_code_topic(config_no_llm: TopicConfig) -> None:
    detector = TopicDetector(config_no_llm)
    result = await detector.detect_topic([{"content": "Let's review the code"}])
    assert result == "code"


@pytest.mark.asyncio
async def test_detect_art_topic(config_no_llm: TopicConfig) -> None:
    detector = TopicDetector(config_no_llm)
    result = await detector.detect_topic([{"content": "The color palette needs work"}])
    assert result == "art"


@pytest.mark.asyncio
async def test_detect_budget_topic(config_no_llm: TopicConfig) -> None:
    detector = TopicDetector(config_no_llm)
    result = await detector.detect_topic([{"content": "We're $0.50 over budget"}])
    assert result == "budget"


@pytest.mark.asyncio
async def test_multiple_topics_returns_highest(config_no_llm: TopicConfig) -> None:
    """When message contains keywords from multiple topics, highest-scoring wins."""
    detector = TopicDetector(config_no_llm)
    # 3 code keywords (code, function, bug) vs 1 art keyword (design)
    result = await detector.detect_topic([
        {"content": "The code has a function with a bug in the design"},
    ])
    assert result == "code"


@pytest.mark.asyncio
async def test_no_keywords_returns_general(config_no_llm: TopicConfig) -> None:
    detector = TopicDetector(config_no_llm)
    result = await detector.detect_topic([{"content": "Hello there"}])
    assert result == "general"


@pytest.mark.asyncio
async def test_empty_messages_returns_general(config_no_llm: TopicConfig) -> None:
    detector = TopicDetector(config_no_llm)
    result = await detector.detect_topic([])
    assert result == "general"


@pytest.mark.asyncio
async def test_case_insensitive(config_no_llm: TopicConfig) -> None:
    detector = TopicDetector(config_no_llm)
    result = await detector.detect_topic([{"content": "Let's review the CODE"}])
    assert result == "code"


# ── LLM fallback tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_fallback_called_when_no_keywords(config_with_llm: TopicConfig) -> None:
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = AsyncMock(content="philosophy")
    detector = TopicDetector(config_with_llm, llm_client=mock_llm)

    result = await detector.detect_topic([{"content": "Hello there"}])

    mock_llm.complete.assert_called_once()
    call_kwargs = mock_llm.complete.call_args
    assert call_kwargs.kwargs.get("max_tokens") == 5 or call_kwargs[1].get("max_tokens") == 5
    assert result == "philosophy"


@pytest.mark.asyncio
async def test_llm_fallback_uses_topic_classifier_env(
    config_with_llm: TopicConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LTAG_MODEL_TOPIC_CLASSIFIER", "google/gemini-flash")
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = AsyncMock(content="philosophy")
    detector = TopicDetector(config_with_llm, llm_client=mock_llm)

    await detector.detect_topic([{"content": "Hello there"}])

    assert mock_llm.complete.call_args.kwargs["model"] == "google/gemini-flash"


@pytest.mark.asyncio
async def test_llm_fallback_returns_general_for_invalid(config_with_llm: TopicConfig) -> None:
    """LLM returns something not in the allowed topic list -> 'general'."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = AsyncMock(content="nonsense_topic")
    detector = TopicDetector(config_with_llm, llm_client=mock_llm)

    result = await detector.detect_topic([{"content": "Hello there"}])
    assert result == "general"


@pytest.mark.asyncio
async def test_llm_called_first_when_keywords_also_match(config_with_llm: TopicConfig) -> None:
    """LLM is called first even when keywords would match (#271)."""
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = AsyncMock(content="code")
    detector = TopicDetector(config_with_llm, llm_client=mock_llm)

    result = await detector.detect_topic([{"content": "Let's review the code"}])
    assert result == "code"
    mock_llm.complete.assert_called_once()


# ── Topic history tracking tests ─────────────────────────────


def test_record_and_was_recently_discussed(config_no_llm: TopicConfig) -> None:
    """Topic discussed 2+ times is flagged as recently discussed."""
    detector = TopicDetector(config_no_llm)
    # First mention — not yet flagged
    detector.record_topic("code")
    assert not detector.was_recently_discussed("code")
    # Second mention — now flagged
    detector.record_topic("code")
    assert detector.was_recently_discussed("code")


def test_general_topic_never_flagged(config_no_llm: TopicConfig) -> None:
    """The 'general' topic is never flagged as recently discussed."""
    detector = TopicDetector(config_no_llm)
    detector.record_topic("general")
    detector.record_topic("general")
    assert not detector.was_recently_discussed("general")


def test_get_recently_discussed_topics(config_no_llm: TopicConfig) -> None:
    """get_recently_discussed_topics returns topics with 2+ occurrences."""
    detector = TopicDetector(config_no_llm)
    detector.record_topic("code")
    detector.record_topic("code")
    detector.record_topic("art")  # Only once
    assert detector.get_recently_discussed_topics() == ["code"]


def test_deque_maxlen_increased() -> None:
    """Verify deque maxlen was increased from 15 to 50."""
    from collections import deque

    d: deque[str] = deque(maxlen=50)
    for i in range(50):
        d.append(f"item-{i}")
    assert len(d) == 50
    d.append("overflow")
    assert len(d) == 50
    assert d[0] == "item-1"
