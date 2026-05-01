"""Memory evolution section for timeline reports."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def generate_memory_evolution(
    core_memory_history: list[dict[str, Any]],
    recall_counts: dict[str, int],
    journal_entries: list[dict[str, Any]],
    agents: list[str],
) -> dict[str, Any]:
    """Generate memory evolution analysis."""
    # Core memory changes per agent
    agent_changes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in core_memory_history:
        agent_id = entry.get("agent_id", "unknown")
        agent_changes[agent_id].append(
            {
                "version": entry.get("version", 0),
                "changed_at": str(entry.get("changed_at", "")),
                "reason": entry.get("change_reason", ""),
            }
        )

    # Core memory diffs (first vs latest version per agent)
    agent_diffs = {}
    for agent_id, changes in agent_changes.items():
        if len(changes) >= 2:
            agent_diffs[agent_id] = {
                "total_versions": len(changes),
                "first_change": changes[0].get("changed_at", ""),
                "last_change": changes[-1].get("changed_at", ""),
                "first_reason": changes[0].get("reason", ""),
                "last_reason": changes[-1].get("reason", ""),
            }

    # Journal themes
    journal_by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in journal_entries:
        agent_id = entry.get("agent_id", "unknown")
        journal_by_agent[agent_id].append(
            {
                "type": entry.get("reflection_type", "unknown"),
                "content_preview": str(entry.get("content", ""))[:200],
                "created_at": str(entry.get("created_at", "")),
            }
        )

    return {
        "core_memory_changes": {agent: len(changes) for agent, changes in agent_changes.items()},
        "core_memory_diffs": agent_diffs,
        "recall_memory_counts": recall_counts,
        "journal_entries_by_agent": {
            agent: len(entries) for agent, entries in journal_by_agent.items()
        },
        "total_journal_entries": len(journal_entries),
        "agents_with_no_changes": [a for a in agents if a not in agent_changes],
    }
