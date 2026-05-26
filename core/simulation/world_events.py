"""Headless world-event scheduler (issue #854).

Distinct from :mod:`core.events.event_generator` (random show-novelty
events) and :mod:`core.simulation.world_simulator` (background persona
chatter): the :class:`WorldEventScheduler` produces the **environmental
triggers** that an embodied agent would normally read from Minecraft —
nightfall, weather changes, hunger pangs, nearby enemies. In headless
mode it's the only source of these signals; in embodied mode a scenario
can opt out via ``disable_world_event_scheduler: true`` to let real
Minecraft events take over.

The scheduler is purely deterministic given a fixed seed.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Canonical event-type vocabulary. Authoring a scenario with an unknown
# event_type fails scenario-schema validation via the lookup below.
WorldEventType = Literal[
    "hunger_critical",
    "sleep_critical",
    "energy_critical",
    "social_critical",
    "safety_critical",
    "enemy_nearby",
    "nightfall",
    "dawn",
    "weather_change",
    "low_health",
    "resource_depleted",
    "home_unsafe",
]
WORLD_EVENT_TYPES: tuple[str, ...] = (
    "hunger_critical",
    "sleep_critical",
    "energy_critical",
    "social_critical",
    "safety_critical",
    "enemy_nearby",
    "nightfall",
    "dawn",
    "weather_change",
    "low_health",
    "resource_depleted",
    "home_unsafe",
)


class WorldEvent(BaseModel):
    """A single event emitted on a tick (scheduled or probabilistic)."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    tick: int
    trigger: Literal["scheduled", "probabilistic"]
    source: str = "world_event_scheduler"
    actor_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WorldEventScheduler:
    """Owns the per-tick world-event emission loop for one run.

    The scheduler is seeded so two runs with the same scenario + seed
    produce the same event stream. Active state — which scheduled events
    have already fired and which gating events have been triggered — is
    held internally so tests can introspect after a run.
    """

    def __init__(
        self,
        *,
        schedule: Iterable[dict[str, Any]] | None = None,
        probabilistic: Iterable[dict[str, Any]] | None = None,
        seed: int | None = None,
    ) -> None:
        # Defensive copy so the caller's lists aren't mutated.
        self._schedule: list[dict[str, Any]] = [dict(item) for item in schedule or []]
        self._probabilistic: list[dict[str, Any]] = [dict(item) for item in probabilistic or []]
        self._scheduled_fired: set[int] = set()
        self._active_gates: set[str] = set()
        self._rng = random.Random(seed)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        *,
        seed: int | None = None,
    ) -> WorldEventScheduler:
        """Build a scheduler from a parsed ``world_events:`` block."""
        if not config:
            return cls(seed=seed)
        return cls(
            schedule=config.get("schedule") or [],
            probabilistic=config.get("probabilistic") or [],
            seed=seed,
        )

    @property
    def active_gates(self) -> frozenset[str]:
        return frozenset(self._active_gates)

    def tick(self, sim_tick: int) -> list[WorldEvent]:
        """Emit any events that fire on ``sim_tick``."""
        emitted: list[WorldEvent] = []

        # Scheduled events fire exactly once when their tick is reached.
        for idx, entry in enumerate(self._schedule):
            if idx in self._scheduled_fired:
                continue
            target = entry.get("tick")
            if not isinstance(target, int) or target > sim_tick:
                continue
            event_type = entry.get("event")
            if not isinstance(event_type, str):
                continue
            self._scheduled_fired.add(idx)
            self._activate_gate(event_type)
            emitted.append(
                WorldEvent(
                    event_type=event_type,
                    tick=sim_tick,
                    trigger="scheduled",
                    details={"scheduled_tick": target},
                )
            )

        # Probabilistic events check their per-tick probability after the
        # scheduled batch so a ``requires`` gate that just activated this
        # tick can already be honored.
        for entry in self._probabilistic:
            event_type = entry.get("event")
            if not isinstance(event_type, str):
                continue
            requires = entry.get("requires")
            if requires and requires not in self._active_gates:
                continue
            prob = float(entry.get("prob_per_tick", 0.0))
            if prob <= 0.0:
                continue
            if self._rng.random() < prob:
                self._activate_gate(event_type)
                emitted.append(
                    WorldEvent(
                        event_type=event_type,
                        tick=sim_tick,
                        trigger="probabilistic",
                        details={"prob_per_tick": prob, "requires": requires},
                    )
                )

        return emitted

    def force(self, event_type: str, sim_tick: int) -> WorldEvent:
        """Inject an event manually (mainly for tests / runtime hooks)."""
        self._activate_gate(event_type)
        return WorldEvent(
            event_type=event_type,
            tick=sim_tick,
            trigger="scheduled",
            details={"forced": True},
        )

    def reset(self) -> None:
        self._scheduled_fired.clear()
        self._active_gates.clear()

    def _activate_gate(self, event_type: str) -> None:
        """Update the gating set used by ``requires:`` checks.

        Dawn/nightfall behave like a toggle pair so probabilistic events
        gated on ``nightfall`` stop firing after ``dawn``.
        """
        if event_type == "dawn":
            self._active_gates.discard("nightfall")
            self._active_gates.add("dawn")
            return
        if event_type == "nightfall":
            self._active_gates.discard("dawn")
            self._active_gates.add("nightfall")
            return
        self._active_gates.add(event_type)


__all__ = [
    "WORLD_EVENT_TYPES",
    "WorldEvent",
    "WorldEventScheduler",
    "WorldEventType",
]
