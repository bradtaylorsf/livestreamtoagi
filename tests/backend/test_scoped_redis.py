"""Tests for ScopedRedis simulation-scoped key prefixing.

Covers key isolation added in issue #252.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from core.constants import LIVE_SIMULATION_ID
from core.redis_keys import ScopedRedis


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.incr = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=True)
    r.rpush = AsyncMock(return_value=1)
    r.ltrim = AsyncMock(return_value=True)
    r.lrange = AsyncMock(return_value=[])
    r.hset = AsyncMock(return_value=1)
    r.hget = AsyncMock(return_value=None)
    r.hgetall = AsyncMock(return_value={})
    r.scan = AsyncMock(return_value=(0, []))
    r.publish = AsyncMock(return_value=1)
    return r


@pytest.fixture
def live_scoped(mock_redis):
    return ScopedRedis(mock_redis, LIVE_SIMULATION_ID)


@pytest.fixture
def sim_id():
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def sim_scoped(mock_redis, sim_id):
    return ScopedRedis(mock_redis, sim_id)


# ── Prefix computation ──────────────────────────────────────────


def test_live_prefix(live_scoped):
    """With LIVE_SIMULATION_ID, keys get a 'live:' prefix."""
    assert live_scoped._prefix == "live"
    assert live_scoped._key("somekey") == "live:somekey"


def test_sim_prefix(sim_scoped, sim_id):
    """With a random UUID, keys get a 'sim:<uuid>:' prefix."""
    expected_prefix = f"sim:{sim_id}"
    assert sim_scoped._prefix == expected_prefix
    assert sim_scoped._key("somekey") == f"{expected_prefix}:somekey"


# ── String operations ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_prefixes_key(live_scoped, mock_redis):
    """get('foo') calls redis.get('live:foo')."""
    mock_redis.get.return_value = "bar"

    result = await live_scoped.get("foo")

    mock_redis.get.assert_called_once_with("live:foo")
    assert result == "bar"


@pytest.mark.asyncio
async def test_set_prefixes_key(live_scoped, mock_redis):
    """set('foo', 'bar') calls redis.set('live:foo', 'bar')."""
    await live_scoped.set("foo", "bar")

    mock_redis.set.assert_called_once_with("live:foo", "bar", ex=None)


@pytest.mark.asyncio
async def test_set_with_expiry(live_scoped, mock_redis):
    """set with ex= passes the expiry through correctly."""
    await live_scoped.set("session", "token", ex=3600)

    mock_redis.set.assert_called_once_with("live:session", "token", ex=3600)


@pytest.mark.asyncio
async def test_delete_prefixes_keys(live_scoped, mock_redis):
    """delete('a', 'b') calls redis.delete with both keys prefixed."""
    await live_scoped.delete("a", "b")

    mock_redis.delete.assert_called_once_with("live:a", "live:b")


@pytest.mark.asyncio
async def test_incr_prefixes(live_scoped, mock_redis):
    """incr prefixes the key correctly."""
    mock_redis.incr.return_value = 5

    result = await live_scoped.incr("counter")

    mock_redis.incr.assert_called_once_with("live:counter")
    assert result == 5


# ── List operations ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rpush_prefixes(live_scoped, mock_redis):
    """List rpush prefixes the key correctly."""
    mock_redis.rpush.return_value = 3

    result = await live_scoped.rpush("mylist", "v1", "v2")

    mock_redis.rpush.assert_called_once_with("live:mylist", "v1", "v2")
    assert result == 3


# ── Hash operations ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hset_uses_abstraction(live_scoped, mock_redis):
    """hset calls redis.hset (the abstraction), not redis.client.hset."""
    await live_scoped.hset("myhash", "field1", "value1")

    mock_redis.hset.assert_called_once_with("live:myhash", "field1", "value1")


@pytest.mark.asyncio
async def test_hget_uses_abstraction(live_scoped, mock_redis):
    """hget calls redis.hget with the prefixed key."""
    mock_redis.hget.return_value = "stored_value"

    result = await live_scoped.hget("myhash", "field1")

    mock_redis.hget.assert_called_once_with("live:myhash", "field1")
    assert result == "stored_value"


@pytest.mark.asyncio
async def test_hgetall_uses_abstraction(live_scoped, mock_redis):
    """hgetall calls redis.hgetall with the prefixed key."""
    mock_redis.hgetall.return_value = {"k": "v"}

    result = await live_scoped.hgetall("myhash")

    mock_redis.hgetall.assert_called_once_with("live:myhash")
    assert result == {"k": "v"}


# ── Scan ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_strips_prefix(live_scoped, mock_redis):
    """scan() returns keys with the 'live:' prefix stripped."""
    mock_redis.scan.return_value = (0, ["live:agent:vera", "live:agent:rex"])

    cursor, keys = await live_scoped.scan(0, match="agent:*")

    # Prefix should be stripped from returned keys
    assert keys == ["agent:vera", "agent:rex"]
    # But the scan call itself should use the prefixed match pattern
    mock_redis.scan.assert_called_once_with(0, match="live:agent:*", count=None)


@pytest.mark.asyncio
async def test_scan_strips_prefix_sim_scoped(sim_scoped, mock_redis, sim_id):
    """scan() strips sim-scoped prefix correctly."""
    prefixed_key = f"sim:{sim_id}:state:vera"
    mock_redis.scan.return_value = (0, [prefixed_key])

    cursor, keys = await sim_scoped.scan(0, match="state:*")

    assert keys == ["state:vera"]


@pytest.mark.asyncio
async def test_scan_no_match_pattern(live_scoped, mock_redis):
    """scan() with no match pattern passes None to the underlying client."""
    mock_redis.scan.return_value = (0, ["live:foo"])

    cursor, keys = await live_scoped.scan()

    mock_redis.scan.assert_called_once_with(0, match=None, count=None)
    assert keys == ["foo"]


# ── Pub/Sub ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_not_prefixed(live_scoped, mock_redis):
    """publish() does NOT prefix the channel name — channels are global."""
    mock_redis.publish.return_value = 2

    result = await live_scoped.publish("events:speech", '{"msg": "hello"}')

    # Channel must be passed as-is, without 'live:' prefix
    mock_redis.publish.assert_called_once_with("events:speech", '{"msg": "hello"}')
    assert result == 2


@pytest.mark.asyncio
async def test_publish_not_prefixed_sim_scoped(sim_scoped, mock_redis):
    """publish() does not prefix the channel even on sim-scoped instances."""
    await sim_scoped.publish("global:broadcast", "ping")

    mock_redis.publish.assert_called_once_with("global:broadcast", "ping")


# ── Cross-sim isolation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_sim_and_live_keys_are_distinct(mock_redis):
    """Keys for live and sim scopes never collide."""
    sim_id = uuid.uuid4()
    live = ScopedRedis(mock_redis, LIVE_SIMULATION_ID)
    sim = ScopedRedis(mock_redis, sim_id)

    assert live._key("foo") != sim._key("foo")
    assert live._key("foo") == "live:foo"
    assert sim._key("foo") == f"sim:{sim_id}:foo"


@pytest.mark.asyncio
async def test_two_sim_scopes_are_distinct(mock_redis):
    """Two different sim UUIDs produce distinct key prefixes."""
    sim_a = uuid.uuid4()
    sim_b = uuid.uuid4()
    scoped_a = ScopedRedis(mock_redis, sim_a)
    scoped_b = ScopedRedis(mock_redis, sim_b)

    assert scoped_a._key("data") != scoped_b._key("data")
