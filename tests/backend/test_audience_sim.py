"""Tests for audience simulation layer (Issue #215)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.simulation.audience_sim import (
    AudienceSimulator,
    _CHAT_POOLS,
    _DEFAULT_PERSONAS,
    _GROWTH_CURVES,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_redis_mock() -> AsyncMock:
    """Create a mock Redis client with basic get/set/rpush/ltrim/delete."""
    redis = AsyncMock()
    redis._store: dict[str, str] = {}
    redis._lists: dict[str, list[str]] = {}

    async def _get(key):
        return redis._store.get(key)

    async def _set(key, value, **kwargs):
        redis._store[key] = value

    async def _rpush(key, value):
        if key not in redis._lists:
            redis._lists[key] = []
        redis._lists[key].append(value)

    async def _ltrim(key, start, end):
        if key in redis._lists:
            redis._lists[key] = redis._lists[key][start:]

    async def _delete(key):
        redis._store.pop(key, None)
        redis._lists.pop(key, None)

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.rpush = AsyncMock(side_effect=_rpush)
    redis.ltrim = AsyncMock(side_effect=_ltrim)
    redis.delete = AsyncMock(side_effect=_delete)
    return redis


# ── Growth curves ────────────────────────────────────────────────


def test_growth_curves_slow():
    """Slow growth should reach ~20 viewers."""
    fn = _GROWTH_CURVES["slow"]
    assert fn(0) == 0
    assert fn(10) == 5
    assert fn(60) == 20  # capped


def test_growth_curves_medium():
    """Medium growth should reach ~100 viewers."""
    fn = _GROWTH_CURVES["medium"]
    assert fn(0) == 0
    assert fn(10) == 20
    assert fn(100) == 100  # capped


def test_growth_curves_fast():
    """Fast growth should reach ~500 viewers."""
    fn = _GROWTH_CURVES["fast"]
    assert fn(0) == 0
    assert fn(10) == 80
    assert fn(100) == 500  # capped


# ── AudienceSimulator ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_initial_state():
    """seed_initial_state should set viewer count and clear chat."""
    redis = _make_redis_mock()
    sim = AudienceSimulator(redis, {"initial_viewers": 5})
    await sim.seed_initial_state()

    redis.set.assert_any_call("audience:viewer_count", "5")
    redis.delete.assert_called_with("audience:recent_chat")


@pytest.mark.asyncio
async def test_tick_updates_viewer_count():
    """A single tick should update the viewer count in Redis."""
    redis = _make_redis_mock()
    sim = AudienceSimulator(redis, {
        "initial_viewers": 0,
        "growth_rate": "slow",
        "chat_frequency": "quiet",
    })
    sim._start_time = 0  # Simulate some time passed
    # Manually set start time to make elapsed_minutes ~10
    import time
    sim._start_time = time.monotonic() - 600  # 10 minutes ago
    await sim._tick()

    # Viewer count should have been set
    redis.set.assert_called()
    calls = [c for c in redis.set.call_args_list if c[0][0] == "audience:viewer_count"]
    assert len(calls) >= 1
    viewer_count = int(calls[-1][0][1])
    assert viewer_count >= 5  # 10 minutes * 0.5 = 5


@pytest.mark.asyncio
async def test_inject_chat_message():
    """_inject_chat_message should add a message to Redis."""
    redis = _make_redis_mock()
    sim = AudienceSimulator(redis, {"viewer_personas": _DEFAULT_PERSONAS})
    await sim._inject_chat_message()

    redis.rpush.assert_called_once()
    key = redis.rpush.call_args[0][0]
    assert key == "audience:recent_chat"
    msg = json.loads(redis.rpush.call_args[0][1])
    assert "user" in msg
    assert "text" in msg
    assert "timestamp" in msg


@pytest.mark.asyncio
async def test_vote_on_active_poll():
    """Votes should be added to active polls."""
    redis = _make_redis_mock()
    sim = AudienceSimulator(redis)

    # Set up an active poll
    poll_id = "test-poll-123"
    redis._store["poll:active"] = poll_id
    redis._store[f"poll:{poll_id}"] = json.dumps({
        "options": ["Option A", "Option B"],
        "votes": {"Option A": 0, "Option B": 0},
    })

    await sim._vote_on_active_poll()

    # Votes should have been added
    updated_raw = redis._store.get(f"poll:{poll_id}")
    assert updated_raw is not None
    updated = json.loads(updated_raw)
    total_votes = sum(updated["votes"].values())
    assert total_votes >= 1


@pytest.mark.asyncio
async def test_no_vote_without_active_poll():
    """No crash when there's no active poll."""
    redis = _make_redis_mock()
    sim = AudienceSimulator(redis)
    await sim._vote_on_active_poll()  # Should not raise


def test_default_personas_exist():
    """Default personas should have chat pools available."""
    for persona in _DEFAULT_PERSONAS:
        style = persona["style"]
        assert style in _CHAT_POOLS, f"Missing chat pool for style: {style}"
        assert len(_CHAT_POOLS[style]) >= 3


@pytest.mark.asyncio
async def test_start_stop_lifecycle():
    """Start/stop should work without error."""
    redis = _make_redis_mock()
    sim = AudienceSimulator(redis)
    assert not sim._running

    # start() creates a task
    sim.start()
    assert sim._running
    assert sim._task is not None

    # stop() should cancel cleanly
    await sim.stop()
    assert not sim._running


# ── Scenario config ──────────────────────────────────────────────


def test_awakening_yaml_has_audience_config():
    """awakening.yaml should contain audience configuration."""
    import yaml
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent.parent / "scenarios" / "awakening.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)

    assert "audience" in data
    audience = data["audience"]
    assert "initial_viewers" in audience
    assert "growth_rate" in audience
    assert "viewer_personas" in audience
    assert len(audience["viewer_personas"]) >= 3


# ── Infrastructure prompt ────────────────────────────────────────


def test_infrastructure_prompt_has_low_viewer_guidance():
    """INFRASTRUCTURE_PROMPT should guide agents on low viewer counts."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    assert "zero viewers" in INFRASTRUCTURE_PROMPT.lower() or "viewer count" in INFRASTRUCTURE_PROMPT.lower()
    assert "day one" in INFRASTRUCTURE_PROMPT.lower() or "exciting" in INFRASTRUCTURE_PROMPT.lower()
