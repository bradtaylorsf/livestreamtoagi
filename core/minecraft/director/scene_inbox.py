"""Minecraft scene inbox for Director V2.

The inbox translates raw bridge/chat/action telemetry into bounded scene
updates. It is opt-in: importing this module does not subscribe to the live
bridge, and #753 will decide where to register it in the Director V2 path.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.bridge.contract import Vec3
from core.event_bus import EventBus, EventType
from core.event_bus import event_bus as default_event_bus
from core.minecraft.director.spatial_hearing import (
    AgentPose,
    SpatialHearingAdapter,
)
from core.minecraft.director.timeline import emit_director_timeline_event


class SceneEventType(str, Enum):
    CHAT = "chat"
    MOVEMENT_MILESTONE = "movement_milestone"
    BUILD_ACTION = "build_action"
    BLOCK_INTERACTION = "block_interaction"
    HEALTH_DANGER = "health_danger"
    STUCK = "stuck"
    UNSTUCK = "unstuck"
    INVENTORY_CHANGE = "inventory_change"
    RESOURCE_CHANGE = "resource_change"
    TOOL_RESULT = "tool_result"


class SceneEvent(BaseModel):
    """Normalized event used by the Director V2 scene inbox."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    type: SceneEventType
    source_agent_id: str
    origin: Vec3
    dimension: str
    timestamp_ms: int
    direct_addressees: set[str] = Field(default_factory=set)
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str


class Scene(BaseModel):
    """Bounded scene record emitted for later Director V2 scheduling."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    triggering_event_type: SceneEventType
    participants: list[str]
    observers: list[str]
    event_ids: list[str]
    opened_at_ms: int
    last_event_at_ms: int


class SceneBufferEntry(BaseModel):
    """Rendered evidence line retained until a scene is compacted."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: SceneEventType
    category: str
    source_agent_id: str
    timestamp_ms: int
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ClosedScene(BaseModel):
    """A scene plus its buffered evidence after the inbox closes it."""

    model_config = ConfigDict(extra="forbid")

    scene: Scene
    buffered_events: list[SceneBufferEntry]
    closed_at_ms: int
    close_reason: str


