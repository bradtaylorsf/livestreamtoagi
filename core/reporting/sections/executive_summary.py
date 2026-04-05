"""Executive summary section for timeline reports."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def generate_executive_summary(
    sim: dict[str, Any],
    conversations: list[dict[str, Any]],
    cost_events: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    management_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate the executive summary section."""
    total_cost = sum(Decimal(str(c.get("amount", 0))) for c in cost_events)
    total_turns = sum(c.get("turn_count", 0) for c in conversations)
    total_tokens = sim.get("total_tokens", 0)

    # Determine trajectory
    if len(conversations) >= 4:
        first_half = conversations[: len(conversations) // 2]
        second_half = conversations[len(conversations) // 2 :]
        avg_turns_first = sum(c.get("turn_count", 0) for c in first_half) / max(len(first_half), 1)
        avg_turns_second = sum(c.get("turn_count", 0) for c in second_half) / max(len(second_half), 1)
        if avg_turns_second > avg_turns_first * 1.1:
            trajectory = "improving"
        elif avg_turns_second < avg_turns_first * 0.9:
            trajectory = "degrading"
        else:
            trajectory = "stable"
    else:
        trajectory = "insufficient_data"

    return {
        "simulated_duration": str(sim.get("simulated_duration", "N/A")),
        "real_duration": str(sim.get("real_duration", "N/A")),
        "total_cost": str(total_cost),
        "total_conversations": len(conversations),
        "total_turns": total_turns,
        "total_tokens": total_tokens,
        "total_tool_invocations": len(artifacts),
        "total_management_flags": len(management_log),
        "agents_participated": sim.get("agents_participated", []),
        "trajectory": trajectory,
        "status": sim.get("status", "unknown"),
    }
