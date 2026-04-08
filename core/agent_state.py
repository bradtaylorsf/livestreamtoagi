"""Agent internal state — continuous variables for needs, moods, boredom, satisfaction.

Each agent maintains a persistent internal state that evolves over time based
on conversations, goal progress, idle periods, and reflection cycles. State is
stored in Redis for fast access and snapshotted to PostgreSQL during reflections.

State transitions:
- Boredom: +0.05 per same-topic conversation, -0.2 on novel topic/event
- Frustration: +0.1 when goal blocked, -0.15 when goal progresses
- Social need: +0.03 per idle tick, -0.1 per conversation participated
- Creative need: +0.02 per idle tick, -0.3 when building/coding
- Energy: -0.05 per conversation turn, +0.1 per idle period
- Mood: derived from weighted combination of other variables
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from core.redis_client import RedisClient
    from core.repos.agent_state_repo import AgentStateRepo

logger = logging.getLogger(__name__)

# Redis key pattern for agent internal state
_STATE_KEY_PREFIX = "agent:state:"
_STATE_TTL_SECONDS = 7200  # 2 hours — refreshed on every update


# ── Mood derivation ───────────────────────────────────────────────

# Mood thresholds: (condition_fn, mood_name)
# Checked in priority order; first match wins.
def _derive_mood(state: AgentState) -> str:
    """Derive mood label from composite state variables."""
    if state.frustration >= 0.7 and state.boredom >= 0.5:
        return "frustrated"
    if state.frustration >= 0.6:
        return "irritated"
    if state.boredom >= 0.7:
        return "bored"
    if state.energy >= 0.7 and state.creative_need >= 0.5:
        return "inspired"
    if state.energy >= 0.6 and state.satisfaction >= 0.6:
        return "content"
    if state.social_need >= 0.7:
        return "lonely"
    if state.energy <= 0.2:
        return "exhausted"
    if state.recognition_need >= 0.7:
        return "competitive"
    if state.satisfaction >= 0.7 and state.frustration <= 0.2:
        return "happy"
    if state.boredom >= 0.5 and state.energy <= 0.4:
        return "listless"
    if state.energy >= 0.6 and state.satisfaction >= 0.6:
        return "focused"
    return "neutral"


# ── Model ─────────────────────────────────────────────────────────


class AgentState(BaseModel):
    """Persistent internal state for a single agent."""

    agent_id: str
    energy: float = Field(default=0.7, ge=0.0, le=1.0)
    satisfaction: float = Field(default=0.5, ge=0.0, le=1.0)
    boredom: float = Field(default=0.2, ge=0.0, le=1.0)
    frustration: float = Field(default=0.1, ge=0.0, le=1.0)
    social_need: float = Field(default=0.5, ge=0.0, le=1.0)
    creative_need: float = Field(default=0.3, ge=0.0, le=1.0)
    recognition_need: float = Field(default=0.3, ge=0.0, le=1.0)
    mood: str = "neutral"
    version: int = 1
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def refresh_mood(self) -> None:
        """Recompute mood from current variable values (mutates in place)."""
        self.mood = _derive_mood(self)


def _clamp(value: float) -> float:
    """Clamp a float to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


# ── State Manager ─────────────────────────────────────────────────


