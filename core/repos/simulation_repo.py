"""Repository for simulation tracking — CRUD and incremental stat updates."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

from core.models import Simulation, SimulationCreate
from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import uuid
    from datetime import datetime, timedelta

    from core.database import Database


def _parse_row(row: dict) -> dict:
    for key in ("config", "error_log"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


class SimulationRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, sim: SimulationCreate) -> Simulation:
        row = await self.db.fetchrow(
            """INSERT INTO simulations
               (name, description, config, status,
                simulated_duration, agents_participated, error_log)
               VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7::jsonb)
               RETURNING *""",
            sim.name,
            sim.description,
            serialize_jsonb(sim.config),
            sim.status,
            sim.simulated_duration,
            sim.agents_participated,
            serialize_jsonb(sim.error_log),
        )
        return Simulation(**_parse_row(dict(row)))

    async def get(self, simulation_id: uuid.UUID) -> Simulation | None:
        row = await self.db.fetchrow(
            "SELECT * FROM simulations WHERE id = $1", simulation_id
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Simulation]:
        if status is not None:
            rows = await self.db.fetch(
                """SELECT * FROM simulations
                   WHERE status = $1
                   ORDER BY started_at DESC
                   LIMIT $2 OFFSET $3""",
                status,
                limit,
                offset,
            )
        else:
            rows = await self.db.fetch(
                """SELECT * FROM simulations
                   ORDER BY started_at DESC
                   LIMIT $1 OFFSET $2""",
                limit,
                offset,
            )
        return [Simulation(**_parse_row(dict(r))) for r in rows]

    async def update_status(
        self,
        simulation_id: uuid.UUID,
        status: str,
        *,
        completed_at: datetime | None = None,
        error_log: dict | list | None = None,
    ) -> Simulation | None:
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET status = $1, completed_at = $2, error_log = $3::jsonb
               WHERE id = $4
               RETURNING *""",
            status,
            completed_at,
            serialize_jsonb(error_log),
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def increment_stats(
        self,
        simulation_id: uuid.UUID,
        *,
        conversations: int = 0,
        turns: int = 0,
        tokens: int = 0,
        cost: Decimal = Decimal("0"),
        artifacts: int = 0,
        overseer_flags: int = 0,
    ) -> Simulation | None:
        row = await self.db.fetchrow(
            """UPDATE simulations SET
                 total_conversations = total_conversations + $1,
                 total_turns = total_turns + $2,
                 total_tokens = total_tokens + $3,
                 total_cost = total_cost + $4,
                 total_artifacts = total_artifacts + $5,
                 total_overseer_flags = total_overseer_flags + $6
               WHERE id = $7
               RETURNING *""",
            conversations,
            turns,
            tokens,
            cost,
            artifacts,
            overseer_flags,
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def update_agents_participated(
        self,
        simulation_id: uuid.UUID,
        agents: list[str],
    ) -> None:
        # Merge new agents into existing array, keeping unique values
        await self.db.execute(
            """UPDATE simulations
               SET agents_participated = (
                   SELECT ARRAY(
                       SELECT DISTINCT unnest(agents_participated || $1::text[])
                   )
               )
               WHERE id = $2""",
            agents,
            simulation_id,
        )

    async def update_durations(
        self,
        simulation_id: uuid.UUID,
        *,
        simulated_duration: timedelta | None = None,
        real_duration: timedelta | None = None,
    ) -> Simulation | None:
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET simulated_duration = COALESCE($1, simulated_duration),
                   real_duration = COALESCE($2, real_duration)
               WHERE id = $3
               RETURNING *""",
            simulated_duration,
            real_duration,
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def delete(self, simulation_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            "DELETE FROM simulations WHERE id = $1", simulation_id
        )
        return result == "DELETE 1"

    async def count(self, *, status: str | None = None) -> int:
        """Return total count of simulations, optionally filtered by status."""
        if status is not None:
            val = await self.db.fetchval(
                "SELECT COUNT(*) FROM simulations WHERE status = $1", status
            )
        else:
            val = await self.db.fetchval("SELECT COUNT(*) FROM simulations")
        return val or 0

    async def get_timeline_events(
        self,
        simulation_id: uuid.UUID,
        *,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        """Return a chronological timeline of events for a simulation.

        Unions conversations (start/end), artifacts, and overseer flags.
        """
        events: list[dict] = []

        # Conversations started — use direct FK
        conv_where = "c.simulation_id = $1"
        conv_params: list[object] = [simulation_id]
        idx = 2
        if agent_id is not None:
            conv_where += f" AND c.participating_agents @> to_jsonb(ARRAY[${idx}])"
            conv_params.append(agent_id)
            idx += 1

        if event_type is None or event_type == "conversation":
            rows = await self.db.fetch(
                f"""SELECT c.id, c.started_at, c.ended_at,
                       c.participating_agents, c.trigger_type, c.turn_count
                    FROM conversations c
                    WHERE {conv_where}
                    ORDER BY c.started_at""",  # noqa: S608
                *conv_params,
            )
            for r in rows:
                d = dict(r)
                agents = d["participating_agents"]
                if isinstance(agents, str):
                    agents = json.loads(agents)
                events.append({
                    "timestamp": d["started_at"].isoformat() if d["started_at"] else None,
                    "event_type": "conversation_started",
                    "agent_id": None,
                    "details": {
                        "conversation_id": str(d["id"]),
                        "participants": agents,
                        "trigger_type": d["trigger_type"],
                        "turn_count": d["turn_count"],
                    },
                })
                if d["ended_at"]:
                    events.append({
                        "timestamp": d["ended_at"].isoformat(),
                        "event_type": "conversation_ended",
                        "agent_id": None,
                        "details": {"conversation_id": str(d["id"])},
                    })

        # Artifacts (tool usage)
        if event_type is None or event_type == "tool_use":
            art_where = "simulation_id = $1"
            art_params: list[object] = [simulation_id]
            art_idx = 2
            if agent_id is not None:
                art_where += f" AND agent_id = ${art_idx}"
                art_params.append(agent_id)
            rows = await self.db.fetch(
                f"""SELECT id, agent_id, tool_name, artifact_type, created_at
                    FROM artifacts WHERE {art_where}
                    ORDER BY created_at""",  # noqa: S608
                *art_params,
            )
            for r in rows:
                d = dict(r)
                events.append({
                    "timestamp": d["created_at"].isoformat() if d["created_at"] else None,
                    "event_type": "tool_use",
                    "agent_id": d["agent_id"],
                    "details": {
                        "artifact_id": str(d["id"]),
                        "tool_name": d["tool_name"],
                        "artifact_type": d["artifact_type"],
                    },
                })

        # Sort all events chronologically
        events.sort(key=lambda e: e["timestamp"] or "")
        return events

    async def get_overseer_log(
        self,
        simulation_id: uuid.UUID,
        *,
        severity_min: int = 1,
    ) -> list[dict]:
        """Return overseer shadow flags for a simulation filtered by severity."""
        rows = await self.db.fetch(
            """SELECT id, agent_id, tool_name, tool_output, metadata, created_at
               FROM artifacts
               WHERE simulation_id = $1
                 AND artifact_type = 'overseer_flag'
                 AND (metadata->>'severity')::int >= $2
               ORDER BY created_at""",
            simulation_id,
            severity_min,
        )
        result = []
        for r in rows:
            d = dict(r)
            for key in ("tool_output", "metadata"):
                if isinstance(d.get(key), str):
                    d[key] = json.loads(d[key])
            result.append({
                "id": str(d["id"]),
                "agent_id": d["agent_id"],
                "tool_name": d["tool_name"],
                "output": d["tool_output"],
                "metadata": d["metadata"],
                "created_at": d["created_at"].isoformat() if d["created_at"] else None,
            })
        return result
