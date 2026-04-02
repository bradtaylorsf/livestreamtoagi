"""Async PostgreSQL connection pool using asyncpg."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register custom codecs on each new connection (e.g. pgvector)."""
    try:
        await conn.set_type_codec(
            "vector",
            encoder=lambda v: v,
            decoder=lambda v: v,
            schema="public",
            format="text",
        )
    except ValueError:
        # pgvector extension not yet installed — codec will be registered
        # once migrations create the extension and the pool reconnects.
        pass


class Database:
    """Manages an asyncpg connection pool with convenience query methods."""

    def __init__(
        self,
        dsn: str | None = None,
        min_size: int = 5,
        max_size: int = 20,
    ) -> None:
        self.dsn = dsn or os.getenv("DATABASE_URL")
        self.min_size = min_size
        self.max_size = max_size
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    async def connect(self, *, retries: int = 3, delay: float = 2.0) -> None:
        """Create the connection pool with retry logic."""
        if not self.dsn:
            raise RuntimeError("DATABASE_URL environment variable is required")
        for attempt in range(1, retries + 1):
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self.dsn,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    init=_init_connection,
                    command_timeout=30,
                )
                logger.info(
                    "Database pool created (%d-%d connections)",
                    self.min_size, self.max_size,
                )
                return
            except (OSError, asyncpg.PostgresError) as exc:
                if attempt == retries:
                    raise ConnectionError(
                        f"Failed to connect to database after {retries} attempts: {exc}"
                    ) from exc
                logger.warning("DB connect attempt %d/%d failed: %s", attempt, retries, exc)
                await asyncio.sleep(delay)

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Database pool closed")

    @asynccontextmanager
    async def acquire(self, *, timeout: float = 10.0):
        """Acquire a connection from the pool."""
        async with self.pool.acquire(timeout=timeout) as conn:
            yield conn

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        async with self.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None,
    ) -> list[asyncpg.Record]:
        async with self.acquire() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None,
    ) -> asyncpg.Record | None:
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(self, query: str, *args: Any, timeout: float | None = None) -> Any:
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, timeout=timeout)
