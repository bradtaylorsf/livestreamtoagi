"""Cost analysis section for timeline reports."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any


def generate_cost_analysis(
    cost_events: list[dict[str, Any]],
    sim: dict[str, Any],
) -> dict[str, Any]:
    """Generate cost analysis with projections."""
    if not cost_events:
        return {
            "total_cost": "0",
            "by_day": {},
            "by_agent": {},
            "by_type": {},
            "projection": None,
        }

    total = Decimal("0")
    by_day: dict[str, Decimal] = defaultdict(Decimal)
    by_agent: dict[str, Decimal] = defaultdict(Decimal)
    by_type: dict[str, Decimal] = defaultdict(Decimal)
    tokens_by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0})

    for event in cost_events:
        amount = Decimal(str(event.get("amount", 0)))
        total += amount
        agent = event.get("agent_id", "unknown")
        cost_type = event.get("cost_type", "unknown")

        by_agent[agent] += amount
        by_type[cost_type] += amount

        created = event.get("created_at")
        if created and hasattr(created, "strftime"):
            day = created.strftime("%Y-%m-%d")
            by_day[day] += amount
            details = event.get("details") or {}
            if isinstance(details, dict):
                tokens_by_day[day]["input"] += details.get("input_tokens", 0)
                tokens_by_day[day]["output"] += details.get("output_tokens", 0)

    # Cost projection via simple linear extrapolation
    projection = None
    sorted_days = sorted(by_day.keys())
    if len(sorted_days) >= 2:
        daily_costs = [float(by_day[d]) for d in sorted_days]
        avg_daily = sum(daily_costs) / len(daily_costs)
        last_day_cost = daily_costs[-1]

        # Check growth trend
        first_half_avg = sum(daily_costs[: len(daily_costs) // 2]) / max(len(daily_costs) // 2, 1)
        second_half_avg = sum(daily_costs[len(daily_costs) // 2 :]) / max(
            len(daily_costs) - len(daily_costs) // 2, 1
        )

        if first_half_avg > 0:
            growth_rate = (second_half_avg - first_half_avg) / first_half_avg
        else:
            growth_rate = 0

        projection = {
            "avg_daily_cost": str(round(Decimal(str(avg_daily)), 4)),
            "weekly_estimate": str(round(Decimal(str(avg_daily * 7)), 4)),
            "monthly_estimate": str(round(Decimal(str(avg_daily * 30)), 4)),
            "growth_rate_pct": round(growth_rate * 100, 1),
            "is_sustainable": growth_rate < 0.1,  # <10% growth rate
            "last_day_cost": str(round(Decimal(str(last_day_cost)), 4)),
        }

    return {
        "total_cost": str(total),
        "by_day": {day: str(cost) for day, cost in sorted(by_day.items())},
        "by_agent": {agent: str(cost) for agent, cost in sorted(by_agent.items(), key=lambda x: x[1], reverse=True)},
        "by_type": {t: str(cost) for t, cost in sorted(by_type.items(), key=lambda x: x[1], reverse=True)},
        "token_trends": {
            day: tokens for day, tokens in sorted(tokens_by_day.items())
        },
        "projection": projection,
    }
