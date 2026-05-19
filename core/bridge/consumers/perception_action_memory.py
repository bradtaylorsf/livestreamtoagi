"""Persist bridge perception/action events through the existing memory managers.

The bridge inbound layer emits schema-validated event bus envelopes. This
consumer is the downstream memory subscriber: it renders those events into the
same kind of interaction text that conversation memory compaction already
accepts, then delegates to ``MemoryCompactor.compact_interaction`` for archival
storage, summary generation, embedding creation, and recall persistence.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from core.event_bus import EventBus, EventCallback, EventType

if TYPE_CHECKING:
    from core.memory.compaction import MemoryCompactor

logger = logging.getLogger(__name__)

_registered_callbacks: dict[int, tuple[EventCallback, EventCallback]] = {}


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


async def on_bridge_perception(event: dict[str, Any], *, compactor: MemoryCompactor) -> None:
    """Compact a bridge perception event into archival and recall memory."""
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


async def on_bridge_action_result(
    event: dict[str, Any], *, compactor: MemoryCompactor
) -> None:
    """Compact a bridge action-result event into archival and recall memory."""
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


async def _compact_bridge_event(
    *,
    data: dict[str, Any],
    compactor: MemoryCompactor,
    interaction: str,
    event_type: str,
) -> None:
    agent_id = _clean_text(data.get("agent_id"))
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


def register_memory_consumer(event_bus: EventBus, compactor: MemoryCompactor) -> None:
    """Register bridge perception/action memory callbacks on an event bus."""
    unregister_memory_consumer(event_bus)

    perception_cb = cast(
        "EventCallback",
        partial(on_bridge_perception, compactor=compactor),
    )
    action_cb = cast(
        "EventCallback",
        partial(on_bridge_action_result, compactor=compactor),
    )

    _registered_callbacks[id(event_bus)] = (perception_cb, action_cb)
    event_bus.on(EventType.BRIDGE_PERCEPTION, perception_cb)
    event_bus.on(EventType.BRIDGE_ACTION_RESULT, action_cb)


def unregister_memory_consumer(event_bus: EventBus) -> None:
    """Remove bridge memory callbacks previously registered for an event bus."""
    callbacks = _registered_callbacks.pop(id(event_bus), None)
    if callbacks is None:
        return

    perception_cb, action_cb = callbacks
    event_bus.off(EventType.BRIDGE_PERCEPTION, perception_cb)
    event_bus.off(EventType.BRIDGE_ACTION_RESULT, action_cb)
