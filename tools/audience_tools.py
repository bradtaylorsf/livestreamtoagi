"""Audience communication tools — send_chat, create_poll, get_poll_results."""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from core.event_bus import EventType

from .base import BaseTool

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.overseer import Overseer
    from core.redis_client import RedisClient


class SendChatMessageTool(BaseTool):
    """Send a message to Twitch/YouTube chat (passes through Overseer filter first)."""

    name = "send_chat_message"
    description = "Send a message to Twitch/YouTube chat"
    parameters = {
        "message": {"type": "string", "description": "The chat message to send"},
    }

    ALLOWED_AGENTS = frozenset({"pixel", "sentinel", "vera"})

    def __init__(
        self, overseer: Overseer, event_bus: EventBus, redis_client: RedisClient, agent_id: str
    ) -> None:
        self._overseer = overseer
        self._event_bus = event_bus
        self._redis = redis_client
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        message: str = kwargs["message"]

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        review = await self._overseer.review(self._agent_id, message)
        if not review.approved:
            return {"status": "rejected", "reason": review.reason}

        # Store in Redis for audience status reads
        await self._redis.set(
            "audience:recent_chat",
            json.dumps({"agent": self._agent_id, "message": message, "timestamp": time.time()}),
        )

        return {"status": "sent", "message": message, "agent": self._agent_id}


class CreatePollTool(BaseTool):
    """Create a Twitch poll for audience engagement."""

    name = "create_poll"
    description = "Create a Twitch poll with 2-5 options"
    parameters = {
        "title": {"type": "string", "description": "Poll question"},
        "options": {
            "type": "array",
            "description": "2-5 answer options",
            "items": {"type": "string"},
        },
        "duration": {"type": "integer", "description": "Duration in seconds (default 120)"},
    }

    ALLOWED_AGENTS = frozenset({"vera", "pixel"})

    def __init__(self, redis_client: RedisClient, event_bus: EventBus, agent_id: str) -> None:
        self._redis = redis_client
        self._event_bus = event_bus
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        title: str = kwargs["title"]
        options: list[str] = kwargs["options"]
        duration: int = kwargs.get("duration", 120)

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        if not (2 <= len(options) <= 5):
            return {"status": "rejected", "reason": "Poll must have 2-5 options"}

        # Check for existing active poll
        active = await self._redis.get("poll:active")
        if active is not None:
            return {"status": "rejected", "reason": "An active poll already exists"}

        poll_id = str(uuid.uuid4())
        poll_data = {
            "poll_id": poll_id,
            "title": title,
            "options": [{"name": opt, "votes": 0} for opt in options],
            "duration": duration,
            "created_by": self._agent_id,
            "created_at": time.time(),
        }

        await self._redis.set(f"poll:{poll_id}", json.dumps(poll_data), ex=duration)
        await self._redis.set("poll:active", poll_id, ex=duration)

        await self._event_bus.emit(
            EventType.POLL_CREATED,
            {"poll_id": poll_id, "title": title, "options": options, "duration": duration},
        )

        return {"status": "created", "poll_id": poll_id}


class GetPollResultsTool(BaseTool):
    """Get results of a poll by ID."""

    name = "get_poll_results"
    description = "Get poll results including vote counts and percentages"
    parameters = {
        "poll_id": {"type": "string", "description": "The poll ID to get results for"},
    }

    def __init__(self, redis_client: RedisClient, event_bus: EventBus) -> None:
        self._redis = redis_client
        self._event_bus = event_bus

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        poll_id: str = kwargs["poll_id"]

        raw = await self._redis.get(f"poll:{poll_id}")
        if raw is None:
            return {"status": "not_found", "reason": f"Poll {poll_id!r} not found"}

        poll_data = json.loads(raw)
        options = poll_data["options"]
        total_votes = sum(opt["votes"] for opt in options)

        results = []
        for opt in options:
            pct = (opt["votes"] / total_votes * 100) if total_votes > 0 else 0.0
            results.append({
                "name": opt["name"],
                "votes": opt["votes"],
                "percentage": round(pct, 1),
            })

        winner = max(options, key=lambda o: o["votes"])["name"] if total_votes > 0 else None

        result = {
            "status": "ok",
            "options": results,
            "total_votes": total_votes,
            "winner": winner,
        }

        await self._event_bus.emit(
            EventType.POLL_RESULT,
            {"poll_id": poll_id, **result},
        )

        return result
