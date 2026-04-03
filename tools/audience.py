"""get_audience_status tool — viewer count, chat, polls from cached Twitch data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BaseTool, parse_json

if TYPE_CHECKING:
    from core.redis_client import RedisClient


class GetAudienceStatusTool(BaseTool):
    """Get current viewer count, recent chat highlights, active polls."""

    name = "get_audience_status"
    description = "Get current viewer count, recent chat highlights, active polls"
    parameters = {}

    def __init__(self, redis_client: RedisClient) -> None:
        self._redis = redis_client

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        viewer_count_raw = await self._redis.get("audience:viewer_count")
        polls_raw = await self._redis.get("audience:active_polls")

        # recent_chat is stored as a Redis list (one JSON entry per message)
        chat_entries_raw: list[str] = await self._redis.lrange("audience:recent_chat", 0, -1)
        chat_messages = [parse_json(entry, None) for entry in (chat_entries_raw or [])]
        chat_messages = [m for m in chat_messages if m is not None]

        return {
            "viewer_count": _parse_int(viewer_count_raw, 0),
            "recent_chat_messages": chat_messages,
            "active_polls": parse_json(polls_raw, []),
        }


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default
