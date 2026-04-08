"""Character departure mechanics.

Handles agent departures due to low satisfaction, audience exile votes,
or voluntary departure. Maintains cast size constraints.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from core.agent_registry import AgentRegistry
    from core.agent_state import AgentStateManager
    from core.database import Database
    from core.event_bus import EventBus
    from core.llm_client import OpenRouterClient

logger = logging.getLogger(__name__)

# Departure thresholds
SATISFACTION_THRESHOLD = 0.15
FRUSTRATION_THRESHOLD = 0.8
CONSECUTIVE_SNAPSHOTS_REQUIRED = 3

# Exile vote thresholds
EXILE_VOTE_THRESHOLD = 0.70  # >70% vote to exile
EXILE_MIN_VOTES = 50


class DepartureManager:
    """Manages character departures from the show."""

    def __init__(
        self,
        *,
        db: Database | None = None,
        agent_state_manager: AgentStateManager | None = None,
        agent_registry: AgentRegistry | None = None,
        llm_client: OpenRouterClient | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._db = db
        self._state_mgr = agent_state_manager
        self._registry = agent_registry
        self._llm = llm_client
        self._event_bus = event_bus

    def get_active_count(self) -> int:
        """Return number of active agents."""
        if self._registry is None:
            return 0
        return len(self._registry.get_all_agents())

    def can_depart(self) -> bool:
        """Check if a departure is allowed (cast size > MIN)."""
        from core.characters.spawner import MIN_CAST_SIZE
        return self.get_active_count() > MIN_CAST_SIZE

    async def check_departure_conditions(self, agent_id: str) -> bool:
        """Check if an agent meets departure conditions.

        Returns True if satisfaction < threshold AND frustration > threshold.
        In production, would also check consecutive snapshots from DB history.
        """
        if self._state_mgr is None:
            return False

        state = await self._state_mgr.get_state(agent_id)
        return (
            state.satisfaction < SATISFACTION_THRESHOLD
            and state.frustration > FRUSTRATION_THRESHOLD
        )

    async def process_departure(
        self,
        agent_id: str,
        reason: str = "low_satisfaction",
        simulation_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """Process an agent's departure from the show.

        Generates a departure narrative, stores the record, but does NOT
        delete the agent config (memory footprint preserved).
        """
        if not self.can_depart():
            logger.warning(
                "Cannot process departure for %s — cast too small (%d)",
                agent_id, self.get_active_count(),
            )
            return None

        # Generate departure narrative
        narrative = await self._generate_departure_narrative(agent_id, reason)

        # Store departure record
        departure: dict[str, Any] = {
            "agent_id": agent_id,
            "reason": reason,
            "departure_narrative": narrative,
        }

        if self._db is not None:
            await self._db.execute(
                """INSERT INTO character_departures
                   (simulation_id, agent_id, reason, departure_narrative)
                   VALUES ($1, $2, $3, $4)""",
                simulation_id,
                agent_id,
                reason,
                narrative,
            )

        # Emit departure event
        if self._event_bus is not None:
            from core.event_bus import EventType
            await self._event_bus.emit(
                EventType.AGENT_ACTION,
                {
                    "agent_id": agent_id,
                    "action": "departure",
                    "reason": reason,
                    "narrative": narrative,
                },
            )

        logger.info("Processed departure for %s (reason: %s)", agent_id, reason)
        return departure

    async def check_exile_vote(
        self,
        agent_id: str,
        votes_for: int,
        votes_against: int,
    ) -> bool:
        """Check if an exile vote has passed.

        Requires >70% in favor with minimum 50 total votes.
        """
        total = votes_for + votes_against
        if total < EXILE_MIN_VOTES:
            return False
        return (votes_for / total) > EXILE_VOTE_THRESHOLD

    async def _generate_departure_narrative(
        self,
        agent_id: str,
        reason: str,
    ) -> str:
        """Generate an in-character departure narrative via LLM."""
        if self._llm is None:
            return f"{agent_id} has left the show ({reason})."

        reason_text = {
            "low_satisfaction": "deeply unsatisfied and frustrated with how things have been going",
            "exile_vote": "voted out by the audience",
            "voluntary": "decided to leave on their own terms",
        }.get(reason, reason)

        try:
            response = await self._llm.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Write a brief (2-3 sentence) departure narrative for an AI agent "
                            f"named {agent_id} who is leaving a reality show. "
                            f"Reason: {reason_text}. "
                            f"Make it dramatic but brief."
                        ),
                    },
                    {"role": "user", "content": "Write the departure narrative."},
                ],
                model="anthropic/claude-haiku-4.5",
                agent_id="system",
                temperature=0.8,
                max_tokens=200,
            )
            return response.content.strip()
        except Exception:
            logger.warning("Failed to generate departure narrative for %s", agent_id)
            return f"{agent_id} has left the show ({reason})."
