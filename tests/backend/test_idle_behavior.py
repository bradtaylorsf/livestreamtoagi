"""Tests for core.idle_behavior module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.idle_behavior import (
    AREA_POSITIONS,
    BEHAVIORS,
    DESK_POSITIONS,
    EXCLUDED_AGENTS,
    IdleBehaviorSystem,
)


@pytest.fixture()
def mock_registry() -> MagicMock:
    """Create a mock agent registry with active agents."""
    registry = MagicMock()

    def make_agent(agent_id: str, initiative: float) -> MagicMock:
        agent = MagicMock()
        agent.id = agent_id
        agent.initiative = initiative
        agent.status = "active"
        return agent

    agents = [
        make_agent("vera", 0.8),
        make_agent("rex", 0.2),
        make_agent("aurora", 0.5),
        make_agent("management", 0.0),  # excluded
    ]
    registry.get_active_agents.return_value = agents
    return registry


class TestIdleBehaviorSystem:
    def test_init(self, mock_registry: MagicMock) -> None:
        system = IdleBehaviorSystem(mock_registry)
        assert system._task is None

    def test_pick_agent_excludes_management_and_alpha(
        self, mock_registry: MagicMock
    ) -> None:
        system = IdleBehaviorSystem(mock_registry)
        # Run many picks — management should never be selected
        picked = set()
        for _ in range(100):
            agent_id = system._pick_agent()
            if agent_id:
                picked.add(agent_id)
        assert "management" not in picked
        assert "alpha" not in picked

    def test_pick_agent_returns_none_when_no_active(self) -> None:
        registry = MagicMock()
        registry.get_active_agents.return_value = []
        system = IdleBehaviorSystem(registry)
        assert system._pick_agent() is None

    def test_pick_agent_returns_none_when_only_excluded(self) -> None:
        registry = MagicMock()
        mgmt = MagicMock()
        mgmt.id = "management"
        mgmt.initiative = 0.0
        registry.get_active_agents.return_value = [mgmt]
        system = IdleBehaviorSystem(registry)
        assert system._pick_agent() is None

    @pytest.mark.asyncio()
    async def test_emit_move(self) -> None:
        # Positions are tile coordinates; _emit_move converts to pixels (tile * TILE_SIZE)
        from core.idle_behavior import TILE_SIZE
        with patch("core.idle_behavior.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            from_pos: dict[str, float] = {"x": 3.5, "y": 6.0}
            to_pos: dict[str, float] = {"x": 19.5, "y": 2.5}
            await IdleBehaviorSystem._emit_move("vera", from_pos, to_pos)
            mock_bus.emit.assert_called_once()
            call_args = mock_bus.emit.call_args
            assert call_args[0][0] == "agent_move"
            assert call_args[0][1]["agent_id"] == "vera"
            # Wire format is pixels
            assert call_args[0][1]["from"]["x"] == int(3.5 * TILE_SIZE)
            assert call_args[0][1]["to"]["x"] == int(19.5 * TILE_SIZE)
            assert call_args[0][1]["to"]["y"] == int(2.5 * TILE_SIZE)

    @pytest.mark.asyncio()
    async def test_emit_action(self) -> None:
        with patch("core.idle_behavior.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            await IdleBehaviorSystem._emit_action("rex", "thinking")
            mock_bus.emit.assert_called_once()
            call_args = mock_bus.emit.call_args
            assert call_args[0][0] == "agent_action"
            assert call_args[0][1]["agent_id"] == "rex"
            assert call_args[0][1]["action"] == "thinking"

    def test_weighted_choice_returns_valid_behavior(self) -> None:
        valid_names = {name for name, _ in BEHAVIORS}
        for _ in range(50):
            result = IdleBehaviorSystem._weighted_choice(BEHAVIORS)
            assert result in valid_names

    def test_desk_positions_match_expected_agents(self) -> None:
        expected = {"vera", "aurora", "sentinel", "grok", "rex", "fork", "pixel"}
        assert set(DESK_POSITIONS.keys()) == expected

    def test_excluded_agents(self) -> None:
        assert "management" in EXCLUDED_AGENTS
        assert "alpha" in EXCLUDED_AGENTS

    def test_area_positions_defined(self) -> None:
        assert "coffee_machine" in AREA_POSITIONS
        assert "whiteboard" in AREA_POSITIONS
        assert "meeting_area" in AREA_POSITIONS
        assert "workshop" in AREA_POSITIONS
        for pos in AREA_POSITIONS.values():
            assert "x" in pos
            assert "y" in pos

    @pytest.mark.asyncio()
    async def test_coffee_run_emits_events(
        self, mock_registry: MagicMock
    ) -> None:
        system = IdleBehaviorSystem(mock_registry)
        with patch("core.idle_behavior.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            with patch("core.idle_behavior.asyncio.sleep", new_callable=AsyncMock):
                await system._coffee_run("vera", DESK_POSITIONS["vera"])
            # Should emit: action + move to coffee + move back
            assert mock_bus.emit.call_count == 3

    def test_start_and_stop(self, mock_registry: MagicMock) -> None:
        system = IdleBehaviorSystem(mock_registry)
        # Mock create_task to avoid actually running the loop
        with patch("asyncio.create_task") as mock_create:
            mock_task = MagicMock()
            mock_task.done.return_value = False
            mock_create.return_value = mock_task

            system.start()
            assert system._task is not None
            mock_create.assert_called_once()

            system.stop()
            mock_task.cancel.assert_called_once()
