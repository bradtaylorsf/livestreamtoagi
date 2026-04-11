"""Tests for weighted speaker selection in ProximityManager."""

from __future__ import annotations

import time
from collections import Counter
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.conversation.proximity import ProximityManager, _LOCATION_KEY_PREFIX
from tests.backend.conversation_helpers import make_agent_config, make_conversation_config


# ── Helpers ───────────────────────────────────────────────────


def _make_config(**overrides):
    proximity_defaults = {
        "proximity": {
            "enabled": True,
            "max_conversation_size": 3,
            "eavesdrop_tendency": {},
        },
    }
    proximity_defaults.update(overrides)
    return make_conversation_config(**proximity_defaults)


def _make_redis_mock(locations: dict[str, str]) -> MagicMock:
    store: dict[str, str] = {
        f"{_LOCATION_KEY_PREFIX}{aid}": chunk
        for aid, chunk in locations.items()
    }

    mock = MagicMock()
    mock.client = MagicMock()

    async def fake_scan(
        cursor: int | str = 0, *, match: str = "*", count: int = 50,
    ) -> tuple[int, list[str]]:
        prefix = match.replace("*", "")
        matched = [k for k in store if k.startswith(prefix)]
        return (0, matched)

    async def fake_get(key: str) -> str | None:
        return store.get(key)

    async def fake_set(key: str, value: str, *, ex: int | None = None) -> bool:
        store[key] = value
        return True

    mock.scan = AsyncMock(side_effect=fake_scan)
    mock.get = AsyncMock(side_effect=fake_get)
    mock.set = AsyncMock(side_effect=fake_set)
    return mock


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit = AsyncMock()
    return bus


# ── Tests ─────────────────────────────────────────────────────


class TestWeightedSelection:
    """get_eligible_speakers uses weighted random selection."""

    @pytest.mark.asyncio
    async def test_returns_different_sets_across_calls(self) -> None:
        """Over many calls, the selected agent sets should vary."""
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 3,
                "eavesdrop_tendency": {},
            },
        )
        agents_map = {
            "vera": "office",
            "rex": "office",
            "aurora": "office",
            "pixel": "office",
            "fork": "office",
            "sentinel": "office",
        }
        redis = _make_redis_mock(agents_map)
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [make_agent_config(aid) for aid in agents_map]

        seen_sets: set[frozenset[str]] = set()
        for _ in range(30):
            eligible = await pm.get_eligible_speakers("office", all_agents)
            assert len(eligible) == 3
            seen_sets.add(frozenset(a.id for a in eligible))

        # With 6 agents and weighted random, we should see multiple distinct sets
        assert len(seen_sets) > 1, "Selection should not always return the same set"

    @pytest.mark.asyncio
    async def test_vera_and_sentinel_can_appear(self) -> None:
        """Vera and Sentinel should appear in results thanks to role bonuses."""
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 3,
                "eavesdrop_tendency": {},
            },
        )
        agents_map = {
            "vera": "office",
            "rex": "office",
            "aurora": "office",
            "pixel": "office",
            "fork": "office",
            "sentinel": "office",
        }
        redis = _make_redis_mock(agents_map)
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [make_agent_config(aid) for aid in agents_map]

        vera_seen = False
        sentinel_seen = False
        for _ in range(50):
            eligible = await pm.get_eligible_speakers("office", all_agents)
            ids = {a.id for a in eligible}
            if "vera" in ids:
                vera_seen = True
            if "sentinel" in ids:
                sentinel_seen = True
            if vera_seen and sentinel_seen:
                break

        assert vera_seen, "Vera should appear in eligible speakers"
        assert sentinel_seen, "Sentinel should appear in eligible speakers"

    @pytest.mark.asyncio
    async def test_record_spoke_affects_weights(self) -> None:
        """Agents who recently spoke should be less likely to be selected."""
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 2,
                "eavesdrop_tendency": {},
            },
        )
        agents_map = {"vera": "office", "rex": "office", "aurora": "office"}
        redis = _make_redis_mock(agents_map)
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [make_agent_config(aid) for aid in agents_map]

        # Mark vera and rex as having just spoken
        pm.record_spoke("vera")
        pm.record_spoke("rex")

        # Aurora hasn't spoken, so should be selected more often
        counts: Counter[str] = Counter()
        for _ in range(100):
            eligible = await pm.get_eligible_speakers("office", all_agents)
            for a in eligible:
                counts[a.id] += 1

        # Aurora should appear more frequently than either vera or rex
        assert counts["aurora"] > counts.get("vera", 0) or counts["aurora"] > counts.get("rex", 0), (
            f"Aurora (never spoke) should be selected more often: {counts}"
        )

    @pytest.mark.asyncio
    async def test_required_agents_always_included(self) -> None:
        """Required agents must always appear in the result."""
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 3,
                "eavesdrop_tendency": {},
            },
        )
        agents_map = {
            "vera": "office",
            "rex": "office",
            "aurora": "office",
            "pixel": "office",
            "fork": "office",
        }
        redis = _make_redis_mock(agents_map)
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [make_agent_config(aid) for aid in agents_map]

        for _ in range(20):
            eligible = await pm.get_eligible_speakers(
                "office", all_agents, required_agents={"vera", "sentinel"},
            )
            ids = {a.id for a in eligible}
            # vera is in the chunk and required — must be present
            assert "vera" in ids, "Required agent vera should always be included"
            assert len(eligible) == 3

    @pytest.mark.asyncio
    async def test_small_group_returns_all(self) -> None:
        """When eligible <= max_size, all agents are returned."""
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 5,
                "eavesdrop_tendency": {},
            },
        )
        agents_map = {"vera": "office", "rex": "office"}
        redis = _make_redis_mock(agents_map)
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [make_agent_config(aid) for aid in agents_map]
        eligible = await pm.get_eligible_speakers("office", all_agents)
        assert len(eligible) == 2


class TestRecordSpoke:
    """record_spoke tracks when agents last spoke."""

    def test_record_spoke_updates_timestamp(self) -> None:
        config = _make_config()
        redis = MagicMock()
        bus = MagicMock()
        pm = ProximityManager(redis, config, bus)

        before = time.monotonic()
        pm.record_spoke("vera")
        after = time.monotonic()

        assert "vera" in pm._last_spoke
        assert before <= pm._last_spoke["vera"] <= after
