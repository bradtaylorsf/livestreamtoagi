"""Structured build-quality feedback for embodied Minecraft runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict

from core.embodiment.building import verify_break, verify_place
from core.eval.loader import BUILD_ACTION_NAMES, BUILD_METRIC_RE


class FeedbackBucket(TypedDict):
    count: int
    items: list[dict[str, Any]]


class BuildFeedback(TypedDict):
    attempt_id: str
    agent_id: str
    goal: str
    intended: FeedbackBucket
    present: FeedbackBucket
    missing: FeedbackBucket
    unexpected: FeedbackBucket
    unsafe: FeedbackBucket
    completion: float
    suggested_next_step: str
    classification: str


BUILD_FEEDBACK_ARTIFACT_TYPE = "build_feedback"
BUILD_FEEDBACK_EVENT_TYPE = "build_feedback"

_BLOCKED_CLASSES = {"blocked", "protected", "interrupted", "aborted", "invalid", "timed-out"}
_BREAK_OPERATIONS = {"break", "remove", "removed", "mine", "mined", "dig", "dug"}
_UNSAFE_CLASSES = {"unsafe", "danger", "hazard", "lava", "fall", "fire", "protected"}


def is_build_action_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether an action-result payload appears to be a build attempt."""
    action_name = str(
        _first_present(payload, "action", "verb", "command", "tool", "tool_name", "action_type")
        or ""
    )
    if _is_build_action_name(action_name):
        return True

    action_id = str(_first_present(payload, "action_id", "actionId") or "")
    detail = str(_first_present(payload, "detail", "result", "message") or "")
    combined = f"{action_id} {detail}".lower()
    return (
        "build" in combined
        or "planandbuild" in combined
        or "plan-and-build" in combined
        or ("intended=" in combined and "completion=" in combined)
    )


