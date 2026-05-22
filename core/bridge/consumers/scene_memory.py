"""Batched scene-level memory compaction for Director V2 Minecraft runs."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, cast

from core.event_bus import EventBus, EventCallback, EventType
from core.llm_client import LLMError
from core.minecraft.director.scene_inbox import (
    ClosedScene,
    SceneBufferEntry,
    SceneInbox,
)
from core.minecraft.director.timeline import emit_director_timeline_event

if TYPE_CHECKING:
    from core.memory.compaction import MemoryCompactor

logger = logging.getLogger(__name__)

SCENE_EVENT_TYPE = "minecraft_scene"
SCENE_TRANSCRIPT_CATEGORIES = (
    "Chat",
    "Actions",
    "Tool results",
    "Build progress",
    "Stuck-Unstuck",
    "Health danger",
    "Inventory changes",
    "Help requests",
)
_MODEL_UNLOADED_MARKERS = ("model unloaded", "model_not_loaded")

_registered_consumers: dict[int, SceneMemoryConsumer] = {}


class SceneMemoryConsumer:
    """Close scene buffers and compact one digest per scene."""

    def __init__(
        self,
        event_bus: EventBus,
        compactor: MemoryCompactor,
        *,
        inbox: SceneInbox | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.event_bus = event_bus
        self.compactor = compactor
        self.inbox = inbox or SceneInbox(event_bus=event_bus)
        self.poll_interval_seconds = poll_interval_seconds
        self._callbacks: list[tuple[EventType, EventCallback]] = []
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._poll_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()

    def start(self) -> None:
        """Subscribe source and scene-update callbacks."""

        if self._callbacks:
            return

        source_cb = cast("EventCallback", self.ingest_source_event)
        update_cb = cast("EventCallback", self.on_scene_update)
        self._callbacks = [
            (EventType.BRIDGE_PERCEPTION, source_cb),
            (EventType.BRIDGE_ACTION_RESULT, source_cb),
            (EventType.AGENT_SPEAK, source_cb),
            (EventType.BRIDGE_SCENE_UPDATE, update_cb),
        ]
        for event_type, callback in self._callbacks:
            self.event_bus.on(event_type, callback)
        self._poll_task = asyncio.create_task(self._poll_for_closures())

    def stop(self) -> None:
        """Unsubscribe callbacks and cancel background polling."""

        for event_type, callback in self._callbacks:
            self.event_bus.off(event_type, callback)
        self._callbacks = []
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        for task in list(self._background_tasks):
            task.cancel()

    async def ingest_source_event(self, event: dict[str, Any]) -> None:
        """Feed one bridge/public-speech event into the scene inbox."""

        await self.inbox.ingest(event)

    async def on_scene_update(self, event: dict[str, Any]) -> None:
        """Piggyback major-outcome closure checks on scene updates."""

        data = event.get("data", {})
        scene = None
        if isinstance(data, dict):
            scene_id = data.get("scene_id")
            if isinstance(scene_id, str):
                scene = self.inbox.get_scene(scene_id)
        now_ms = scene.last_event_at_ms if scene is not None else _now_ms()
        self._track_background_task(self.flush_due_scenes(now_ms=now_ms))

    async def flush_due_scenes(self, *, now_ms: int | None = None) -> None:
        """Detect and compact currently closed scenes."""

        async with self._flush_lock:
            closed_scenes = self.inbox.detect_closures(now_ms if now_ms is not None else _now_ms())
            for closed_scene in closed_scenes:
                await self._compact_closed_scene(closed_scene)

    async def _poll_for_closures(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.poll_interval_seconds)
                await self.flush_due_scenes()
        except asyncio.CancelledError:
            pass

    def _track_background_task(self, coro: Awaitable[None]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _discard(completed: asyncio.Task[None]) -> None:
            self._background_tasks.discard(completed)
            try:
                completed.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Unhandled scene memory background task failure")

        task.add_done_callback(_discard)

    async def _compact_closed_scene(self, closed_scene: ClosedScene) -> None:
        scene = closed_scene.scene
        interaction = render_scene_transcript(closed_scene)
        recipients = _merge_ordered(scene.participants, scene.observers)
        if not recipients or not interaction.strip():
            return

        primary_agent_id = scene.participants[0] if scene.participants else recipients[0]
        started = time.perf_counter()
        try:
            result = await self.compactor.compact_interaction(
                agent_id=primary_agent_id,
                interaction=interaction,
                event_type=SCENE_EVENT_TYPE,
                participants=recipients,
                conversation_id=scene.scene_id,
                summary_style="scene",
            )
            if result is None:
                return

            transcript_id = result.transcript.id
            for agent_id in recipients:
                if agent_id == primary_agent_id:
                    continue
                await self.compactor.compact_recall_only(
                    agent_id=agent_id,
                    interaction=interaction,
                    event_type=SCENE_EVENT_TYPE,
                    transcript_id=transcript_id,
                    participants=recipients,
                    summary_style="scene",
                )

            summary = _recall_summary(result) or _fallback_summary(interaction)
            latency_ms = int((time.perf_counter() - started) * 1000)
            digest_payload = {
                "scene_id": scene.scene_id,
                "participants": scene.participants,
                "observers": scene.observers,
                "entries_count": len(closed_scene.buffered_events),
                "distributed_to": recipients,
                "tokens": _estimate_tokens(interaction) + _estimate_tokens(summary),
                "latency_ms": latency_ms,
                "transcript_id": transcript_id,
                "close_reason": closed_scene.close_reason,
                "summary": summary,
            }
            emit_director_timeline_event(
                "director.memory.compaction",
                {
                    **digest_payload,
                    "primary_agent_id": primary_agent_id,
                    "ok": True,
                },
                agent_id=primary_agent_id,
                trace_id=scene.scene_id,
            )
            emit_director_timeline_event(
                "director.scene.digest",
                digest_payload,
                agent_id=primary_agent_id,
                trace_id=scene.scene_id,
            )
            await self.event_bus.emit(
                EventType.BRIDGE_SCENE_DIGEST,
                {
                    "scene_id": scene.scene_id,
                    "summary": summary,
                    "participants": scene.participants,
                    "observers": scene.observers,
                    "commitments": extract_commitments(interaction),
                    "transcript_id": transcript_id,
                    "close_reason": closed_scene.close_reason,
                },
            )
        except Exception as exc:
            error_class = classify_compaction_error(exc) or exc.__class__.__name__
            emit_director_timeline_event(
                "director.memory.compaction",
                {
                    "scene_id": scene.scene_id,
                    "participants": scene.participants,
                    "observers": scene.observers,
                    "entries_count": len(closed_scene.buffered_events),
                    "distributed_to": recipients,
                    "tokens": _estimate_tokens(interaction),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "primary_agent_id": primary_agent_id,
                    "close_reason": closed_scene.close_reason,
                    "ok": False,
                    "error_class": error_class,
                },
                agent_id=primary_agent_id,
                trace_id=scene.scene_id,
            )
            logger.error(
                "Scene memory compaction failed",
                extra={
                    "event": "memory_compaction_error",
                    "scene_id": scene.scene_id,
                    "error_class": error_class,
                },
                exc_info=True,
            )


def register_scene_memory_consumer(
    event_bus: EventBus,
    compactor: MemoryCompactor,
    *,
    inbox: SceneInbox | None = None,
    poll_interval_seconds: float = 1.0,
) -> SceneMemoryConsumer:
    """Register Director V2 scene-level memory compaction callbacks."""

    unregister_scene_memory_consumer(event_bus)
    consumer = SceneMemoryConsumer(
        event_bus,
        compactor,
        inbox=inbox,
        poll_interval_seconds=poll_interval_seconds,
    )
    consumer.start()
    _registered_consumers[id(event_bus)] = consumer
    return consumer


def unregister_scene_memory_consumer(event_bus: EventBus) -> None:
    """Remove a scene memory consumer from the event bus."""

    consumer = _registered_consumers.pop(id(event_bus), None)
    if consumer is None:
        return
    consumer.stop()


def render_scene_transcript(closed_scene: ClosedScene) -> str:
    """Render buffered scene evidence into one archival transcript."""

    scene = closed_scene.scene
    lines = [
        f"Minecraft scene: {scene.scene_id}",
        f"Close reason: {closed_scene.close_reason}",
        f"Opened at ms: {scene.opened_at_ms}",
        f"Closed at ms: {closed_scene.closed_at_ms}",
        f"Participants: {', '.join(scene.participants) or 'none'}",
        f"Observers: {', '.join(scene.observers) or 'none'}",
    ]
    for category in SCENE_TRANSCRIPT_CATEGORIES:
        entries = _entries_for_category(closed_scene.buffered_events, category)
        if not entries:
            continue
        lines.extend(("", f"## {category}"))
        lines.extend(f"- {entry.text}" for entry in entries)
    return "\n".join(lines)


def classify_compaction_error(exc: BaseException) -> str | None:
    """Return a memory-compaction error class for expected compaction failures."""

    lowered = str(exc).lower()
    if any(marker in lowered for marker in _MODEL_UNLOADED_MARKERS):
        return "model_unloaded"
    if isinstance(exc, LLMError):
        return "llm_error"
    if isinstance(exc, OSError):
        return "os_error"
    if isinstance(exc, RuntimeError):
        return "runtime_error"
    return None


def extract_commitments(interaction: str) -> list[str]:
    """Extract concise commitment lines from a rendered scene transcript."""

    commitments = []
    for line in interaction.splitlines():
        if not re.search(
            r"\b(i'll|i will|we'll|we will|promise|commit|committed|plan to|going to)\b",
            line,
            flags=re.IGNORECASE,
        ):
            continue
        commitments.append(_clip(line.removeprefix("- ").strip(), 240))
    return commitments[:8]


def _entries_for_category(
    events: list[SceneBufferEntry],
    category: str,
) -> list[SceneBufferEntry]:
    return [event for event in events if event.category == category]


def _merge_ordered(first: list[str], second: list[str]) -> list[str]:
    merged = []
    seen: set[str] = set()
    for agent_id in [*first, *second]:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        merged.append(agent_id)
    return merged


def _recall_summary(result: object) -> str | None:
    recall = getattr(result, "recall_memory", None)
    summary = getattr(recall, "summary", None)
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return None


def _fallback_summary(interaction: str) -> str:
    for line in interaction.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("##"):
            return _clip(stripped, 280)
    return "Minecraft scene compacted."


def _estimate_tokens(value: Any) -> int:
    text = str(value or "")
    return max(1, (len(text) + 3) // 4) if text else 0


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _now_ms() -> int:
    return int(time.time() * 1000)
