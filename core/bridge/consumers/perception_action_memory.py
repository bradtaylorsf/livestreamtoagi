"""Persist bridge perception/action events through the existing memory managers.

The bridge inbound layer emits schema-validated event bus envelopes. This
consumer is the downstream memory subscriber: it renders those events into the
same kind of interaction text that conversation memory compaction already
accepts, then delegates to ``MemoryCompactor.compact_interaction`` for archival
storage, summary generation, embedding creation, and recall persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from core.conversation_mode import is_director_v2_run
from core.embodiment.build_feedback import (
    BUILD_FEEDBACK_ARTIFACT_TYPE,
    BUILD_FEEDBACK_EVENT_TYPE,
    build_feedback_from_attempt,
    format_build_feedback,
    is_build_action_payload,
)
from core.event_bus import EventBus, EventCallback, EventType
from core.models import ArtifactCreate

if TYPE_CHECKING:
    from core.memory.compaction import MemoryCompactor
    from core.repos.artifact_repo import ArtifactRepo

logger = logging.getLogger(__name__)

_registered_callbacks: dict[int, tuple[EventCallback, EventCallback]] = {}
_background_tasks: set[asyncio.Task[None]] = set()
_pending_build_attempts: dict[tuple[str, str], dict[str, Any]] = {}
_MAX_PENDING_BUILD_ATTEMPTS = 256


def _track_background_task(coro: Awaitable[None]) -> None:
    """Run memory compaction without blocking the bridge acknowledgement path."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _discard(completed: asyncio.Task[None]) -> None:
        _background_tasks.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unhandled bridge memory consumer task failure")

    task.add_done_callback(_discard)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _canonical_agent_id(value: object) -> str:
    return _clean_text(value).lower()