def build_feedback_from_attempt(
    plan: Mapping[str, Any],
    perception_snapshot: Mapping[str, Any] | None,
    action_results: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> BuildFeedback:
    """Compare intended build work with observed block/action state."""
    results = _as_mapping_list(action_results)
    observations = _extract_observations(perception_snapshot)
    sources: list[Mapping[str, Any]] = [plan, *results, *observations]
    if perception_snapshot is not None:
        sources.append(perception_snapshot)
    metrics = _extract_build_metrics(sources)
    intended_items = _extract_intended_items(plan)

    present_items: list[dict[str, Any]] = []
    missing_items: list[dict[str, Any]] = []
    unmatched_observations = list(observations)

    for step in intended_items:
        observation = _match_observation(step, unmatched_observations)
        if observation is not None:
            unmatched_observations.remove(observation)
        verified = _verify_step(step, observation)
        checked_step = {**step}
        if observation is not None:
            checked_step["observation"] = observation
        if verified["verified"]:
            checked_step["class"] = verified["class"]
            present_items.append(checked_step)
        else:
            checked_step["class"] = verified["class"]
            missing_items.append(checked_step)

    unexpected_items = _extract_unexpected_items(unmatched_observations)
    unsafe_items = _extract_unsafe_items(sources)

    intended_count = _count_or_metric(intended_items, metrics.get("intended"))
    present_count = _count_or_metric(present_items, metrics.get("present"))
    missing_count = _count_or_metric(missing_items, metrics.get("missing"))
    unexpected_count = _count_or_metric(unexpected_items, metrics.get("unexpected"))
    unsafe_count = len(unsafe_items)

    completion = _coerce_float(metrics.get("completion"))
    if completion is None:
        completion = round(present_count / intended_count, 4) if intended_count else 0.0
    completion = max(0.0, min(1.0, completion))

    classification = _classify_feedback(
        completion=completion,
        missing_count=missing_count,
        unexpected_count=unexpected_count,
        unsafe_count=unsafe_count,
        action_results=results,
    )
    feedback: BuildFeedback = {
        "attempt_id": _attempt_id(plan, results),
        "agent_id": _agent_id(plan, perception_snapshot, results),
        "goal": _goal(plan, results),
        "intended": _bucket(intended_count, intended_items),
        "present": _bucket(present_count, present_items),
        "missing": _bucket(missing_count, missing_items),
        "unexpected": _bucket(unexpected_count, unexpected_items),
        "unsafe": _bucket(unsafe_count, unsafe_items),
        "completion": completion,
        "suggested_next_step": "",
        "classification": classification,
    }
    feedback["suggested_next_step"] = _suggest_next_step(feedback)
    return feedback


def format_build_feedback(feedback: BuildFeedback) -> str:
    """Render feedback into deterministic interaction text for recall memory."""
    completion_pct = round(float(feedback["completion"]) * 100)
    return "\n".join(
        [
            "Build quality feedback:",
            f"- attempt_id: {feedback['attempt_id']}",
            f"- goal: {feedback['goal']}",
            f"- completion: {completion_pct}%",
            f"- classification: {feedback['classification']}",
            f"- intended: {feedback['intended']['count']}",
            f"- present: {feedback['present']['count']}",
            f"- missing: {feedback['missing']['count']}",
            f"- unexpected: {feedback['unexpected']['count']}",
            f"- unsafe: {feedback['unsafe']['count']}",
            f"- suggested_next_step: {feedback['suggested_next_step']}",
        ]
    )


def _as_mapping_list(
    value: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    return [item for item in value if isinstance(item, Mapping)]


def _extract_observations(snapshot: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, Mapping):
        return []
    observations: list[dict[str, Any]] = []
    for key in ("observations", "blocks", "visible_blocks", "changed_blocks"):
        value = snapshot.get(key)
        if isinstance(value, list):
            observations.extend(dict(item) for item in value if isinstance(item, Mapping))
    nested = snapshot.get("snapshot")
    if isinstance(nested, Mapping):
        observations.extend(_extract_observations(nested))
    return observations


def _extract_intended_items(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("intended", "expected", "blocks", "placements", "steps"):
        value = plan.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    nested = plan.get("plan") or plan.get("build_plan")
    if isinstance(nested, Mapping):
        candidates.extend(_extract_intended_items(nested))

    items: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            items.append(_normalize_step(candidate))
    return items


def _normalize_step(step: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(step)
    position = _position_from(step)
    if position:
        normalized["position"] = position
    expected = _first_present(
        step,
        "block_type",
        "blockType",
        "expected_block_type",
        "expectedBlockType",
        "type",
        "name",
    )
    if expected is not None:
        normalized["expected_block_type"] = expected
    operation = _first_present(step, "operation", "action", "verb", "mode")
    if operation is not None:
        normalized["operation"] = str(operation).strip().lower()
    return normalized


def _position_from(value: Mapping[str, Any]) -> dict[str, Any]:
    position = value.get("position")
    if isinstance(position, Mapping):
        x = _first_present(position, "x")
        y = _first_present(position, "y")
        z = _first_present(position, "z")
    else:
        x = _first_present(value, "x")
        y = _first_present(value, "y")
        z = _first_present(value, "z")
    if x is None or y is None or z is None:
        return {}
    return {"x": x, "y": y, "z": z}


def _match_observation(
    step: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    step_location = _location_key(step)
    if step_location is None:
        return None
    for observation in observations:
        if _location_key(observation) == step_location:
            return observation
    return None


def _verify_step(
    step: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if observation is None:
        return {"verified": False, "class": "missing"}

    operation = str(step.get("operation") or "").lower()
    expected = step.get("expected_block_type")
    if operation in _BREAK_OPERATIONS:
        return verify_break(observation, expected)
    return verify_place(observation, expected)


def _extract_unexpected_items(observations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unexpected: list[dict[str, Any]] = []
    for observation in observations:
        label = str(_first_present(observation, "class", "outcome_class", "type") or "").lower()
        if bool(observation.get("unexpected")) or label == "unexpected":
            unexpected.append(dict(observation))
    return unexpected


def _extract_unsafe_items(sources: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unsafe: list[dict[str, Any]] = []
    for source in sources:
        added = False
        hazards = source.get("hazards") or source.get("unsafe")
        if isinstance(hazards, list):
            unsafe.extend(dict(item) for item in hazards if isinstance(item, Mapping))
            added = True
        elif isinstance(hazards, Mapping):
            unsafe.append(dict(hazards))
            added = True
        elif hazards is True:
            unsafe.append({"reason": source.get("reason") or source.get("detail") or "unsafe"})
            added = True

        label = str(_first_present(source, "class", "outcome_class", "type", "kind") or "").lower()
        if not added and (label in _UNSAFE_CLASSES or source.get("is_safe") is False):
            unsafe.append(dict(source))
    return unsafe


def _extract_build_metrics(sources: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for source in sources:
        for candidate in _metric_candidates(source):
            for src, dest in (
                ("intended", "intended"),
                ("intended_count", "intended"),
                ("present", "present"),
                ("blocks_present", "present"),
                ("missing", "missing"),
                ("blocks_missing", "missing"),
                ("unexpected", "unexpected"),
                ("blocks_unexpected", "unexpected"),
                ("completion", "completion"),
                ("completion_ratio", "completion"),
            ):
                if src in candidate and candidate.get(src) is not None:
                    metrics[dest] = candidate.get(src)
        detail = str(_first_present(source, "detail", "result", "message") or "")
        for name, value in BUILD_METRIC_RE.findall(detail):
            metrics[name] = value
    return metrics


def _metric_candidates(source: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = [source]
    for key in ("verification", "verify_build_plan", "build_plan", "metric"):
        value = source.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    return candidates


def _classify_feedback(
    *,
    completion: float,
    missing_count: int,
    unexpected_count: int,
    unsafe_count: int,
    action_results: Sequence[Mapping[str, Any]],
) -> str:
    if unsafe_count:
        return "unsafe"
    if completion >= 1.0 and missing_count == 0 and unexpected_count == 0:
        return "complete"
    if missing_count:
        return "needs_repair"
    if unexpected_count:
        return "cleanup_needed"
    if any(
        str(result.get("outcome_class") or "").lower() in _BLOCKED_CLASSES
        for result in action_results
    ):
        return "blocked"
    if completion > 0:
        return "partial"
    return "no_verified_progress"


def _suggest_next_step(feedback: BuildFeedback) -> str:
    if feedback["unsafe"]["count"]:
        item = _first_item_label(feedback["unsafe"]["items"])
        return f"Address unsafe build condition before continuing: {item}."
    if feedback["missing"]["count"]:
        item = _first_item_label(feedback["missing"]["items"])
        return f"Repair missing intended block or step at {item}."
    if feedback["unexpected"]["count"]:
        item = _first_item_label(feedback["unexpected"]["items"])
        return f"Remove or reconcile unexpected block at {item}."
    if feedback["classification"] == "blocked":
        return "Clear the blockage or choose a safer adjacent build location."
    if feedback["classification"] == "complete":
        return "Plan complete; continue with the next goal."
    return "Re-check the build goal and continue with the next smallest repair."


def _first_item_label(items: list[dict[str, Any]]) -> str:
    if not items:
        return "the reported build site"
    item = items[0]
    location = _location_key(item)
    if location is not None:
        return f"x={location[0]}, y={location[1]}, z={location[2]}"
    return str(
        _first_present(item, "reason", "detail", "class", "type") or "the reported build site"
    )


def _attempt_id(plan: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> str:
    for source in (plan, *results):
        value = _first_present(source, "attempt_id", "action_id", "actionId", "request_id")
        if value:
            return str(value)
    return "unknown"


def _agent_id(
    plan: Mapping[str, Any],
    perception_snapshot: Mapping[str, Any] | None,
    results: Sequence[Mapping[str, Any]],
) -> str:
    sources = [plan]
    if perception_snapshot is not None:
        sources.append(perception_snapshot)
    sources.extend(results)
    for source in sources:
        value = _first_present(source, "agent_id", "agent", "source_agent_id")
        if value:
            return str(value).strip().lower()
    return "unknown"


def _goal(plan: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> str:
    for source in (plan, *results):
        value = _first_present(source, "goal", "description", "objective", "prompt")
        if value:
            return str(value)
    for source in results:
        detail = str(source.get("detail") or "").strip()
        if detail:
            return detail[:240]
    return "Build attempt"


def _bucket(count: int, items: list[dict[str, Any]]) -> FeedbackBucket:
    return {"count": max(0, count), "items": items}


def _count_or_metric(items: list[dict[str, Any]], metric: Any) -> int:
    coerced = _coerce_int(metric)
    return coerced if coerced is not None else len(items)


def _location_key(value: Mapping[str, Any]) -> tuple[str, str, str] | None:
    position = value.get("position")
    if isinstance(position, Mapping):
        x = _first_present(position, "x")
        y = _first_present(position, "y")
        z = _first_present(position, "z")
    else:
        x = _first_present(value, "x")
        y = _first_present(value, "y")
        z = _first_present(value, "z")
    if x is None or y is None or z is None:
        return None
    return (str(x), str(y), str(z))


def _is_build_action_name(value: str) -> bool:
    normalized = value.strip().lower().replace("_", "-").replace("!", "")
    return normalized in {name.replace("!", "") for name in BUILD_ACTION_NAMES}


def _first_present(source: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
