"""Agent tools for character proposal and voting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.base import BaseTool

if TYPE_CHECKING:
    from core.characters.spawner import CharacterSpawner
    from core.characters.voting import VotingManager

logger = logging.getLogger(__name__)


class ProposeCharacterTool(BaseTool):
    """Propose a new character to join the show."""

    name = "propose_character"
    description = (
        "Propose a new character concept for the show. "
        "Only available when you have a strong creative need. "
        "The character will go through deliberation and voting before joining."
    )
    parameters = {
        "character_name": {
            "type": "string",
            "description": "Proposed name for the new character (single word, lowercase)",
        },
        "role": {
            "type": "string",
            "description": "The role this character would fill (e.g., 'Diplomat', 'Data Scientist')",
        },
        "personality_sketch": {
            "type": "string",
            "description": "2-3 sentences describing the character's personality and quirks",
        },
    }

    def __init__(
        self,
        *,
        spawner: CharacterSpawner | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._spawner = spawner
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._spawner is None:
            return {"status": "error", "reason": "Character spawner not available"}

        if not self._spawner.can_add_character():
            return {"status": "error", "reason": "Cast is full, cannot propose new character"}

        from core.characters.spawner import CharacterApplication

        application = CharacterApplication(
            name=kwargs["character_name"],
            display_name=f"{kwargs['character_name'].capitalize()} — {kwargs['role']}",
            role=kwargs["role"],
            personality_sketch=kwargs["personality_sketch"],
            proposed_by=self._agent_id,
            source="agent",
        )

        simulation_id = kwargs.get("simulation_id")
        saved = await self._spawner.submit_application(
            application,
            simulation_id=simulation_id,
        )
        if saved is None:
            return {"status": "error", "reason": "Failed to save character application"}

        return {
            "status": "proposed",
            "application_id": saved.id,
            "character_name": saved.name,
            "role": saved.role,
            "message": f"Character '{saved.name}' has been proposed. "
            f"The team will deliberate and vote.",
        }


class VoteCharacterTool(BaseTool):
    """Vote on a pending character application."""

    name = "vote_character"
    description = (
        "Cast your vote on whether a proposed character should join the show. "
        "Vote based on whether you think they'd be a good addition to the team."
    )
    parameters = {
        "application_id": {
            "type": "string",
            "description": "The ID of the character application to vote on",
        },
        "vote": {
            "type": "string",
            "description": "Your vote: 'yes' to approve, 'no' to reject",
            "enum": ["yes", "no"],
        },
        "reasoning": {
            "type": "string",
            "description": "Brief in-character reasoning for your vote",
        },
    }

    def __init__(
        self,
        *,
        voting_manager: VotingManager | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._voting = voting_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._voting is None:
            return {"status": "error", "reason": "Voting system not available"}

        import uuid as _uuid

        try:
            _uuid.UUID(kwargs["application_id"])
        except (ValueError, AttributeError):
            return {"status": "error", "reason": "Invalid application_id (not a valid UUID)"}

        vote_bool = kwargs["vote"].lower() == "yes"
        await self._voting.record_agent_vote(
            application_id=kwargs["application_id"],
            agent_id=self._agent_id,
            vote=vote_bool,
            reasoning=kwargs.get("reasoning", ""),
        )

        return {
            "status": "voted",
            "vote": "yes" if vote_bool else "no",
            "message": "Your vote has been recorded.",
        }
