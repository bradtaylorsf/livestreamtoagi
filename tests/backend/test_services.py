"""Integration tests for Docker Compose development services.

These tests require running services: docker compose up -d
Run with: pytest tests/backend/test_services.py -m integration
"""

import asyncpg
import pytest
import redis

integration = pytest.mark.integration


@integration
def test_redis_ping():
    """Redis accepts connections and responds to PING."""
    r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=5)
    assert r.ping() is True


@integration
@pytest.mark.asyncio
async def test_postgres_connection():
    """PostgreSQL accepts connections."""
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="agi",
        password="devpassword",
        database="livestream_agi",
    )
    try:
        result = await conn.fetchval("SELECT 1")
        assert result == 1
    finally:
        await conn.close()


@integration
@pytest.mark.asyncio
async def test_pgvector_extension():
    """pgvector extension is installed in livestream_agi database."""
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="agi",
        password="devpassword",
        database="livestream_agi",
    )
    try:
        result = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert result == "vector"
    finally:
        await conn.close()


@integration
@pytest.mark.asyncio
async def test_pg_trgm_extension():
    """pg_trgm extension is installed in livestream_agi database."""
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="agi",
        password="devpassword",
        database="livestream_agi",
    )
    try:
        result = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
        assert result == "pg_trgm"
    finally:
        await conn.close()
