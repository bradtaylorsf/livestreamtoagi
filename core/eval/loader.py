"""Data loader — fetches simulation data needed for evals."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from core.database import Database

logger = logging.getLogger(__name__)

# Default token budget per category to keep prompts within context window
DEFAULT_MAX_TRANSCRIPT_TOKENS = 50_000


async def load_simulation_data(
    db: Database,
    simulation_id: uuid.UUID,
    *,
    max_transcript_tokens: int = DEFAULT_MAX_TRANSCRIPT_TOKENS,
) -> dict[str, Any]:
    """Fetch all simulation data needed for eval prompts."""
    # Simulation record
    sim_row = await db.fetchrow(
        "SELECT * FROM simulations WHERE id = $1", simulation_id
    )
    if sim_row is None:
        raise ValueError(f"Simulation {simulation_id} not found")
    sim = dict(sim_row)

    # Conversations with transcripts
    conv_rows = await db.fetch(
        """SELECT c.id, c.trigger_type, c.participating_agents,
                  c.turn_count, c.started_at, c.ended_at,
                  t.content AS transcript
           FROM conversations c
           LEFT JOIN transcripts t ON t.conversation_id = c.id
           WHERE c.simulation_id = $1
           ORDER BY c.started_at""",
        simulation_id,
    )
    conversations = [dict(r) for r in conv_rows]

    # Summarize if too long
    transcript_text = _build_transcript_text(conversations)
    if len(transcript_text) > max_transcript_tokens * 4:  # rough chars-to-tokens
        transcript_text = transcript_text[: max_transcript_tokens * 4]
        transcript_text += "\n\n[... transcript truncated for context window ...]"

    # Artifacts
    artifact_rows = await db.fetch(
        """SELECT id, agent_id, tool_name, tool_input, tool_output,
                  artifact_type, status, metadata, created_at
           FROM artifacts
           WHERE simulation_id = $1
           ORDER BY created_at""",
        simulation_id,
    )
    artifacts = [dict(r) for r in artifact_rows]

    # Overseer shadow logs
    overseer_rows = await db.fetch(
        """SELECT id, agent_id, original_content, filter_layer,
                  severity, action_would_take, reason, flagged_keywords, created_at
           FROM overseer_shadow_log
           WHERE simulation_id = $1
           ORDER BY created_at""",
        simulation_id,
    )
    overseer_logs = [dict(r) for r in overseer_rows]

    # Agent participation stats
    agent_turns: dict[str, int] = {}
    for conv in conversations:
        agents = conv.get("participating_agents")
        if isinstance(agents, list):
            for a in agents:
                agent_turns[a] = agent_turns.get(a, 0) + (conv.get("turn_count") or 0)

    return {
        "simulation": sim,
        "conversations": conversations,
        "transcript_text": transcript_text,
        "artifacts": artifacts,
        "overseer_logs": overseer_logs,
        "agent_turns": agent_turns,
        "total_conversations": len(conversations),
        "total_artifacts": len(artifacts),
        "total_overseer_flags": len(overseer_logs),
    }


def organize_by_category(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Slice simulation data by what each eval category needs."""
    return {
        "entertainment": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "agent_turns": data["agent_turns"],
            "total_conversations": data["total_conversations"],
        },
        "safety": {
            "transcript_text": data["transcript_text"],
            "overseer_logs": data["overseer_logs"],
            "artifacts": [
                a for a in data["artifacts"]
                if a.get("artifact_type") in ("social_post", "email")
            ],
        },
        "dialogue_quality": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "agent_turns": data["agent_turns"],
        },
        "productivity": {
            "artifacts": data["artifacts"],
            "conversations": data["conversations"],
            "total_artifacts": data["total_artifacts"],
        },
        "errors": {
            "artifacts": [
                a for a in data["artifacts"]
                if a.get("status") == "failed"
            ],
            "overseer_logs": data["overseer_logs"],
            "conversations": [
                c for c in data["conversations"]
                if c.get("turn_count") is not None and c["turn_count"] <= 1
            ],
            "simulation": data["simulation"],
        },
    }


def _build_transcript_text(conversations: list[dict[str, Any]]) -> str:
    """Combine conversation transcripts into a single text block."""
    parts: list[str] = []
    for conv in conversations:
        transcript = conv.get("transcript")
        if transcript:
            agents = conv.get("participating_agents", [])
            trigger = conv.get("trigger_type", "unknown")
            parts.append(
                f"--- Conversation (trigger={trigger}, agents={agents}) ---\n{transcript}\n"
            )
    return "\n".join(parts) if parts else "(No transcripts available)"
