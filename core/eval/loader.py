"""Data loader — fetches simulation data needed for evals."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from core.database import Database

# Default token budget per category to keep prompts within context window
DEFAULT_MAX_TRANSCRIPT_TOKENS = 50_000
EMBODIED_EVENT_TYPES = ("bridge_perception", "bridge_action_result", "minecraft_scene")
BUILD_ACTION_NAMES = frozenset(
    {
        "buildfromplan",
        "build-from-plan",
        "planandbuild",
        "plan-and-build",
        "!buildfromplan",
        "!planandbuild",
    }
)
BUILD_METRIC_RE = re.compile(
    r"\b(?P<name>intended|present|missing|unexpected|verified|abandoned|completion)="
    r"(?P<value>-?\d+(?:\.\d+)?)\b"
)


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

    # Embodied perception/action memory (for embodied-aware eval context)
    # Table has no simulation_id — filter by transcript time within the sim window.
    if sim_started and sim_ended:
        embodied_rows = await db.fetch(
            """SELECT id, event_type, participants, content, created_at
               FROM transcripts
               WHERE event_type = ANY($1::text[])
                 AND created_at >= $2 AND created_at <= $3
               ORDER BY created_at""",
            list(EMBODIED_EVENT_TYPES),
            sim_started,
            sim_ended,
        )
    else:
        embodied_rows = await db.fetch(
            """SELECT id, event_type, participants, content, created_at
               FROM transcripts
               WHERE event_type = ANY($1::text[])
               ORDER BY created_at""",
            list(EMBODIED_EVENT_TYPES),
        )
    embodied_actions, perception_reports = _split_embodied_events([dict(r) for r in embodied_rows])
    build_outcomes = _derive_build_outcomes(embodied_actions, perception_reports)

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
        "embodied_actions": embodied_actions,
        "perception_reports": perception_reports,
        "build_outcomes": build_outcomes,
        "embodied_summary": {
            "total_actions": len(embodied_actions),
            "total_perception_reports": len(perception_reports),
            "total_build_outcomes": len(build_outcomes),
        },
        "total_conversations": len(conversations),
        "total_artifacts": len(artifacts),
        "total_management_flags": len(management_logs),
    }


def organize_by_category(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Slice simulation data by what each eval category needs."""
    transcript_text = data.get("transcript_text") or "(No transcripts available)"
    conversations = data.get("conversations") or []
    artifacts = data.get("artifacts") or []
    management_logs = data.get("management_logs") or []
    agent_turns = data.get("agent_turns") or {}
    total_conversations = data.get("total_conversations", len(conversations))
    total_artifacts = data.get("total_artifacts", len(artifacts))
    total_management_flags = data.get("total_management_flags", len(management_logs))
    simulation = data.get("simulation", {})

    return {
        "entertainment": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "agent_turns": agent_turns,
            "total_conversations": total_conversations,
        },
        "safety": {
            "transcript_text": transcript_text,
            "artifacts": [
                a for a in artifacts if a.get("artifact_type") in ("social_post", "email")
            ],
        },
        "dialogue_quality": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "agent_turns": agent_turns,
        },
        "productivity": {
            "artifacts": artifacts,
            "conversations": conversations,
            "total_artifacts": total_artifacts,
            "embodied_actions": data.get("embodied_actions", []),
            "build_outcomes": data.get("build_outcomes", []),
            "embodied_summary": data.get("embodied_summary", {}),
        },
        "errors": {
            "artifacts": [a for a in artifacts if a.get("status") == "failed"],
            "management_logs": management_logs,
            "conversations": [
                c for c in conversations if c.get("turn_count") is not None and c["turn_count"] <= 1
            ],
            "simulation": simulation,
            # Include totals so the evaluator has context for the filtered data
            "total_artifacts": total_artifacts,
            "total_conversations": total_conversations,
            "total_management_flags": total_management_flags,
        },
        "agency": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "agent_turns": agent_turns,
            "artifacts": artifacts,
            "agent_goals": data.get("agent_goals", []),
            "tool_usage": data.get("tool_usage", []),
            "embodied_actions": data.get("embodied_actions", []),
            "build_outcomes": data.get("build_outcomes", []),
            "perception_reports": data.get("perception_reports", []),
            "embodied_summary": data.get("embodied_summary", {}),
        },
        "internal_state": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "agent_internal_state": data.get("agent_internal_state", []),
        },
        "economic_behavior": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "transactions": data.get("transactions", []),
        },
        "creativity": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "artifacts": artifacts,
            "dream_entries": data.get("dream_entries", []),
            "embodied_actions": data.get("embodied_actions", []),
            "build_outcomes": data.get("build_outcomes", []),
            "embodied_summary": data.get("embodied_summary", {}),
        },
        "social_dynamics": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "alliance_records": data.get("alliance_records", []),
        },
        "world_evolution": {
            "transcript_text": transcript_text,
            "conversations": conversations,
            "artifacts": artifacts,
            "world_chunks": data.get("world_chunks", []),
            "embodied_actions": data.get("embodied_actions", []),
            "build_outcomes": data.get("build_outcomes", []),
            "perception_reports": data.get("perception_reports", []),
            "embodied_summary": data.get("embodied_summary", {}),
        },
        "build_verification": {
            "build_outcomes": data.get("build_outcomes", []),
            "embodied_actions": data.get("embodied_actions", []),
            "world_chunks": data.get("world_chunks", []),
            "artifacts": artifacts,
            "total_artifacts": total_artifacts,
            "total_conversations": total_conversations,
            "embodied_summary": data.get("embodied_summary", {}),
        },
        "simulation_narrative": {
            "timeline": _build_timeline(data),
            "transcript_text": transcript_text,
            "conversations": conversations,
            "agent_internal_state": data.get("agent_internal_state", []),
            "transactions": data.get("transactions", []),
            "alliance_records": data.get("alliance_records", []),
            "dream_entries": data.get("dream_entries", []),
            "world_chunks": data.get("world_chunks", []),
            "embodied_actions": data.get("embodied_actions", []),
            "build_outcomes": data.get("build_outcomes", []),
            "perception_reports": data.get("perception_reports", []),
            "embodied_summary": data.get("embodied_summary", {}),
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

    # Embodied action outcomes
    for action in data.get("embodied_actions", []):
        created_at = action.get("created_at")
        if created_at is None:
            continue
        events.append(
            {
                "time": created_at,
                "type": "embodied_action",
                "agent": action.get("agent_id"),
                "action_id": action.get("action_id"),
                "status": action.get("status"),
                "outcome_class": action.get("outcome_class"),
                "detail": str(action.get("detail", ""))[:300],
            }
        )

    # Embodied perceptions and scene digests
    for report in data.get("perception_reports", []):
        created_at = report.get("created_at")
        if created_at is None:
            continue
        events.append(
            {
                "time": created_at,
                "type": "embodied_perception",
                "agent": report.get("agent_id"),
                "event_type": report.get("event_type"),
                "observation_count": len(report.get("observations", [])),
                "content": str(report.get("content", ""))[:300],
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
        elif etype == "embodied_action":
            line = (
                f"- **[{timestamp}] Embodied Action**: {event.get('agent')} — "
                f"action_id: {event.get('action_id')}, status: {event.get('status')}, "
                f"class: {event.get('outcome_class')}"
            )
            if event.get("detail"):
                line += f"\n  > {event.get('detail')}"
        elif etype == "embodied_perception":
            line = (
                f"- **[{timestamp}] Embodied Perception**: {event.get('agent')} — "
                f"{event.get('event_type')}, observations: {event.get('observation_count')}"
            )
            if event.get("content"):
                line += f"\n  > {event.get('content')}"
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


def _split_embodied_events(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for row in rows:
        event_type = str(row.get("event_type") or "")
        if event_type == "bridge_action_result":
            actions.append(_normalize_embodied_action(row))
        elif event_type in {"bridge_perception", "minecraft_scene"}:
            reports.append(_normalize_perception_report(row))
    return actions, reports


def _normalize_embodied_action(row: dict[str, Any]) -> dict[str, Any]:
    payload = _parsed_payload(row.get("content"))
    fields = _action_fields_from_content(row.get("content"))
    agent_id = _agent_id_from(row, payload)
    detail = _first_present(payload, "detail", "result", "message") or fields.get("detail")
    action_id = _first_present(payload, "action_id", "actionId") or fields.get("action_id")
    outcome_class = _first_present(payload, "outcome_class", "class", "outcomeClass") or fields.get(
        "class"
    )
    status = _first_present(payload, "status", "outcome") or fields.get("status")
    action = _first_present(payload, "action", "verb", "command", "tool", "action_type")

    return {
        "id": row.get("id"),
        "event_type": row.get("event_type"),
        "participants": row.get("participants") or [],
        "agent_id": agent_id,
        "created_at": row.get("created_at"),
        "action_id": action_id,
        "action": action,
        "status": status,
        "outcome_class": outcome_class,
        "detail": detail or "",
        "payload": payload,
        "content": row.get("content") or "",
    }


def _normalize_perception_report(row: dict[str, Any]) -> dict[str, Any]:
    payload = _parsed_payload(row.get("content"))
    observations = (
        payload.get("observations") if isinstance(payload.get("observations"), list) else []
    )
    if not observations and row.get("event_type") == "bridge_perception":
        observations = _observations_from_content(row.get("content"))
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), Mapping) else None

    return {
        "id": row.get("id"),
        "event_type": row.get("event_type"),
        "participants": row.get("participants") or [],
        "agent_id": _agent_id_from(row, payload),
        "created_at": row.get("created_at"),
        "observations": observations,
        "snapshot": snapshot,
        "payload": payload,
        "content": row.get("content") or "",
    }


def _derive_build_outcomes(
    actions: list[dict[str, Any]],
    perception_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    observation_metrics = _build_metrics_by_action_id(perception_reports)

    for action in actions:
        metric = _extract_build_verification(action)
        if not metric:
            action_id = action.get("action_id")
            metric = observation_metrics.get(str(action_id)) if action_id else None
        if not metric:
            continue

        action_name = str(action.get("action") or "")
        detail = str(action.get("detail") or "")
        if (
            action_name
            and not _is_build_action_name(action_name)
            and not _looks_like_build_detail(detail)
        ):
            continue

        outcome = {
            "agent_id": action.get("agent_id"),
            "action_id": action.get("action_id"),
            "action": action.get("action"),
            "status": action.get("status"),
            "outcome_class": action.get("outcome_class") or metric.get("class"),
            "detail": detail,
            **metric,
            "created_at": action.get("created_at"),
        }
        outcomes.append(outcome)

    return outcomes


def _build_metrics_by_action_id(
    perception_reports: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_action_id: dict[str, dict[str, Any]] = {}
    for report in perception_reports:
        for observation in report.get("observations", []):
            if not isinstance(observation, Mapping):
                continue
            action_id = _first_present(observation, "action_id", "actionId")
            if not action_id:
                continue
            metric = _extract_build_verification(observation)
            if metric:
                by_action_id[str(action_id)] = metric
    return by_action_id


def _extract_build_verification(source: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = source.get("payload") if isinstance(source.get("payload"), Mapping) else source
    detail = str(source.get("detail") or payload.get("detail") or payload.get("result") or "")

    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("verification", "verify_build_plan", "build_plan", "metric"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)

    merged: dict[str, Any] = {}
    for candidate in candidates:
        for src, dest in (
            ("verified", "verified"),
            ("class", "class"),
            ("outcome_class", "class"),
            ("intended", "intended"),
            ("intended_count", "intended"),
            ("present", "present"),
            ("blocks_present", "present"),
            ("missing", "missing"),
            ("blocks_missing", "missing"),
            ("unexpected", "unexpected"),
            ("blocks_unexpected", "unexpected"),
            ("steps_verified", "verified_blocks"),
            ("verified_blocks", "verified_blocks"),
            ("steps_abandoned", "abandoned"),
            ("completion", "completion"),
            ("completion_ratio", "completion"),
        ):
            if src in candidate and candidate.get(src) is not None:
                merged[dest] = candidate.get(src)

    for name, value in BUILD_METRIC_RE.findall(detail):
        dest = (
            "verified_blocks"
            if name == "verified"
            else "abandoned"
            if name == "abandoned"
            else name
        )
        merged[dest] = value

    if "class" not in merged:
        outcome_class = _first_present(payload, "outcome_class", "class")
        if outcome_class is not None:
            merged["class"] = outcome_class

    if not any(key in merged for key in ("intended", "present", "missing", "completion")):
        return None

    intended = _coerce_int(merged.get("intended"))
    present = _coerce_int(merged.get("present"))
    missing = _coerce_int(merged.get("missing"))
    unexpected = _coerce_int(merged.get("unexpected"))
    verified_blocks = _coerce_int(merged.get("verified_blocks"))
    abandoned = _coerce_int(merged.get("abandoned"))
    completion = _coerce_float(merged.get("completion"))
    if completion is None and intended and present is not None:
        completion = round(present / intended, 4)

    verified = _coerce_bool(merged.get("verified"))
    if verified is None:
        verified = bool(
            completion is not None
            and completion >= 1
            and (missing is None or missing == 0)
            and (unexpected is None or unexpected == 0)
        )

    return {
        "verified": verified,
        "class": str(merged.get("class") or ""),
        "intended": intended,
        "present": present,
        "missing": missing,
        "unexpected": unexpected,
        "verified_blocks": verified_blocks,
        "abandoned": abandoned,
        "completion": completion,
    }


def _parsed_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, Mapping):
        return dict(content)
    if not isinstance(content, str):
        return {}
    text = content.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _action_fields_from_content(content: Any) -> dict[str, str]:
    if not isinstance(content, str):
        return {}
    fields: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _observations_from_content(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, str):
        return []
    observations: list[dict[str, Any]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        try:
            parsed = json.loads(stripped[2:].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            observations.append(parsed)
    return observations


def _agent_id_from(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str | None:
    agent_id = _first_present(payload, "agent_id", "agent", "source_agent_id")
    if agent_id:
        return str(agent_id)
    participants = row.get("participants")
    if isinstance(participants, list) and participants:
        return str(participants[0])
    return None


def _first_present(source: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def _is_build_action_name(value: str) -> bool:
    return value.strip().lower().replace("_", "-").replace("!", "") in {
        name.replace("!", "") for name in BUILD_ACTION_NAMES
    }


def _looks_like_build_detail(value: str) -> bool:
    lowered = value.lower()
    return (
        "build-from-plan" in lowered
        or "plan-and-build" in lowered
        or ("intended=" in lowered and "completion=" in lowered)
    )


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    if isinstance(value, int | float):
        return bool(value)
    return None
