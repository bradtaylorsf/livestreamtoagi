"""Relationship evolution section for timeline reports."""

from __future__ import annotations

from typing import Any


def _build_interaction_heatmap(relationships: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Build agent -> target -> interaction_count mapping."""
    heatmap: dict[str, dict[str, int]] = {}
    for rel in relationships:
        agent = rel.get("agent_id", "")
        target = rel.get("target_agent_id", "")
        count = rel.get("interaction_count", 0)
        if agent not in heatmap:
            heatmap[agent] = {}
        heatmap[agent][target] = count
    return heatmap


def generate_relationship_evolution(
    relationships: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Generate relationship evolution analysis.

    Gracefully handles None when relationship tracker is unavailable.
    """
    if relationships is None:
        return {
            "available": False,
            "note": "Relationship tracker not available for this simulation",
        }

    if not relationships:
        return {
            "available": True,
            "total_relationships": 0,
            "matrix": {},
            "biggest_changes": [],
        }

    # Build matrix
    matrix: dict[str, dict[str, Any]] = {}
    biggest_changes: list[dict[str, Any]] = []

    for rel in relationships:
        agent = rel.get("agent_id", "")
        target = rel.get("target_agent_id", "")
        sentiment = rel.get("sentiment_score")
        trust = rel.get("trust_score")
        interactions = rel.get("interaction_count", 0)
        evolution = rel.get("evolution_log", [])

        if agent not in matrix:
            matrix[agent] = {}
        matrix[agent][target] = {
            "sentiment": str(sentiment) if sentiment is not None else None,
            "trust": str(trust) if trust is not None else None,
            "interactions": interactions,
            "summary": rel.get("relationship_summary", ""),
        }

        # Track biggest sentiment changes from evolution log
        if evolution and len(evolution) >= 2:
            first_event = evolution[0]
            last_event = evolution[-1]
            s_before = first_event.get("sentiment_before") or first_event.get("sentiment_after", 0)
            s_after = last_event.get("sentiment_after", 0)
            if s_before is not None and s_after is not None:
                delta = abs(float(s_after) - float(s_before))
                if delta > 0.1:
                    biggest_changes.append({
                        "from": agent,
                        "to": target,
                        "sentiment_start": float(s_before),
                        "sentiment_end": float(s_after),
                        "delta": round(delta, 2),
                        "direction": "improved" if float(s_after) > float(s_before) else "worsened",
                    })

    biggest_changes.sort(key=lambda x: x["delta"], reverse=True)

    return {
        "available": True,
        "total_relationships": len(relationships),
        "matrix": matrix,
        "biggest_changes": biggest_changes[:10],
        "interaction_heatmap": _build_interaction_heatmap(relationships),
    }
