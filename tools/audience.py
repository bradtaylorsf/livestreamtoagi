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
        chat_raw = await self._redis.get("audience:recent_chat")
        polls_raw = await self._redis.get("audience:active_polls")

        return {
            "viewer_count": _parse_int(viewer_count_raw, 0),
            "recent_chat_messages": parse_json(chat_raw, []),
            "active_polls": parse_json(polls_raw, []),
        }


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default
