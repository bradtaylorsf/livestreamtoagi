"""Topic detection for conversation messages.

Classifies conversation content into predefined topics using keyword matching,
with optional LLM fallback for ambiguous cases.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm_client import OpenRouterClient
    from core.models import TopicConfig

logger = logging.getLogger(__name__)


class TopicDetector:
    """Detects conversation topics via keyword matching with optional LLM fallback."""

    def __init__(
        self,
        config: TopicConfig,
        llm_client: OpenRouterClient | None = None,
        simulation_id: object | None = None,
    ) -> None:
        self._config = config
        self._llm_client = llm_client
        self._simulation_id = simulation_id

    async def detect_topic(self, recent_messages: list[dict]) -> str:
        """Classify recent messages into a single topic string.

        1. Concatenate message contents, lowercase.
        2. Count keyword hits per topic.
        3. Return highest-scoring topic, or fall back to LLM / "general".
        """
        if not recent_messages:
            return "general"

        text = " ".join(m.get("content", "") for m in recent_messages).lower()

        topic_scores: dict[str, int] = {}
        for topic, keywords in self._config.topic_keywords.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                topic_scores[topic] = hits

        if topic_scores:
            return max(topic_scores, key=topic_scores.get)  # type: ignore[arg-type]

        if self._config.fallback_to_llm and self._llm_client is not None:
            return await self._llm_classify_topic(recent_messages)

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
