"""Simulation-scoped Redis key proxy.

Every Redis key used by simulation-aware components goes through ScopedRedis,
which transparently prefixes keys with ``live:`` (for the live simulation) or
``sim:<uuid>:`` (for test/dev simulations).

Global keys that are NOT simulation-scoped (kill_switch, ratelimit:*, challenge_vote:*)
should use the raw RedisClient directly.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from core.constants import LIVE_SIMULATION_ID

if TYPE_CHECKING:
    from core.redis_client import RedisClient


class ScopedRedis:
    """Wraps a RedisClient, auto-prefixing all keys with simulation scope.

    Parameters
    ----------
    redis:
        The underlying RedisClient instance.
    simulation_id:
        UUID of the simulation this scope belongs to.
    """

    def __init__(
        self,
        redis: RedisClient,
        simulation_id: uuid.UUID,
    ) -> None:
        self._redis = redis
        self.simulation_id = simulation_id
        if simulation_id == LIVE_SIMULATION_ID:
            self._prefix = "live"
        else:
            self._prefix = f"sim:{simulation_id}"

    def _key(self, raw: str) -> str:
        return f"{self._prefix}:{raw}"

    # ── String operations ──────────────────────────────────────

    async def get(self, key: str) -> str | None:
        return await self._redis.get(self._key(key))

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        return await self._redis.set(self._key(key), value, ex=ex)

    async def delete(self, *keys: str) -> int:
        return await self._redis.delete(*(self._key(k) for k in keys))

    async def incr(self, key: str) -> int:
        return await self._redis.incr(self._key(key))

    async def expire(self, key: str, seconds: int) -> bool:
        return await self._redis.expire(self._key(key), seconds)

    # ── List operations ────────────────────────────────────────

    async def rpush(self, key: str, *values: str) -> int:
        return await self._redis.rpush(self._key(key), *values)

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        return await self._redis.ltrim(self._key(key), start, stop)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        return await self._redis.lrange(self._key(key), start, stop)

    # ── Hash operations ────────────────────────────────────────

    async def hset(self, key: str, field: str, value: Any) -> int:
        return await self._redis.hset(self._key(key), field, value)

    async def hget(self, key: str, field: str) -> str | None:
        return await self._redis.hget(self._key(key), field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self._redis.hgetall(self._key(key))

    async def hdel(self, key: str, *fields: str) -> int:
        return await self._redis.hdel(self._key(key), *fields)

    # ── Scan (prefixes the match pattern) ──────────────────────

    async def scan(
        self,
        cursor: int = 0,
        *,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[str]]:
        prefixed_match = self._key(match) if match else None
        result_cursor, keys = await self._redis.scan(
            cursor,
            match=prefixed_match,
            count=count,
        )
        # Strip prefix from returned keys so callers see raw key names
        prefix_len = len(self._prefix) + 1  # +1 for the ':'
        stripped = [k[prefix_len:] if k.startswith(self._prefix + ":") else k for k in keys]
        return result_cursor, stripped

    # ── Pub/Sub (channels are NOT prefixed — they're global) ───

    async def publish(self, channel: str, message: str) -> int:
        return await self._redis.publish(channel, message)

    async def subscribe(self, *channels: str) -> Any:
        return await self._redis.subscribe(*channels)
