"""RecallMemoryManager — Tier 2 recall memory with vector search and blended scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Awaitable

from core.models import RecallMemoryCreate

if TYPE_CHECKING:
    from core.models import RecallMemory
    from core.repos.memory_repo import MemoryRepo


# Scoring weights from spec
SIMILARITY_WEIGHT = 0.7
RECENCY_WEIGHT = 0.3

# Over-fetch multiplier to get enough candidates for blended scoring
CANDIDATE_MULTIPLIER = 3


class RecallMemoryManager:
    """Manages Tier 2 recall memory: store, retrieve with blended scoring."""

    def __init__(
        self,
        memory_repo: MemoryRepo,
        embedding_fn: Callable[[str], Awaitable[list[float]]],
    ) -> None:
        self._repo = memory_repo
        self._embedding_fn = embedding_fn

    async def store_recall_memory(
        self,
        agent_id: str,
        summary: str,
        embedding: list[float],
        transcript_id: int | None = None,
        event_type: str | None = None,
        participants: list[str] | None = None,
        importance_score: float = 0.5,
    ) -> RecallMemory:
        """Store a new recall memory with its pre-computed embedding."""
        create = RecallMemoryCreate(
            agent_id=agent_id,
            summary=summary,
            embedding=embedding,
            event_type=event_type,
            participants=participants,
            transcript_id=transcript_id,
            importance_score=importance_score,
        )
        return await self._repo.add_recall(create)

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
    ) -> str:
        """Retrieve most relevant memories using blended similarity + recency scoring.

        Returns formatted markdown block.
        """
        query_embedding = await self._embedding_fn(query_text)

        # Over-fetch candidates so blended scoring can re-rank
        candidates = await self._repo.search_recall(
            agent_id, query_embedding, limit=limit * CANDIDATE_MULTIPLIER
        )

        if not candidates:
            return ""

        scored = _score_candidates(candidates, query_embedding)
        top = sorted(scored, key=lambda x: x[1], reverse=True)[:limit]

        # Increment recalled_count for each returned memory
        for memory, _ in top:
            await self._repo.increment_recalled_count(memory.id)

        return _format_memories([m for m, _ in top])


def _score_candidates(
    candidates: list[RecallMemory],
    query_embedding: list[float],
) -> list[tuple[RecallMemory, float]]:
    """Compute blended score: similarity * 0.7 + recency * 0.3."""
    now = datetime.now(timezone.utc)

    # Collect timestamps for normalization
    timestamps = []
    for m in candidates:
        ts = m.timestamp
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            timestamps.append(ts)

    if timestamps:
        oldest = min(timestamps)
        newest = max(timestamps)
        time_range = (newest - oldest).total_seconds()
    else:
        oldest = now
        time_range = 0.0

    results: list[tuple[RecallMemory, float]] = []
    for m in candidates:
        similarity = _cosine_similarity(query_embedding, m.embedding)

        ts = m.timestamp
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if time_range > 0:
                recency = (ts - oldest).total_seconds() / time_range
            else:
                recency = 1.0
        else:
            recency = 0.0

        score = similarity * SIMILARITY_WEIGHT + recency * RECENCY_WEIGHT
        results.append((m, score))

    return results


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _format_memories(memories: list[RecallMemory]) -> str:
    """Format memories as markdown block per spec."""
    lines = ["## Relevant memories"]
    for m in memories:
        event_tag = f"[{m.event_type}]" if m.event_type else "[memory]"
        lines.append(f"- {event_tag} {m.summary}")
        if m.transcript_id is not None:
            lines.append(f"  (Full transcript available: transcript_{m.transcript_id})")
    return "\n".join(lines)
