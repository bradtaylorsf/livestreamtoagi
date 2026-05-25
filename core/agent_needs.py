"""Per-agent needs state machine (issue #854).

In embodied mode, hunger / sleep / safety / social signals come from the
Minecraft world. In headless mode, this module is the substitute: it
ticks each agent's needs forward deterministically given a fixed seed,
emits threshold-crossing events (e.g. ``hunger_critical``) for the
:class:`~core.simulation.world_events.WorldEventScheduler` to lift onto
the shared blackboard, and surfaces the current state to prompt assembly.

Design notes:

- State lives in process memory (``self._states``) and, when a Redis
  client is provided, mirrored to a sim-scoped Redis key so reflection
  snapshots can pick it up. Keeping a local dict means tests don't need
  Redis.
- ``tick`` is deterministic in the seed: decay is constant per need and
  the only randomness lives in the world-event scheduler, not here.
- ``threshold_events`` returns events for downward crossings only — i.e.
  the moment a need *first* falls below ``critical`` (or
  ``warning``). Once below, no further events fire until the value
  recovers above the threshold.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

NeedName = Literal["hunger", "sleep", "energy", "safety", "social"]
NEED_NAMES: tuple[NeedName, ...] = ("hunger", "sleep", "energy", "safety", "social")

_NEEDS_KEY_PREFIX = "agent:needs:"


class NeedConfig(BaseModel):
    """Decay/threshold config for one need (mirrors the YAML block).

    Mirrors :class:`core.simulation.scenario_schema.NeedDecayConfig`; kept
    in a separate file so the manager doesn't pull the full scenario
    schema into hot paths.
    """

    model_config = ConfigDict(extra="forbid")

    tick_decay: float = Field(default=0.0, ge=0.0)
    critical_threshold: float = Field(default=25.0, ge=0.0, le=100.0)
    warning_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    recovery_per_action: float | None = Field(default=None, ge=0.0)


class AgentNeedsState(BaseModel):
    """Snapshot of one agent's needs at a single tick."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    simulation_id: str | None = None
    last_tick: int = 0
    hunger: float = Field(default=100.0, ge=0.0, le=100.0)
    sleep: float = Field(default=100.0, ge=0.0, le=100.0)
    energy: float = Field(default=100.0, ge=0.0, le=100.0)
    safety: float = Field(default=100.0, ge=0.0, le=100.0)
    social: float = Field(default=100.0, ge=0.0, le=100.0)
    # Per-need flags recording which thresholds the agent is currently
    # *under*. Used so we only emit a threshold-crossing event the first
    # time a need passes the line.
    below_warning: dict[str, bool] = Field(default_factory=dict)
    below_critical: dict[str, bool] = Field(default_factory=dict)

    def get(self, need: str) -> float:
        return float(getattr(self, need))

    def set(self, need: str, value: float) -> None:
        value = max(0.0, min(100.0, value))
        setattr(self, need, value)

    def active_needs(self, configs: dict[str, NeedConfig]) -> list[tuple[str, float]]:
        """Needs currently below their warning threshold, worst first."""
        out: list[tuple[str, float]] = []
        for need in NEED_NAMES:
            cfg = configs.get(need)
            if cfg is None:
                continue
            value = self.get(need)
            threshold = cfg.warning_threshold or cfg.critical_threshold
            if value <= threshold:
                out.append((need, value))
        out.sort(key=lambda item: item[1])
        return out


