"""Embodied activity section for timeline reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from core.eval.loader import _derive_build_outcomes, _extract_build_feedback_artifacts


def generate_embodied_activity(
    actions: list[dict[str, Any]],
    perception_reports: list[dict[str, Any]],
    world_chunks: list[dict[str, Any]],
    build_feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize embodied actions, perceptions, and verified build outcomes."""
    build_outcomes = _derive_build_outcomes(actions, perception_reports)
    feedback_records = build_feedback or []
    status_counts = Counter(str(action.get("status") or "unknown") for action in actions)

    completions = [
        float(outcome["completion"])
        for outcome in build_outcomes
        if outcome.get("completion") is not None
    ]
    builds_verified = sum(1 for outcome in build_outcomes if bool(outcome.get("verified")))
    builds_partial = sum(1 for outcome in build_outcomes if _is_partial_build(outcome))
    builds_failed = sum(1 for outcome in build_outcomes if _is_failed_build(outcome))

    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "actions": 0,
            "perception_reports": 0,
            "builds_attempted": 0,
            "builds_verified": 0,
            "build_feedback_records": 0,
            "avg_completion": None,
            "_completion_total": 0.0,
            "_completion_count": 0,
        }
    )

    for action in actions:
        agent_id = str(action.get("agent_id") or "unknown")
        by_agent[agent_id]["actions"] += 1

    for report in perception_reports:
        agent_id = str(report.get("agent_id") or "unknown")
        by_agent[agent_id]["perception_reports"] += 1

    for outcome in build_outcomes:
        agent_id = str(outcome.get("agent_id") or "unknown")
        by_agent[agent_id]["builds_attempted"] += 1
        if bool(outcome.get("verified")):
            by_agent[agent_id]["builds_verified"] += 1
        completion = outcome.get("completion")
        if completion is not None:
            by_agent[agent_id]["_completion_total"] += float(completion)
            by_agent[agent_id]["_completion_count"] += 1

    for feedback in feedback_records:
        agent_id = str(feedback.get("agent_id") or "unknown")
        by_agent[agent_id]["build_feedback_records"] += 1

    clean_by_agent = {}
    for agent_id, stats in by_agent.items():
        count = stats.pop("_completion_count")
        total = stats.pop("_completion_total")
        if count:
            stats["avg_completion"] = round(total / count, 4)
        clean_by_agent[agent_id] = dict(stats)

    return {
        "total_actions": len(actions),
        "total_perception_reports": len(perception_reports),
        "action_status_counts": dict(status_counts),
        "builds_attempted": len(build_outcomes),
        "builds_verified": builds_verified,
        "builds_partial": builds_partial,
        "builds_failed": builds_failed,
        "avg_completion": round(sum(completions) / len(completions), 4) if completions else None,
        "build_feedback_records": len(feedback_records),
        "build_feedback_missing": sum(
            _feedback_bucket_count(item.get("missing")) for item in feedback_records
        ),
        "build_feedback_unsafe": sum(
            _feedback_bucket_count(item.get("unsafe")) for item in feedback_records
        ),
        "latest_suggested_next_step": _latest_suggested_next_step(feedback_records),
        "world_chunks": len(world_chunks),
        "by_agent": clean_by_agent,
    }


def extract_build_feedback_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return structured build-feedback records from report artifact rows."""
    return _extract_build_feedback_artifacts(artifacts)


def _is_partial_build(outcome: dict[str, Any]) -> bool:
    if bool(outcome.get("verified")):
        return False
    label = str(outcome.get("class") or outcome.get("outcome_class") or "").lower()
    if label == "partial":
        return True
    completion = outcome.get("completion")
    return completion is not None and 0 < float(completion) < 1


def _is_failed_build(outcome: dict[str, Any]) -> bool:
    label = str(outcome.get("class") or outcome.get("outcome_class") or "").lower()
    status = str(outcome.get("status") or "").lower()
    failed_labels = {"abandoned", "blocked", "failed", "failure", "invalid", "timeout"}
    if label in failed_labels or status in failed_labels:
        return True
    completion = outcome.get("completion")
    return completion is not None and float(completion) == 0


def _feedback_bucket_count(value: Any) -> int:
    if isinstance(value, dict):
        raw = value.get("count")
    else:
        raw = value
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _latest_suggested_next_step(feedback_records: list[dict[str, Any]]) -> str | None:
    for feedback in reversed(feedback_records):
        next_step = str(feedback.get("suggested_next_step") or "").strip()
        if next_step:
            return next_step
    return None
