"""Backend idle behavior system.

Periodically emits movement and action events for active agents,
creating ambient activity in the office (wandering to coffee machine,
visiting other agents, using the whiteboard, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from core.event_bus import EventType, event_bus

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)

# Known office locations in pixel coordinates (tile * 32 + 16 for center)
AREA_POSITIONS: dict[str, dict[str, int]] = {
    "coffee_machine": {"x": 19 * 32 + 16, "y": 2 * 32 + 16},
    "meeting_area": {"x": 16 * 32 + 16, "y": 9 * 32 + 16},
    "workshop": {"x": 16 * 32 + 16, "y": 14 * 32 + 16},
    "whiteboard": {"x": 33 * 32 + 16, "y": 17 * 32 + 16},
}

# Agent desk positions matching frontend agents.ts
DESK_POSITIONS: dict[str, dict[str, int]] = {
    "vera": {"x": 2 * 32 + 48, "y": 6 * 32},
    "aurora": {"x": 10 * 32 + 48, "y": 6 * 32},
    "sentinel": {"x": 24 * 32 + 48, "y": 6 * 32},
    "grok": {"x": 33 * 32 + 48, "y": 6 * 32},
    "rex": {"x": 2 * 32 + 48, "y": 16 * 32},
    "fork": {"x": 10 * 32 + 48, "y": 16 * 32},
    "pixel": {"x": 24 * 32 + 48, "y": 16 * 32},
}

# Behavior types with relative weights
BEHAVIORS: list[tuple[str, float]] = [
    ("coffee_run", 0.3),
    ("visit_agent", 0.25),
    ("whiteboard", 0.2),
    ("wander", 0.25),
]

# Idle agents excluded from wandering behaviors
EXCLUDED_AGENTS = frozenset({"management", "alpha"})

# Interval range between behavior triggers (seconds)
MIN_INTERVAL_S = 30
MAX_INTERVAL_S = 60


class IdleBehaviorSystem:
    """Emits ambient movement/action events for active agents."""

    def __init__(self, agent_registry: AgentRegistry) -> None:
        self._registry = agent_registry
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the idle behavior loop as a background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())
            logger.info("IdleBehaviorSystem started")

    def stop(self) -> None:
        """Stop the idle behavior loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("IdleBehaviorSystem stopped")

    async def _run_loop(self) -> None:
        """Main loop: sleep, pick an agent, emit a behavior."""
        try:
            while True:
                interval = random.uniform(MIN_INTERVAL_S, MAX_INTERVAL_S)
                await asyncio.sleep(interval)

                agent = self._pick_agent()
                if agent is None:
                    continue

                await self._emit_behavior(agent)
        except asyncio.CancelledError:
            pass

    def _pick_agent(self) -> str | None:
        """Pick an active agent weighted by initiative."""
        agents = [
            a
            for a in self._registry.get_active_agents()
            if a.id not in EXCLUDED_AGENTS
        ]
        if not agents:
            return None

        weights = [a.initiative for a in agents]
        total = sum(weights)
        if total == 0:
            return random.choice(agents).id

        chosen = random.choices(agents, weights=weights, k=1)[0]
        return chosen.id

    async def _emit_behavior(self, agent_id: str) -> None:
        """Emit events for a randomly selected behavior."""
        behavior = self._weighted_choice(BEHAVIORS)
        desk = DESK_POSITIONS.get(agent_id)
        if desk is None:
            return

        if behavior == "coffee_run":
            await self._coffee_run(agent_id, desk)
        elif behavior == "visit_agent":
            await self._visit_agent(agent_id, desk)
        elif behavior == "whiteboard":
            await self._whiteboard(agent_id, desk)
        elif behavior == "wander":
            await self._wander(agent_id, desk)

    async def _coffee_run(
        self, agent_id: str, desk: dict[str, int]
    ) -> None:
        """Walk to coffee machine, pause, walk back."""
        target = AREA_POSITIONS["coffee_machine"]
        await self._emit_action(agent_id, "getting_coffee")
        await self._emit_move(agent_id, desk, target)
        await asyncio.sleep(random.uniform(5, 10))
        await self._emit_move(agent_id, target, desk)

    async def _visit_agent(
        self, agent_id: str, desk: dict[str, int]
    ) -> None:
        """Walk to another agent's desk, pause, walk back."""
        others = [aid for aid in DESK_POSITIONS if aid != agent_id]
        if not others:
            return
        target_id = random.choice(others)
        target_desk = DESK_POSITIONS[target_id]
        # Stand near their desk (offset slightly)
        near = {"x": target_desk["x"] + 32, "y": target_desk["y"]}

        await self._emit_action(agent_id, "visiting")
        await self._emit_move(agent_id, desk, near)
        await asyncio.sleep(random.uniform(5, 15))
        await self._emit_move(agent_id, near, desk)

    async def _whiteboard(
        self, agent_id: str, desk: dict[str, int]
    ) -> None:
        """Walk to whiteboard, think, walk back."""
        target = AREA_POSITIONS["whiteboard"]
        await self._emit_action(agent_id, "thinking")
        await self._emit_move(agent_id, desk, target)
        await asyncio.sleep(random.uniform(5, 12))
        await self._emit_move(agent_id, target, desk)

    async def _wander(
        self, agent_id: str, desk: dict[str, int]
    ) -> None:
        """Wander to a random area and back."""
        area_name = random.choice(list(AREA_POSITIONS.keys()))
        target = AREA_POSITIONS[area_name]
        await self._emit_action(agent_id, "thinking")
        await self._emit_move(agent_id, desk, target)
        await asyncio.sleep(random.uniform(3, 8))
        await self._emit_move(agent_id, target, desk)

    @staticmethod
    async def _emit_move(
        agent_id: str,
        from_pos: dict[str, int],
        to_pos: dict[str, int],
    ) -> None:
        await event_bus.emit(
            EventType.AGENT_MOVE,
            {
                "agent_id": agent_id,
                "from": {"x": from_pos["x"], "y": from_pos["y"]},
                "to": {"x": to_pos["x"], "y": to_pos["y"]},
            },
        )

    @staticmethod
    async def _emit_action(agent_id: str, action: str) -> None:
        await event_bus.emit(
            EventType.AGENT_ACTION,
            {"agent_id": agent_id, "action": action},
        )

    @staticmethod
    def _weighted_choice(items: list[tuple[str, float]]) -> str:
        names = [name for name, _ in items]
        weights = [w for _, w in items]
        return random.choices(names, weights=weights, k=1)[0]
