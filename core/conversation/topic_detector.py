"""Topic detection for conversation messages.

Classifies conversation content into predefined topics using keyword matching,
with optional LLM fallback for ambiguous cases. Tracks topic history to
prevent the same topic from being discussed repeatedly.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from core.llm_client import OpenRouterClient
    from core.models import TopicConfig

logger = logging.getLogger(__name__)

# Default window for topic deduplication (30 minutes)
TOPIC_DEDUP_WINDOW_SECONDS = 1800.0


class TopicDetector:
    """Detects conversation topics via keyword matching with optional LLM fallback."""

    def __init__(
        self,
        config: TopicConfig,
        llm_client: OpenRouterClient | None = None,
        simulation_id: uuid.UUID | None = None,
        topic_history: dict[str, list[float]] | None = None,
    ) -> None:
        self._config = config
        self._llm_client = llm_client
        self._simulation_id = simulation_id
        # Topic history: {topic: [timestamp, ...]}
        self._topic_history: dict[str, list[float]] = topic_history or {}

    @property
    def topic_history(self) -> dict[str, list[float]]:
        """Return the accumulated topic history for cross-conversation persistence."""
        return self._topic_history

    def record_topic(self, topic: str) -> None:
        """Record that a topic was discussed at the current time."""
        now = time.monotonic()
        if topic not in self._topic_history:
            self._topic_history[topic] = []
        self._topic_history[topic].append(now)

    def was_recently_discussed(
        self,
        topic: str,
        window_seconds: float = TOPIC_DEDUP_WINDOW_SECONDS,
    ) -> bool:
        """Check if a topic was discussed within the given time window.

        Returns True if the topic was discussed 2+ times within the window.
        """
        if topic == "general" or topic not in self._topic_history:
            return False
        now = time.monotonic()
        recent = [t for t in self._topic_history[topic] if now - t < window_seconds]
        return len(recent) >= 2

    def get_recently_discussed_topics(
        self,
        window_seconds: float = TOPIC_DEDUP_WINDOW_SECONDS,
    ) -> list[str]:
        """Return topics discussed 2+ times within the window."""
        now = time.monotonic()
        result = []
        for topic, timestamps in self._topic_history.items():
            recent = [t for t in timestamps if now - t < window_seconds]
            if len(recent) >= 2:
                result.append(topic)
        return result

    def get_topic_exhaustion(self, topic: str) -> str:
        """Return exhaustion status for a topic based on recent mention count.

        Returns:
            "available" (0-2 mentions), "cooling_down" (3-4), or "exhausted" (5+).
        """
        if topic == "general" or topic not in self._topic_history:
            return "available"
        now = time.monotonic()
        recent = [t for t in self._topic_history[topic] if now - t < TOPIC_DEDUP_WINDOW_SECONDS]
        count = len(recent)
        if count >= 5:
            return "exhausted"
        if count >= 3:
            return "cooling_down"
        return "available"

    def get_all_exhaustion(self) -> dict[str, str]:
        """Return exhaustion status for all tracked topics."""
        result: dict[str, str] = {}
        for topic in self._topic_history:
            status = self.get_topic_exhaustion(topic)
            if status != "available":
                result[topic] = status
        return result

    async def detect_topic(self, recent_messages: list[dict]) -> str:
        """Classify recent messages into a single topic string.

        When an LLM client is available, uses LLM classification first for
        higher accuracy. Falls back to keyword matching when LLM is unavailable
        or on LLM failure.
        """
        if not recent_messages:
            return "general"

        # LLM-first when available
        if self._llm_client is not None:
            try:
                return await self._llm_classify_topic(recent_messages)
            except Exception:
                logger.warning("LLM topic classification failed, falling back to keywords")

        # Keyword matching fallback
        text = " ".join(m.get("content", "") for m in recent_messages).lower()

        topic_scores: dict[str, int] = {}
        for topic, keywords in self._config.topic_keywords.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                topic_scores[topic] = hits

        if topic_scores:
            return max(topic_scores, key=topic_scores.get)  # type: ignore[arg-type]

        return "general"

    async def _llm_classify_topic(self, messages: list[dict]) -> str:
        """Use a cheap model to classify topic when keywords fail."""
        assert self._llm_client is not None

        allowed = list(self._config.relevance_map.keys())
        prompt = (
            "Classify this conversation snippet into exactly one topic.\n"
            f"Options: {', '.join(allowed)}, general\n"
            "Conversation:\n"
            + "\n".join(
                f"{m.get('agent_id', '?')}: {m.get('content', '')}"
                for m in messages
            )
            + "\n\nTopic (one word):"
        )

        response = await self._llm_client.complete(
            messages=[{"role": "user", "content": prompt}],
            model=self._config.classifier_model,
            max_tokens=5,
            simulation_id=self._simulation_id,
        )
        topic = response.content.strip().lower()
        return topic if topic in allowed else "general"
