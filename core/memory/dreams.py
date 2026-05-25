"""Dream system — high-temperature creative reflection during idle periods.

During extended idle or "nighttime" periods, agents enter a dream state
where temperature is cranked up and they freely recombine recent memories
into creative ideas, novel goals, and narrative-driving insights.

Dreams are the mechanism for breaking out of local optima and generating
surprising, personality-consistent behavior.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from core.model_config import resolve_internal_model

if TYPE_CHECKING:
    from core.agent_goals import AgentGoalManager
    from core.agent_registry import AgentRegistry
    from core.agent_state import AgentStateManager
    from core.llm_client import OpenRouterClient
    from core.memory.core_memory import CoreMemoryManager
    from core.repos.memory_repo import MemoryRepo

EmbeddingFn = Callable[[str], Coroutine[Any, Any, list[float]]]

logger = logging.getLogger(__name__)

# Dream LLM temperature — much higher than conversation (0.7-0.9)
DREAM_TEMPERATURE = 1.3

# Mood shift values and their state effects
MOOD_SHIFT_EFFECTS: dict[str, dict[str, float]] = {
    "inspired": {"creative_need": -0.3, "satisfaction": 0.15},
    "anxious": {"frustration": 0.1, "energy": -0.05},
    "determined": {"energy": 0.1, "boredom": -0.2},
    "melancholy": {"social_need": 0.15, "satisfaction": -0.1},
    "energized": {"energy": 0.2, "boredom": -0.3},
}

MoodShift = Literal["inspired", "anxious", "determined", "melancholy", "energized"]


class DreamGoal(BaseModel):
    """A goal generated from a dream."""

    description: str
    category: str = "creative"
    priority: int = Field(default=3, ge=1, le=5)


class DreamResult(BaseModel):
    """The output of a dream cycle."""

    dream_narrative: str
    insights: list[str] = Field(default_factory=list)
    new_goals: list[DreamGoal] = Field(default_factory=list)
    mood_shift: MoodShift = "inspired"


DREAM_PROMPT = """\
You are dreaming. In this state, your thoughts are free-associative and creative.
Reality is fluid. You can imagine impossible things. This is where your best ideas come from.

Recent memories to recombine:
{shuffled_memories}

Your current frustrations: {frustrations}
Your unfulfilled desires: {unmet_needs}

Dream freely. What do you see? What ideas emerge?
Then, when you "wake up," distill 1-2 actionable insights or goals from the dream.

Respond with valid JSON only:
{{
  "dream_narrative": "...",
  "insights": ["...", "..."],
  "new_goals": [{{"description": "...", "category": "...", "priority": 3}}],
  "mood_shift": "inspired"
}}

