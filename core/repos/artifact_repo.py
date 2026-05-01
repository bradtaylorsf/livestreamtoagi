"""Repository for artifact persistence — stores every tool invocation and output."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.models import Artifact, ArtifactCreate
from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from core.database import Database


def _parse_jsonb_fields(d: dict) -> None:
    for key in ("tool_input", "tool_output", "metadata"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])


class ArtifactRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_artifact(self, artifact: ArtifactCreate) -> Artifact:
        row = await self.db.fetchrow(
            """INSERT INTO artifacts
               (simulation_id, conversation_id, agent_id, tool_name,
                tool_input, tool_output, artifact_type, status, metadata)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9::jsonb)
               RETURNING *""",
            artifact.simulation_id,
            artifact.conversation_id,
            artifact.agent_id,
            artifact.tool_name,
            serialize_jsonb(artifact.tool_input),
            serialize_jsonb(artifact.tool_output),
            artifact.artifact_type,
            artifact.status,
            serialize_jsonb(artifact.metadata),
        )
        d = dict(row)
        _parse_jsonb_fields(d)
        return Artifact(**d)

    async def get_artifacts_by_simulation(
        self,
        simulation_id: uuid.UUID,
        *,
        agent_id: str | None = None,
        artifact_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Artifact]:
        clauses = ["simulation_id = $1"]
        params: list[object] = [simulation_id]
        idx = 2

        if agent_id is not None:
            clauses.append(f"agent_id = ${idx}")
            params.append(agent_id)
            idx += 1
        if artifact_type is not None:
            clauses.append(f"artifact_type = ${idx}")
            params.append(artifact_type)
            idx += 1
        if since is not None:
            clauses.append(f"created_at >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"created_at <= ${idx}")
            params.append(until)
            idx += 1

        where = " AND ".join(clauses)
        rows = await self.db.fetch(
            f"SELECT * FROM artifacts WHERE {where} ORDER BY created_at DESC",  # noqa: S608
            *params,
        )
        result = []
        for r in rows:
            d = dict(r)
            _parse_jsonb_fields(d)
            result.append(Artifact(**d))
        return result

    async def get_artifacts_by_agent(
        self,
        agent_id: str,
        *,
        artifact_type: str | None = None,
        simulation_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Artifact], int]:
        """Return paginated artifacts for an agent with total count."""
        clauses = ["agent_id = $1"]
        params: list[object] = [agent_id]
        idx = 2

        if artifact_type is not None:
            clauses.append(f"artifact_type = ${idx}")
            params.append(artifact_type)
            idx += 1
        if simulation_id is not None:
            clauses.append(f"simulation_id = ${idx}")
            params.append(simulation_id)
            idx += 1

        where = " AND ".join(clauses)
        count = await self.db.fetchval(
            f"SELECT COUNT(*) FROM artifacts WHERE {where}",  # noqa: S608
            *params,
        )
        rows = await self.db.fetch(
            f"SELECT * FROM artifacts WHERE {where}"  # noqa: S608
            f" ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
            limit,
            offset,
        )
        result = []
        for r in rows:
            d = dict(r)
            _parse_jsonb_fields(d)
            result.append(Artifact(**d))
        return result, count or 0

    async def get_all_artifacts(
        self,
        *,
        simulation_id: uuid.UUID | None = None,
        agent_ids: list[str] | None = None,
        artifact_type: list[str] | None = None,
        status: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        search: str | None = None,
        sort: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Artifact], int]:
        """Global artifact query with filtering, search, sorting, and pagination."""
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if simulation_id is not None:
            clauses.append(f"simulation_id = ${idx}")
            params.append(simulation_id)
            idx += 1
        if agent_ids:
            clauses.append(f"agent_id = ANY(${idx}::text[])")
            params.append(agent_ids)
            idx += 1
        if artifact_type:
            clauses.append(f"artifact_type = ANY(${idx}::text[])")
            params.append(artifact_type)
            idx += 1
        if status:
            clauses.append(f"status = ANY(${idx}::text[])")
            params.append(status)
            idx += 1
        if since is not None:
            clauses.append(f"created_at >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"created_at <= ${idx}")
            params.append(until)
            idx += 1
        if search:
            clauses.append(f"(tool_input::text ILIKE ${idx} OR tool_output::text ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        order = {
            "newest": "created_at DESC",
            "oldest": "created_at ASC",
            "agent": "agent_id ASC, created_at DESC",
            "type": "artifact_type ASC, created_at DESC",
        }.get(sort, "created_at DESC")

        count = await self.db.fetchval(
            f"SELECT COUNT(*) FROM artifacts{where}",  # noqa: S608
            *params,
        )
        rows = await self.db.fetch(
            f"SELECT * FROM artifacts{where}"  # noqa: S608
            f" ORDER BY {order} LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
            limit,
            offset,
        )
        result = []
        for r in rows:
            d = dict(r)
            _parse_jsonb_fields(d)
            result.append(Artifact(**d))
        return result, count or 0

    async def get_artifacts_by_type(
        self,
        artifact_type: str,
        *,
        simulation_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Artifact]:
        if simulation_id is not None:
            rows = await self.db.fetch(
                """SELECT * FROM artifacts
                   WHERE artifact_type = $1 AND simulation_id = $2
                   ORDER BY created_at DESC LIMIT $3""",
                artifact_type,
                simulation_id,
                limit,
            )
        else:
            rows = await self.db.fetch(
                """SELECT * FROM artifacts
                   WHERE artifact_type = $1
                   ORDER BY created_at DESC LIMIT $2""",
                artifact_type,
                limit,
            )
        result = []
        for r in rows:
            d = dict(r)
            _parse_jsonb_fields(d)
            result.append(Artifact(**d))
        return result
