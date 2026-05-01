"""Self-modification tools — propose changes and view evolution history."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models import SelfModificationProposalCreate

from .base import BaseTool

if TYPE_CHECKING:
    import uuid as _uuid

    from core.repos.memory_repo import MemoryRepo

logger = logging.getLogger(__name__)

# Patterns that indicate a permissions-related file
_PERMISSION_PATTERNS = frozenset({"permissions", "access_control", "acl"})


class ProposeSelfModificationTool(BaseTool):
    """Propose a change to the agent's own personality, behaviors, or configuration."""

    name = "propose_self_modification"
    description = (
        "Propose a modification to your own configuration file. "
        "Changes are queued for human review before taking effect."
    )
    parameters = {
        "file": {
            "type": "string",
            "description": (
                "Path to the configuration file to modify (must be your own agent config)"
            ),
        },
        "change_description": {
            "type": "string",
            "description": "Human-readable description of the proposed change",
        },
        "new_content": {
            "type": "string",
            "description": "The proposed new content for the file",
        },
    }

    AUTO_APPROVAL_ENABLED: bool = False

    def __init__(self, agent_id: str, memory_repo: MemoryRepo) -> None:
        self.agent_id = agent_id
        self.memory_repo = memory_repo

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        file: str = kwargs.get("file", "")
        change_description: str = kwargs.get("change_description", "")
        new_content: str = kwargs.get("new_content", "")
        simulation_id: _uuid.UUID | None = kwargs.get("simulation_id")

        if not file or not change_description or not new_content:
            return {
                "status": "error",
                "reason": "file, change_description, and new_content are all required",
            }

        # --- Safety restrictions ---

        file_lower = file.lower()

        # Cannot modify Management
        if "management" in file_lower:
            logger.warning(
                "Agent %s attempted to modify Management file: %s",
                self.agent_id,
                file,
            )
            return {
                "status": "rejected",
                "reason": "Cannot modify Management configuration",
            }

        # Cannot modify permissions files
        if any(pat in file_lower for pat in _PERMISSION_PATTERNS):
            logger.warning(
                "Agent %s attempted to modify permissions file: %s",
                self.agent_id,
                file,
            )
            return {
                "status": "rejected",
                "reason": "Cannot modify permissions or access control files",
            }

        # Cannot modify other agents' files
        # Agent configs live under agents/<agent_id>/ — extract target agent from path
        if not self._is_own_file(file):
            logger.warning(
                "Agent %s attempted to modify another agent's file: %s",
                self.agent_id,
                file,
            )
            return {
                "status": "rejected",
                "reason": (
                    f"Cannot modify files belonging to other agents. "
                    f"You can only modify your own files under agents/{self.agent_id}/"
                ),
            }

        # --- Create proposal ---
        proposal = SelfModificationProposalCreate(
            agent_id=self.agent_id,
            proposal_type="self_modification",
            description=change_description,
            reasoning=f"Agent {self.agent_id} proposed modification to {file}",
            file=file,
            new_content=new_content,
            simulation_id=simulation_id,
        )

        result = await self.memory_repo.create_proposal(proposal)

        logger.info(
            "Agent %s created self-modification proposal %d for file %s",
            self.agent_id,
            result.id,
            file,
        )

        return {
            "status": "success",
            "proposal_id": result.id,
            "proposal_status": result.status,
            "message": f"Proposal #{result.id} created and queued for human review",
        }

    def _is_own_file(self, file: str) -> bool:
        """Check if the file path belongs to this agent."""
        # Normalize path separators and resolve traversal
        normalized = file.replace("\\", "/")

        # Reject any path traversal attempts
        if ".." in normalized:
            return False

        # Reject absolute paths — all agent config paths must be relative
        if normalized.startswith("/"):
            return False

        parts = normalized.lower().split("/")

        # Must start with "agents/<agent_id>/..." to be a valid agent config path
        if len(parts) < 3 or parts[0] != "agents":
            return False

        target_agent = parts[1]
        return target_agent == self.agent_id.lower()


class ViewEvolutionLogTool(BaseTool):
    """View this agent's evolution log — history of proposed self-modifications."""

    name = "view_evolution_log"
    description = (
        "View your evolution log showing past self-modification proposals "
        "and their approval status."
    )
    parameters = {
        "limit": {
            "type": "integer",
            "description": "Maximum number of entries to return (default 10)",
        },
    }

    def __init__(
        self,
        agent_id: str,
        memory_repo: MemoryRepo,
        simulation_id: _uuid.UUID | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.memory_repo = memory_repo
        self.simulation_id = simulation_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        limit: int = kwargs.get("limit", 10)
        if not isinstance(limit, int) or limit < 1:
            limit = 10

        sim_id = kwargs.get("simulation_id") or self.simulation_id
        proposals = await self.memory_repo.get_evolution_log(
            agent_id=self.agent_id, limit=limit, simulation_id=sim_id
        )

        entries = [
            {
                "date": p.created_at.isoformat() if p.created_at else None,
                "change_description": p.description,
                "status": p.status,
                "impact_notes": p.impact_notes,
            }
            for p in proposals
        ]

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "entries": entries,
            "count": len(entries),
        }
