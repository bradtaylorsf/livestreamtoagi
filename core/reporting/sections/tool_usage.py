"""Tool usage section for timeline reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def generate_tool_usage(
    artifacts: list[dict[str, Any]],
    cost_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate tool usage analysis."""
    if not artifacts:
        return {
            "total_invocations": 0,
            "tools_used": [],
            "tools_never_used": [],
            "by_tool": {},
            "by_day": {},
            "success_rate": None,
        }

    tool_counts = Counter()
    tool_statuses: dict[str, Counter] = defaultdict(Counter)
    tool_by_day: dict[str, Counter] = defaultdict(Counter)
    agent_tool_counts: dict[str, Counter] = defaultdict(Counter)

    for artifact in artifacts:
        tool = artifact.get("tool_name", "unknown")
        status = artifact.get("status", "unknown")
        agent_id = artifact.get("agent_id", "unknown")
        tool_counts[tool] += 1
        tool_statuses[tool][status] += 1
        agent_tool_counts[agent_id][tool] += 1

        created = artifact.get("created_at")
        if created and hasattr(created, "strftime"):
            day = created.strftime("%Y-%m-%d")
            tool_by_day[day][tool] += 1

    # Success rates
    by_tool = {}
    for tool, count in tool_counts.most_common():
        statuses = tool_statuses[tool]
        total = sum(statuses.values())
        executed = statuses.get("executed", 0) + statuses.get("completed", 0)
        by_tool[tool] = {
            "count": count,
            "success_rate": round(executed / total * 100, 1) if total > 0 else 0,
            "statuses": dict(statuses),
        }

    # All known tools vs used tools
    from core.models import ARTIFACT_TYPE_MAP

    all_tools = set(ARTIFACT_TYPE_MAP.keys())
    used_tools = set(tool_counts.keys())
    never_used = sorted(all_tools - used_tools)

    # Build by_agent summary: agent -> {tool -> count}
    by_agent = {
        agent: dict(counts.most_common()) for agent, counts in sorted(agent_tool_counts.items())
    }

    return {
        "total_invocations": len(artifacts),
        "tools_used": sorted(used_tools),
        "tools_never_used": never_used,
        "by_tool": by_tool,
        "by_agent": by_agent,
        "by_day": {day: dict(counts) for day, counts in sorted(tool_by_day.items())},
        "success_rate": round(
            sum(1 for a in artifacts if a.get("status") in ("executed", "completed"))
            / max(len(artifacts), 1)
            * 100,
            1,
        ),
    }
