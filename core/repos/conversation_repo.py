"""Repository for conversations, conversation_selection_log, interrupt_log."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.models import (
    Conversation,
    ConversationCreate,
    EnergyLogCreate,
    InterruptLogCreate,
    SelectionLog,
    SelectionLogCreate,
)
from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import uuid

    import asyncpg

    from core.database import Database


def _row_to_conversation(row: asyncpg.Record) -> Conversation:
    d = dict(row)
    for key in ("trigger_details", "participating_agents", "topics_discussed"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
    return Conversation(**d)


class ConversationRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, conv: ConversationCreate) -> Conversation:
        if conv.id is not None:
            row = await self.db.fetchrow(
                """INSERT INTO conversations
                   (id, trigger_type, trigger_details, initial_energy,
                    participating_agents, location, config_hash, simulation_id)
                   VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7, $8)
                   RETURNING *""",
                conv.id,
                conv.trigger_type,
                serialize_jsonb(conv.trigger_details),
                conv.initial_energy,
                serialize_jsonb(conv.participating_agents),
                conv.location,
                conv.config_hash,
                conv.simulation_id,
            )
        else:
            row = await self.db.fetchrow(
                """INSERT INTO conversations
                   (trigger_type, trigger_details, initial_energy,
                    participating_agents, location, config_hash, simulation_id)
                   VALUES ($1, $2::jsonb, $3, $4::jsonb, $5, $6, $7)
                   RETURNING *""",
                conv.trigger_type,
                serialize_jsonb(conv.trigger_details),
                conv.initial_energy,
                serialize_jsonb(conv.participating_agents),
                conv.location,
                conv.config_hash,
                conv.simulation_id,
            )
        return _row_to_conversation(row)

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        row = await self.db.fetchrow(
            "SELECT * FROM conversations WHERE id = $1", conversation_id
        )
        return _row_to_conversation(row) if row else None

    async def close(
        self,
        conversation_id: uuid.UUID,
        final_energy: float,
        closed_by: str,
        turn_count: int | None = None,
    ) -> Conversation | None:
        row = await self.db.fetchrow(
            """UPDATE conversations
               SET ended_at = NOW(), final_energy = $1, closed_by = $2,
                   turn_count = COALESCE($3, turn_count)
               WHERE id = $4
               RETURNING *""",
            final_energy,
            closed_by,
            turn_count,
            conversation_id,
        )
        return _row_to_conversation(row) if row else None

    async def log_selection(self, entry: SelectionLogCreate) -> None:
        await self.db.execute(
            """INSERT INTO conversation_selection_log
               (conversation_id, turn_number, selected_agent_id, was_interrupt,
                agent_scores, detected_topic, previous_speaker_id,
                conversation_energy, active_agents, trigger_type, config_hash)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9::jsonb, $10, $11)""",
            entry.conversation_id,
            entry.turn_number,
            entry.selected_agent_id,
            entry.was_interrupt,
            serialize_jsonb(entry.agent_scores),
            entry.detected_topic,
            entry.previous_speaker_id,
            entry.conversation_energy,
            serialize_jsonb(entry.active_agents),
            entry.trigger_type,
            entry.config_hash,
        )

    async def log_interrupt(self, entry: InterruptLogCreate) -> None:
        await self.db.execute(
            """INSERT INTO interrupt_log
               (conversation_id, attempting_agent_id, would_have_spoken_id,
                interrupt_score, threshold_at_time, succeeded, reason)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            entry.conversation_id,
            entry.attempting_agent_id,
            entry.would_have_spoken_id,
            entry.interrupt_score,
            entry.threshold_at_time,
            entry.succeeded,
            entry.reason,
        )

    async def log_energy(self, entry: EnergyLogCreate) -> None:
        await self.db.execute(
            """INSERT INTO energy_change_log
               (conversation_id, turn_number, changes)
               VALUES ($1, $2, $3::jsonb)""",
            entry.conversation_id,
            entry.turn_number,
            serialize_jsonb(entry.changes),
        )

    async def cleanup_old_logs(self, retention_days: int) -> None:
        interval = f"{retention_days} days"
        for table in (
            "conversation_selection_log",
            "interrupt_log",
            "energy_change_log",
        ):
            await self.db.execute(
                f"DELETE FROM {table} WHERE timestamp < NOW() - $1::interval",  # noqa: S608
                interval,
            )

    async def get_selection_log(
        self, conversation_id: uuid.UUID
    ) -> list[SelectionLog]:
        rows = await self.db.fetch(
            """SELECT * FROM conversation_selection_log
               WHERE conversation_id = $1
               ORDER BY turn_number""",
            conversation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            for key in ("agent_scores", "active_agents"):
                if isinstance(d.get(key), str):
                    d[key] = json.loads(d[key])
            result.append(SelectionLog(**d))
        return result

    async def get_conversations_by_agent(
        self,
        agent_id: str,
        *,
        simulation_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Conversation], int]:
        """Return paginated conversations where agent participated."""
        clauses = ["participating_agents @> to_jsonb(ARRAY[$1])"]
        params: list[object] = [agent_id]
        idx = 2

        if simulation_id is not None:
            clauses.append(f"simulation_id = ${idx}")
            params.append(simulation_id)
            idx += 1

        where = " AND ".join(clauses)
        count = await self.db.fetchval(
            f"SELECT COUNT(*) FROM conversations WHERE {where}",  # noqa: S608
            *params,
        )
        query = (
            f"SELECT * FROM conversations WHERE {where}"  # noqa: S608
            f" ORDER BY started_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
        )
        rows = await self.db.fetch(
            query,
            *params,
            limit,
            offset,
        )
        return [_row_to_conversation(r) for r in rows], count or 0

    async def get_conversations_by_simulation(
        self,
        simulation_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Conversation], int]:
        """Return paginated conversations linked to a simulation via direct FK."""
        count = await self.db.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE simulation_id = $1",
            simulation_id,
        )
        rows = await self.db.fetch(
            """SELECT * FROM conversations
               WHERE simulation_id = $1
               ORDER BY started_at DESC
               LIMIT $2 OFFSET $3""",
            simulation_id,
            limit,
            offset,
        )
        return [_row_to_conversation(r) for r in rows], count or 0

    async def get_energy_log(
        self, conversation_id: uuid.UUID
    ) -> list[dict[str, object]]:
        """Return energy change log entries for a conversation."""
        rows = await self.db.fetch(
            """SELECT * FROM energy_change_log
               WHERE conversation_id = $1
               ORDER BY turn_number""",
            conversation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("changes"), str):
                d["changes"] = json.loads(d["changes"])
            result.append(d)
        return result

    async def get_overseer_flags(
        self, conversation_id: uuid.UUID
    ) -> list[dict[str, object]]:
        """Return overseer shadow flags for a conversation."""
        rows = await self.db.fetch(
            """SELECT * FROM overseer_shadow_log
               WHERE conversation_id = $1
               ORDER BY created_at""",
            conversation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            result.append({
                "id": str(d["id"]),
                "agent_id": d["agent_id"],
                "original_content": d["original_content"],
                "filter_layer": d["filter_layer"],
                "severity": d["severity"],
                "action_would_take": d["action_would_take"],
                "reason": d["reason"],
                "flagged_keywords": d.get("flagged_keywords") or [],
                "created_at": (
                    d["created_at"].isoformat() if d["created_at"] else None
                ),
            })
        return result

    async def get_artifacts(
        self, conversation_id: uuid.UUID
    ) -> list[dict[str, object]]:
        """Return artifacts (tool invocations) for a conversation."""
        rows = await self.db.fetch(
            """SELECT * FROM artifacts
               WHERE conversation_id = $1
               ORDER BY created_at""",
            conversation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            for key in ("tool_input", "tool_output", "metadata"):
                if isinstance(d.get(key), str):
                    d[key] = json.loads(d[key])
            result.append({
                "id": str(d["id"]),
                "agent_id": d["agent_id"],
                "tool_name": d["tool_name"],
                "tool_input": d.get("tool_input") or {},
                "tool_output": d.get("tool_output"),
                "artifact_type": d["artifact_type"],
                "status": d["status"],
                "metadata": d.get("metadata"),
                "created_at": (
                    d["created_at"].isoformat() if d["created_at"] else None
                ),
            })
        return result

    async def get_interrupts(
        self, conversation_id: uuid.UUID
    ) -> list[dict[str, object]]:
        """Return interrupt log entries for a conversation."""
        rows = await self.db.fetch(
            """SELECT * FROM interrupt_log
               WHERE conversation_id = $1
               ORDER BY timestamp""",
            conversation_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            result.append({
                "id": d["id"],
                "attempting_agent_id": d["attempting_agent_id"],
                "would_have_spoken_id": d["would_have_spoken_id"],
                "interrupt_score": d["interrupt_score"],
                "threshold_at_time": d["threshold_at_time"],
                "succeeded": d["succeeded"],
                "reason": d.get("reason"),
                "timestamp": (
                    d["timestamp"].isoformat() if d["timestamp"] else None
                ),
            })
        return result
