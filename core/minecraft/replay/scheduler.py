"""Replay event scheduler (issue #858).

Reads a sim folder's ``decision_log.jsonl`` (E22-2) and
``build_intents.jsonl`` (E22-5) and produces a deterministic, ordered
queue of replay events:

- :class:`ChatEvent` for utterance rows (route to ``!chat``)
- :class:`PoseEvent` for utterance rows that include a pose (route to a
  move command); pose data is optional and gracefully skipped if absent
- :class:`ExecuteBuildScriptEvent` for each ``propose_build`` tool intent
  (the CLI loads the compiled script from
  ``<sim-folder>/build_scripts/<intent_id>.script.json`` and feeds each
  ``BuildCommand`` to the bridge)
- :class:`ScreenshotEvent` for declared milestones, derived from the
  surrounding row context (build_start/build_complete, hourly tick,
  relationship-conflict, alliance-form)

Ordering is keyed by ``(sim_time, tick, row_idx)`` so the same sim folder
always produces the same event sequence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.minecraft.collaborative_build import (
    CollaborativeBuildJob,
    CollaborativeBuildLedger,
    ledger_path_for,
    load_collaborative_build_ledger,
)
from core.simulation.decision_logger import DecisionLogReader

ReplayMilestone = Literal[
    "build_start",
    "build_complete",
    "hourly",
    "conflict",
    "alliance_form",
]

REPLAY_MILESTONES: tuple[ReplayMilestone, ...] = (
    "build_start",
    "build_complete",
    "hourly",
    "conflict",
    "alliance_form",
)

# A relationship-delta is a "conflict" when sentiment drops by at least this
# much. Tuned by reading the deltas the relationship tracker emits today;
# can be raised later if the bar is too sensitive.
_CONFLICT_SENTIMENT_DROP = 0.10


@dataclass(frozen=True)
class _BaseEvent:
    sim_time: float
    tick: int
    row_idx: int


@dataclass(frozen=True)
class ChatEvent(_BaseEvent):
    actor_id: str
    text: str
    channel: str = "chat"


@dataclass(frozen=True)
class PoseEvent(_BaseEvent):
    actor_id: str
    position: dict[str, int]


@dataclass(frozen=True)
class ExecuteBuildScriptEvent(_BaseEvent):
    actor_id: str
    intent_id: str
    script_path: Path


@dataclass(frozen=True)
class ScreenshotEvent(_BaseEvent):
    milestone: ReplayMilestone
    label: str
    intent_id: str | None = None


ReplayEvent = ChatEvent | PoseEvent | ExecuteBuildScriptEvent | ScreenshotEvent


@dataclass
class _BuildIntentRow:
    intent_id: str
    actor_id: str
    submitted_at: float
    args: dict[str, Any]
    row_idx: int = 0


@dataclass
class ReplayScheduler:
    """Plan a deterministic event queue from a sim folder.

    Use :meth:`events` to iterate the ordered ``ReplayEvent`` queue. The
    scheduler is read-only — it never touches the Minecraft bridge.
    """

    sim_folder: Path
    enabled_milestones: tuple[ReplayMilestone, ...] = REPLAY_MILESTONES
    collaborative_builds: bool = False
    collaborative_step_seconds: float = 3.0
    intent_ids: frozenset[str] | None = None
    _events: list[ReplayEvent] = field(default_factory=list, init=False)
    _build_intent_rows: list[_BuildIntentRow] = field(default_factory=list, init=False)
    _build_scripts_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.sim_folder = Path(self.sim_folder)
        self._build_scripts_dir = self.sim_folder / "build_scripts"
        self.enabled_milestones = tuple(self.enabled_milestones)
        if self.intent_ids is not None:
            self.intent_ids = frozenset(str(intent_id) for intent_id in self.intent_ids)

    def events(self) -> list[ReplayEvent]:
        if self._events:
            return list(self._events)
        self._build_intent_rows = self._load_build_intents()
        rows = list(self._iter_decision_rows())
        events: list[ReplayEvent] = []
        intents_by_id = {row.intent_id: row for row in self._build_intent_rows}
        consumed_intent_ids: set[str] = set()
        last_hour_emitted: int | None = None

        for row_idx, row in rows:
            event_type = row.event_type
            sim_time = float(row.sim_time)
            tick = int(row.tick)

            if event_type == "utterance":
                events.append(
                    ChatEvent(
                        sim_time=sim_time,
                        tick=tick,
                        row_idx=row_idx,
                        actor_id=row.actor_id or "unknown",
                        text=row.payload.text,
                        channel=row.payload.channel,
                    )
                )
            elif event_type == "tool_intent" and row.payload.tool_name == "propose_build":
                intent_id = (
                    row.payload.args.get("intent_id")
                    if isinstance(row.payload.args, dict)
                    else None
                )
                if (
                    isinstance(intent_id, str)
                    and intent_id in intents_by_id
                    and self._intent_allowed(intent_id)
                ):
                    consumed_intent_ids.add(intent_id)
                    collaborative_events = self._collaborative_events_for(
                        intent_id=intent_id,
                        actor_id=row.actor_id or "unknown",
                        sim_time=sim_time,
                        tick=tick,
                        row_idx=row_idx,
                    )
                    if collaborative_events:
                        events.extend(collaborative_events)
                    else:
                        script_path = self._script_path_for(intent_id)
                        events.append(
                            ExecuteBuildScriptEvent(
                                sim_time=sim_time,
                                tick=tick,
                                row_idx=row_idx,
                                actor_id=row.actor_id or "unknown",
                                intent_id=intent_id,
                                script_path=script_path,
                            )
                        )
                        if "build_start" in self.enabled_milestones:
                            events.append(
                                ScreenshotEvent(
                                    sim_time=sim_time,
                                    tick=tick,
                                    row_idx=row_idx,
                                    milestone="build_start",
                                    label=f"build_start_{intent_id}",
                                    intent_id=intent_id,
                                )
                            )
                        if "build_complete" in self.enabled_milestones:
                            events.append(
                                ScreenshotEvent(
                                    sim_time=sim_time,
                                    tick=tick,
                                    row_idx=row_idx + 1,
                                    milestone="build_complete",
                                    label=f"build_complete_{intent_id}",
                                    intent_id=intent_id,
                                )
                            )
            elif event_type == "relationship_delta" and "conflict" in self.enabled_milestones:
                before = row.payload.before or {}
                after = row.payload.after or {}
                before_sentiment = _coerce_float(before.get("sentiment"))
                after_sentiment = _coerce_float(after.get("sentiment"))
                if (
                    before_sentiment is not None
                    and after_sentiment is not None
                    and (before_sentiment - after_sentiment) >= _CONFLICT_SENTIMENT_DROP
                ):
                    events.append(
                        ScreenshotEvent(
                            sim_time=sim_time,
                            tick=tick,
                            row_idx=row_idx,
                            milestone="conflict",
                            label=f"conflict_{row.payload.a}_{row.payload.b}",
                        )
                    )
            elif event_type == "alliance_delta" and "alliance_form" in self.enabled_milestones:
                before_members = (
                    row.payload.before.get("members")
                    if isinstance(row.payload.before, dict)
                    else None
                )
                after_members = row.payload.members or []
                before_count = (
                    len(before_members) if isinstance(before_members, (list, tuple)) else 0
                )
                if before_count == 0 and len(after_members) > 0:
                    events.append(
                        ScreenshotEvent(
                            sim_time=sim_time,
                            tick=tick,
                            row_idx=row_idx,
                            milestone="alliance_form",
                            label=f"alliance_form_{row.payload.alliance_id}",
                        )
                    )

            if "hourly" in self.enabled_milestones:
                current_hour = int(sim_time // 3600)
                if last_hour_emitted is None or current_hour > last_hour_emitted:
                    if last_hour_emitted is not None:
                        events.append(
                            ScreenshotEvent(
                                sim_time=float(current_hour * 3600),
                                tick=tick,
                                row_idx=row_idx,
                                milestone="hourly",
                                label=f"hourly_{current_hour:04d}",
                            )
                        )
                    last_hour_emitted = current_hour

        # Any build intents that never produced a tool_intent row in the
        # decision log are still executed in order — they're equally part
        # of the recorded sim.
        for row in self._build_intent_rows:
            if row.intent_id in consumed_intent_ids:
                continue
            if not self._intent_allowed(row.intent_id):
                continue
            events.append(
                ExecuteBuildScriptEvent(
                    sim_time=row.submitted_at,
                    tick=0,
                    row_idx=row.row_idx,
                    actor_id=row.actor_id,
                    intent_id=row.intent_id,
                    script_path=self._script_path_for(row.intent_id),
                )
            )

        events.sort(key=_event_sort_key)
        self._events = events
        return list(events)

    # ─── helpers ───────────────────────────────────────────────

    def _script_path_for(self, intent_id: str) -> Path:
        return self._build_scripts_dir / f"{intent_id}.script.json"

    def _intent_allowed(self, intent_id: str) -> bool:
        return self.intent_ids is None or intent_id in self.intent_ids

    def _collaborative_events_for(
        self,
        *,
        intent_id: str,
        actor_id: str,
        sim_time: float,
        tick: int,
        row_idx: int,
    ) -> list[ReplayEvent]:
        if not self.collaborative_builds:
            return []
        ledger_path = ledger_path_for(self.sim_folder, intent_id)
        if not ledger_path.is_file():
            return []
        ledger = load_collaborative_build_ledger(ledger_path)
        events: list[ReplayEvent] = []
        step = max(0.0, float(self.collaborative_step_seconds))
        base_row_idx = row_idx * 1000
        for offset, job in enumerate(ledger.jobs):
            job_time = sim_time + (offset * step)
            job_row_idx = base_row_idx + offset
            events.append(
                ChatEvent(
                    sim_time=job_time,
                    tick=tick,
                    row_idx=job_row_idx,
                    actor_id=job.owner_agent_id,
                    text=_collaborative_chat_for_job(ledger, job),
                )
            )
            if job.role != "builder" or not job.script_path:
                continue
            script_path = self.sim_folder / job.script_path
            if "build_start" in self.enabled_milestones:
                events.append(
                    ScreenshotEvent(
                        sim_time=job_time,
                        tick=tick,
                        row_idx=job_row_idx,
                        milestone="build_start",
                        label=f"collab_build_start_{job.job_id}",
                        intent_id=job.job_id,
                    )
                )
            events.append(
                ExecuteBuildScriptEvent(
                    sim_time=job_time,
                    tick=tick,
                    row_idx=job_row_idx,
                    actor_id=job.owner_agent_id or actor_id,
                    intent_id=job.job_id,
                    script_path=script_path,
                )
            )
            if "build_complete" in self.enabled_milestones:
                events.append(
                    ScreenshotEvent(
                        sim_time=job_time,
                        tick=tick,
                        row_idx=job_row_idx + 1,
                        milestone="build_complete",
                        label=f"collab_build_complete_{job.job_id}",
                        intent_id=job.job_id,
                    )
                )
        return events

    def _iter_decision_rows(self):
        log_path = self.sim_folder / "decision_log.jsonl"
        if not log_path.is_file():
            return
        reader = DecisionLogReader(self.sim_folder)
        yield from enumerate(reader.replay())

    def _load_build_intents(self) -> list[_BuildIntentRow]:
        path = self.sim_folder / "build_intents.jsonl"
        if not path.is_file():
            return []
        rows: list[_BuildIntentRow] = []
        for row_idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
            stripped = raw.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            rows.append(
                _BuildIntentRow(
                    intent_id=str(payload.get("intent_id") or ""),
                    actor_id=str(payload.get("actor_id") or "unknown"),
                    submitted_at=float(payload.get("submitted_at") or 0.0),
                    args=dict(payload.get("args") or {}),
                    row_idx=row_idx,
                )
            )
        return rows


def _event_sort_key(event: ReplayEvent) -> tuple[float, int, int, int]:
    # Stable ordering: sim_time, tick, row_idx, then a per-event-type
    # priority so a build_start screenshot precedes its
    # execute_build_script event when they share a row_idx.
    priority = {
        ScreenshotEvent: 0,
        PoseEvent: 1,
        ChatEvent: 2,
        ExecuteBuildScriptEvent: 3,
    }[type(event)]
    return (event.sim_time, event.tick, event.row_idx, priority)


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _collaborative_chat_for_job(
    ledger: CollaborativeBuildLedger,
    job: CollaborativeBuildJob,
) -> str:
    if job.role == "manager":
        return (
            f"I am managing {ledger.source_intent_id}: {len(ledger.jobs)} jobs, "
            f"{ledger.total_source_commands} build commands, with dependencies assigned."
        )
    if job.role == "resource_gatherer":
        return f"Resource job {job.job_id}: staging {_materials_text(job.materials)}."
    if job.role == "crafter":
        return f"Crafting job {job.job_id}: preparing {_materials_text(job.materials)}."
    if job.role == "builder":
        return (
            f"Builder job {job.job_id}: {job.title.lower()}, "
            f"{job.command_count} commands and {job.total_blocks} blocks."
        )
    if job.role == "inspector":
        return (
            f"Inspection job {job.job_id}: checking dimensions, materials, gates, "
            "and recognizable completion."
        )
    return f"Collaborative job {job.job_id}: {job.title}."


def _materials_text(materials: dict[str, int]) -> str:
    if not materials:
        return "no block materials"
    chunks = [f"{count} {material}" for material, count in sorted(materials.items())[:4]]
    extra = len(materials) - len(chunks)
    if extra > 0:
        chunks.append(f"{extra} more material types")
    return ", ".join(chunks)
