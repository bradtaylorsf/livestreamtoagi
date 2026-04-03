"""Unit tests for the proximity group manager."""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.conversation.proximity import _LOCATION_KEY_PREFIX, ProximityManager
from core.models import AgentConfig, ConversationConfig
from tests.backend.conversation_helpers import make_agent_config, make_conversation_config

# ── Helpers ───────────────────────────────────────────────


def _make_agent(
    agent_id: str,
    *,
    eavesdrop_tendency: float = 0.3,
) -> AgentConfig:
    return make_agent_config(agent_id, eavesdrop_tendency=eavesdrop_tendency)


def _make_config(**overrides) -> ConversationConfig:
    proximity_defaults = {
        "proximity": {
            "enabled": True,
            "max_conversation_size": 5,
            "eavesdrop_tendency": {
                "pixel": 0.7,
                "grok": 0.8,
                "rex": 0.2,
            },
        },
    }
    proximity_defaults.update(overrides)
    return make_conversation_config(**proximity_defaults)


def _make_redis_mock(locations: dict[str, str] | None = None) -> MagicMock:
    """Create a mock RedisClient that stores agent locations in memory.

    ``locations`` maps agent_id → chunk_name.
    """
    locations = dict(locations or {})
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
        return (0, matched)  # return cursor=0 to signal done

    async def fake_get(key: str) -> str | None:
        return store.get(key)

    async def fake_set(key: str, value: str, *, ex: int | None = None) -> bool:
        store[key] = value
        return True

    mock.client.scan = fake_scan
    mock.get = AsyncMock(side_effect=fake_get)
    mock.set = AsyncMock(side_effect=fake_set)

    return mock


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit = AsyncMock()
    return bus


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def config() -> ConversationConfig:
    return _make_config()


# ── Tests ─────────────────────────────────────────────────