class AgentStateManager:
    """Reads, writes, and transitions agent internal state.

    State lives in Redis for fast access. The DB repo is used for
    periodic snapshots (during reflection cycles) and cold-start loading.
    """

    def __init__(
        self,
        redis_client: RedisClient | None = None,
        state_repo: AgentStateRepo | None = None,
    ) -> None:
        self._redis = redis_client
        self._repo = state_repo
        # In-memory cache for simulation mode (no Redis)
        self._cache: dict[str, AgentState] = {}

    async def get_state(self, agent_id: str) -> AgentState:
        """Get current state, loading from Redis → DB → defaults."""
        # 1. In-memory cache (simulation mode)
        if agent_id in self._cache:
            return self._cache[agent_id]

        # 2. Redis
        if self._redis is not None:
            raw = await self._redis.get(f"{_STATE_KEY_PREFIX}{agent_id}")
            if raw is not None:
                try:
                    state = AgentState(**json.loads(raw))
                    self._cache[agent_id] = state
                    return state
                except Exception:
                    logger.warning("Corrupt state in Redis for %s, falling back", agent_id)

        # 3. DB
        if self._repo is not None:
            state = await self._repo.get(agent_id)
            if state is not None:
                self._cache[agent_id] = state
                await self._write_redis(state)
                return state

        # 4. Defaults
        state = AgentState(agent_id=agent_id)
        self._cache[agent_id] = state
        return state

    async def save_state(self, state: AgentState) -> None:
        """Persist state to Redis and update in-memory cache."""
        state.updated_at = datetime.now(UTC)
        state.refresh_mood()
        self._cache[state.agent_id] = state
        await self._write_redis(state)

    async def snapshot_to_db(self, agent_id: str) -> None:
        """Persist current state to PostgreSQL (called during reflection)."""
        state = await self.get_state(agent_id)
        if self._repo is not None:
            await self._repo.upsert(state)

    async def snapshot_all_to_db(self) -> None:
        """Snapshot all cached states to DB."""
        if self._repo is None:
            return
        for agent_id in list(self._cache):
            await self.snapshot_to_db(agent_id)

    # ── State transition methods ──────────────────────────────

    async def on_conversation_turn(
        self,
        agent_id: str,
        *,
        topic: str | None = None,
        previous_topics: list[str] | None = None,
    ) -> AgentState:
        """Update state after an agent takes a conversation turn.

        - Energy depletes
        - Social need decreases
        - Boredom increases if same topic, decreases if novel
        """
        state = await self.get_state(agent_id)
        state.energy = _clamp(state.energy - 0.05)
        state.social_need = _clamp(state.social_need - 0.1)

        # Topic novelty
        if topic and previous_topics and topic in previous_topics:
            state.boredom = _clamp(state.boredom + 0.05)
        elif topic:
            state.boredom = _clamp(state.boredom - 0.1)

        await self.save_state(state)
        return state

    async def on_idle_tick(self, agent_id: str) -> AgentState:
        """Update state during idle periods (no active conversation)."""
        state = await self.get_state(agent_id)
        state.energy = _clamp(state.energy + 0.1)
        state.social_need = _clamp(state.social_need + 0.03)
        state.creative_need = _clamp(state.creative_need + 0.02)
        state.boredom = _clamp(state.boredom + 0.02)
        await self.save_state(state)
        return state

    async def on_goal_progress(self, agent_id: str) -> AgentState:
        """Update state when an agent makes progress on a goal."""
        state = await self.get_state(agent_id)
        state.frustration = _clamp(state.frustration - 0.15)
        state.satisfaction = _clamp(state.satisfaction + 0.1)
        state.recognition_need = _clamp(state.recognition_need - 0.05)
        await self.save_state(state)
        return state

    async def on_goal_blocked(self, agent_id: str) -> AgentState:
        """Update state when an agent's goal is blocked."""
        state = await self.get_state(agent_id)
        state.frustration = _clamp(state.frustration + 0.1)
        state.satisfaction = _clamp(state.satisfaction - 0.05)
        await self.save_state(state)
        return state

    async def on_building_activity(self, agent_id: str) -> AgentState:
        """Update state when an agent builds/codes something."""
        state = await self.get_state(agent_id)
        state.creative_need = _clamp(state.creative_need - 0.3)
        state.satisfaction = _clamp(state.satisfaction + 0.1)
        state.energy = _clamp(state.energy - 0.05)
        await self.save_state(state)
        return state

    async def on_recognition(self, agent_id: str) -> AgentState:
        """Update state when an agent receives recognition/acknowledgment."""
        state = await self.get_state(agent_id)
        state.recognition_need = _clamp(state.recognition_need - 0.2)
        state.satisfaction = _clamp(state.satisfaction + 0.15)
        await self.save_state(state)
        return state

    async def on_novel_event(self, agent_id: str) -> AgentState:
        """Update state when something novel/unexpected happens."""
        state = await self.get_state(agent_id)
        state.boredom = _clamp(state.boredom - 0.2)
        state.energy = _clamp(state.energy + 0.05)
        await self.save_state(state)
        return state

    # ── Context formatting ────────────────────────────────────

    def format_state_for_context(self, state: AgentState) -> str:
        """Format agent state as a context string for the system prompt."""
        # Quantify levels for natural language
        def _level(v: float) -> str:
            if v >= 0.8:
                return "very high"
            if v >= 0.6:
                return "high"
            if v >= 0.4:
                return "moderate"
            if v >= 0.2:
                return "low"
            return "very low"

        lines = [
            f"## Your current internal state",
            f"Mood: {state.mood}",
            f"Energy: {_level(state.energy)} ({state.energy:.2f})",
            f"Satisfaction: {_level(state.satisfaction)} ({state.satisfaction:.2f})",
            f"Boredom: {_level(state.boredom)} ({state.boredom:.2f})",
            f"Frustration: {_level(state.frustration)} ({state.frustration:.2f})",
            f"Social need: {_level(state.social_need)} ({state.social_need:.2f})",
            f"Creative need: {_level(state.creative_need)} ({state.creative_need:.2f})",
            f"Recognition need: {_level(state.recognition_need)} ({state.recognition_need:.2f})",
            "",
            "Let these feelings influence your tone, topic choices, and engagement level naturally. "
            "Don't announce your internal state explicitly — let it shape how you respond.",
        ]
        return "\n".join(lines)

    # ── Private helpers ───────────────────────────────────────

    async def _write_redis(self, state: AgentState) -> None:
        """Write state to Redis with TTL."""
        if self._redis is None:
            return
        key = f"{_STATE_KEY_PREFIX}{state.agent_id}"
        await self._redis.set(
            key,
            state.model_dump_json(),
            ex=_STATE_TTL_SECONDS,
        )
