"""Data loader — fetches simulation data needed for evals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from core.database import Database

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
    sim_row = await db.fetchrow("SELECT * FROM simulations WHERE id = $1", simulation_id)
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

    # Derive simulation time window for tables lacking a simulation_id column.
    sim_started = sim.get("started_at")
    sim_ended = sim.get("completed_at")

    # Agent internal state snapshots (for internal_state eval)
    # Table has no simulation_id — filter by update time within the sim window.
    if sim_started and sim_ended:
        internal_state_rows = await db.fetch(
            """SELECT agent_id, energy, satisfaction, boredom, frustration,
                      social_need, creative_need, recognition_need, mood,
                      version, updated_at
               FROM agent_internal_state
               WHERE updated_at >= $1 AND updated_at <= $2
               ORDER BY agent_id""",
            sim_started,
            sim_ended,
        )
    else:
        internal_state_rows = await db.fetch(
            """SELECT agent_id, energy, satisfaction, boredom, frustration,
                      social_need, creative_need, recognition_need, mood,
                      version, updated_at
               FROM agent_internal_state
               ORDER BY agent_id"""
        )
    agent_internal_state = [dict(r) for r in internal_state_rows]

    # Transaction history (for economic_behavior eval)
    # Table has no simulation_id — filter by created_at within the sim window.
    if sim_started and sim_ended:
        transaction_rows = await db.fetch(
            """SELECT id, agent_id, type, amount, counterparty_agent_id,
                      description, created_at
               FROM agent_transactions
               WHERE created_at >= $1 AND created_at <= $2
               ORDER BY created_at""",
            sim_started,
            sim_ended,
        )
    else:
        transaction_rows = await db.fetch(
            """SELECT id, agent_id, type, amount, counterparty_agent_id,
                      description, created_at
               FROM agent_transactions
               ORDER BY created_at"""
        )
    transactions = [dict(r) for r in transaction_rows]

    # Dream journal entries (for creativity eval)
    # Table has no simulation_id — filter by created_at within the sim window.
    if sim_started and sim_ended:
        dream_rows = await db.fetch(
            """SELECT id, agent_id, reflection_type, content, created_at
               FROM journal_entries
               WHERE entry_type = 'dream' AND created_at >= $1 AND created_at <= $2
               ORDER BY created_at""",
            sim_started,
            sim_ended,
        )
    else:
        dream_rows = await db.fetch(
            """SELECT id, agent_id, reflection_type, content, created_at
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
                a for a in data["artifacts"] if a.get("artifact_type") in ("social_post", "email")
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
            "artifacts": [a for a in data["artifacts"] if a.get("status") == "failed"],
            "management_logs": data["management_logs"],
            "conversations": [
                c
                for c in data["conversations"]
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
        "simulation_narrative": {
            "timeline": _build_timeline(data),
            "transcript_text": data["transcript_text"],
            "conversations": data["conversations"],
            "agent_internal_state": data.get("agent_internal_state", []),
            "transactions": data.get("transactions", []),
            "alliance_records": data.get("alliance_records", []),
            "dream_entries": data.get("dream_entries", []),
            "world_chunks": data.get("world_chunks", []),
        },
    }


def _build_timeline(data: dict[str, Any]) -> str:
    """Build a chronological timeline of all simulation events."""
    events: list[dict[str, Any]] = []

    # Conversations (with timestamps)
    for conv in data.get("conversations", []):
        started_at = conv.get("started_at")
        if started_at is None:
            continue
        events.append(
            {
                "time": started_at,
                "type": "conversation",
                "agents": conv.get("participating_agents", []),
                "trigger": conv.get("trigger_type", "unknown"),
                "summary": str(conv.get("transcript", ""))[:500],
            }
        )

    # Internal state changes
    for state in data.get("agent_internal_state", []):
        updated_at = state.get("updated_at")
        if updated_at is None:
            continue
        events.append(
            {
                "time": updated_at,
                "type": "state_change",
                "agent": state.get("agent_id"),
                "mood": state.get("mood"),
                "energy": state.get("energy"),
            }
        )

    # Transactions
    for txn in data.get("transactions", []):
        created_at = txn.get("created_at")
        if created_at is None:
            continue
        events.append(
            {
                "time": created_at,
                "type": "transaction",
                "agent": txn.get("agent_id"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
            }
        )

    # Alliance formations
    for alliance in data.get("alliance_records", []):
        created_at = alliance.get("created_at")
        if created_at is None:
            continue
        events.append(
            {
                "time": created_at,
                "type": "alliance_formed",
                "name": alliance.get("name"),
                "members": alliance.get("members", []),
            }
        )

    # Dreams
    for dream in data.get("dream_entries", []):
        created_at = dream.get("created_at")
        if created_at is None:
            continue
        events.append(
            {
                "time": created_at,
                "type": "dream",
                "agent": dream.get("agent_id"),
                "content": str(dream.get("content", ""))[:300],
            }
        )

    # World builds
    for chunk in data.get("world_chunks", []):
        built_date = chunk.get("built_date")
        if built_date is None:
            continue
        events.append(
            {
                "time": built_date,
                "type": "world_build",
                "name": chunk.get("name"),
                "built_by": chunk.get("built_by"),
            }
        )

    # Sort chronologically
    events.sort(
        key=lambda e: (
            e["time"] if isinstance(e["time"], datetime) else datetime.min.replace(tzinfo=UTC)
        )
    )

    return _render_timeline_markdown(events)


def _render_timeline_markdown(events: list[dict[str, Any]]) -> str:
    """Render a list of timeline events as a markdown document."""
    if not events:
        return "(No timeline events available)"

    lines: list[str] = ["# Simulation Timeline", ""]
    for event in events:
        ts = event["time"]
        timestamp = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        etype = event["type"]

        if etype == "conversation":
            agents = ", ".join(event.get("agents", []))
            trigger = event.get("trigger", "unknown")
            summary = event.get("summary", "")
            line = f"- **[{timestamp}] Conversation** ({trigger}): {agents}"
            if summary:
                line += f"\n  > {summary[:200]}"
        elif etype == "state_change":
            line = (
                f"- **[{timestamp}] State Change**: {event.get('agent')} — "
                f"mood: {event.get('mood')}, energy: {event.get('energy')}"
            )
        elif etype == "transaction":
            line = (
                f"- **[{timestamp}] Transaction**: {event.get('agent')} — "
                f"amount: {event.get('amount')}, {event.get('description', '')}"
            )
        elif etype == "alliance_formed":
            members = ", ".join(event.get("members", []))
            line = f"- **[{timestamp}] Alliance Formed**: {event.get('name')} — members: {members}"
        elif etype == "dream":
            line = f"- **[{timestamp}] Dream**: {event.get('agent')} — {event.get('content', '')}"
        elif etype == "world_build":
            line = (
                f"- **[{timestamp}] World Build**: {event.get('name')} — "
                f"built by {event.get('built_by')}"
            )
        else:
            line = f"- **[{timestamp}] {etype}**: {event}"

        lines.append(line)

    return "\n".join(lines)


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
