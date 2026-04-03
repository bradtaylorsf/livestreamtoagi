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
        limit: int = 50,
    ) -> list[Artifact]:
        if artifact_type is not None:
            rows = await self.db.fetch(
                """SELECT * FROM artifacts
                   WHERE agent_id = $1 AND artifact_type = $2
                   ORDER BY created_at DESC LIMIT $3""",
                agent_id,
                artifact_type,
                limit,
            )
        else:
            rows = await self.db.fetch(
                """SELECT * FROM artifacts
                   WHERE agent_id = $1
                   ORDER BY created_at DESC LIMIT $2""",
                agent_id,
                limit,
            )
        result = []
        for r in rows:
            d = dict(r)
            _parse_jsonb_fields(d)
            result.append(Artifact(**d))
        return result

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
