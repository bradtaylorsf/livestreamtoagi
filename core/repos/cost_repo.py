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
