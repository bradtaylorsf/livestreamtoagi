"""Day-by-day breakdown section for timeline reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any


def _get_day_key(record: dict[str, Any], date_field: str = "started_at") -> str:
    """Extract a day key from a record's timestamp."""
    ts = record.get(date_field) or record.get("created_at")
    if ts and hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return "unknown"


def generate_daily_breakdown(
    conversations: list[dict[str, Any]],
    cost_events: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate per-day statistics and trends."""
    days: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "conversations": 0,
        "turns": 0,
        "cost": Decimal("0"),
        "tools_used": set(),
        "unique_tools": 0,
        "agents_active": set(),
        "most_active_agent": None,
    })

    # Conversations by day
    agent_turns_by_day: dict[str, Counter] = defaultdict(Counter)
    for conv in conversations:
        day = _get_day_key(conv)
        days[day]["conversations"] += 1
        days[day]["turns"] += conv.get("turn_count", 0)
        for agent in conv.get("participating_agents", []):
            days[day]["agents_active"].add(agent)
            agent_turns_by_day[day][agent] += conv.get("turn_count", 0)

    # Costs by day
    for cost in cost_events:
        day = _get_day_key(cost, "created_at")
        days[day]["cost"] += Decimal(str(cost.get("amount", 0)))

    # Artifacts by day
    for artifact in artifacts:
        day = _get_day_key(artifact, "created_at")
        tool = artifact.get("tool_name", "unknown")
        days[day]["tools_used"].add(tool)

    # Finalize
    result_days = []
    sorted_days = sorted(days.keys())
    for day in sorted_days:
        d = days[day]
        most_active = agent_turns_by_day[day].most_common(1)
        result_days.append({
            "date": day,
            "conversations": d["conversations"],
            "turns": d["turns"],
            "cost": str(d["cost"]),
            "unique_tools": len(d["tools_used"]),
            "tools_used": sorted(d["tools_used"]),
            "agents_active": sorted(d["agents_active"]),
            "most_active_agent": most_active[0][0] if most_active else None,
        })

    # Day-over-day trends
    trends = {}
    if len(result_days) >= 2:
        first = result_days[0]
        last = result_days[-1]
        first_cost = Decimal(first["cost"])
        last_cost = Decimal(last["cost"])
        if first_cost > 0:
            trends["cost_change_pct"] = str(
                round(((last_cost - first_cost) / first_cost) * 100, 1)
            )
        first_turns = first["turns"]
        last_turns = last["turns"]
        if first_turns > 0:
            trends["turns_change_pct"] = str(
                round(((last_turns - first_turns) / first_turns) * 100, 1)
            )

    return {
        "days": result_days,
        "total_days": len(result_days),
        "trends": trends,
    }