Valid mood_shift values: "inspired", "anxious", "determined", "melancholy", "energized"
Valid category values for goals: "creative", "social", "economic", "personal", "competitive"
The dream narrative should be 2-3 paragraphs, surreal but anchored in your personality.
Generate 1-2 goals that are creative and actionable.
"""


class DreamManager:
    """Manages dream cycles — high-temperature creative reflection."""

    def __init__(
        self,
        *,
        memory_repo: MemoryRepo | None = None,
        llm_client: OpenRouterClient | None = None,
        core_memory_mgr: CoreMemoryManager | None = None,
        goal_manager: AgentGoalManager | None = None,
        agent_state_manager: AgentStateManager | None = None,
        agent_registry: AgentRegistry | None = None,
        token_counter: Any = None,
        simulation_id: Any = None,
        embedding_fn: EmbeddingFn | None = None,
    ) -> None:
        self._repo = memory_repo
        self._llm = llm_client
        self._core = core_memory_mgr
        self._goals = goal_manager
        self._state_mgr = agent_state_manager
        self._registry = agent_registry
        self._tc = token_counter
        self._simulation_id = simulation_id
        self._embedding_fn = embedding_fn
        self._rng = random.Random()

    async def run_dream(self, agent_id: str) -> DreamResult | None:
        """Run a dream cycle for an agent.

        1. Fetch and shuffle recent memories
        2. Read current frustrations/unmet needs from state
        3. Call LLM at high temperature with dream prompt
        4. Parse result and apply effects (goals, mood, journal)

        Returns DreamResult or None if dream generation fails.
        """
        if self._llm is None:
            logger.warning("No LLM client for dream generation")
            return None

        # 1. Gather dream ingredients
        memories = await self._get_shuffled_memories(agent_id)
        frustrations, unmet_needs = await self._get_state_context(agent_id)
        core_memory = await self._get_core_memory(agent_id)

        # 2. Build dream prompt
        prompt = DREAM_PROMPT.format(
            shuffled_memories=memories or "No recent memories available.",
            frustrations=frustrations or "None in particular.",
            unmet_needs=unmet_needs or "None in particular.",
        )

        # 3. Get the agent's building model for dreaming
        agent_model = resolve_internal_model("dream_fallback")
        if self._registry is not None:
            agent_cfg = self._registry.get_agent(agent_id)
            if agent_cfg is not None:
                agent_model = agent_cfg.model_building

        # 4. Call LLM at high temperature
        system_content = prompt
        if core_memory:
            system_content = f"{core_memory}\n\n{prompt}"

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": "Dream now. Let your thoughts flow freely."},
                ],
                model=agent_model,
                agent_id=agent_id,
                temperature=DREAM_TEMPERATURE,
                max_tokens=1200,
                simulation_id=self._simulation_id,
            )
        except Exception:
            logger.warning("Dream LLM call failed for %s", agent_id, exc_info=True)
            return None

        # 5. Parse dream result
        dream = self._parse_dream_response(response.content)
        if dream is None:
            return None

        # 6. Apply dream effects
        await self._apply_dream_effects(agent_id, dream)

        logger.info(
            "Dream completed for %s: mood_shift=%s, goals=%d, insights=%d",
            agent_id,
            dream.mood_shift,
            len(dream.new_goals),
            len(dream.insights),
        )
        return dream

    async def _get_shuffled_memories(self, agent_id: str) -> str:
        """Fetch recent recall memories and shuffle them for recombination."""
        if self._repo is None:
            return ""

        try:
            # Get recent journal entries and recall memories
            entries = await self._repo.get_recent_journal_entries(
                agent_id,
                limit=10,
                simulation_id=self._simulation_id,
            )
            texts = [e.content for e in entries] if entries else []

            recent_recall = getattr(self._repo, "get_recent_recall_memories", None)
            if callable(recent_recall):
                since = datetime.now(UTC) - timedelta(hours=24)
                recall_memories = await recent_recall(
                    agent_id,
                    since,
                    limit=10,
                    simulation_id=self._simulation_id,
                )
                if isinstance(recall_memories, list):
                    texts.extend(
                        f"[{m.event_type or 'recall'}] {m.summary}"
                        for m in recall_memories
                        if getattr(m, "summary", None)
                    )

            if not texts:
                return ""

            self._rng.shuffle(texts)
            # Take up to 5 shuffled fragments
            selected = texts[:5]
            return "\n- ".join([""] + selected)
        except Exception:
            logger.warning("Failed to fetch memories for dream: %s", agent_id, exc_info=True)
            return ""

    async def _get_state_context(self, agent_id: str) -> tuple[str, str]:
        """Extract frustrations and unmet needs from agent state."""
        if self._state_mgr is None:
            return ("", "")

        try:
            state = await self._state_mgr.get_state(agent_id)
            frustrations_parts: list[str] = []
            unmet_parts: list[str] = []

            if state.frustration > 0.5:
                frustrations_parts.append(f"Frustration level: {state.frustration:.2f}")
            if state.boredom > 0.5:
                frustrations_parts.append(f"Boredom level: {state.boredom:.2f}")

            if state.creative_need > 0.5:
                unmet_parts.append(f"Creative need: {state.creative_need:.2f}")
            if state.social_need > 0.5:
                unmet_parts.append(f"Social need: {state.social_need:.2f}")
            if state.recognition_need > 0.5:
                unmet_parts.append(f"Recognition need: {state.recognition_need:.2f}")

            return (
                "; ".join(frustrations_parts) if frustrations_parts else "",
                "; ".join(unmet_parts) if unmet_parts else "",
            )
        except Exception:
            logger.warning("Failed to get agent state for dream: %s", agent_id, exc_info=True)
            return ("", "")

    async def _get_core_memory(self, agent_id: str) -> str:
        """Get core memory for personality anchoring in dreams."""
        if self._core is None:
            return ""
        try:
            return (
                await self._core.get_core_memory(
                    agent_id,
                    simulation_id=self._simulation_id,
                )
                or ""
            )
        except Exception:
            logger.warning("Failed to get core memory for dream: %s", agent_id, exc_info=True)
            return ""

    def _parse_dream_response(self, content: str) -> DreamResult | None:
        """Parse the LLM dream response into a DreamResult."""
        from core.memory.reflection import _parse_json_response

        data = _parse_json_response(content)
        if not data:
            logger.warning("Failed to parse dream response")
            return None

        try:
            _valid_categories = {"creative", "social", "economic", "personal", "competitive"}
            goals = []
            for g in data.get("new_goals", []):
                if isinstance(g, dict) and "description" in g:
                    category = g.get("category", "creative")
                    if category not in _valid_categories:
                        category = "creative"
                    goals.append(
                        DreamGoal(
                            description=g["description"],
                            category=category,
                            priority=min(5, max(1, int(g.get("priority", 3)))),
                        )
                    )

            mood = data.get("mood_shift", "inspired")
            if mood not in MOOD_SHIFT_EFFECTS:
                mood = "inspired"

            return DreamResult(
                dream_narrative=data.get("dream_narrative", "A formless dream..."),
                insights=data.get("insights", []),
                new_goals=goals,
                mood_shift=mood,
            )
        except Exception:
            logger.warning("Failed to construct DreamResult from parsed data", exc_info=True)
            return None

    async def _apply_dream_effects(
        self,
        agent_id: str,
        dream: DreamResult,
    ) -> None:
        """Apply dream effects: mood shift, goals, journal entry, recall continuity."""
        # Apply mood shift to agent state
        if self._state_mgr is not None:
            await self._apply_mood_shift(agent_id, dream.mood_shift)

        # Add dream-generated goals
        if self._goals is not None:
            for goal in dream.new_goals:
                try:
                    await self._goals.add_goal(
                        agent_id,
                        goal.description,
                        priority=goal.priority,
                        source="dream",
                        category=goal.category,
                        simulation_id=self._simulation_id,
                    )
                    await self._store_dream_recall(agent_id, f"[Dream goal] {goal.description}")
                except Exception as exc:
                    logger.warning(
                        "Failed to add dream goal for %s: %s", agent_id, exc, exc_info=True
                    )

        # Store dream narrative as journal entry
        if self._repo is not None:
            try:
                from core.models import JournalEntryCreate

                token_count = 0
                if self._tc is not None:
                    token_count = self._tc.count_tokens(dream.dream_narrative)

                await self._repo.create_journal_entry(
                    JournalEntryCreate(
                        agent_id=agent_id,
                        reflection_type="dream",
                        content=dream.dream_narrative,
                        token_count=token_count,
                        simulation_id=self._simulation_id,
                    )
                )
            except Exception:
                logger.warning("Failed to store dream journal for %s", agent_id, exc_info=True)

        # Store insights as high-importance recall memories (only if we can embed)
        for insight in dream.insights:
            await self._store_dream_recall(agent_id, f"[Dream insight] {insight}")

    async def _store_dream_recall(self, agent_id: str, text: str) -> None:
        """Mirror dream outputs into recall for the next embodied memory-context fetch."""
        if self._repo is None or self._embedding_fn is None:
            return
        try:
            from core.models import RecallMemoryCreate

            embedding = await self._embedding_fn(text)
            await self._repo.add_recall(
                RecallMemoryCreate(
                    agent_id=agent_id,
                    summary=text,
                    embedding=embedding,
                    event_type="dream",
                    importance_score=0.8,
                    simulation_id=self._simulation_id,
                )
            )
        except Exception:
            logger.warning("Failed to store dream recall for %s", agent_id, exc_info=True)

    async def _apply_mood_shift(
        self,
        agent_id: str,
        mood_shift: str,
    ) -> None:
        """Apply mood shift effects to agent internal state."""
        from core.agent_state import _clamp

        effects = MOOD_SHIFT_EFFECTS.get(mood_shift, {})
        if not effects or self._state_mgr is None:
            return

        state = await self._state_mgr.get_state(agent_id)

        for field_name, delta in effects.items():
            current = getattr(state, field_name, None)
            if current is not None:
                setattr(state, field_name, _clamp(current + delta))

        await self._state_mgr.save_state(state)
