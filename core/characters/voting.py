"""Character deliberation and voting mechanics.

Manages the voting pipeline for new character applications:
agent deliberation → audience poll → final tally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from core.conversation.triggers import TriggerSystem
    from core.database import Database
    from core.event_bus import EventBus

logger = logging.getLogger(__name__)

# Vote weight distribution
AGENT_VOTE_WEIGHT = 0.6
AUDIENCE_VOTE_WEIGHT = 0.4

# Approval thresholds
APPROVAL_THRESHOLD = 0.5  # >50% combined score to approve


class VotingManager:
    """Manages character application voting — agent deliberation + audience polls."""

    def __init__(
        self,
        *,
        db: Database | None = None,
        trigger_system: TriggerSystem | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._db = db
        self._triggers = trigger_system
        self._event_bus = event_bus

    async def start_deliberation(
        self,
        application_id: str | UUID,
    ) -> None:
        """Transition application to 'deliberating' and queue a conversation trigger."""
        if self._db is not None:
            await self._db.execute(
                "UPDATE character_applications SET status = 'deliberating' WHERE id = $1",
                str(application_id),
            )

        if self._triggers is not None:
            self._triggers.queue_event(
                "character_deliberation",
                {
                    "application_id": str(application_id),
                    "description": "A new character wants to join the team. Discuss and vote.",
                },
            )

        logger.info("Started deliberation for application %s", application_id)

    async def record_agent_vote(
        self,
        application_id: str | UUID,
        agent_id: str,
        vote: bool,
        reasoning: str = "",
    ) -> None:
        """Record an agent's in-character vote on a character application."""
        if self._db is None:
            return

        # Read current votes, add this one, write back
        row = await self._db.fetchrow(
            "SELECT agent_votes FROM character_applications WHERE id = $1",
            str(application_id),
        )
        if row is None:
            logger.warning("Application %s not found", application_id)
            return

        import json
        votes = row["agent_votes"] or {}
        if isinstance(votes, str):
            votes = json.loads(votes)

        votes[agent_id] = {"vote": vote, "reasoning": reasoning}

        await self._db.execute(
            "UPDATE character_applications SET agent_votes = $1::jsonb WHERE id = $2",
            json.dumps(votes),
            str(application_id),
        )

        logger.info("Agent %s voted %s on application %s", agent_id, vote, application_id)

    async def start_audience_vote(
        self,
        application_id: str | UUID,
    ) -> None:
        """Transition to audience voting phase."""
        if self._db is not None:
            await self._db.execute(
                "UPDATE character_applications SET status = 'voting' WHERE id = $1",
                str(application_id),
            )

        if self._event_bus is not None:
            from core.event_bus import EventType
            await self._event_bus.emit(
                EventType.POLL_CREATED,
                {
                    "poll_type": "character_vote",
                    "application_id": str(application_id),
                    "question": "Should this new character join the show?",
                },
            )

        logger.info("Started audience vote for application %s", application_id)

    async def record_audience_vote(
        self,
        application_id: str | UUID,
        votes_for: int,
        votes_against: int,
    ) -> None:
        """Record audience poll results."""
        if self._db is None:
            return

        await self._db.execute(
            """UPDATE character_applications
               SET audience_votes_for = $1, audience_votes_against = $2
               WHERE id = $3""",
            votes_for,
            votes_against,
            str(application_id),
        )

    async def tally_votes(
        self,
        application_id: str | UUID,
    ) -> str:
        """Tally combined agent + audience votes. Returns 'approved' or 'rejected'."""
        if self._db is None:
            return "rejected"

        row = await self._db.fetchrow(
            """SELECT agent_votes, audience_votes_for, audience_votes_against
               FROM character_applications WHERE id = $1""",
            str(application_id),
        )
        if row is None:
            return "rejected"

        import json
        votes = row["agent_votes"] or {}
        if isinstance(votes, str):
            votes = json.loads(votes)

        # Agent vote score: fraction that voted yes
        if votes:
            yes_count = sum(1 for v in votes.values() if v.get("vote", False))
            agent_score = yes_count / len(votes)
        else:
            agent_score = 0.0

        # Audience vote score: fraction that voted yes
        total_audience = (row["audience_votes_for"] or 0) + (row["audience_votes_against"] or 0)
        if total_audience > 0:
            audience_score = (row["audience_votes_for"] or 0) / total_audience
        else:
            audience_score = 0.5  # Neutral if no audience votes

        combined = agent_score * AGENT_VOTE_WEIGHT + audience_score * AUDIENCE_VOTE_WEIGHT
        result = "approved" if combined > APPROVAL_THRESHOLD else "rejected"

        await self._db.execute(
            "UPDATE character_applications SET status = $1, decided_at = NOW() WHERE id = $2",
            result,
            str(application_id),
        )

        logger.info(
            "Vote tally for %s: agent=%.2f, audience=%.2f, combined=%.2f → %s",
            application_id, agent_score, audience_score, combined, result,
        )
        return result

    async def get_pending_applications(
        self,
        simulation_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Get all pending/deliberating/voting applications."""
        if self._db is None:
            return []

        rows = await self._db.fetch(
            """SELECT * FROM character_applications
               WHERE status IN ('proposed', 'deliberating', 'voting')
               AND ($1::uuid IS NULL OR simulation_id = $1)
               ORDER BY created_at DESC""",
            simulation_id,
        )
        return [dict(r) for r in rows]
