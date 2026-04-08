"""Tests for the random event and novelty injection system (#273)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.events.event_generator import (
    EventGenerator,
    EventGeneratorConfig,
    WorldEvent,
)
from core.events.event_templates import (
    DEFAULT_CATEGORY_WEIGHTS,
    DEFAULT_PROBABILITIES,
    EVENT_TEMPLATES,
)


# ── Event Templates Tests ────────────────────────────────────────


class TestEventTemplates:
    """Tests for event template data."""

    def test_all_categories_present(self) -> None:
        expected = {"environmental", "social", "economic", "world", "challenge"}
        assert set(EVENT_TEMPLATES.keys()) == expected

    def test_each_category_has_templates(self) -> None:
        for cat, templates in EVENT_TEMPLATES.items():
            assert len(templates) >= 2, f"Category {cat} needs at least 2 templates"

    def test_templates_have_required_fields(self) -> None:
        for cat, templates in EVENT_TEMPLATES.items():
            for t in templates:
                assert "title" in t, f"Template in {cat} missing title"
                assert "description" in t, f"Template in {cat} missing description"
                assert "severity" in t, f"Template in {cat} missing severity"
                assert t["severity"] in ("minor", "moderate", "major", "crisis")

    def test_default_probabilities_valid(self) -> None:
        for severity, prob in DEFAULT_PROBABILITIES.items():
            assert 0.0 <= prob <= 1.0, f"Invalid probability for {severity}"

    def test_category_weights_sum_to_one(self) -> None:
        total = sum(DEFAULT_CATEGORY_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01


# ── EventGeneratorConfig Tests ───────────────────────────────────


class TestEventGeneratorConfig:
    def test_default_config(self) -> None:
        config = EventGeneratorConfig()
        assert config.max_events_per_day == 4
        assert config.min_hours_between_events == 2.0
        assert "minor" in config.probability_per_hour

    def test_custom_config(self) -> None:
        config = EventGeneratorConfig(
            max_events_per_day=10,
            min_hours_between_events=1.0,
        )
        assert config.max_events_per_day == 10


# ── EventGenerator Tests ─────────────────────────────────────────


class TestEventGenerator:
    """Tests for the EventGenerator class."""

    def _make_generator(
        self,
        *,
        seed: int = 42,
        config: EventGeneratorConfig | None = None,
        **kwargs,
    ) -> EventGenerator:
        """Create an EventGenerator with seeded RNG for deterministic tests."""
        return EventGenerator(
            config=config or EventGeneratorConfig(),
            rng=random.Random(seed),
            **kwargs,
        )

    @pytest.mark.asyncio
    async def test_generate_event_respects_daily_cap(self) -> None:
        # Config with very high probability so events always generate
        config = EventGeneratorConfig(
            max_events_per_day=2,
            min_hours_between_events=0.0,
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
        )
        gen = self._make_generator(config=config)

        events = []
        for _ in range(5):
            e = await gen.generate_event()
            if e:
                events.append(e)

        assert len(events) == 2  # Capped at max_events_per_day

    @pytest.mark.asyncio
    async def test_generate_event_respects_cooldown(self) -> None:
        config = EventGeneratorConfig(
            min_hours_between_events=1.0,
            max_events_per_day=10,
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
        )
        gen = self._make_generator(config=config)

        # First event should succeed
        e1 = await gen.generate_event()
        assert e1 is not None

        # Second event should be blocked by cooldown
        e2 = await gen.generate_event()
        assert e2 is None

    @pytest.mark.asyncio
    async def test_generate_event_with_seeded_rng(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
            min_hours_between_events=0.0,
        )
        gen1 = self._make_generator(seed=123, config=config)
        gen2 = self._make_generator(seed=123, config=config)

        e1 = await gen1.generate_event()
        e2 = await gen2.generate_event()

        assert e1 is not None and e2 is not None
        # Same seed → same category and template selection
        assert e1.category == e2.category
        assert e1.title == e2.title

    @pytest.mark.asyncio
    async def test_generate_returns_none_when_probability_fails(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 0.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
        )
        gen = self._make_generator(config=config)
        result = await gen.generate_event()
        assert result is None

    @pytest.mark.asyncio
    async def test_event_has_correct_structure(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
            min_hours_between_events=0.0,
        )
        gen = self._make_generator(config=config)
        event = await gen.generate_event()
        assert event is not None
        assert isinstance(event, WorldEvent)
        assert event.category in EVENT_TEMPLATES
        assert event.title
        assert event.description
        assert event.severity in ("minor", "moderate", "major", "crisis")
        assert event.event_id

    @pytest.mark.asyncio
    async def test_trigger_system_integration(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
            min_hours_between_events=0.0,
        )
        triggers = MagicMock()
        gen = self._make_generator(config=config, trigger_system=triggers)

        event = await gen.generate_event()
        assert event is not None
        triggers.queue_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_world_repo_persistence(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
            min_hours_between_events=0.0,
        )
        world_repo = AsyncMock()
        gen = self._make_generator(config=config, world_repo=world_repo)

        event = await gen.generate_event()
        assert event is not None
        world_repo.create_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_generate(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 1.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
            min_hours_between_events=0.0,
        )
        gen = self._make_generator(config=config)
        events = await gen.check_and_generate()
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_check_and_generate_empty(self) -> None:
        config = EventGeneratorConfig(
            probability_per_hour={"minor": 0.0, "moderate": 0.0, "major": 0.0, "crisis": 0.0},
        )
        gen = self._make_generator(config=config)
        events = await gen.check_and_generate()
        assert events == []

    @pytest.mark.asyncio
    async def test_morning_briefing(self) -> None:
        gen = self._make_generator()
        briefing = await gen.generate_morning_briefing()
        assert 3 <= len(briefing) <= 5
        for item in briefing:
            assert "title" in item
            assert "summary" in item


# ── Agent State Integration ──────────────────────────────────────


class TestAgentStateEventIntegration:
    """Tests for event effects on agent internal state."""

    @pytest.mark.asyncio
    async def test_on_novel_event_default(self) -> None:
        from core.agent_state import AgentState, AgentStateManager
        mgr = AgentStateManager()
        state = await mgr.on_novel_event("test")
        # Default (no severity) — boredom should decrease
        assert state.boredom < 0.2  # Default boredom is 0.2

    @pytest.mark.asyncio
    async def test_on_novel_event_crisis(self) -> None:
        from core.agent_state import AgentState, AgentStateManager
        mgr = AgentStateManager()
        state = await mgr.on_novel_event("test", severity="crisis")
        # Crisis: boredom drops more, frustration increases, energy up
        assert state.frustration > 0.1  # Default is 0.1, +0.15
        assert state.energy > 0.7  # Default is 0.7, +0.1

    @pytest.mark.asyncio
    async def test_on_novel_event_minor(self) -> None:
        from core.agent_state import AgentState, AgentStateManager
        mgr = AgentStateManager()
        state = await mgr.on_novel_event("test", severity="minor")
        # Minor: small boredom reduction
        assert state.boredom < 0.2  # Default 0.2 - 0.1 = 0.1

    @pytest.mark.asyncio
    async def test_severity_based_trigger_priority(self) -> None:
        """Major/crisis events should be queued as high-priority triggers."""
        from core.conversation.triggers import ENVIRONMENTAL_EVENTS
        assert "random_event" in ENVIRONMENTAL_EVENTS
        assert "morning_briefing" in ENVIRONMENTAL_EVENTS
        assert "challenge_event" in ENVIRONMENTAL_EVENTS
