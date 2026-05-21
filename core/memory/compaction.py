"""MemoryCompactor — compaction cycle that bridges Tier 2 (recall) and Tier 3 (archival).

After every event (conversation, building session, challenge), the compactor:
1. Stores the full transcript in Tier 3 (archival)
2. Generates a summary using a cheap LLM model (Haiku)
3. Creates an embedding from the summary
4. Stores the summary + embedding + transcript_id in Tier 2 (recall)
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Literal

from core.memory.embeddings import generate_embedding

if TYPE_CHECKING:
    import uuid

    import httpx

    from core.llm_client import OpenRouterClient
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.models import RecallMemory, Transcript

EmbeddingFn = Callable[[str], Coroutine[object, object, list[float]]]
SummaryStyle = Literal["default", "scene"]

# Cheap model for summary generation (~$0.001 per call)
SUMMARY_MODEL = "anthropic/claude-haiku-4.5"
SUMMARY_MAX_TOKENS = 300

# Buffer management thresholds
BUFFER_MAX_SIZE = 20
BUFFER_COMPACT_COUNT = 10

SUMMARY_SYSTEM_PROMPT = (
    "You are {agent_id}. Summarize this interaction from your perspective "
    "in 100-300 tokens. Include: what happened (2-3 sentences), key decisions "
    "made, your emotional tone, anything surprising."
)

SCENE_SUMMARY_SYSTEM_PROMPT = (
    "You are {agent_id}. Summarize this Minecraft scene from your perspective "
    "in 100-300 tokens. Surface continuity that matters next: commitments or "
    "promises, discovered constraints, repeated failures, help requests, build "
    "progress, tool outcomes, and the next practical thing to try. Stay concise."
)


class CompactionResult:
    """Result of a compaction cycle."""

    __slots__ = ("recall_memory", "transcript")

    def __init__(self, transcript: Transcript, recall_memory: RecallMemory) -> None:
        self.transcript = transcript
        self.recall_memory = recall_memory


class MemoryCompactor:
    """Runs the compaction cycle after every event."""

    def __init__(
        self,
        archival: ArchivalMemoryManager,
        recall: RecallMemoryManager,
        llm_client: OpenRouterClient,
        http_client: httpx.AsyncClient,
        openrouter_api_key: str,
        embedding_fn: EmbeddingFn | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> None:
        self._archival = archival
        self._recall = recall
        self._llm = llm_client
        self._http = http_client
        self._api_key = openrouter_api_key
        self._embedding_fn = embedding_fn
        self._simulation_id = simulation_id

    async def compact_interaction(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        participants: list[str] | None = None,
        conversation_id: object | None = None,
        summary_style: SummaryStyle = "default",
    ) -> CompactionResult | None:
        """Compact a full interaction into Tier 3 transcript + Tier 2 recall memory.

        Returns None if interaction is empty/whitespace.
        """
        if not interaction or not interaction.strip():
            return None

        if participants is None:
            participants = [agent_id]

        # Step 1: Store full transcript in Tier 3
        transcript = await self._archival.store_transcript(
            event_type=event_type,
            participants=participants,
            content=interaction,
            conversation_id=conversation_id,
        )

        # Step 2: Generate summary via cheap LLM
        summary = await self._generate_summary(
            agent_id,
            interaction,
            event_type,
            summary_style=summary_style,
        )

        # Step 3: Generate embedding from summary
        embedding = await self._generate_embedding(summary)

        # Step 4: Store in Tier 2
        recall_memory = await self._recall.store_recall_memory(
            agent_id=agent_id,
            summary=summary,
            embedding=embedding,
            transcript_id=transcript.id,
            event_type=event_type,
            participants=participants,
            simulation_id=self._simulation_id,
        )

        return CompactionResult(transcript=transcript, recall_memory=recall_memory)

    async def compact_recall_only(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        transcript_id: int,
        participants: list[str] | None = None,
        summary_style: SummaryStyle = "default",
    ) -> RecallMemory | None:
        """Create per-agent recall memory without storing a duplicate transcript.

        Used when the transcript has already been stored once for the conversation
        and we only need per-agent recall memories for the remaining participants.
        """
        if not interaction or not interaction.strip():
            return None

        if participants is None:
            participants = [agent_id]

        summary = await self._generate_summary(
            agent_id,
            interaction,
            event_type,
            summary_style=summary_style,
        )
        embedding = await self._generate_embedding(summary)

        return await self._recall.store_recall_memory(
            agent_id=agent_id,
            summary=summary,
            embedding=embedding,
            transcript_id=transcript_id,
            event_type=event_type,
            participants=participants,
            simulation_id=self._simulation_id,
        )

    async def compact_scene(
        self,
        agent_id: str,
        interaction: str,
        participants: list[str],
        conversation_id: object | None,
    ) -> CompactionResult | None:
        """Compact a Minecraft scene with the scene-continuity summary prompt."""

        return await self.compact_interaction(
            agent_id=agent_id,
            interaction=interaction,
            event_type="minecraft_scene",
            participants=participants,
            conversation_id=conversation_id,
            summary_style="scene",
        )

    async def manage_conversation_buffer(
        self,
        agent_id: str,
        buffer: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Compact oldest messages when buffer exceeds threshold.

        If buffer has more than 20 messages, compact the oldest 10 into
        a recall memory and return the remaining messages.
        """
        if len(buffer) <= BUFFER_MAX_SIZE:
            return buffer

        to_compact = buffer[:BUFFER_COMPACT_COUNT]
        remaining = buffer[BUFFER_COMPACT_COUNT:]

        transcript_text = self._format_buffer_messages(to_compact)
        await self.compact_interaction(
            agent_id=agent_id,
            interaction=transcript_text,
            event_type="conversation_segment",
        )

        return remaining

    async def _generate_summary(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        *,
        summary_style: SummaryStyle = "default",
    ) -> str:
        """Generate a summary of the interaction from the agent's perspective."""
        prompt = SCENE_SUMMARY_SYSTEM_PROMPT if summary_style == "scene" else SUMMARY_SYSTEM_PROMPT
        system_msg = prompt.format(agent_id=agent_id)
        user_msg = f"Agent: {agent_id}\nEvent type: {event_type}\n\nFull transcript:\n{interaction}"

        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            model=SUMMARY_MODEL,
            agent_id=agent_id,
            max_tokens=SUMMARY_MAX_TOKENS,
            temperature=0.3,
            simulation_id=self._simulation_id,
        )
        return response.content

    async def _generate_embedding(self, text: str) -> list[float]:
        if self._embedding_fn is not None:
            return await self._embedding_fn(text)
        return await generate_embedding(text, self._http, self._api_key)

    @staticmethod
    def _format_buffer_messages(messages: list[dict[str, str]]) -> str:
        """Format a list of message dicts into transcript text."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)
