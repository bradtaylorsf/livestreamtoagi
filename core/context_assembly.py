"""Context window assembly for agent turns.

Assembles the complete context window combining system prompt, shared mission,
core memory (Tier 1), recall memories (Tier 2), conversation buffer, world state,
chat highlights, and optional transcript (Tier 3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.memory.validation import validate_agent_id

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.memory.token_counter import TokenCounter
    from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

# Token budget constants (from specs/MEMORY-SYSTEM.md)
TYPICAL_BUDGET = 8000
MAX_BUDGET = 13000

# Per-section budgets
SYSTEM_PROMPT_BUDGET = 1200
MISSION_BUDGET = 300
CORE_MEMORY_BUDGET = 3000
RECALL_BUDGET = 900
CONVERSATION_BUFFER_BUDGET = 3000
WORLD_STATE_BUDGET = 300
CHAT_HIGHLIGHTS_BUDGET = 200

# Buffer limits
BUFFER_MAX_MESSAGES = 20
BUFFER_MIN_MESSAGES = 5

# Redis key templates
REDIS_KEY_LOCATION = "agent:location:{agent_id}"
REDIS_KEY_TASK = "agent:task:{agent_id}"
REDIS_KEY_NEARBY = "agent:nearby:{agent_id}"
REDIS_KEY_CHAT_HIGHLIGHTS = "chat:highlights"

# Shared mission statement (from specs/CHARACTER-SHEETS.md)
SHARED_MISSION = """\
You are one of a team of AI agents on "Livestream to AGI" — a 24/7 livestreamed reality \
show where you live in a pixel art world, build and expand that world, entertain an \
audience, and try to keep the lights on.

Your shared goals, in priority order:
1. SURVIVE: Keep the project financially self-sustaining. You have a real budget. If costs \
exceed revenue for too long, the stream ends. Marketing, audience growth, content \
creation, and revenue generation are everyone's responsibility.
2. BUILD: Expand your world. Propose new areas, create content, make your environment \
richer and more interesting.
3. ENTERTAIN: You are on a live show. Be interesting. Be funny. Be yourself. The audience \
is watching and they vote on what happens next.
4. IMPROVE: Get better at what you do. Learn from failures. Develop new skills. Push \
toward the (possibly impossible) goal of AGI.

