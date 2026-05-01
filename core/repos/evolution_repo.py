"""Repository for evolution loop cycle tracking."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.models import EvolutionCycle

if TYPE_CHECKING:
    import uuid

    from core.database import Database

logger = logging.getLogger(__name__)


class EvolutionRepo:
    """CRUD operations for evolution loop cycles."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def insert_cycle(
        self,
        *,
        loop_run_id: uuid.UUID,
        cycle_number: int,
        simulation_id: uuid.UUID | None = None,
        eval_run_id: uuid.UUID | None = None,
        overall_score: Decimal | None = None,
        score_delta: Decimal | None = None,
        changes_applied: int = 0,
        issues_filed: int = 0,
        config_version_before: int | None = None,
        config_version_after: int | None = None,
        status: str = "completed",
        cost: Decimal = Decimal("0"),
    ) -> EvolutionCycle:
        """Insert a completed cycle record."""
        row = await self.db.fetchrow(
            """INSERT INTO evolution_cycles
               (loop_run_id, cycle_number, simulation_id, eval_run_id,
                overall_score, score_delta, changes_applied, issues_filed,
                config_version_before, config_version_after, status, cost)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               RETURNING *""",
            loop_run_id,
            cycle_number,
            simulation_id,
            eval_run_id,
            overall_score,
            score_delta,
            changes_applied,
            issues_filed,
            config_version_before,
            config_version_after,
            status,
            cost,
        )
        return EvolutionCycle(**dict(row))

    async def get_loop_history(self, loop_run_id: uuid.UUID) -> list[EvolutionCycle]:
        """Get all cycles for a loop run."""
        rows = await self.db.fetch(
            """SELECT * FROM evolution_cycles
               WHERE loop_run_id = $1
               ORDER BY cycle_number ASC""",
            loop_run_id,
        )
        return [EvolutionCycle(**dict(r)) for r in rows]

    async def get_all_loops(self, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """Get summary of all loop runs."""
        rows = await self.db.fetch(
            """SELECT loop_run_id,
                      COUNT(*) AS cycle_count,
                      MIN(created_at) AS started_at,
                      MAX(created_at) AS ended_at,
                      SUM(cost) AS total_cost,
                      MAX(overall_score) AS best_score,
                      (array_agg(status ORDER BY cycle_number DESC))[1] AS final_status
               FROM evolution_cycles
               GROUP BY loop_run_id
               ORDER BY MIN(created_at) DESC
               LIMIT $1 OFFSET $2""",
            limit,
            offset,
        )
        return [dict(r) for r in rows]

    async def get_cycle(self, cycle_id: uuid.UUID) -> EvolutionCycle | None:
        """Get a specific cycle by ID."""
        row = await self.db.fetchrow("SELECT * FROM evolution_cycles WHERE id = $1", cycle_id)
        if row is None:
            return None
        return EvolutionCycle(**dict(row))

    async def compare_cycles(self, id_a: uuid.UUID, id_b: uuid.UUID) -> dict[str, Any]:
        """Compare two cycles side by side."""
        cycle_a = await self.get_cycle(id_a)
        cycle_b = await self.get_cycle(id_b)
        if cycle_a is None or cycle_b is None:
            raise ValueError("One or both cycles not found")
        return {
            "cycle_a": cycle_a.model_dump(mode="json"),
            "cycle_b": cycle_b.model_dump(mode="json"),
            "score_improvement": (
                float(cycle_b.overall_score or 0) - float(cycle_a.overall_score or 0)
            ),
        }
