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
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "conversations": 0,
            "turns": 0,
            "cost": Decimal("0"),
            "tools_used": set(),
            "unique_tools": 0,
            "agents_active": set(),
            "most_active_agent": None,
        }
    )

    # Conversations by day
    agent_turns_by_day: dict[str, Counter] = defaultdict(Counter)
    for conv in conversations:
        day = _get_day_key(conv)
        days[day]["conversations"] += 1
        days[day]["turns"] += conv.get("turn_count", 0)
        agents = conv.get("participating_agents", [])
        if isinstance(agents, str):
            import json

            try:
                agents = json.loads(agents)
            except (json.JSONDecodeError, TypeError):
                agents = []
        for agent in agents:
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
        result_days.append(
            {
                "date": day,
                "conversations": d["conversations"],
                "turns": d["turns"],
                "cost": str(d["cost"]),
                "unique_tools": len(d["tools_used"]),
                "tools_used": sorted(d["tools_used"]),
                "agents_active": sorted(d["agents_active"]),
                "most_active_agent": most_active[0][0] if most_active else None,
            }
        )

    # Day-over-day trends
    trends = {}
    if len(result_days) >= 2:
        first = result_days[0]
        last = result_days[-1]
        first_cost = Decimal(first["cost"])
        last_cost = Decimal(last["cost"])
        if first_cost > 0:
            trends["cost_change_pct"] = str(round(((last_cost - first_cost) / first_cost) * 100, 1))
        first_turns = first["turns"]
        last_turns = last["turns"]
        if first_turns > 0:
            trends["turns_change_pct"] = str(
                round(((last_turns - first_turns) / first_turns) * 100, 1)
            )

    # Day-over-day metric series for #195
    dod_metrics = _compute_day_over_day_metrics(result_days, agent_turns_by_day)

    return {
        "days": result_days,
        "total_days": len(result_days),
        "trends": trends,
        "day_over_day": dod_metrics,
    }


def _compute_day_over_day_metrics(
    result_days: list[dict[str, Any]],
    agent_turns_by_day: dict[str, Counter],
) -> dict[str, Any]:
    """Compute day-over-day metric series for comparison reporting."""
    if len(result_days) < 2:
        return {}

    # Conversation depth trend
    turns_series = [d["turns"] / max(d["conversations"], 1) for d in result_days]
    first_avg = turns_series[0]
    last_avg = turns_series[-1]
    depth_trend = (
        "up" if last_avg > first_avg * 1.1 else ("down" if last_avg < first_avg * 0.9 else "flat")
    )

    # Tool diversity trend (cumulative new tools)
    cumulative_tools: list[int] = []
    seen: set[str] = set()
    for d in result_days:
        for tool in d.get("tools_used", []):
            seen.add(tool)
        cumulative_tools.append(len(seen))

    # Cost trajectory
    cost_series = [Decimal(d["cost"]) for d in result_days]
    first_cost = cost_series[0]
    last_cost = cost_series[-1]
    cost_trend = (
        "up"
        if last_cost > first_cost * Decimal("1.1")
        else ("down" if last_cost < first_cost * Decimal("0.9") else "flat")
    )

    # Agent participation balance (stddev of turns per agent)
    balance_series = []
    for d in result_days:
        day = d["date"]
        agent_counts = agent_turns_by_day.get(day, Counter())
        if agent_counts:
            values = list(agent_counts.values())
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            balance_series.append(round(variance**0.5, 1))
        else:
            balance_series.append(0)

    return {
        "avg_turns_per_conversation": turns_series,
        "depth_trend": depth_trend,
        "cumulative_tools": cumulative_tools,
        "cost_series": [str(c) for c in cost_series],
        "cost_trend": cost_trend,
        "participation_stddev": balance_series,
    }
