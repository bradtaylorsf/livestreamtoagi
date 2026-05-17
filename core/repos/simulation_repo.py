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
    from typing import Any

    from core.database import Database


def _parse_row(row: dict) -> dict:
    for key in (
        "config",
        "error_log",
        "model_versions",
        "outcomes",
        "learnings",
        "factions",
    ):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    # Fallback: derive real_duration from start/end timestamps for legacy rows
    # where the column is NULL but both timestamps were persisted.
    if (
        row.get("real_duration") is None
        and row.get("started_at") is not None
        and row.get("completed_at") is not None
    ):
        row["real_duration"] = row["completed_at"] - row["started_at"]
    return row


class SimulationRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, sim: SimulationCreate) -> Simulation:
        row = await self.db.fetchrow(
            """INSERT INTO simulations
               (name, description, config, status,
                simulated_duration, agents_participated, error_log,
                model_versions, hypothesis, outcomes, learnings,
                factions, submitted_by_user_id, publish_to_youtube)
               VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7::jsonb, $8::jsonb,
                       $9, $10::jsonb, $11::jsonb, $12::jsonb, $13, $14)
               RETURNING *""",
            sim.name,
            sim.description,
            serialize_jsonb(sim.config),
            sim.status,
            sim.simulated_duration,
            sim.agents_participated,
            serialize_jsonb(sim.error_log),
            serialize_jsonb(sim.model_versions),
            sim.hypothesis,
            serialize_jsonb(sim.outcomes),
            serialize_jsonb(sim.learnings),
            serialize_jsonb(sim.factions),
            sim.submitted_by_user_id,
            sim.publish_to_youtube,
        )
        return Simulation(**_parse_row(dict(row)))

    async def count_active_for_user(self, user_id: uuid.UUID) -> int:
        """Count this user's simulations that are still queued or running."""
        val = await self.db.fetchval(
            """SELECT COUNT(*) FROM simulations
               WHERE submitted_by_user_id = $1
                 AND status IN ('queued', 'running')""",
            user_id,
        )
        return val or 0

    async def count_today_for_user(self, user_id: uuid.UUID) -> int:
        """Count submissions in the last 24 hours for the daily rate limit."""
        val = await self.db.fetchval(
            """SELECT COUNT(*) FROM simulations
               WHERE submitted_by_user_id = $1
                 AND started_at >= now() - interval '1 day'""",
            user_id,
        )
        return val or 0

    async def update_factions(
        self,
        simulation_id: uuid.UUID,
        factions: list[dict[str, Any]],
    ) -> Simulation | None:
        """Overwrite the factions JSONB column for a simulation."""
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET factions = $1::jsonb
               WHERE id = $2
               RETURNING *""",
            serialize_jsonb(factions),
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def update_research_fields(
        self,
        simulation_id: uuid.UUID,
        *,
        hypothesis: str | None = None,
        outcomes: dict[str, Any] | None = None,
        learnings: list[dict[str, Any]] | None = None,
    ) -> Simulation | None:
        """Partial update of the hypothesis/outcomes/learnings columns.

        Any field passed as ``None`` is left untouched (COALESCE-style).
        """
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET hypothesis = COALESCE($1, hypothesis),
                   outcomes   = COALESCE($2::jsonb, outcomes),
                   learnings  = COALESCE($3::jsonb, learnings)
               WHERE id = $4
               RETURNING *""",
            hypothesis,
            serialize_jsonb(outcomes) if outcomes is not None else None,
            serialize_jsonb(learnings) if learnings is not None else None,
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def append_learning(
        self,
        simulation_id: uuid.UUID,
        *,
        author: str,
        text: str,
    ) -> Simulation | None:
        """Append a single ``{author, text, created_at}`` entry to learnings."""
        from datetime import UTC, datetime

        entry = {
            "author": author,
            "text": text,
            "created_at": datetime.now(UTC).isoformat(),
        }
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET learnings = COALESCE(learnings, '[]'::jsonb) || $1::jsonb
               WHERE id = $2
               RETURNING *""",
            serialize_jsonb([entry]),
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def get(self, simulation_id: uuid.UUID) -> Simulation | None:
        row = await self.db.fetchrow("SELECT * FROM simulations WHERE id = $1", simulation_id)
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def get_by_name(self, name: str) -> Simulation | None:
        """Look up a simulation by name."""
        row = await self.db.fetchrow(
            "SELECT * FROM simulations WHERE name = $1 ORDER BY started_at DESC LIMIT 1",
            name,
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
        include_live: bool = False,
        is_featured: bool | None = None,
        completed_within_hours: int | None = None,
    ) -> list[Simulation]:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1
        if status is not None:
            clauses.append(f"s.status = ${idx}")
            params.append(status)
            idx += 1
        if not include_live:
            clauses.append("s.is_live IS NOT TRUE")
        if is_featured is not None:
            clauses.append(f"s.is_featured = ${idx}")
            params.append(is_featured)
            idx += 1
        if completed_within_hours is not None:
            clauses.append(
                f"s.completed_at IS NOT NULL "
                f"AND s.completed_at >= now() - make_interval(hours => ${idx})"
            )
            params.append(completed_within_hours)
            idx += 1
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        limit_idx = idx
        idx += 1
        params.append(offset)
        offset_idx = idx
        # LEFT JOIN users to expose the submitter's display name (email
        # local-part) without a second round-trip. None == anonymous.
        rows = await self.db.fetch(
            f"""SELECT s.*,
                       split_part(u.email, '@', 1) AS submitter_display_name
                  FROM simulations s
                  LEFT JOIN users u ON u.id = s.submitted_by_user_id
                  {where}
                 ORDER BY s.started_at DESC
                 LIMIT ${limit_idx} OFFSET ${offset_idx}""",  # noqa: S608
            *params,
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
        management_flags: int = 0,
    ) -> Simulation | None:
        row = await self.db.fetchrow(
            """UPDATE simulations SET
                 total_conversations = total_conversations + $1,
                 total_turns = total_turns + $2,
                 total_tokens = total_tokens + $3,
                 total_cost = total_cost + $4,
                 total_artifacts = total_artifacts + $5,
                 total_management_flags = total_management_flags + $6
               WHERE id = $7
               RETURNING *""",
            conversations,
            turns,
            tokens,
            cost,
            artifacts,
            management_flags,
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

    async def update_video_status(
        self,
        simulation_id: uuid.UUID,
        *,
        status: str,
        url: str | None = None,
        failure_reason: str | None = None,
    ) -> Simulation | None:
        """Set video_render_status and optional URL/failure detail.

        ``video_rendered_at`` is stamped only when status == 'done'. Terminal
        failures/skips keep a reason; successful or retry states clear stale
        failure detail.
        """
        if status not in {"pending", "rendering", "done", "failed", "skipped"}:
            raise ValueError(f"Invalid video_render_status: {status}")
        rendered_at_clause = (
            "video_rendered_at = CASE WHEN $1 = 'done' THEN now() ELSE video_rendered_at END"
        )
        failure_reason_clause = (
            "video_render_failure_reason = CASE "
            "WHEN $1 IN ('failed', 'skipped') THEN COALESCE($3, video_render_failure_reason) "
            "ELSE NULL END"
        )
        row = await self.db.fetchrow(
            f"""UPDATE simulations
               SET video_render_status = $1,
                   video_url = COALESCE($2, video_url),
                   {rendered_at_clause},
                   {failure_reason_clause}
               WHERE id = $4
               RETURNING *""",  # noqa: S608
            status,
            url,
            failure_reason,
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def claim_for_render(
        self,
        simulation_id: uuid.UUID,
    ) -> str | None:
        """Atomically claim a simulation for rendering.

        Returns 'claimed' if we transitioned NULL/failed/pending → rendering,
        'done' if a video already exists, or None if another worker already
        owns the render.
        """
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET video_render_status = 'rendering',
                   video_render_failure_reason = NULL
               WHERE id = $1
                 AND (
                     video_render_status IS NULL
                     OR video_render_status IN ('pending', 'failed')
                 )
               RETURNING video_render_status""",
            simulation_id,
        )
        if row is not None:
            return "claimed"
        # Find out why we couldn't claim — already rendering, done, or skipped.
        existing = await self.db.fetchval(
            "SELECT video_render_status FROM simulations WHERE id = $1",
            simulation_id,
        )
        return existing

    async def claim_for_youtube_publish(
        self,
        simulation_id: uuid.UUID,
    ) -> str | None:
        """Atomically claim a simulation for YouTube publishing.

        Returns 'claimed' if we transitioned NULL/failed/pending → publishing,
        or the existing youtube_publish_status (e.g. 'publishing', 'done') if
        another worker already owns it.
        """
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET youtube_publish_status = 'publishing'
               WHERE id = $1
                 AND (
                     youtube_publish_status IS NULL
                     OR youtube_publish_status IN ('pending', 'failed')
                 )
               RETURNING youtube_publish_status""",
            simulation_id,
        )
        if row is not None:
            return "claimed"
        existing = await self.db.fetchval(
            "SELECT youtube_publish_status FROM simulations WHERE id = $1",
            simulation_id,
        )
        return existing

    async def update_youtube_status(
        self,
        simulation_id: uuid.UUID,
        *,
        status: str | None,
        url: str | None = None,
        failure_reason: str | None = None,
        increment_attempts: bool = False,
    ) -> Simulation | None:
        """Set youtube_publish_status and optionally url/failure/attempts.

        ``youtube_published_at`` is stamped only when status == 'done'.
        Pass status=None to leave the status untouched (useful when only
        updating attempts after a retryable failure).
        """
        if status is not None and status not in {
            "pending",
            "publishing",
            "done",
            "failed",
        }:
            raise ValueError(f"Invalid youtube_publish_status: {status}")
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET youtube_publish_status = COALESCE($1, youtube_publish_status),
                   youtube_url = COALESCE($2, youtube_url),
                   youtube_failure_reason = CASE
                       WHEN $3::text IS NOT NULL THEN $3
                       WHEN $1 = 'done' THEN NULL
                       ELSE youtube_failure_reason
                   END,
                   youtube_published_at = CASE
                       WHEN $1 = 'done' THEN now()
                       ELSE youtube_published_at
                   END,
                   youtube_publish_attempts = youtube_publish_attempts
                       + CASE WHEN $4 THEN 1 ELSE 0 END
               WHERE id = $5
               RETURNING *""",
            status,
            url,
            failure_reason,
            increment_attempts,
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def update_config(
        self,
        simulation_id: uuid.UUID,
        config: dict[str, Any],
    ) -> Simulation | None:
        """Overwrite the config JSONB column (e.g. to persist clock state)."""
        row = await self.db.fetchrow(
            """UPDATE simulations
               SET config = $1::jsonb
               WHERE id = $2
               RETURNING *""",
            serialize_jsonb(config),
            simulation_id,
        )
        if row is None:
            return None
        return Simulation(**_parse_row(dict(row)))

    async def delete(self, simulation_id: uuid.UUID) -> bool:
        result = await self.db.execute("DELETE FROM simulations WHERE id = $1", simulation_id)
        return result == "DELETE 1"

    async def count(
        self,
        *,
        status: str | None = None,
        include_live: bool = False,
        is_featured: bool | None = None,
        completed_within_hours: int | None = None,
    ) -> int:
        """Return total count of simulations, optionally filtered by status."""
        clauses: list[str] = []
        params: list[object] = []
        idx = 1
        if status is not None:
            clauses.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if not include_live:
            clauses.append("is_live IS NOT TRUE")
        if is_featured is not None:
            clauses.append(f"is_featured = ${idx}")
            params.append(is_featured)
            idx += 1
        if completed_within_hours is not None:
            clauses.append(
                f"completed_at IS NOT NULL "
                f"AND completed_at >= now() - make_interval(hours => ${idx})"
            )
            params.append(completed_within_hours)
            idx += 1
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        val = await self.db.fetchval(
            f"SELECT COUNT(*) FROM simulations{where}",  # noqa: S608
            *params,
        )
        return val or 0

    async def get_total_cost_from_events(
        self,
        simulation_id: uuid.UUID,
    ) -> Decimal:
        """Derive total cost from cost_events table instead of manual accumulation."""
        val = await self.db.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cost_events WHERE simulation_id = $1",
            simulation_id,
        )
        return Decimal(str(val)) if val is not None else Decimal("0")

    async def get_timeline_events(
        self,
        simulation_id: uuid.UUID,
        *,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        """Return a chronological timeline of events for a simulation.

        Unions conversations (start/end), artifacts, and management flags.
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
                events.append(
                    {
                        "timestamp": d["started_at"].isoformat() if d["started_at"] else None,
                        "event_type": "conversation_started",
                        "agent_id": None,
                        "details": {
                            "conversation_id": str(d["id"]),
                            "participants": agents,
                            "trigger_type": d["trigger_type"],
                            "turn_count": d["turn_count"],
                        },
                    }
                )
                if d["ended_at"]:
                    events.append(
                        {
                            "timestamp": d["ended_at"].isoformat(),
                            "event_type": "conversation_ended",
                            "agent_id": None,
                            "details": {"conversation_id": str(d["id"])},
                        }
                    )

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
                events.append(
                    {
                        "timestamp": d["created_at"].isoformat() if d["created_at"] else None,
                        "event_type": "tool_use",
                        "agent_id": d["agent_id"],
                        "details": {
                            "artifact_id": str(d["id"]),
                            "tool_name": d["tool_name"],
                            "artifact_type": d["artifact_type"],
                        },
                    }
                )

        # Sort all events chronologically
        events.sort(key=lambda e: e["timestamp"] or "")
        return events

    async def get_management_log(
        self,
        simulation_id: uuid.UUID,
        *,
        severity_min: int = 1,
    ) -> list[dict]:
        """Return management shadow flags for a simulation filtered by severity."""
        rows = await self.db.fetch(
            """SELECT id, agent_id, original_content, filter_layer,
                      severity, action_would_take, reason,
                      flagged_keywords, created_at
               FROM management_shadow_log
               WHERE simulation_id = $1
                 AND severity >= $2
               ORDER BY created_at""",
            simulation_id,
            severity_min,
        )
        return [
            {
                "id": str(r["id"]),
                "agent_id": r["agent_id"],
                "original_content": r["original_content"],
                "filter_layer": r["filter_layer"],
                "severity": r["severity"],
                "action_would_take": r["action_would_take"],
                "reason": r["reason"],
                "flagged_keywords": list(r["flagged_keywords"] or []),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
