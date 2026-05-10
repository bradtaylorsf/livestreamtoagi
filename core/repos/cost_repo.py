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
            """INSERT INTO cost_events (agent_id, cost_type, amount, details, simulation_id)
               VALUES ($1, $2, $3, $4::jsonb, $5)
               RETURNING *""",
            cost.agent_id,
            cost.cost_type,
            cost.amount,
            serialize_jsonb(cost.details),
            cost.simulation_id,
        )
        d = dict(row)
        _parse_jsonb_field(d, "details")
        return CostEvent(**d)

    async def get_total_costs(
        self,
        since: datetime | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> Decimal:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"created_at >= ${idx}")
            params.append(since)
            idx += 1
        if simulation_id is not None:
            clauses.append(f"simulation_id = ${idx}")
            params.append(simulation_id)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        val = await self.db.fetchval(
            f"SELECT COALESCE(SUM(amount), 0) FROM cost_events {where}",  # noqa: S608
            *params,
        )
        return Decimal(str(val))

    async def get_costs_by_agent(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> list[CostEvent]:
        clauses = ["agent_id = $1"]
        params: list[object] = [agent_id]
        if simulation_id is not None:
            clauses.append("simulation_id = $2")
            params.append(simulation_id)
        where = " AND ".join(clauses)
        rows = await self.db.fetch(
            f"SELECT * FROM cost_events WHERE {where} ORDER BY created_at DESC",  # noqa: S608
            *params,
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
        simulation_id: uuid.UUID | None = None,
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
        if simulation_id is not None:
            clauses.append(f"simulation_id = ${idx}")
            params.append(simulation_id)
            idx += 1

        where = " AND ".join(clauses)

        by_day_rows = await self.db.fetch(
            f"""SELECT DATE(created_at) as day, SUM(amount) as total
                FROM cost_events WHERE {where}
                GROUP BY DATE(created_at) ORDER BY day""",  # noqa: S608
            *params,
        )
        by_type_rows = await self.db.fetch(
            f"""SELECT cost_type, SUM(amount) as total,
                       SUM(COALESCE((details->>'input_tokens')::int, 0)
                         + COALESCE((details->>'output_tokens')::int, 0)) as tokens
                FROM cost_events WHERE {where}
                GROUP BY cost_type ORDER BY total DESC""",  # noqa: S608
            *params,
        )
        totals_row = await self.db.fetchrow(
            f"""SELECT COALESCE(SUM(amount), 0) as total,
                       SUM(COALESCE((details->>'input_tokens')::int, 0)) as input_tokens,
                       SUM(COALESCE((details->>'output_tokens')::int, 0)) as output_tokens
                FROM cost_events WHERE {where}""",  # noqa: S608
            *params,
        )

        return {
            "by_day": [{"day": str(r["day"]), "total": str(r["total"])} for r in by_day_rows],
            "by_type": [
                {"type": r["cost_type"], "total": str(r["total"]), "tokens": int(r["tokens"] or 0)}
                for r in by_type_rows
            ],
            "total": str(totals_row["total"]),
            "total_input_tokens": int(totals_row["input_tokens"] or 0),
            "total_output_tokens": int(totals_row["output_tokens"] or 0),
        }

    async def get_costs_by_simulation(
        self,
        simulation_id: uuid.UUID,
    ) -> dict[str, object]:
        """Return cost breakdown by agent and cost type for a simulation using direct FK."""
        by_agent_rows = await self.db.fetch(
            """SELECT COALESCE(agent_id, 'system') as agent_id,
                      SUM(amount) as total,
                      SUM(COALESCE((details->>'input_tokens')::int, 0)) as input_tokens,
                      SUM(COALESCE((details->>'output_tokens')::int, 0)) as output_tokens
               FROM cost_events
               WHERE simulation_id = $1
               GROUP BY COALESCE(agent_id, 'system') ORDER BY total DESC""",
            simulation_id,
        )
        by_type_rows = await self.db.fetch(
            """SELECT cost_type,
                      SUM(amount) as total,
                      SUM(COALESCE((details->>'input_tokens')::int, 0)
                        + COALESCE((details->>'output_tokens')::int, 0)) as tokens
               FROM cost_events
               WHERE simulation_id = $1
               GROUP BY cost_type ORDER BY total DESC""",
            simulation_id,
        )

        total = (
            sum(r["total"] or Decimal("0") for r in by_agent_rows)
            if by_agent_rows
            else Decimal("0")
        )
        total_input = sum(r["input_tokens"] or 0 for r in by_agent_rows) if by_agent_rows else 0
        total_output = sum(r["output_tokens"] or 0 for r in by_agent_rows) if by_agent_rows else 0

        return {
            "by_agent": [
                {"agent_id": r["agent_id"], "total": str(r["total"])} for r in by_agent_rows
            ],
            "by_type": [
                {"type": r["cost_type"], "cost": str(r["total"]), "tokens": int(r["tokens"] or 0)}
                for r in by_type_rows
            ],
            "total": str(total),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
        }

    # ── Revenue Events ──────────────────────────────────────

    async def add_revenue(self, revenue: RevenueEventCreate) -> RevenueEvent:
        row = await self.db.fetchrow(
            """INSERT INTO revenue_events (source, amount, details, simulation_id)
               VALUES ($1, $2, $3::jsonb, $4)
               RETURNING *""",
            revenue.source,
            revenue.amount,
            serialize_jsonb(revenue.details),
            revenue.simulation_id,
        )
        d = dict(row)
        _parse_jsonb_field(d, "details")
        return RevenueEvent(**d)

    async def get_total_revenue(
        self,
        since: datetime | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> Decimal:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"created_at >= ${idx}")
            params.append(since)
            idx += 1
        if simulation_id is not None:
            clauses.append(f"simulation_id = ${idx}")
            params.append(simulation_id)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        val = await self.db.fetchval(
            f"SELECT COALESCE(SUM(amount), 0) FROM revenue_events {where}",  # noqa: S608
            *params,
        )
        return Decimal(str(val))

    # ── Challenges ──────────────────────────────────────────

    async def create_challenge(self, challenge: ChallengeCreate) -> Challenge:
        row = await self.db.fetchrow(
            """INSERT INTO challenges
               (description, submitted_by, source, assigned_agents, cost_estimate, simulation_id)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            challenge.description,
            challenge.submitted_by,
            challenge.source,
            challenge.assigned_agents,
            challenge.cost_estimate,
            challenge.simulation_id,
        )
        return Challenge(**dict(row))

    async def update_challenge_status(
        self,
        challenge_id: int,
        status: str,
        result: str | None = None,
        actual_cost: float | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> Challenge | None:
        row = await self.db.fetchrow(
            """UPDATE challenges
               SET status = $1, result = $2, actual_cost = $3,
                   completed_at = CASE WHEN $1 = 'completed' THEN NOW() ELSE completed_at END
               WHERE id = $4 AND simulation_id = $5
               RETURNING *""",
            status,
            result,
            actual_cost,
            challenge_id,
            simulation_id,
        )
        return Challenge(**dict(row)) if row else None