class SceneUpdate(BaseModel):
    """Result returned by ``SceneInbox.ingest``."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str | None
    is_new_scene: bool
    participants_added: list[str]
    observers_added: list[str]
    suppression_reason: str | None = None
    event_id: str | None = None
    event_type: SceneEventType | None = None
    scene: Scene | None = None


@dataclass(frozen=True)
class SceneInboxConfig:
    """Tunable windowing and dedupe settings for scene formation."""

    scene_window_ms: int = 30_000
    coarse_bucket_size_blocks: int = 16
    max_recent_scenes: int = 128
    dedupe_window_ms: int = 30_000
    dedupe_event_types: frozenset[SceneEventType] = field(
        default_factory=lambda: frozenset(
            {
                SceneEventType.MOVEMENT_MILESTONE,
                SceneEventType.BUILD_ACTION,
                SceneEventType.BLOCK_INTERACTION,
                SceneEventType.INVENTORY_CHANGE,
            }
        )
    )
    telemetry_only_event_types: frozenset[SceneEventType] = field(
        default_factory=lambda: frozenset(
            {
                SceneEventType.MOVEMENT_MILESTONE,
                SceneEventType.INVENTORY_CHANGE,
            }
        )
    )
    major_outcome_event_types: frozenset[SceneEventType] = field(
        default_factory=lambda: frozenset(
            {
                SceneEventType.HEALTH_DANGER,
                SceneEventType.STUCK,
            }
        )
    )
    terminal_build_statuses: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "blocked",
                "cancelled",
                "complete",
                "completed",
                "done",
                "failed",
                "failure",
                "finished",
                "success",
                "succeeded",
            }
        )
    )


class SceneInbox:
    """Group bridge noise into deterministic, bounded Minecraft scenes."""

    def __init__(
        self,
        *,
        hearing: SpatialHearingAdapter | None = None,
        config: SceneInboxConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.hearing = hearing or SpatialHearingAdapter()
        self.config = config or SceneInboxConfig()
        self._event_bus = event_bus or default_event_bus
        self._scenes: OrderedDict[str, Scene] = OrderedDict()
        self._active_scenes: dict[tuple[str, str], str] = {}
        self._dedupe_seen: dict[str, tuple[int, str]] = {}
        self._event_buffers: dict[str, OrderedDict[str, SceneBufferEntry]] = {}
        self._closed_queue: list[ClosedScene] = []

    @property
    def scenes(self) -> Mapping[str, Scene]:
        return self._scenes

    def get_scene(self, scene_id: str) -> Scene | None:
        return self._scenes.get(scene_id)

    def detect_closures(self, now_ms: int) -> list[ClosedScene]:
        """Close scenes that reached a quiet window or meaningful outcome."""

        for scene_id, scene in list(self._scenes.items()):
            close_reason = self._closure_reason(scene, now_ms)
            if close_reason is None:
                continue
            self._close_scene(
                scene_id,
                close_reason=close_reason,
                closed_at_ms=max(now_ms, scene.last_event_at_ms),
            )
        return self.drain_closed_scenes()

    def drain_closed_scenes(self) -> list[ClosedScene]:
        """Return scenes forced closed by trim or prior closure detection."""

        closed = self._closed_queue
        self._closed_queue = []
        return closed

    async def ingest(
        self,
        raw_event: Mapping[str, Any],
        *,
        emit_update: bool = True,
    ) -> SceneUpdate:
        """Translate and group one raw Minecraft/bridge event."""

        event = self._to_scene_event(raw_event)
        if event is None:
            return SceneUpdate(
                scene_id=None,
                is_new_scene=False,
                participants_added=[],
                observers_added=[],
                suppression_reason="telemetry_only",
            )

        duplicate = self._dedupe(event)
        if duplicate is not None:
            return SceneUpdate(
                scene_id=duplicate,
                is_new_scene=False,
                participants_added=[],
                observers_added=[],
                suppression_reason="duplicate_event",
                event_id=event.event_id,
                event_type=event.type,
                scene=self._scenes.get(duplicate),
            )

        participants, observers, suppression_reason = self._classify_event(event)
        scene, is_new_scene, participants_added, observers_added = self._upsert_scene(
            event,
            participants,
            observers,
        )
        update = SceneUpdate(
            scene_id=scene.scene_id,
            is_new_scene=is_new_scene,
            participants_added=participants_added,
            observers_added=observers_added,
            suppression_reason=suppression_reason,
            event_id=event.event_id,
            event_type=event.type,
            scene=scene,
        )
        if emit_update:
            await self._emit_scene_update(event, scene, update)
        return update

    def _dedupe(self, event: SceneEvent) -> str | None:
        if event.type not in self.config.dedupe_event_types:
            return None
        previous = self._dedupe_seen.get(event.dedupe_key)
        if previous is not None:
            previous_ts, previous_scene_id = previous
            if event.timestamp_ms - previous_ts <= self.config.dedupe_window_ms:
                return previous_scene_id
        return None

    def _classify_event(self, event: SceneEvent) -> tuple[list[str], list[str], str | None]:
        if self._is_telemetry_only(event):
            observers = [
                agent_id
                for agent_id in self.hearing.agents_within(
                    event.origin,
                    event.dimension,
                    max(
                        self.hearing.config.observer_radius_blocks,
                        self.hearing.config.hearing_radius_for(event.type.value),
                    ),
                )
                if agent_id != event.source_agent_id
            ]
            return [], observers, "telemetry_only"

        required = set(event.direct_addressees)
        if event.source_agent_id:
            required.add(event.source_agent_id)
        participants, observers = self.hearing.classify_listeners(
            event.origin,
            event.dimension,
            direct_addressees=required,
            event_type=event.type.value,
        )

        hearing_radius = self.hearing.config.hearing_radius_for(event.type.value)
        automatic_candidates = (
            set(self.hearing.agents_within(event.origin, event.dimension, hearing_radius))
            - required
        )
        capped_candidates = automatic_candidates - set(participants)
        if capped_candidates:
            return participants, observers, "participant_cap"
        if not participants and observers:
            return participants, observers, "observer_only"
        return participants, observers, None

    def _upsert_scene(
        self,
        event: SceneEvent,
        participants: list[str],
        observers: list[str],
    ) -> tuple[Scene, bool, list[str], list[str]]:
        active_key = self._active_key(event)
        scene = None if self._forces_new_scene(event) else self._active_scene_for(active_key, event)

        if scene is None:
            scene = Scene(
                scene_id=self._scene_id(event),
                triggering_event_type=event.type,
                participants=participants,
                observers=[agent_id for agent_id in observers if agent_id not in participants],
                event_ids=[event.event_id],
                opened_at_ms=event.timestamp_ms,
                last_event_at_ms=event.timestamp_ms,
            )
            self._scenes[scene.scene_id] = scene
            self._active_scenes[active_key] = scene.scene_id
            self._remember_dedupe(event, scene.scene_id)
            self._append_scene_event(scene.scene_id, event)
            self._trim_recent_scenes()
            return scene, True, participants, scene.observers

        existing_participants = set(scene.participants)
        merged_participants = _merge_ordered(scene.participants, participants)
        merged_participant_set = set(merged_participants)
        merged_observers = [
            agent_id
            for agent_id in _merge_ordered(scene.observers, observers)
            if agent_id not in merged_participant_set
        ]
        participants_added = [
            agent_id for agent_id in merged_participants if agent_id not in existing_participants
        ]
        existing_observers = set(scene.observers)
        observers_added = [
            agent_id
            for agent_id in merged_observers
            if agent_id not in existing_observers and agent_id not in existing_participants
        ]
        updated = scene.model_copy(
            update={
                "participants": merged_participants,
                "observers": merged_observers,
                "event_ids": [*scene.event_ids, event.event_id],
                "last_event_at_ms": event.timestamp_ms,
            }
        )
        self._scenes[updated.scene_id] = updated
        self._active_scenes[active_key] = updated.scene_id
        self._remember_dedupe(event, updated.scene_id)
        self._append_scene_event(updated.scene_id, event)
        return updated, False, participants_added, observers_added

    def _active_scene_for(
        self,
        active_key: tuple[str, str],
        event: SceneEvent,
    ) -> Scene | None:
        scene_id = self._active_scenes.get(active_key)
        if scene_id is None:
            return None
        scene = self._scenes.get(scene_id)
        if scene is None:
            return None
        if event.timestamp_ms - scene.last_event_at_ms > self.config.scene_window_ms:
            return None
        return scene

    def _remember_dedupe(self, event: SceneEvent, scene_id: str) -> None:
        if event.type in self.config.dedupe_event_types:
            self._dedupe_seen[event.dedupe_key] = (event.timestamp_ms, scene_id)

    def _trim_recent_scenes(self) -> None:
        while len(self._scenes) > self.config.max_recent_scenes:
            scene_id = next(iter(self._scenes))
            self._close_scene(
                scene_id,
                close_reason="trimmed",
                closed_at_ms=self._scenes[scene_id].last_event_at_ms,
            )

    def _append_scene_event(self, scene_id: str, event: SceneEvent) -> None:
        buffer = self._event_buffers.setdefault(scene_id, OrderedDict())
        buffer[event.event_id] = SceneBufferEntry(
            event_id=event.event_id,
            event_type=event.type,
            category=_scene_event_category(event),
            source_agent_id=event.source_agent_id,
            timestamp_ms=event.timestamp_ms,
            text=_render_scene_event(event),
            payload=dict(event.payload),
        )

    def _close_scene(
        self,
        scene_id: str,
        *,
        close_reason: str,
        closed_at_ms: int,
    ) -> ClosedScene | None:
        scene = self._scenes.pop(scene_id, None)
        if scene is None:
            return None

        self._active_scenes = {
            key: active_scene_id
            for key, active_scene_id in self._active_scenes.items()
            if active_scene_id != scene_id
        }
        buffer = list(self._event_buffers.pop(scene_id, OrderedDict()).values())
        closed = ClosedScene(
            scene=scene,
            buffered_events=buffer,
            closed_at_ms=closed_at_ms,
            close_reason=close_reason,
        )
        self._closed_queue.append(closed)
        emit_director_timeline_event(
            "director.scene.closed",
            {
                "scene_id": scene.scene_id,
                "participants": scene.participants,
                "observers": scene.observers,
                "event_ids": scene.event_ids,
                "triggering_event_type": scene.triggering_event_type.value,
                "opened_at_ms": scene.opened_at_ms,
                "closed_at_ms": closed_at_ms,
                "close_reason": close_reason,
                "entries_count": len(buffer),
                "queue_depth": len(self._scenes),
            },
        )
        return closed

    def _closure_reason(self, scene: Scene, now_ms: int) -> str | None:
        latest_event = _latest_scene_event(self._event_buffers.get(scene.scene_id))
        if latest_event is not None:
            if latest_event.event_type in self.config.major_outcome_event_types:
                return f"{latest_event.event_type.value}_outcome"
            if latest_event.event_type == SceneEventType.BUILD_ACTION and _is_terminal_build(
                latest_event.payload,
                self.config.terminal_build_statuses,
            ):
                return "build_outcome"
        if now_ms - scene.last_event_at_ms >= self.config.scene_window_ms:
            return "time_window"
        return None

    def _scene_id(self, event: SceneEvent) -> str:
        window_start = (event.timestamp_ms // self.config.scene_window_ms) * (
            self.config.scene_window_ms
        )
        digest = hashlib.sha1(
            f"{event.dimension}|{self._group_key(event)}|{window_start}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:12]
        return f"mcscene-{window_start}-{digest}"

    def _active_key(self, event: SceneEvent) -> tuple[str, str]:
        return event.dimension, self._group_key(event)

    def _group_key(self, event: SceneEvent) -> str:
        if self._forces_new_scene(event):
            return f"urgent:{event.type.value}:{event.source_agent_id}:{event.event_id}"
        active_task = _first_text(
            event.payload,
            "active_task_id",
            "task_id",
            "build_id",
            "build_site_id",
            "site_id",
        )
        if active_task is not None:
            return f"task:{active_task}"
        return f"bucket:{self._coarse_bucket(event.origin)}"

    def _coarse_bucket(self, origin: Vec3) -> str:
        size = self.config.coarse_bucket_size_blocks
        return ":".join(
            str(math.floor(value / size))
            for value in (
                origin.x,
                origin.y,
                origin.z,
            )
        )

    def _forces_new_scene(self, event: SceneEvent) -> bool:
        return event.type == SceneEventType.HEALTH_DANGER

    def _is_telemetry_only(self, event: SceneEvent) -> bool:
        if event.type not in self.config.telemetry_only_event_types:
            return False
        return not bool(event.payload.get("milestone"))

    async def _emit_scene_update(
        self,
        event: SceneEvent,
        scene: Scene,
        update: SceneUpdate,
    ) -> None:
        await self._event_bus.emit(
            EventType.BRIDGE_SCENE_UPDATE,
            {
                "scene_id": scene.scene_id,
                "participants": scene.participants,
                "observers": scene.observers,
                "triggering_event_type": event.type.value,
                "event_id": event.event_id,
                "source_agent_id": event.source_agent_id,
                "participants_added": update.participants_added,
                "observers_added": update.observers_added,
                "suppression_reason": update.suppression_reason,
                "source_inbox_id": id(self),
                "source_event": event.model_dump(mode="json"),
            },
        )
        if update.is_new_scene:
            emit_director_timeline_event(
                "director.scene.opened",
                {
                    "scene_id": scene.scene_id,
                    "participants": scene.participants,
                    "observers": scene.observers,
                    "event_ids": scene.event_ids,
                    "triggering_event_type": event.type.value,
                    "source_agent": event.source_agent_id,
                    "opened_at_ms": scene.opened_at_ms,
                    "last_event_at_ms": scene.last_event_at_ms,
                    "suppression_reason": update.suppression_reason,
                    "queue_depth": len(self._scenes),
                },
                agent_id=event.source_agent_id,
            )

    def _to_scene_event(self, raw_event: Mapping[str, Any]) -> SceneEvent | None:
        envelope_type = _text(raw_event.get("event_type"))
        data = raw_event.get("data") if isinstance(raw_event.get("data"), Mapping) else raw_event
        if not isinstance(data, Mapping):
            return None

        if envelope_type == EventType.BRIDGE_PERCEPTION.value:
            return self._from_bridge_perception(data, raw_event)
        if envelope_type == EventType.BRIDGE_ACTION_RESULT.value:
            return self._from_bridge_action_result(data, raw_event)
        if envelope_type == EventType.AGENT_SPEAK.value:
            return self._from_explicit_event(data, raw_event, default_type=SceneEventType.CHAT)
        return self._from_explicit_event(data, raw_event)

    def _from_bridge_perception(
        self,
        data: Mapping[str, Any],
        raw_event: Mapping[str, Any],
    ) -> SceneEvent | None:
        source_agent_id = _canonical_agent_id(data.get("agent_id"))
        timestamp_ms = _timestamp_ms(raw_event, data)
        snapshot = data.get("snapshot")
        observations = data.get("observations", [])
        pose = _pose_from_snapshot(snapshot) or _pose_from_observations(observations)
        if pose is None:
            return None

        position, dimension = pose
        self.hearing.update_pose(
            source_agent_id,
            AgentPose(
                agent_id=source_agent_id,
                position=position,
                dimension=dimension,
                last_seen_ts=timestamp_ms,
            ),
        )
        event_type, payload = _perception_event_type(observations)
        direct_addressees = _direct_addressees(data, payload)
        return self._build_event(
            data,
            raw_event,
            event_type=event_type,
            source_agent_id=source_agent_id,
            origin=position,
            dimension=dimension,
            timestamp_ms=timestamp_ms,
            direct_addressees=direct_addressees,
            payload=payload,
        )

    def _from_bridge_action_result(
        self,
        data: Mapping[str, Any],
        raw_event: Mapping[str, Any],
    ) -> SceneEvent | None:
        source_agent_id = _canonical_agent_id(data.get("agent_id"))
        timestamp_ms = _timestamp_ms(raw_event, data)
        origin = _position_from_any(data.get("origin")) or _position_from_any(data.get("position"))
        dimension = _text(data.get("dimension"))
        pose = self.hearing.get_pose(source_agent_id)
        if origin is None and pose is not None:
            origin = pose.position
            dimension = dimension or pose.dimension
        if origin is None:
            return None

        payload = dict(data)
        event_type = _action_event_type(data)
        direct_addressees = _direct_addressees(data, payload)
        return self._build_event(
            data,
            raw_event,
            event_type=event_type,
            source_agent_id=source_agent_id,
            origin=origin,
            dimension=dimension or "overworld",
            timestamp_ms=timestamp_ms,
            direct_addressees=direct_addressees,
            payload=payload,
        )

    def _from_explicit_event(
        self,
        data: Mapping[str, Any],
        raw_event: Mapping[str, Any],
        *,
        default_type: SceneEventType | None = None,
    ) -> SceneEvent | None:
        event_type = (
            _scene_event_type(data.get("type"))
            or _scene_event_type(data.get("event_type"))
            or default_type
        )
        if event_type is None:
            return None

        source_agent_id = _canonical_agent_id(
            data.get("source_agent_id")
            or data.get("source")
            or data.get("agent_id")
            or data.get("speaker_id")
        )
        timestamp_ms = _timestamp_ms(raw_event, data)
        origin = (
            _position_from_any(data.get("origin"))
            or _position_from_any(data.get("position"))
            or _position_from_any(data.get("pose"))
        )
        dimension = _text(data.get("dimension"))
        pose = self.hearing.get_pose(source_agent_id)
        if origin is None and pose is not None:
            origin = pose.position
            dimension = dimension or pose.dimension
        if origin is None:
            return None

        payload = data.get("payload") if isinstance(data.get("payload"), Mapping) else {}
        payload = {**dict(payload), **_select_payload_fields(data)}
        direct_addressees = _direct_addressees(data, payload)
        return self._build_event(
            data,
            raw_event,
            event_type=event_type,
            source_agent_id=source_agent_id,
            origin=origin,
            dimension=dimension or "overworld",
            timestamp_ms=timestamp_ms,
            direct_addressees=direct_addressees,
            payload=payload,
        )

    def _build_event(
        self,
        data: Mapping[str, Any],
        raw_event: Mapping[str, Any],
        *,
        event_type: SceneEventType,
        source_agent_id: str,
        origin: Vec3,
        dimension: str,
        timestamp_ms: int,
        direct_addressees: set[str],
        payload: dict[str, Any],
    ) -> SceneEvent:
        payload = {**payload}
        if event_type == SceneEventType.CHAT and "milestone" not in payload:
            payload["milestone"] = True
        event_id = _event_id(data, raw_event, event_type, source_agent_id, timestamp_ms)
        dedupe_key = _text(data.get("dedupe_key")) or (
            f"{event_type.value}:{source_agent_id}:{dimension}:{self._coarse_bucket(origin)}:"
            f"{_first_text(payload, 'active_task_id', 'task_id', 'build_site_id') or ''}"
        )
        return SceneEvent(
            event_id=event_id,
            type=event_type,
            source_agent_id=source_agent_id,
            origin=origin,
            dimension=dimension,
            timestamp_ms=timestamp_ms,
            direct_addressees=direct_addressees,
            payload=payload,
            dedupe_key=dedupe_key,
        )


def register(bus: EventBus, inbox: SceneInbox | None = None) -> SceneInbox:
    """Subscribe an inbox to bridge reports and public speech events."""

    scene_inbox = inbox or SceneInbox(event_bus=bus)

    async def on_scene_source(event: dict[str, Any]) -> None:
        await scene_inbox.ingest(event)

    bus.on(EventType.BRIDGE_PERCEPTION, on_scene_source)
    bus.on(EventType.BRIDGE_ACTION_RESULT, on_scene_source)
    bus.on(EventType.AGENT_SPEAK, on_scene_source)
    return scene_inbox


def _latest_scene_event(
    buffer: OrderedDict[str, SceneBufferEntry] | None,
) -> SceneBufferEntry | None:
    if not buffer:
        return None
    return next(reversed(buffer.values()))


def _is_terminal_build(payload: Mapping[str, Any], terminal_statuses: frozenset[str]) -> bool:
    for field_name in ("status", "outcome", "outcome_class", "result", "phase", "state"):
        text = _text(payload.get(field_name))
        if text is not None and text.lower() in terminal_statuses:
            return True
    return False


def _scene_event_category(event: SceneEvent) -> str:
    if _is_help_request(event.payload):
        return "Help requests"
    if event.type == SceneEventType.CHAT:
        return "Chat"
    if event.type in {SceneEventType.BUILD_ACTION, SceneEventType.BLOCK_INTERACTION}:
        return "Build progress"
    if event.type == SceneEventType.TOOL_RESULT:
        return "Tool results"
    if event.type in {SceneEventType.STUCK, SceneEventType.UNSTUCK}:
        return "Stuck-Unstuck"
    if event.type == SceneEventType.HEALTH_DANGER:
        return "Health danger"
    if event.type in {SceneEventType.INVENTORY_CHANGE, SceneEventType.RESOURCE_CHANGE}:
        return "Inventory changes"
    return "Actions"


def _is_help_request(payload: Mapping[str, Any]) -> bool:
    text = _payload_text(payload, "message", "text", "utterance", "detail").lower()
    return bool(
        re.search(
            r"\b(help|assist|support|need a hand|can someone|could someone|please)\b",
            text,
        )
    )


def _render_scene_event(event: SceneEvent) -> str:
    payload = event.payload
    source = event.source_agent_id or "unknown"
    detail = _scene_event_detail(event.type, payload)
    if not detail:
        detail = _payload_excerpt(payload)
    return f"[{event.timestamp_ms}] {source}: {detail or event.type.value}"


def _scene_event_detail(event_type: SceneEventType, payload: Mapping[str, Any]) -> str:
    if event_type == SceneEventType.CHAT:
        return _payload_text(payload, "message", "text", "utterance", "dialogue", "content")
    if event_type in {SceneEventType.BUILD_ACTION, SceneEventType.BLOCK_INTERACTION}:
        return _field_summary(
            payload,
            "action_id",
            "action_type",
            "status",
            "outcome_class",
            "detail",
            "message",
        )
    if event_type == SceneEventType.TOOL_RESULT:
        return _field_summary(
            payload,
            "tool_name",
            "tool",
            "action_id",
            "status",
            "result",
            "detail",
            "message",
        )
    if event_type in {SceneEventType.STUCK, SceneEventType.UNSTUCK, SceneEventType.HEALTH_DANGER}:
        return _field_summary(payload, "status", "detail", "message", "reason", "blocker")
    if event_type in {SceneEventType.INVENTORY_CHANGE, SceneEventType.RESOURCE_CHANGE}:
        return _field_summary(payload, "item", "resource", "delta", "count", "detail", "message")
    return _field_summary(payload, "status", "detail", "message", "class")


def _field_summary(payload: Mapping[str, Any], *field_names: str) -> str:
    fields = []
    for field_name in field_names:
        value = _text(payload.get(field_name))
        if value is None:
            continue
        fields.append(f"{field_name}={value}")
    return "; ".join(fields)


def _payload_text(payload: Mapping[str, Any], *field_names: str) -> str:
    values = []
    for field_name in field_names:
        value = _text(payload.get(field_name))
        if value is not None:
            values.append(value)
    return " ".join(values)


def _payload_excerpt(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)[:600]
    except (TypeError, ValueError):
        return str(dict(payload))[:600]


def _canonical_agent_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _scene_event_type(value: Any) -> SceneEventType | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return SceneEventType(text)
    except ValueError:
        return None


def _position_from_any(value: Any) -> Vec3 | None:
    if isinstance(value, Vec3):
        return value
    if not isinstance(value, Mapping):
        return None
    if "position" in value and isinstance(value["position"], Mapping):
        return _position_from_any(value["position"])
    try:
        return Vec3.model_validate(value)
    except ValueError:
        return None


def _pose_from_snapshot(value: Any) -> tuple[Vec3, str] | None:
    if not isinstance(value, Mapping):
        return None
    pose = value.get("pose")
    if not isinstance(pose, Mapping):
        return None
    position = _position_from_any(pose.get("position"))
    dimension = _text(pose.get("dimension"))
    if position is None or dimension is None:
        return None
    return position, dimension


def _pose_from_observations(value: Any) -> tuple[Vec3, str] | None:
    if not isinstance(value, list):
        return None
    for observation in value:
        if not isinstance(observation, Mapping):
            continue
        snapshot_pose = _pose_from_snapshot(observation)
        if snapshot_pose is not None:
            return snapshot_pose
        if observation.get("type") != "pose":
            continue
        position = (
            _position_from_any(observation.get("after"))
            or _position_from_any(observation.get("position"))
            or _position_from_any(observation.get("origin"))
        )
        if position is None:
            continue
        return position, _text(observation.get("dimension")) or "overworld"
    return None


def _perception_event_type(observations: Any) -> tuple[SceneEventType, dict[str, Any]]:
    if not isinstance(observations, list):
        return SceneEventType.MOVEMENT_MILESTONE, {}
    payload: dict[str, Any] = {"observations": observations}
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        explicit_type = _scene_event_type(observation.get("scene_event_type"))
        if explicit_type is not None:
            payload.update(dict(observation))
            return explicit_type, payload
        obs_type = _text(observation.get("type"))
        if obs_type == "perception_snapshot":
            payload.update(dict(observation))
            return SceneEventType.MOVEMENT_MILESTONE, payload
        if obs_type == "pose":
            payload.update(dict(observation))
            reported_class = _text(observation.get("class")) or _text(observation.get("status"))
            payload["milestone"] = bool(
                observation.get("milestone")
                or reported_class in {"reached", "arrived", "milestone"}
            )
            return SceneEventType.MOVEMENT_MILESTONE, payload
        if obs_type in {"inventory", "inventory_change"}:
            payload.update(dict(observation))
            return SceneEventType.INVENTORY_CHANGE, payload
        if obs_type in {"resource", "resource_change"}:
            payload.update(dict(observation))
            return SceneEventType.RESOURCE_CHANGE, payload
        if obs_type in {"health", "danger", "health_danger"}:
            payload.update(dict(observation))
            return SceneEventType.HEALTH_DANGER, payload
        if obs_type == "stuck":
            payload.update(dict(observation))
            return SceneEventType.STUCK, payload
        if obs_type == "unstuck":
            payload.update(dict(observation))
            return SceneEventType.UNSTUCK, payload
        if obs_type in {"block", "block_interaction"}:
            payload.update(dict(observation))
            return SceneEventType.BLOCK_INTERACTION, payload
    return SceneEventType.MOVEMENT_MILESTONE, payload


def _action_event_type(data: Mapping[str, Any]) -> SceneEventType:
    explicit_type = _scene_event_type(data.get("scene_event_type") or data.get("type"))
    if explicit_type is not None:
        return explicit_type
    action_text = " ".join(
        str(value).lower()
        for value in (
            data.get("action_id"),
            data.get("action_type"),
            data.get("outcome_class"),
            data.get("detail"),
        )
        if value is not None
    )
    if "health" in action_text or "danger" in action_text or "damage" in action_text:
        return SceneEventType.HEALTH_DANGER
    if "unstuck" in action_text:
        return SceneEventType.UNSTUCK
    if "stuck" in action_text:
        return SceneEventType.STUCK
    if "build" in action_text:
        return SceneEventType.BUILD_ACTION
    if any(word in action_text for word in ("place", "break", "block", "dig")):
        return SceneEventType.BLOCK_INTERACTION
    if "inventory" in action_text:
        return SceneEventType.INVENTORY_CHANGE
    if "resource" in action_text or "gather" in action_text:
        return SceneEventType.RESOURCE_CHANGE
    return SceneEventType.TOOL_RESULT


def _direct_addressees(data: Mapping[str, Any], payload: Mapping[str, Any]) -> set[str]:
    addressees: set[str] = set()
    for source in (data, payload):
        raw = (
            source.get("direct_addressees")
            or source.get("addressees")
            or source.get("recipients")
            or source.get("addressed_agents")
        )
        addressees.update(_agent_id_set(raw))
        for field_name in (
            "to_agent_id",
            "target_agent_id",
            "addressed_agent_id",
            "recipient_agent_id",
        ):
            value = _text(source.get(field_name))
            if value is not None:
                addressees.add(_canonical_agent_id(value))
        for text_field in ("message", "text", "detail", "utterance"):
            text = _text(source.get(text_field))
            if text is not None:
                addressees.update(_mentions(text))
    return {agent_id for agent_id in addressees if agent_id}


def _agent_id_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {_canonical_agent_id(value)}
    if isinstance(value, list | tuple | set | frozenset):
        return {_canonical_agent_id(item) for item in value if _canonical_agent_id(item)}
    return set()


def _mentions(text: str) -> set[str]:
    return {_canonical_agent_id(match) for match in re.findall(r"@([A-Za-z][A-Za-z0-9_-]*)", text)}


def _timestamp_ms(raw_event: Mapping[str, Any], data: Mapping[str, Any]) -> int:
    for source in (data, raw_event):
        value = source.get("timestamp_ms")
        if isinstance(value, int | float):
            return int(value)
        timestamp = source.get("timestamp")
        if isinstance(timestamp, int | float):
            return int(timestamp * 1000 if timestamp < 10_000_000_000 else timestamp)
    return 0


def _event_id(
    data: Mapping[str, Any],
    raw_event: Mapping[str, Any],
    event_type: SceneEventType,
    source_agent_id: str,
    timestamp_ms: int,
) -> str:
    for source in (data, raw_event):
        for field_name in ("event_id", "request_id", "action_id", "id"):
            value = _text(source.get(field_name))
            if value is not None:
                return value
    return f"{event_type.value}:{source_agent_id}:{timestamp_ms}"


def _select_payload_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {
        "event_id",
        "type",
        "source_agent_id",
        "source",
        "agent_id",
        "speaker_id",
        "origin",
        "position",
        "pose",
        "dimension",
        "timestamp",
        "timestamp_ms",
        "direct_addressees",
        "addressees",
        "recipients",
        "addressed_agents",
        "dedupe_key",
    }
    return {str(key): value for key, value in data.items() if key not in excluded}


def _first_text(source: Mapping[str, Any], *field_names: str) -> str | None:
    for field_name in field_names:
        value = _text(source.get(field_name))
        if value is not None:
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    text = str(value).strip()
    return text or None


def _merge_ordered(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for agent_id in [*existing, *incoming]:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        merged.append(agent_id)
    return merged