class NeedsEvent(BaseModel):
    """A threshold crossing emitted by :meth:`NeedsManager.tick`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    need: str
    event_type: str  # e.g. "hunger_critical", "sleep_warning"
    value: float
    threshold: float


class NeedsManager:
    """Owns per-agent need state and tick-decay logic.

    Deterministic given a fixed seed: ``tick`` applies linear decay only.
    Threshold-crossing logic runs after decay; events are produced for the
    first crossing only (state recorded in :attr:`AgentNeedsState.below_*`).
    """

    def __init__(
        self,
        *,
        configs: dict[str, NeedConfig] | None = None,
        simulation_id: str | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._configs: dict[str, NeedConfig] = dict(configs or {})
        self._states: dict[str, AgentNeedsState] = {}
        self._simulation_id = simulation_id
        self._redis = redis_client

    # ── Configuration ────────────────────────────────────────────────

    @property
    def configs(self) -> dict[str, NeedConfig]:
        return self._configs

    def set_configs(self, configs: dict[str, NeedConfig]) -> None:
        self._configs = dict(configs)

    # ── State access ─────────────────────────────────────────────────

    def get_state(self, agent_id: str) -> AgentNeedsState:
        state = self._states.get(agent_id)
        if state is None:
            state = AgentNeedsState(
                agent_id=agent_id, simulation_id=self._simulation_id
            )
            self._states[agent_id] = state
        return state

    def all_states(self) -> dict[str, AgentNeedsState]:
        return dict(self._states)

    def reset(self) -> None:
        self._states.clear()

    # ── Tick / decay ─────────────────────────────────────────────────

    def tick(self, agent_id: str, ticks: int = 1) -> list[NeedsEvent]:
        """Advance one agent's needs by ``ticks``. Returns threshold events."""
        if ticks <= 0:
            return []
        state = self.get_state(agent_id)
        for need, cfg in self._configs.items():
            if cfg.tick_decay <= 0:
                continue
            state.set(need, state.get(need) - cfg.tick_decay * ticks)
        state.last_tick += ticks
        return self._threshold_events(state)

    def tick_all(self, agent_ids: Iterable[str], ticks: int = 1) -> list[NeedsEvent]:
        events: list[NeedsEvent] = []
        for agent_id in agent_ids:
            events.extend(self.tick(agent_id, ticks))
        return events

    def apply_effect(self, agent_id: str, need: str, delta: float) -> AgentNeedsState:
        """Apply an action-driven change (eating, sleeping, fighting, ...)."""
        if need not in NEED_NAMES:
            raise ValueError(f"unknown need: {need}")
        state = self.get_state(agent_id)
        state.set(need, state.get(need) + delta)
        # Clear under-threshold flags when the need recovers above them so
        # the next crossing re-fires correctly.
        cfg = self._configs.get(need)
        if cfg is not None:
            value = state.get(need)
            if value > cfg.critical_threshold:
                state.below_critical.pop(need, None)
            if cfg.warning_threshold is not None and value > cfg.warning_threshold:
                state.below_warning.pop(need, None)
        return state

    # ── Persistence ──────────────────────────────────────────────────

    async def snapshot_to_redis(self, agent_id: str) -> None:
        """Mirror an agent's needs to Redis for cross-process readers.

        No-op when no Redis client is configured (the headless and unit-test
        paths). Failures are logged but never raised.
        """
        if self._redis is None:
            return
        try:
            state = self.get_state(agent_id)
            await self._redis.set(
                f"{_NEEDS_KEY_PREFIX}{agent_id}",
                json.dumps(state.model_dump()),
            )
        except Exception:
            logger.warning("Failed to persist needs state for %s", agent_id, exc_info=True)

    # ── Internal: threshold detection ────────────────────────────────

    def _threshold_events(self, state: AgentNeedsState) -> list[NeedsEvent]:
        events: list[NeedsEvent] = []
        for need, cfg in self._configs.items():
            value = state.get(need)
            if value <= cfg.critical_threshold and not state.below_critical.get(need):
                state.below_critical[need] = True
                events.append(
                    NeedsEvent(
                        agent_id=state.agent_id,
                        need=need,
                        event_type=f"{need}_critical",
                        value=value,
                        threshold=cfg.critical_threshold,
                    )
                )
                continue
            warn = cfg.warning_threshold
            if (
                warn is not None
                and value <= warn
                and not state.below_warning.get(need)
                and not state.below_critical.get(need)
            ):
                state.below_warning[need] = True
                events.append(
                    NeedsEvent(
                        agent_id=state.agent_id,
                        need=need,
                        event_type=f"{need}_warning",
                        value=value,
                        threshold=warn,
                    )
                )
        return events


__all__ = [
    "NEED_NAMES",
    "AgentNeedsState",
    "NeedConfig",
    "NeedName",
    "NeedsEvent",
    "NeedsManager",
]
