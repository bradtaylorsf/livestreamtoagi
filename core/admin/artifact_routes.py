"""Global artifact browsing endpoints."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from core.admin.dependencies import get_db
from core.models import Artifact, PaginatedResponse

if TYPE_CHECKING:
    from core.database import Database

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts")
async def list_artifacts(
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
    agent_id: str | None = Query(None),
    artifact_type: str | None = Query(None, alias="type"),
    status: str | None = Query(None),
    since: datetime | None = Query(default=None),  # noqa: B008
    until: datetime | None = Query(default=None),  # noqa: B008
    search: str | None = Query(None),
    sort: str = Query("newest"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> PaginatedResponse[Artifact]:
    """Browse all artifacts with filtering, search, and pagination."""
    from core.repos.artifact_repo import ArtifactRepo

    artifact_repo = ArtifactRepo(db)

    # Parse comma-separated lists for multi-select filters
    agent_ids = [a.strip() for a in agent_id.split(",") if a.strip()] if agent_id else None
    types = [t.strip() for t in artifact_type.split(",") if t.strip()] if artifact_type else None
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else None

    artifacts, total = await artifact_repo.get_all_artifacts(
        simulation_id=simulation_id,
        agent_ids=agent_ids,
        artifact_type=types,
        status=statuses,
        since=since,
        until=until,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=artifacts, total=total, limit=limit, offset=offset)
