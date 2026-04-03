"""Input validation utilities for the memory system."""

from __future__ import annotations

import re

# Agent IDs must be alphanumeric with underscores/hyphens, 1-50 chars
_AGENT_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,49}$")


class InvalidAgentIdError(ValueError):
    """Raised when an agent_id fails format validation."""


def validate_agent_id(agent_id: str) -> str:
    """Validate and return the agent_id, or raise InvalidAgentIdError.

    Agent IDs must:
    - Start with a letter
    - Contain only alphanumeric characters, underscores, or hyphens
    - Be 1-50 characters long
    """
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.match(agent_id):
        raise InvalidAgentIdError(
            f"Invalid agent_id {agent_id!r}. Must start with a letter and "
            "contain only alphanumeric characters, underscores, or hyphens (1-50 chars)."
        )
    return agent_id
