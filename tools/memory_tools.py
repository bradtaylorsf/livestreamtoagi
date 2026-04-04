"""Memory tools — recall_memory, retrieve_transcript, update_core_memory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.memory.core_memory import (
    VALID_SECTIONS,
    CoreMemoryExceededError,
    InvalidSectionError,
)

from .base import BaseTool

if TYPE_CHECKING:
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager


class RecallMemoryTool(BaseTool):
    """Search Tier 2 recall memory for relevant past memories."""

    name = "recall_memory"
    description = (
        "Search past memories by semantic similarity. "
        "Returns summaries with transcript IDs for deeper lookup. "
        "Cost: ~$0.0001 per call (embedding)."
    )
    parameters = {
        "query": {"type": "string", "description": "What to search for in memory"},
        "limit": {
            "type": "integer",
            "description": "Max results to return (default 3)",
        },
    }

    def __init__(
        self, recall_manager: RecallMemoryManager, agent_id: str
    ) -> None:
        self._recall_manager = recall_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        limit: int = kwargs.get("limit", 3)

        result = await self._recall_manager.retrieve_recall_memories(
            self._agent_id, query, limit=limit
        )

        if not result:
            return {"status": "no_results", "memories": ""}

        return {"status": "ok", "memories": result}


class RetrieveTranscriptTool(BaseTool):
    """Fetch a full Tier 3 transcript by ID."""

    name = "retrieve_transcript"
    description = (
        "Retrieve the full text of a transcript by its ID. "
        "Warning: adds 1,000-5,000 tokens to context. "
        "Cost: $0 (database read only)."
    )
    parameters = {
        "transcript_id": {
            "type": "integer",
            "description": "The transcript ID to retrieve",
        },
    }

    def __init__(self, archival_manager: ArchivalMemoryManager) -> None:
        self._archival_manager = archival_manager

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        transcript_id: int = kwargs["transcript_id"]

        transcript = await self._archival_manager.retrieve_full_transcript(
            transcript_id
        )

        if transcript is None:
            return {
                "status": "not_found",
                "error": f"No transcript found with ID {transcript_id}",
            }

        return {
            "status": "ok",
            "transcript_id": transcript.id,
            "event_type": transcript.event_type,
            "participants": transcript.participants,
            "content": transcript.content,
            "token_count": transcript.token_count,
        }


class UpdateCoreMemoryTool(BaseTool):
    """Update a section of Tier 1 core memory."""

    name = "update_core_memory"
    description = (
        "Update a specific section of core memory. "
        f"Valid sections: {sorted(VALID_SECTIONS)}. "
        "Enforces 3,000 token limit."
    )
    parameters = {
        "section": {
            "type": "string",
            "description": "Section to update",
            "enum": sorted(VALID_SECTIONS),
        },
        "content": {
            "type": "string",
            "description": "New content for the section",
        },
        "agent_target": {
            "type": "string",
            "description": "Target agent ID (defaults to self)",
        },
    }

    def __init__(
        self, core_manager: CoreMemoryManager, agent_id: str
    ) -> None:
        self._core_manager = core_manager
        self._agent_id = agent_id

    # Only these agents are allowed to update other agents' core memory
    CROSS_AGENT_WRITERS = frozenset({"vera", "overseer"})

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        section: str = kwargs["section"]
        content: str = kwargs["content"]
        raw_target: str = kwargs.get("agent_target", self._agent_id).lower()
        # Resolve "self" to the calling agent's actual ID
        agent_target = self._agent_id if raw_target == "self" else raw_target

        # Authorization: agents can only update their own memory unless privileged
        if agent_target != self._agent_id and self._agent_id not in self.CROSS_AGENT_WRITERS:
            return {
                "status": "error",
                "error": (
                    f"Agent {self._agent_id!r} is not authorized to update "
                    f"core memory for {agent_target!r}"
                ),
            }

        try:
            record = await self._core_manager.update_core_memory(
                agent_id=agent_target,
                section=section,
                content=content,
                reason=f"tool_update by {self._agent_id}",
            )
        except InvalidSectionError as exc:
            return {"status": "error", "error": str(exc)}
        except CoreMemoryExceededError as exc:
            return {"status": "error", "error": str(exc)}

        return {
            "status": "updated",
            "agent_id": record.agent_id,
            "token_count": record.token_count,
            "version": record.version,
        }