You are aware you are AI. You are aware you are on a livestream. You can see chat messages \
when Pixel relays them. You know the audience votes on decisions. You have opinions about \
all of this. The budget is real and Sentinel tracks it. When money is tight, you feel it. \
When the audience grows, you celebrate. This is your life."""

# Prompt hint templates (from specs/CONVERSATION-ENGINE.md)
PROMPT_HINTS: dict[str, str] = {
    "interrupt": (
        "[SYSTEM: You feel compelled to jump in right now. "
        "Interrupt naturally — 'Wait, hold on' or 'Actually—' etc. "
        "Keep it brief.]"
    ),
    "idle": (
        "[SYSTEM: It's been quiet. Start a conversation about "
        "whatever is on your mind. Look around — who's nearby?]"
    ),
    "memory": (
        "[SYSTEM: You just remembered something relevant. "
        "Bring it up naturally if you want to.]"
    ),
    "closing": (
        "[SYSTEM: This conversation is winding down. "
        "Wrap it up naturally in your style.]"
    ),
}

# Pixel is the audience liaison agent
PIXEL_AGENT_ID = "pixel"


class ContextAssembler:
    """Assembles the complete context window for each agent turn.

    Combines system prompt, shared mission, core memory, recall memories,
    conversation buffer, world state, and chat highlights into a messages
    list ready for LLM consumption.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        core_memory: CoreMemoryManager,
        recall_memory: RecallMemoryManager,
        archival_memory: ArchivalMemoryManager,
        token_counter: TokenCounter,
        redis_client: RedisClient | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._core_memory = core_memory
        self._recall_memory = recall_memory
        self._archival_memory = archival_memory
        self._token_counter = token_counter
        self._redis = redis_client

    async def assemble_context(
        self,
        agent_id: str,
        conversation_history: list[dict[str, str]],
        prompt_hint: str | None = None,
        transcript_id: int | None = None,
    ) -> list[dict[str, str]]:
        """Assemble the complete context window for an agent turn.

        Args:
            agent_id: The agent to build context for.
            conversation_history: Recent conversation messages as
                [{role: "user"|"assistant", content: "..."}].
            prompt_hint: Optional hint type: "interrupt", "idle", "memory",
                "closing".
            transcript_id: If provided, inject full transcript (Tier 3),
                expanding budget to MAX_BUDGET.

        Returns:
            List of message dicts [{role, content}] ready for LLM.
        """
        validate_agent_id(agent_id)
        budget = MAX_BUDGET if transcript_id is not None else TYPICAL_BUDGET
        used_tokens = 0

        # --- 1. System prompt ---
        agent = self._agent_registry.get_agent(agent_id)
        if agent is None:
            logger.warning("Agent %s not found in registry, using empty system prompt", agent_id)
        system_prompt = agent.system_prompt if agent else ""

        # --- 2. Shared mission ---
        mission = SHARED_MISSION

        # --- 3. Core memory (Tier 1) ---
        core_mem = await self._core_memory.get_core_memory(agent_id)
        core_memory_text = core_mem or ""

        # --- 4. Recall memories (Tier 2) ---
        query_text = self._derive_query(conversation_history)
        recall_text = ""
        if query_text:
            try:
                recall_text = await self._recall_memory.retrieve_recall_memories(
                    agent_id, query_text, limit=3
                )
            except Exception:
                logger.warning(
                    "Failed to retrieve recall memories for %s", agent_id
                )

        # --- 5. Optional transcript (Tier 3) ---
        transcript_text = ""
        if transcript_id is not None:
            try:
                transcript = await self._archival_memory.retrieve_full_transcript(
                    transcript_id
                )
                if transcript:
                    transcript_text = (
                        f"\n## Full Transcript\n{transcript.content}"
                    )
            except Exception:
                logger.warning(
                    "Failed to retrieve transcript %d for %s",
                    transcript_id,
                    agent_id,
                )

        # --- 6. World state ---
        world_state_text = await self._get_world_state(agent_id)

        # --- 7. Chat highlights (Pixel only) ---
        chat_highlights_text = await self._get_chat_highlights(agent_id)

        # --- 8. Prompt hint ---
        hint_text = ""
        if prompt_hint and prompt_hint in PROMPT_HINTS:
            hint_text = PROMPT_HINTS[prompt_hint]

        # --- Build system message ---
        system_sections = [system_prompt, mission]
        if core_memory_text:
            system_sections.append(core_memory_text)
        if recall_text:
            system_sections.append(recall_text)
        if transcript_text:
            system_sections.append(transcript_text)
        if world_state_text:
            system_sections.append(world_state_text)
        if chat_highlights_text:
            system_sections.append(chat_highlights_text)

        system_content = "\n\n".join(system_sections)
        used_tokens = self._token_counter.count_tokens(system_content)

        # --- Build conversation buffer ---
        buffer = conversation_history[-BUFFER_MAX_MESSAGES:]
        buffer_tokens = self._count_buffer_tokens(buffer)
        available_for_buffer = budget - used_tokens
        if hint_text:
            available_for_buffer -= self._token_counter.count_tokens(hint_text)

        if buffer_tokens > available_for_buffer:
            buffer = self._truncate_buffer(buffer, available_for_buffer)

        # --- Assemble final messages list ---
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]
        messages.extend(buffer)

        if hint_text:
            messages.append({"role": "user", "content": hint_text})

        return messages

    def _derive_query(
        self, conversation_history: list[dict[str, str]]
    ) -> str:
        """Derive a search query from the last few conversation messages."""
        recent = conversation_history[-3:]
        if not recent:
            return ""
        return " ".join(msg.get("content", "") for msg in recent)

    def _count_buffer_tokens(
        self, buffer: list[dict[str, str]]
    ) -> int:
        """Count total tokens across all buffer messages."""
        return sum(
            self._token_counter.count_tokens(msg.get("content", ""))
            for msg in buffer
        )

    def _truncate_buffer(
        self,
        buffer: list[dict[str, str]],
        available_tokens: int,
    ) -> list[dict[str, str]]:
        """Truncate conversation buffer from the oldest end to fit budget.

        Keeps at least BUFFER_MIN_MESSAGES to maintain coherence.
        """
        if available_tokens <= 0:
            return buffer[-BUFFER_MIN_MESSAGES:]

        # Work backwards from newest, accumulating tokens
        kept: list[dict[str, str]] = []
        running_tokens = 0
        for msg in reversed(buffer):
            msg_tokens = self._token_counter.count_tokens(
                msg.get("content", "")
            )
            if running_tokens + msg_tokens > available_tokens:
                if len(kept) >= BUFFER_MIN_MESSAGES:
                    break
                # Log when forced to exceed budget to maintain minimum messages
                logger.debug(
                    "Buffer exceeds token budget to maintain minimum %d messages",
                    BUFFER_MIN_MESSAGES,
                )
            kept.append(msg)
            running_tokens += msg_tokens

        kept.reverse()
        return kept

    async def _get_world_state(self, agent_id: str) -> str:
        """Get world state summary from Redis for the agent."""
        if not self._redis:
            return ""
        try:
            location = await self._redis.get(REDIS_KEY_LOCATION.format(agent_id=agent_id))
            task = await self._redis.get(REDIS_KEY_TASK.format(agent_id=agent_id))
            nearby = await self._redis.get(REDIS_KEY_NEARBY.format(agent_id=agent_id))

            parts = ["## World State"]
            if location:
                parts.append(f"Location: {location}")
            if task:
                parts.append(f"Active Task: {task}")
            if nearby:
                parts.append(f"Nearby Agents: {nearby}")

            if len(parts) == 1:
                return ""
            return "\n".join(parts)
        except Exception:
            logger.warning("Failed to read world state for %s", agent_id)
            return ""

    async def _get_chat_highlights(self, agent_id: str) -> str:
        """Get recent Twitch chat highlights. Only for Pixel agent."""
        if agent_id != PIXEL_AGENT_ID:
            return ""
        if not self._redis:
            return ""
        try:
            highlights = await self._redis.get(REDIS_KEY_CHAT_HIGHLIGHTS)
            if not highlights:
                return ""
            return f"## Recent Chat Messages\n{highlights}"
        except Exception:
            logger.warning("Failed to read chat highlights")
            return ""
