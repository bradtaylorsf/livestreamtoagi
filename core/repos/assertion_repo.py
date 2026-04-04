"""Repository for phase_assertions table."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import uuid

    from core.database import Database


class AssertionRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_results(
        self,
        simulation_id: uuid.UUID,
        phase_name: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Save a batch of assertion results."""
        for r in results:
            await self.db.execute(
                """INSERT INTO phase_assertions
                   (simulation_id, phase_name, assertion_name, passed,
                    expected, actual, severity, error_message)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)""",
                simulation_id,
                phase_name,
                r.get("name", "unknown"),
                r.get("passed", False),
                serialize_jsonb(r.get("expected")),
                serialize_jsonb(r.get("actual")),
                r.get("severity", "warning"),
                r.get("error_message"),
            )

    async def get_by_simulation(
        self, simulation_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetch(
            """SELECT * FROM phase_assertions
               WHERE simulation_id = $1
               ORDER BY created_at""",
            simulation_id,
        )
        return [self._parse_row(r) for r in rows]

    async def get_by_phase(
        self, simulation_id: uuid.UUID, phase_name: str
    ) -> list[dict[str, Any]]:
        rows = await self.db.fetch(
            """SELECT * FROM phase_assertions
               WHERE simulation_id = $1 AND phase_name = $2
               ORDER BY created_at""",
            simulation_id,
            phase_name,
        )
        return [self._parse_row(r) for r in rows]

    async def get_pass_rates(
        self, simulation_id: uuid.UUID
    ) -> dict[str, Any]:
        """Get assertion pass/fail/warn summary for a simulation."""
        row = await self.db.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE passed = true) as passed,
                 COUNT(*) FILTER (WHERE passed = false AND severity = 'error') as failed_error,
                 COUNT(*) FILTER (WHERE passed = false AND severity = 'warning') as failed_warning,
                 COUNT(*) FILTER (WHERE passed = false AND severity = 'info') as failed_info,
                 COUNT(*) as total
               FROM phase_assertions
               WHERE simulation_id = $1""",
            simulation_id,
        )
        if row is None:
            return {
                "passed": 0, "failed_error": 0, "failed_warning": 0,
                "failed_info": 0, "total": 0,
            }
        return dict(row)

    @staticmethod
    def _parse_row(row) -> dict[str, Any]:
        d = dict(row)
        for key in ("expected", "actual"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key])
        return d
