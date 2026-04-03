"""Repository for cost_events, revenue_events, challenges."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

from core.models import (
    Challenge,
    ChallengeCreate,
    CostEvent,
    CostEventCreate,
    RevenueEvent,
    RevenueEventCreate,
)
from core.repos.utils import serialize_jsonb

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from core.database import Database


def _parse_jsonb_field(d: dict, key: str) -> None:
    if isinstance(d.get(key), str):
        d[key] = json.loads(d[key])


class CostRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Cost Events ─────────────────────────────────────────

    async def add_cost(self, cost: CostEventCreate) -> CostEvent:
        row = await self.db.fetchrow(
            """INSERT INTO cost_events (agent_id, cost_type, amount, details)
               VALUES ($1, $2, $3, $4::jsonb)
               RETURNING *""",
            cost.agent_id,
            cost.cost_type,
            cost.amount,
            serialize_jsonb(cost.details),
        )
        d = dict(row)
        _parse_jsonb_field(d, "details")
        return CostEvent(**d)

    async def get_total_costs(self, since: datetime | None = None) -> Decimal:
        if since:
            val = await self.db.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM cost_events WHERE created_at >= $1",
                since,
            )
        else:
            val = await self.db.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM cost_events"
            )
        return Decimal(str(val))

    async def get_costs_by_agent(self, agent_id: str) -> list[CostEvent]:
        rows = await self.db.fetch(
            "SELECT * FROM cost_events WHERE agent_id = $1 ORDER BY created_at DESC",
            agent_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            _parse_jsonb_field(d, "details")
            result.append(CostEvent(**d))
        return result

    async def get_costs_by_agent_grouped(
        self,
        agent_id: str,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> dict[str, object]:
        """Return cost breakdown by day and by type for an agent."""
        clauses = ["agent_id = $1"]
        params: list[object] = [agent_id]
        idx = 2

        if from_date is not None:
            clauses.append(f"created_at >= ${idx}")
            params.append(from_date)
            idx += 1
        if to_date is not None:
            clauses.append(f"created_at <= ${idx}")
            params.append(to_date)
            idx += 1

        where = " AND ".join(clauses)

        by_day_rows = await self.db.fetch(
            f"""SELECT DATE(created_at) as day, SUM(amount) as total
                FROM cost_events WHERE {where}
                GROUP BY DATE(created_at) ORDER BY day""",  # noqa: S608
            *params,
        )
        by_type_rows = await self.db.fetch(
            f"""SELECT cost_type, SUM(amount) as total
                FROM cost_events WHERE {where}
                GROUP BY cost_type ORDER BY total DESC""",  # noqa: S608
            *params,
        )
        total = await self.db.fetchval(
            f"SELECT COALESCE(SUM(amount), 0) FROM cost_events WHERE {where}",  # noqa: S608
            *params,
        )

        return {
            "by_day": [{"day": str(r["day"]), "total": str(r["total"])} for r in by_day_rows],
            "by_type": [{"type": r["cost_type"], "total": str(r["total"])} for r in by_type_rows],
            "total": str(total),
        }

    async def get_costs_by_simulation(
        self,
        simulation_id: uuid.UUID,
    ) -> dict[str, object]:
        """Return cost breakdown by agent for a simulation's time window."""
        by_agent_rows = await self.db.fetch(
            """SELECT ce.agent_id, SUM(ce.amount) as total
               FROM cost_events ce
               JOIN simulations s ON ce.created_at
                   BETWEEN s.started_at AND COALESCE(s.completed_at, NOW())
               WHERE s.id = $1
               GROUP BY ce.agent_id ORDER BY total DESC""",
            simulation_id,
        )
        total = sum(r["total"] for r in by_agent_rows) if by_agent_rows else Decimal("0")

        return {
            "by_agent": [
                {"agent_id": r["agent_id"], "total": str(r["total"])}
                for r in by_agent_rows
            ],
            "total": str(total),
        }

    # ── Revenue Events ──────────────────────────────────────

    async def add_revenue(self, revenue: RevenueEventCreate) -> RevenueEvent:
        row = await self.db.fetchrow(
            """INSERT INTO revenue_events (source, amount, details)
               VALUES ($1, $2, $3::jsonb)
               RETURNING *""",
            revenue.source,
            revenue.amount,
            serialize_jsonb(revenue.details),
        )
        d = dict(row)
        _parse_jsonb_field(d, "details")
        return RevenueEvent(**d)

    async def get_total_revenue(self, since: datetime | None = None) -> Decimal:
        if since:
            val = await self.db.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM revenue_events WHERE created_at >= $1",
                since,
            )
        else:
            val = await self.db.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM revenue_events"
            )
        return Decimal(str(val))

    # ── Challenges ──────────────────────────────────────────

    async def create_challenge(self, challenge: ChallengeCreate) -> Challenge:
        row = await self.db.fetchrow(
            """INSERT INTO challenges
               (description, submitted_by, source, assigned_agents, cost_estimate)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING *""",
            challenge.description,
            challenge.submitted_by,
            challenge.source,
            challenge.assigned_agents,
            challenge.cost_estimate,
        )
        return Challenge(**dict(row))

    async def update_challenge_status(
        self,
        challenge_id: int,
        status: str,
        result: str | None = None,
        actual_cost: float | None = None,
    ) -> Challenge | None:
        row = await self.db.fetchrow(
            """UPDATE challenges
               SET status = $1, result = $2, actual_cost = $3,
                   completed_at = CASE WHEN $1 = 'completed' THEN NOW() ELSE completed_at END
               WHERE id = $4
               RETURNING *""",
            status,
            result,
            actual_cost,
            challenge_id,
        )
        return Challenge(**dict(row)) if row else None