def _render_observation(observation: object) -> str:
    try:
        return json.dumps(observation, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(observation)


def format_observations(observations: object) -> str:
    """Render structured observations into deterministic interaction text."""
    if not isinstance(observations, list) or not observations:
        return ""

    lines = [f"- {_render_observation(observation)}" for observation in observations]
    return "Perception report:\n" + "\n".join(lines)


def format_action_result(action_id: object, status: object, detail: object) -> str:
    """Render an action outcome into deterministic interaction text."""
    fields = [
        ("action_id", _clean_text(action_id)),
        ("status", _clean_text(status)),
        ("detail", _clean_text(detail)),
    ]
    lines = [f"- {name}: {value}" for name, value in fields if value]
    if not lines:
        return ""
    return "Action result:\n" + "\n".join(lines)


def _pending_key(data: dict[str, Any]) -> tuple[str, str] | None:
    agent_id = _canonical_agent_id(data.get("agent_id"))
    action_id = _clean_text(data.get("action_id") or data.get("actionId") or data.get("request_id"))
    if not agent_id or not action_id:
        return None
    return (agent_id, action_id)


def _remember_build_attempt(data: dict[str, Any]) -> None:
    if not is_build_action_payload(data):
        return
    key = _pending_key(data)
    if key is None:
        return
    _pending_build_attempts[key] = dict(data)
    while len(_pending_build_attempts) > _MAX_PENDING_BUILD_ATTEMPTS:
        _pending_build_attempts.pop(next(iter(_pending_build_attempts)))


def _action_ids_from_perception(data: dict[str, Any]) -> set[str]:
    action_ids: set[str] = set()
    observations = data.get("observations")
    if not isinstance(observations, list):
        return action_ids
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        action_id = observation.get("action_id") or observation.get("actionId")
        if action_id:
            action_ids.add(str(action_id))
    return action_ids


def _pop_matching_build_attempts(data: dict[str, Any]) -> list[dict[str, Any]]:
    agent_id = _canonical_agent_id(data.get("agent_id"))
    if not agent_id:
        return []

    action_ids = _action_ids_from_perception(data)
    matched_keys: list[tuple[str, str]] = []
    for key in list(_pending_build_attempts):
        pending_agent, pending_action = key
        if pending_agent != agent_id:
            continue
        if action_ids and pending_action not in action_ids:
            continue
        matched_keys.append(key)

    attempts: list[dict[str, Any]] = []
    for key in matched_keys:
        attempts.append(_pending_build_attempts.pop(key))
    return attempts


async def on_bridge_perception(event: dict[str, Any], *, compactor: MemoryCompactor) -> None:
    """Compact a bridge perception event into archival and recall memory."""
    if is_director_v2_run():
        logger.debug("Skipping per-event perception compaction during Director V2 run")
        return

    data = event.get("data", {})
    if not isinstance(data, dict):
        logger.debug("Skipping bridge perception memory compaction with non-dict data")
        return

    await _compact_bridge_event(
        data=data,
        compactor=compactor,
        interaction=format_observations(data.get("observations")),
        event_type=EventType.BRIDGE_PERCEPTION.value,
    )


async def on_bridge_action_result(event: dict[str, Any], *, compactor: MemoryCompactor) -> None:
    """Compact a bridge action-result event into archival and recall memory."""
    if is_director_v2_run():
        logger.debug("Skipping per-event action-result compaction during Director V2 run")
        return

    data = event.get("data", {})
    if not isinstance(data, dict):
        logger.debug("Skipping bridge action-result memory compaction with non-dict data")
        return

    await _compact_bridge_event(
        data=data,
        compactor=compactor,
        interaction=format_action_result(
            data.get("action_id"),
            data.get("status"),
            data.get("detail"),
        ),
        event_type=EventType.BRIDGE_ACTION_RESULT.value,
    )


async def on_build_feedback(
    feedback: dict[str, Any],
    *,
    compactor: MemoryCompactor,
    event_bus: EventBus,
    artifact_repo: ArtifactRepo | None = None,
    source_action: dict[str, Any] | None = None,
) -> None:
    """Emit, persist, and compact a build-quality feedback record."""
    agent_id = _canonical_agent_id(feedback.get("agent_id"))
    if not agent_id:
        logger.debug("Skipping build feedback with missing agent_id")
        return

    try:
        await event_bus.emit(EventType.BUILD_FEEDBACK, feedback)
    except Exception:
        logger.exception("Failed to emit build feedback for agent_id=%r", agent_id)

    if artifact_repo is not None:
        await _save_build_feedback_artifact(
            feedback,
            artifact_repo=artifact_repo,
            source_action=source_action or {},
        )

    await _compact_bridge_event(
        data=feedback,
        compactor=compactor,
        interaction=format_build_feedback(feedback),
        event_type=BUILD_FEEDBACK_EVENT_TYPE,
    )


async def _save_build_feedback_artifact(
    feedback: dict[str, Any],
    *,
    artifact_repo: ArtifactRepo,
    source_action: dict[str, Any],
) -> None:
    simulation_id = _uuid_or_none(
        feedback.get("simulation_id") or source_action.get("simulation_id")
    )
    try:
        await artifact_repo.save_artifact(
            ArtifactCreate(
                simulation_id=simulation_id,
                conversation_id=None,
                agent_id=_canonical_agent_id(feedback.get("agent_id")),
                tool_name="build_quality_feedback",
                tool_input={
                    "attempt_id": feedback.get("attempt_id"),
                    "goal": feedback.get("goal"),
                    "source_action": source_action,
                },
                tool_output=dict(feedback),
                artifact_type=BUILD_FEEDBACK_ARTIFACT_TYPE,
                status="executed",
                metadata={
                    "source": "perception_action_memory",
                    "trace_id": source_action.get("trace_id"),
                    "request_id": source_action.get("request_id"),
                },
            )
        )
    except Exception:
        logger.exception(
            "Failed to persist build feedback artifact for agent_id=%r",
            feedback.get("agent_id"),
        )


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _enqueue_bridge_perception(
    event: dict[str, Any],
    *,
    compactor: MemoryCompactor,
    event_bus: EventBus,
    artifact_repo: ArtifactRepo | None = None,
) -> None:
    data = event.get("data", {})
    if isinstance(data, dict):
        for attempt in _pop_matching_build_attempts(data):
            feedback = build_feedback_from_attempt(attempt, data, [attempt])
            feedback["simulation_id"] = attempt.get("simulation_id") or data.get("simulation_id")
            _track_background_task(
                on_build_feedback(
                    feedback,
                    compactor=compactor,
                    event_bus=event_bus,
                    artifact_repo=artifact_repo,
                    source_action=attempt,
                )
            )
    _track_background_task(on_bridge_perception(event, compactor=compactor))


async def _enqueue_bridge_action_result(
    event: dict[str, Any],
    *,
    compactor: MemoryCompactor,
) -> None:
    data = event.get("data", {})
    if isinstance(data, dict):
        _remember_build_attempt(data)
    _track_background_task(on_bridge_action_result(event, compactor=compactor))


async def _compact_bridge_event(
    *,
    data: dict[str, Any],
    compactor: MemoryCompactor,
    interaction: str,
    event_type: str,
) -> None:
    agent_id = _canonical_agent_id(data.get("agent_id"))
    if not agent_id:
        logger.debug("Skipping %s memory compaction with missing agent_id", event_type)
        return
    if not interaction.strip():
        logger.debug("Skipping %s memory compaction with empty interaction", event_type)
        return

    try:
        await compactor.compact_interaction(
            agent_id=agent_id,
            interaction=interaction,
            event_type=event_type,
            participants=[agent_id],
            conversation_id=None,
        )
    except Exception:
        logger.exception("Failed to compact %s memory for agent_id=%r", event_type, agent_id)


def register_memory_consumer(
    event_bus: EventBus,
    compactor: MemoryCompactor,
    *,
    artifact_repo: ArtifactRepo | None = None,
) -> None:
    """Register bridge perception/action memory callbacks on an event bus."""
    unregister_memory_consumer(event_bus)

    perception_cb = cast(
        "EventCallback",
        partial(
            _enqueue_bridge_perception,
            compactor=compactor,
            event_bus=event_bus,
            artifact_repo=artifact_repo,
        ),
    )
    action_cb = cast(
        "EventCallback",
        partial(_enqueue_bridge_action_result, compactor=compactor),
    )

    _registered_callbacks[id(event_bus)] = (perception_cb, action_cb)
    event_bus.on(EventType.BRIDGE_PERCEPTION, perception_cb)
    event_bus.on(EventType.BRIDGE_ACTION_RESULT, action_cb)


def unregister_memory_consumer(event_bus: EventBus) -> None:
    """Remove bridge memory callbacks previously registered for an event bus."""
    callbacks = _registered_callbacks.pop(id(event_bus), None)
    _pending_build_attempts.clear()
    if callbacks is None:
        return

    perception_cb, action_cb = callbacks
    event_bus.off(EventType.BRIDGE_PERCEPTION, perception_cb)
    event_bus.off(EventType.BRIDGE_ACTION_RESULT, action_cb)