class TestGetGroup:
    """get_group returns agents in the specified chunk."""

    @pytest.mark.asyncio
    async def test_agents_in_same_chunk(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock({"vera": "office", "rex": "office", "aurora": "garden"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        group = await pm.get_group("office")
        assert sorted(group) == ["rex", "vera"]

    @pytest.mark.asyncio
    async def test_agents_in_different_chunks(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock({"vera": "office", "rex": "garden"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        office_group = await pm.get_group("office")
        assert office_group == ["vera"]

        garden_group = await pm.get_group("garden")
        assert garden_group == ["rex"]

    @pytest.mark.asyncio
    async def test_empty_chunk(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock({"vera": "office"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        group = await pm.get_group("garden")
        assert group == []


class TestGetEligibleSpeakers:
    """get_eligible_speakers caps at max_conversation_size."""

    @pytest.mark.asyncio
    async def test_caps_at_max_conversation_size(self) -> None:
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 3,
                "eavesdrop_tendency": {},
            },
        )
        agents_in_chunk = {
            "vera": "office",
            "rex": "office",
            "aurora": "office",
            "pixel": "office",
            "fork": "office",
        }
        redis = _make_redis_mock(agents_in_chunk)
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [_make_agent(aid) for aid in agents_in_chunk]
        eligible = await pm.get_eligible_speakers("office", all_agents)

        assert len(eligible) == 3

    @pytest.mark.asyncio
    async def test_returns_only_agents_in_chunk(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock({"vera": "office", "rex": "garden"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [_make_agent("vera"), _make_agent("rex")]
        eligible = await pm.get_eligible_speakers("office", all_agents)

        assert len(eligible) == 1
        assert eligible[0].id == "vera"


class TestCheckEavesdroppers:
    """Eavesdropping: agents in adjacent chunks may walk over."""

    @pytest.mark.asyncio
    async def test_high_tendency_and_relevance_joins(self, config: ConversationConfig) -> None:
        """Grok (eavesdrop_tendency=0.8) hearing a code topic (relevance=0.3 default).

        Probability = 0.8 * 0.6 + 0.3 * 0.4 = 0.48 + 0.12 = 0.60
        Seed random to return < 0.60 so grok joins.
        """
        redis = _make_redis_mock({"vera": "office", "grok": "garden"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [_make_agent("vera"), _make_agent("grok", eavesdrop_tendency=0.8)]

        random.seed(42)  # random.random() with seed 42 → 0.639... then 0.025...
        # We need random() < 0.60, so try a seed that works
        # Let's just mock random.random directly
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(random, "random", lambda: 0.1)  # Always < 0.60
            joiners = await pm.check_eavesdroppers(
                "office", "general", all_agents, ["garden"],
            )

        assert "grok" in joiners
        bus.emit.assert_called_once()
        call_args = bus.emit.call_args
        assert call_args[0][0] == "agent_move"
        assert call_args[0][1]["agent_id"] == "grok"
        assert call_args[0][1]["reason"] == "eavesdrop"

    @pytest.mark.asyncio
    async def test_low_tendency_stays_put(self, config: ConversationConfig) -> None:
        """Rex (eavesdrop_tendency=0.2) with default relevance (0.3).

        Probability = 0.2 * 0.6 + 0.3 * 0.4 = 0.12 + 0.12 = 0.24
        With random() returning 0.5, rex stays put.
        """
        redis = _make_redis_mock({"vera": "office", "rex": "workshop"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [_make_agent("vera"), _make_agent("rex", eavesdrop_tendency=0.2)]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(random, "random", lambda: 0.5)  # > 0.24
            joiners = await pm.check_eavesdroppers(
                "office", "general", all_agents, ["workshop"],
            )

        assert joiners == []
        bus.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_eavesdropping_respects_max_conversation_size(self) -> None:
        """If the conversation is already at max size, no eavesdroppers join."""
        config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 2,
                "eavesdrop_tendency": {"grok": 0.8, "pixel": 0.7},
            },
        )
        # 2 agents already in office = at max
        redis = _make_redis_mock({
            "vera": "office",
            "rex": "office",
            "grok": "garden",
            "pixel": "garden",
        })
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [
            _make_agent("vera"),
            _make_agent("rex"),
            _make_agent("grok", eavesdrop_tendency=0.8),
            _make_agent("pixel", eavesdrop_tendency=0.7),
        ]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(random, "random", lambda: 0.01)  # Would always join
            joiners = await pm.check_eavesdroppers(
                "office", "code", all_agents, ["garden"],
            )

        assert joiners == []

    @pytest.mark.asyncio
    async def test_agent_move_event_emitted(self, config: ConversationConfig) -> None:
        """Verify the agent_move event payload when an eavesdropper joins."""
        redis = _make_redis_mock({"vera": "office", "pixel": "garden"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        all_agents = [_make_agent("vera"), _make_agent("pixel", eavesdrop_tendency=0.7)]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(random, "random", lambda: 0.01)
            await pm.check_eavesdroppers(
                "office", "art", all_agents, ["garden"],
            )

        bus.emit.assert_called_once()
        event_data = bus.emit.call_args[0][1]
        assert event_data["agent_id"] == "pixel"
        assert event_data["from_chunk"] == "garden"
        assert event_data["to_chunk"] == "office"
        assert event_data["reason"] == "eavesdrop"
        assert event_data["topic"] == "art"


class TestUpdateLocation:
    """update_location stores position in Redis."""

    @pytest.mark.asyncio
    async def test_returns_previous_location(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock({"vera": "office"})
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        previous = await pm.update_location("vera", "garden")
        assert previous == "office"

    @pytest.mark.asyncio
    async def test_returns_none_for_new_agent(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock()
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        previous = await pm.update_location("vera", "office")
        assert previous is None


class TestConfigHotReload:
    """Config property supports hot-reload."""

    def test_config_setter(self, config: ConversationConfig) -> None:
        redis = _make_redis_mock()
        bus = _make_event_bus()
        pm = ProximityManager(redis, config, bus)

        new_config = _make_config(
            proximity={
                "enabled": True,
                "max_conversation_size": 3,
                "eavesdrop_tendency": {},
            },
        )
        pm.config = new_config
        assert pm.config.proximity.max_conversation_size == 3
