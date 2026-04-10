"""Async Redis client wrapper using redis.asyncio."""

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://localhost:6381"


class RedisClient:
    """Wraps redis.asyncio with lifecycle management and convenience methods."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        self._client: aioredis.Redis | None = None

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    async def connect(self, *, retries: int = 3, delay: float = 2.0) -> None:
        """Connect to Redis with retry logic."""
        for attempt in range(1, retries + 1):
            try:
                self._client = aioredis.from_url(
                    self.url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                await self._client.ping()
                parsed = urlparse(self.url)
                netloc = f"{parsed.hostname}:{parsed.port or 6379}"
                safe_url = urlunparse(parsed._replace(netloc=netloc))
                logger.info("Redis connected at %s", safe_url)
                return
            except (OSError, aioredis.RedisError) as exc:
                if attempt == retries:
                    raise ConnectionError(
                        f"Failed to connect to Redis after {retries} attempts: {exc}"
                    ) from exc
                logger.warning("Redis connect attempt %d/%d failed: %s", attempt, retries, exc)
                await asyncio.sleep(delay)

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Redis disconnected")

    async def ping(self) -> bool:
        """Ping Redis and return True if alive."""
        return await self.client.ping()

    async def get(self, key: str) -> str | None:
        return await self.client.get(key)

    async def set(
        self, key: str, value: str, *, ex: int | None = None
    ) -> bool:
        return await self.client.set(key, value, ex=ex)

    async def delete(self, *keys: str) -> int:
        return await self.client.delete(*keys)

    async def incr(self, key: str) -> int:
        return await self.client.incr(key)

    async def expire(self, key: str, seconds: int) -> bool:
        return await self.client.expire(key, seconds)

    async def rpush(self, key: str, *values: str) -> int:
        return await self.client.rpush(key, *values)

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        return await self.client.ltrim(key, start, stop)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        return await self.client.lrange(key, start, stop)

    async def scan(
        self, cursor: int = 0, *, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        return await self.client.scan(cursor, match=match, count=count)

    async def hset(self, key: str, field: str, value: Any) -> int:
        return await self.client.hset(key, field, value)

    async def hget(self, key: str, field: str) -> str | None:
        return await self.client.hget(key, field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self.client.hgetall(key)

    async def publish(self, channel: str, message: str) -> int:
        return await self.client.publish(channel, message)

    async def subscribe(self, *channels: str) -> Any:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(*channels)
        return pubsub
