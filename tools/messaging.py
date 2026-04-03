"""send_message tool — inter-agent communication."""

from __future__ import annotations

import time
from typing import Any

from core.event_bus import EventBus, EventType

from .base import BaseTool

VALID_TONES = frozenset({"casual", "urgent", "professional", "dramatic", "sarcastic"})


class SendMessageTool(BaseTool):
    """Send a message to another agent or to the group."""

    name = "send_message"
    description = "Send a message to another agent or to the group"
    parameters = {
        "to": {"type": "string", "description": "agent_id or 'group'"},
        "message": {"type": "string", "description": "The message content"},
        "tone": {
            "type": "string",
            "description": "Message tone",
            "enum": sorted(VALID_TONES),
        },
    }

    def __init__(self, event_bus: EventBus, agent_id: str) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        to: str = kwargs["to"]
        message: str = kwargs["message"]
        tone: str = kwargs.get("tone", "casual")

        if tone not in VALID_TONES:
            raise ValueError(
                f"Invalid tone {tone!r}. Must be one of: {sorted(VALID_TONES)}"
            )

        event = await self._event_bus.emit(
            EventType.AGENT_SPEAK,
            {
                "from_agent": self._agent_id,
                "to": to,
                "message": message,
                "tone": tone,
                "timestamp": time.time(),
            },
        )

        return {
            "status": "sent",
            "event_id": event["event_id"],
            "to": to,
        }
