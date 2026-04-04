"""Repository for eval run and eval result persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.models import EvalResult, EvalRun

if TYPE_CHECKING:
    import uuid
    from datetime import datetime
    from decimal import Decimal

    from core.database import Database


def _parse_jsonb(row: dict) -> dict:
    for key in ("evidence", "sub_scores"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


class EvalRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_eval_run(
        self,
        simulation_id: uuid.UUID,
        eval_suite: str,
    ) -> EvalRun:
        row = await self.db.fetchrow(
            """INSERT INTO eval_runs (simulation_id, eval_suite)
               VALUES ($1, $2)
               RETURNING *""",
            simulation_id,
            eval_suite,
        )
        return EvalRun(**dict(row))

    async def update_eval_run(
        self,
        run_id: uuid.UUID,
        *,
        status: str | None = None,
        overall_score: Decimal | None = None,
        cost: Decimal | None = None,
        completed_at: datetime | None = None,
    ) -> EvalRun | None:
        row = await self.db.fetchrow(
            """UPDATE eval_runs SET
                 status = COALESCE($1, status),
                 overall_score = COALESCE($2, overall_score),
                 cost = COALESCE($3, cost),
                 completed_at = COALESCE($4, completed_at)
               WHERE id = $5
               RETURNING *""",
            status,
            overall_score,
            cost,
            completed_at,
            run_id,
        )
        if row is None:
            return None
        return EvalRun(**dict(row))

    async def save_eval_result(
        self,
        eval_run_id: uuid.UUID,
        category: str,
        score: Decimal,
        reasoning: str,
        evidence: dict[str, Any] | None,
        sub_scores: dict[str, Any] | None,
        tokens_used: int,
        cost: Decimal,
    ) -> EvalResult:
        row = await self.db.fetchrow(
            """INSERT INTO eval_results
               (eval_run_id, category, score, reasoning, evidence, sub_scores,
                tokens_used, cost)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)
               RETURNING *""",
            eval_run_id,
            category,
            score,
            reasoning,
            json.dumps(evidence) if evidence else None,
            json.dumps(sub_scores) if sub_scores else None,
            tokens_used,
            cost,
        )
        d = dict(row)
        _parse_jsonb(d)
        return EvalResult(**d)

    async def get_eval_runs(
        self,
        simulation_id: uuid.UUID,
    ) -> list[EvalRun]:
        rows = await self.db.fetch(
            """SELECT * FROM eval_runs
               WHERE simulation_id = $1
               ORDER BY started_at DESC""",
            simulation_id,
        )
        return [EvalRun(**dict(r)) for r in rows]

    async def get_eval_run(self, run_id: uuid.UUID) -> EvalRun | None:
        row = await self.db.fetchrow(
            "SELECT * FROM eval_runs WHERE id = $1", run_id
        )
        if row is None:
            return None
        return EvalRun(**dict(row))

    async def get_eval_results(self, eval_run_id: uuid.UUID) -> list[EvalResult]:
        rows = await self.db.fetch(
            """SELECT * FROM eval_results
               WHERE eval_run_id = $1
               ORDER BY category""",
            eval_run_id,
        )
        return [EvalResult(**_parse_jsonb(dict(r))) for r in rows]

    async def get_latest_eval_run(
        self, simulation_id: uuid.UUID
    ) -> EvalRun | None:
        row = await self.db.fetchrow(
            """SELECT * FROM eval_runs
               WHERE simulation_id = $1
               ORDER BY started_at DESC
               LIMIT 1""",
            simulation_id,
        )
        if row is None:
            return None
        return EvalRun(**dict(row))

    async def get_all_eval_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvalRun]:
        rows = await self.db.fetch(
            """SELECT * FROM eval_runs
               ORDER BY started_at DESC
               LIMIT $1 OFFSET $2""",
            limit,
            offset,
        )
        return [EvalRun(**dict(r)) for r in rows]

    async def get_eval_history(
        self, category: str
    ) -> list[dict[str, Any]]:
        """Score history for a category across all eval runs, for charting."""
        rows = await self.db.fetch(
            """SELECT er.score, er.created_at, e.simulation_id, e.id AS eval_run_id
               FROM eval_results er
               JOIN eval_runs e ON e.id = er.eval_run_id
               WHERE er.category = $1
               ORDER BY er.created_at""",
            category,
        )
        return [
            {
                "score": float(r["score"]) if r["score"] is not None else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "simulation_id": str(r["simulation_id"]),
                "eval_run_id": str(r["eval_run_id"]),
            }
            for r in rows
        ]
