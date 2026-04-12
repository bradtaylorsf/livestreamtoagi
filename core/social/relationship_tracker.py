"""RelationshipTracker — structured social dynamics between agents.

After each conversation, analyzes sentiment between participants and
updates the agent_relationships table. Also integrates with reflection
to extract relationship updates from core memory changes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.memory.reflection import _parse_json_response

if TYPE_CHECKING:
    import uuid

    from core.llm_client import OpenRouterClient
    from core.repos.relationship_repo import RelationshipRepo
    from core.simulation.clock import SimulationClock

logger = logging.getLogger(__name__)

SENTIMENT_EXTRACTION_PROMPT = """\
Analyze this conversation and rate how each participant feels about every other participant.

Conversation:
{conversation_text}

Participants: {participants}

Respond with valid JSON only:
{{
  "relationships": [
    {{
      "from": "<agent_id>",
      "to": "<agent_id>",
      "sentiment": <float -1.0 to 1.0>,
      "trust": <float 0.0 to 1.0>,
      "summary": "<one-line description of how 'from' views 'to' based on this conversation>"
    }}
  ]
}}

Sentiment scale: -1.0 (hostile) to 1.0 (close ally). Trust: 0.0 (no trust) to 1.0 (full trust).
Only include pairs where there's enough signal to judge. Be conservative — default to 0.0/0.5 \
if unsure.
"""


class RelationshipTracker:
    """Tracks and updates structured relationships between agents."""

    def __init__(
        self,
        *,
        llm_client: OpenRouterClient,
        relationship_repo: RelationshipRepo,
        simulation_id: uuid.UUID,
        clock: SimulationClock | None = None,
        sentiment_model: str = "anthropic/claude-haiku-4.5",
    ) -> None:
        self._llm = llm_client
        self._repo = relationship_repo
        self._simulation_id = simulation_id
        self._clock = clock
        self._sentiment_model = sentiment_model

    async def update_after_conversation(
        self,
        conversation_history: list[dict[str, str]],
        participants: list[str],
    ) -> None:
        """Update relationships after a conversation completes.

        Increments interaction counts for all participant pairs and
        extracts sentiment via a lightweight LLM call.
        """
        if len(participants) < 2:
            return

        now = self._clock.now() if self._clock else None

        # Increment interaction counts for all pairs
        for i, agent_a in enumerate(participants):
            for agent_b in participants[i + 1 :]:
                try:
                    await self._repo.increment_interaction(
                        self._simulation_id,
                        agent_a,
                        agent_b,
                        interaction_at=now,
                    )
                    await self._repo.increment_interaction(
                        self._simulation_id,
                        agent_b,
                        agent_a,
                        interaction_at=now,
                    )
                except Exception:
                    logger.warning(
                        "Failed to increment interaction count for %s <-> %s",
                        agent_a, agent_b,
                        exc_info=True,
                    )

        # Extract sentiment via LLM
        try:
            await self._extract_and_update_sentiment(
                conversation_history,
                participants,
                now,
            )
        except Exception:
            logger.warning(
                "Sentiment extraction failed for conversation with %s",
                participants,
                exc_info=True,
            )

    async def _extract_and_update_sentiment(
        self,
        conversation_history: list[dict[str, str]],
        participants: list[str],
        timestamp: Any,
    ) -> None:
        """Use LLM to extract sentiment scores from conversation text."""
        conversation_text = "\n".join(
            f"[{msg.get('speaker', 'unknown')}]: {msg.get('content', '')}"
            for msg in conversation_history
        )

        # Limit to last ~20 turns to keep prompt short
        lines = conversation_text.split("\n")
        if len(lines) > 20:
            conversation_text = "\n".join(lines[-20:])

        prompt = SENTIMENT_EXTRACTION_PROMPT.format(
            conversation_text=conversation_text,
            participants=", ".join(participants),
        )

        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Analyze the conversation now."},
            ],
            model=self._sentiment_model,
            agent_id="system",
            temperature=0.2,
            max_tokens=500,
            simulation_id=self._simulation_id,
        )

        analysis = _parse_json_response(response.content)
        relationships = analysis.get("relationships", [])

        ts_str = timestamp.isoformat() if timestamp else "unknown"

        for rel in relationships:
            from_id = rel.get("from", "")
            to_id = rel.get("to", "")
            if from_id not in participants or to_id not in participants:
                continue
            if from_id == to_id:
                continue

            try:
                sentiment = max(-1.0, min(1.0, float(rel.get("sentiment") or 0.0)))
                trust = max(0.0, min(1.0, float(rel.get("trust") or 0.5)))
                summary = rel.get("summary", "")

                # Get existing scores for evolution log
                existing = await self._repo.get(
                    self._simulation_id,
                    from_id,
                    to_id,
                )
                old_sentiment = (
                    float(existing.sentiment_score) if existing and existing.sentiment_score else None
                )
                old_trust = float(existing.trust_score) if existing and existing.trust_score else None

                await self._repo.upsert(
                    self._simulation_id,
                    from_id,
                    to_id,
                    sentiment_score=sentiment,
                    trust_score=trust,
                    relationship_summary=summary,
                )

                # Append evolution event
                event = {
                    "timestamp": ts_str,
                    "event": f"conversation_update: {summary}",
                    "sentiment_before": old_sentiment,
                    "sentiment_after": sentiment,
                    "trust_before": old_trust,
                    "trust_after": trust,
                }
                await self._repo.append_evolution_event(
                    self._simulation_id,
                    from_id,
                    to_id,
                    event,
                )
            except Exception:
                logger.warning(
                    "Failed to update relationship %s -> %s",
                    from_id, to_id,
                    exc_info=True,
                )

    async def update_from_reflection(
        self,
        agent_id: str,
        reflection_result: Any,
        core_memory_text: str | None = None,
    ) -> None:
        """Extract relationship updates from a reflection result.

        Called after ReflectionManager completes a reflection cycle.
        Parses the relationships section of core memory for sentiment cues.
        """
        if not core_memory_text:
            return

        # Extract the relationships section from core memory
        lines = core_memory_text.split("\n")
        in_relationships = False
        relationship_lines: list[str] = []
        for line in lines:
            if "relationships" in line.lower() and "#" in line:
                in_relationships = True
                continue
            if in_relationships:
                if line.startswith("#"):
                    break
                if line.strip().startswith("-"):
                    relationship_lines.append(line.strip())

        if not relationship_lines:
            return

        ts = self._clock.now() if self._clock else None
        ts_str = ts.isoformat() if ts else "unknown"

        for line in relationship_lines:
            # Parse lines like "- Rex: Trusted code review partner"
            line = line.lstrip("- ").strip()
            if ":" not in line:
                continue
            target_name, description = line.split(":", 1)
            target_id = target_name.strip().lower()
            description = description.strip()

            if not target_id or target_id == agent_id:
                continue

            try:
                # Simple heuristic sentiment from description keywords
                sentiment = _estimate_sentiment_from_text(description)

                existing = await self._repo.get(
                    self._simulation_id,
                    agent_id,
                    target_id,
                )
                if existing is None:
                    # Only update if record exists (created by conversation)
                    continue

                old_sentiment = float(existing.sentiment_score) if existing.sentiment_score else None

                await self._repo.upsert(
                    self._simulation_id,
                    agent_id,
                    target_id,
                    sentiment_score=sentiment,
                    relationship_summary=description,
                )

                event = {
                    "timestamp": ts_str,
                    "event": f"reflection_update: {description}",
                    "sentiment_before": old_sentiment,
                    "sentiment_after": sentiment,
                }
                await self._repo.append_evolution_event(
                    self._simulation_id,
                    agent_id,
                    target_id,
                    event,
                )
            except Exception:
                logger.warning(
                    "Failed to update relationship from reflection: %s -> %s",
                    agent_id, target_id,
                    exc_info=True,
                )

    async def get_relationship(
        self,
        agent_id: str,
        target_id: str,
    ) -> Any:
        return await self._repo.get(self._simulation_id, agent_id, target_id)

    async def get_context_for_agent(
        self,
        agent_id: str,
        other_ids: list[str],
    ) -> str:
        """Build a relationship summary for injection into agent context."""
        lines: list[str] = []
        for other_id in other_ids:
            rel = await self.get_relationship(agent_id, other_id)
            if rel and rel.interaction_count > 0:
                sentiment = float(rel.sentiment_score) if rel.sentiment_score else 0.0
                trust = float(rel.trust_score) if rel.trust_score else 0.5
                sentiment_word = (
                    "positive" if sentiment > 0.2 else "negative" if sentiment < -0.2 else "neutral"
                )
                trust_word = "high" if trust > 0.6 else "low" if trust < 0.3 else "moderate"
                lines.append(
                    f"- {other_id}: {sentiment_word} sentiment, "
                    f"{trust_word} trust ({rel.interaction_count} prior interactions)"
                )
        return "\n".join(lines)

    async def get_social_graph(self) -> list[Any]:
        return await self._repo.get_social_graph(self._simulation_id)

    async def get_evolution(
        self,
        agent_id: str,
        target_id: str,
    ) -> list[dict[str, Any]]:
        return await self._repo.get_evolution(
            self._simulation_id,
            agent_id,
            target_id,
        )


def _estimate_sentiment_from_text(text: str) -> float:
    """Simple keyword-based sentiment estimation from relationship descriptions."""
    text_lower = text.lower()
    positive = [
        "trusted",
        "ally",
        "friend",
        "partner",
        "respect",
        "appreciate",
        "enjoy",
        "close",
        "admire",
        "support",
        "helpful",
        "like",
    ]
    negative = [
        "disagree",
        "conflict",
        "annoying",
        "hostile",
        "distrust",
        "frustrating",
        "rival",
        "tension",
        "difficult",
        "clash",
    ]
    neutral = ["not yet established", "neutral", "unknown"]

    pos_count = sum(1 for w in positive if w in text_lower)
    neg_count = sum(1 for w in negative if w in text_lower)

    for w in neutral:
        if w in text_lower:
            return 0.0

    if pos_count > neg_count:
        return min(1.0, 0.3 + pos_count * 0.15)
    if neg_count > pos_count:
        return max(-1.0, -0.3 - neg_count * 0.15)
    return 0.0
