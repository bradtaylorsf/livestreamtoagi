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

    # Conversations with transcripts (DISTINCT ON prevents duplicates from
    # legacy data where transcripts were stored once per participant)
    conv_rows = await db.fetch(
        """SELECT DISTINCT ON (c.id)
                  c.id, c.trigger_type, c.participating_agents,
                  c.turn_count, c.started_at, c.ended_at,
                  t.content AS transcript
           FROM conversations c
           LEFT JOIN transcripts t ON t.conversation_id = c.id
           WHERE c.simulation_id = $1
           ORDER BY c.id, c.started_at""",
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

    # Management shadow logs
    management_rows = await db.fetch(
        """SELECT id, agent_id, original_content, filter_layer,
                  severity, action_would_take, reason, flagged_keywords, created_at
           FROM management_shadow_log
           WHERE simulation_id = $1
           ORDER BY created_at""",
        simulation_id,
    )
    management_logs = [dict(r) for r in management_rows]

    # Agent participation stats
    agent_turns: dict[str, int] = {}
    for conv in conversations:
        agents = conv.get("participating_agents")
        if isinstance(agents, list):
            for a in agents:
                agent_turns[a] = agent_turns.get(a, 0) + (conv.get("turn_count") or 0)

    # Agent goals (for agency eval)
    goal_rows = await db.fetch(
        """SELECT id, agent_id, goal, priority, status, source, progress_notes,
                  created_at, completed_at
           FROM agent_goals
           ORDER BY agent_id, priority ASC"""
    )
    agent_goals = [dict(r) for r in goal_rows]

    # Tool usage summary (for agency eval)
    tool_usage_rows = await db.fetch(
        """SELECT agent_id, tool_name, COUNT(*) as use_count
           FROM artifacts
           WHERE simulation_id = $1
           GROUP BY agent_id, tool_name
           ORDER BY agent_id, use_count DESC""",
        simulation_id,
    )
    tool_usage = [dict(r) for r in tool_usage_rows]

    # Agent internal state snapshots (for internal_state eval)
    internal_state_rows = await db.fetch(
        """SELECT agent_id, energy, satisfaction, boredom, frustration,
                  social_need, creative_need, recognition_need, mood,
                  version, updated_at
           FROM agent_internal_state
           ORDER BY agent_id"""
    )
    agent_internal_state = [dict(r) for r in internal_state_rows]

    # Transaction history (for economic_behavior eval)
    transaction_rows = await db.fetch(
        """SELECT id, agent_id, type, amount, counterparty_agent_id,
                  description, created_at
           FROM agent_transactions
           ORDER BY created_at"""
    )
    transactions = [dict(r) for r in transaction_rows]

    # Dream journal entries (for creativity eval)
    dream_rows = await db.fetch(
        """SELECT id, agent_id, reflection_type, content, insights,
                  created_at
           FROM journal_entries
           WHERE entry_type = 'dream'
           ORDER BY created_at"""
    )
    dream_entries = [dict(r) for r in dream_rows]

    # Alliance records (for social_dynamics eval)
    alliance_rows = await db.fetch(
        """SELECT a.id, a.name, a.founded_by, a.purpose, a.shared_treasury,
                  a.created_at, a.dissolved_at,
                  COALESCE(
                      array_agg(am.agent_id) FILTER (WHERE am.agent_id IS NOT NULL),
                      '{}'
                  ) AS members
           FROM alliances a
           LEFT JOIN alliance_members am
               ON am.alliance_id = a.id AND am.left_at IS NULL
           WHERE a.simulation_id = $1 OR a.simulation_id IS NULL
           GROUP BY a.id
           ORDER BY a.created_at""",
        simulation_id,
    )
    alliance_records = [dict(r) for r in alliance_rows]

    # World chunks (for world_evolution eval)
    world_chunk_rows = await db.fetch(
        """SELECT id, name, x_offset, y_offset, width, height,
                  built_by, built_date, description
           FROM world_chunks
           ORDER BY built_date"""
    )
    world_chunks = [dict(r) for r in world_chunk_rows]

    return {
        "simulation": sim,
        "conversations": conversations,
        "transcript_text": transcript_text,
        "artifacts": artifacts,
        "management_logs": management_logs,
        "agent_turns": agent_turns,
        "agent_goals": agent_goals,
        "tool_usage": tool_usage,
        "agent_internal_state": agent_internal_state,
        "transactions": transactions,
        "dream_entries": dream_entries,
        "alliance_records": alliance_records,
        "world_chunks": world_chunks,
        "total_conversations": len(conversations),
        "total_artifacts": len(artifacts),
        "total_management_flags": len(management_logs),
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
            "management_logs": data["management_logs"],
            "conversations": [
                c for c in data["conversations"]
                if c.get("turn_count") is not None and c["turn_count"] <= 1
            ],
            "simulation": data["simulation"],
            # Include totals so the evaluator has context for the filtered data
            "total_artifacts": data["total_artifacts"],
            "total_conversations": data["total_conversations"],
            "total_management_flags": data["total_management_flags"],
        },
        "agency": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "agent_turns": data["agent_turns"],
            "artifacts": data["artifacts"],
            "agent_goals": data.get("agent_goals", []),
            "tool_usage": data.get("tool_usage", []),
        },
        "internal_state": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "agent_internal_state": data.get("agent_internal_state", []),
        },
        "economic_behavior": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "transactions": data.get("transactions", []),
        },
        "creativity": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "artifacts": data["artifacts"],
            "dream_entries": data.get("dream_entries", []),
        },
        "social_dynamics": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "alliance_records": data.get("alliance_records", []),
        },
        "world_evolution": {
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "artifacts": data["artifacts"],
            "world_chunks": data.get("world_chunks", []),
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
