"""Repository classes for database access."""

from __future__ import annotations

import json
from typing import Any


def serialize_jsonb(val: Any) -> str | None:
    """Serialize a value to a JSON string for JSONB columns."""
    if val is None:
        return None
    return json.dumps(val) if not isinstance(val, str) else val


from core.repos.agent_repo import AgentRepo
from core.repos.conversation_repo import ConversationRepo
from core.repos.cost_repo import CostRepo
from core.repos.memory_repo import MemoryRepo
from core.repos.transcript_repo import TranscriptRepo
from core.repos.world_repo import WorldRepo

__all__ = [
    "AgentRepo",
    "ConversationRepo",
    "CostRepo",
    "MemoryRepo",
    "TranscriptRepo",
    "WorldRepo",
]
