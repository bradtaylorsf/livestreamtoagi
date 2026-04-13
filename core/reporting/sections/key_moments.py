"""Key moments section for timeline reports."""

from __future__ import annotations

from typing import Any


def generate_key_moments(
    conversations: list[dict[str, Any]],
    management_log: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate highlight reel of key simulation moments."""
    moments: list[dict[str, Any]] = []

    # Highest-energy conversations (by turn count as proxy)
    sorted_convs = sorted(
        conversations,
        key=lambda c: c.get("turn_count", 0),
        reverse=True,
    )
    for conv in sorted_convs[:3]:
        agents = conv.get("participating_agents", [])
        if isinstance(agents, str):
            agents = [agents]
        elif not isinstance(agents, list):
            agents = list(agents) if agents else []
        moments.append({
            "type": "high_energy_conversation",
            "timestamp": str(conv.get("started_at", "")),
            "description": (
                f"Conversation with {conv.get('turn_count', 0)} turns, "
                f"participants: {', '.join(agents)}"
            ),
            "details": {
                "turn_count": conv.get("turn_count", 0),
                "trigger_type": conv.get("trigger_type", ""),
                "topics": conv.get("topics_discussed", []),
            },
        })

    # Management flags
    for flag in management_log[:5]:
        moments.append({
            "type": "management_flag",
            "timestamp": str(flag.get("created_at", "")),
            "description": f"Management flag: {flag.get('reason', 'unknown')}",
            "details": {
                "severity": flag.get("severity", 0),
                "agent_id": flag.get("agent_id", ""),
            },
        })

    # First usage of each tool type
    seen_tools: set[str] = set()
    for artifact in artifacts:
        tool = artifact.get("tool_name", "")
        if tool and tool not in seen_tools:
            seen_tools.add(tool)
            moments.append({
                "type": "first_tool_usage",
                "timestamp": str(artifact.get("created_at", "")),
                "description": f"First use of {tool} by {artifact.get('agent_id', 'unknown')}",
                "details": {
                    "tool_name": tool,
                    "agent_id": artifact.get("agent_id", ""),
                    "status": artifact.get("status", ""),
                },
            })

    # Sort by timestamp
    moments.sort(key=lambda m: m.get("timestamp", ""))

    return {
        "moments": moments,
        "total_moments": len(moments),
    }
