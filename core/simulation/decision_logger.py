"""Decision-log writer + reader (issue #852).

The decision log is a JSONL file at ``<sim-folder>/decision_log.jsonl`` that
records every meaningful event in a simulation tick — utterances, tool
intents (both executed and blocked-by-policy), relationship/alliance
mutations, dreams, new goals, blackboard mutations, world events, and needs
state. Replay tools and eval scorers consume this file via
:class:`DecisionLogReader`.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from core.simulation.decision_log_schema import (
    SCHEMA_VERSION,
    AllianceDeltaPayload,
    AllianceDeltaRow,
    BlackboardMutationPayload,
    BlackboardMutationRow,
    DecisionLogRow,
    DreamPayload,
    DreamRow,
    MotivationLink,
    NeedsStatePayload,
    NeedsStateRow,
    NewGoalPayload,
    NewGoalRow,
    RelationshipDeltaPayload,
    RelationshipDeltaRow,
    ToolIntentPayload,
    ToolIntentRow,
    UtterancePayload,
    UtteranceRow,
    WorldEventPayload,
    WorldEventRow,
)

logger = logging.getLogger(__name__)

_DECISION_LOG_FILENAME = "decision_log.jsonl"

_ROW_ADAPTER: TypeAdapter[DecisionLogRow] = TypeAdapter(DecisionLogRow)


class DecisionLogger:
    """Append-only JSONL writer for the decision log."""

    def __init__(
        self,
        sim_folder: str | Path,
        *,
        fsync_per_tick: bool = False,
    ) -> None:
        self._sim_folder = Path(sim_folder)
        self._sim_folder.mkdir(parents=True, exist_ok=True)
        self._path = self._sim_folder / _DECISION_LOG_FILENAME
        self._file: io.TextIOBase | None = self._path.open("a", encoding="utf-8")
        self._fsync_per_tick = fsync_per_tick
        self._tick = 0
        self._started_at = datetime.now(UTC)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def tick(self) -> int:
        return self._tick

    def advance_tick(self) -> int:
        self._tick += 1
        return self._tick

    # ─── Public log API ────────────────────────────────────────────────

    def log_utterance(
        self,
        *,
        actor_id: str,
        text: str,
        channel: str = "chat",
        model: str | None = None,
        runtime_model: str | None = None,
        tokens: int | None = None,
        cost: str | None = None,
        sim_time: float = 0.0,
        motivation_chain: list[MotivationLink] | None = None,
    ) -> None:
        self._write(
            UtteranceRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=actor_id,
                motivation_chain=motivation_chain,
                payload=UtterancePayload(
                    text=text,
                    channel=channel,
                    model=model,
                    runtime_model=runtime_model,
                    tokens=tokens,
                    cost=cost,
                ),
            )
        )

    def log_tool_intent(
        self,
        *,
        actor_id: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
        status: str,
        block_reason: str | None = None,
        outcome: Any | None = None,
        sim_time: float = 0.0,
        motivation_chain: list[MotivationLink] | None = None,
    ) -> None:
        self._write(
            ToolIntentRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=actor_id,
                motivation_chain=motivation_chain,
                payload=ToolIntentPayload(
                    tool_name=tool_name,
                    args=args or {},
                    status=status,  # type: ignore[arg-type]
                    block_reason=block_reason,
                    outcome=outcome,
                ),
            )
        )

    def log_relationship_delta(
        self,
        *,
        a: str,
        b: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            RelationshipDeltaRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=a,
                payload=RelationshipDeltaPayload(
                    a=a, b=b, before=before, after=after, reason=reason
                ),
            )
        )

    def log_alliance_delta(
        self,
        *,
        alliance_id: str,
        members: list[str],
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            AllianceDeltaRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=None,
                payload=AllianceDeltaPayload(
                    alliance_id=alliance_id,
                    members=members,
                    before=before,
                    after=after,
                    reason=reason,
                ),
            )
        )

    def log_dream(
        self,
        *,
        actor_id: str,
        dream_narrative: str,
        insights: list[str] | None = None,
        new_goals: list[dict[str, Any]] | None = None,
        mood_shift: str | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            DreamRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=actor_id,
                payload=DreamPayload(
                    dream_narrative=dream_narrative,
                    insights=insights or [],
                    new_goals=new_goals or [],
                    mood_shift=mood_shift,
                ),
            )
        )

    def log_new_goal(
        self,
        *,
        actor_id: str,
        description: str,
        goal_id: str | None = None,
        category: str | None = None,
        priority: int | None = None,
        source: str | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            NewGoalRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=actor_id,
                payload=NewGoalPayload(
                    goal_id=goal_id,
                    description=description,
                    category=category,
                    priority=priority,
                    source=source,
                ),
            )
        )

    def log_blackboard_mutation(
        self,
        *,
        key: str,
        before: Any | None,
        after: Any | None,
        source: str | None = None,
        actor_id: str | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            BlackboardMutationRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=actor_id,
                payload=BlackboardMutationPayload(
                    key=key, before=before, after=after, source=source
                ),
            )
        )

    def log_world_event(
        self,
        *,
        event_type: str,
        trigger: str | None = None,
        severity: str | None = None,
        details: dict[str, Any] | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            WorldEventRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=None,
                payload=WorldEventPayload(
                    event_type=event_type,
                    trigger=trigger,
                    severity=severity,
                    details=details or {},
                ),
            )
        )

    def log_needs_state(
        self,
        *,
        actor_id: str,
        hunger: float | None = None,
        sleep: float | None = None,
        energy: float | None = None,
        other: dict[str, float] | None = None,
        sim_time: float = 0.0,
    ) -> None:
        self._write(
            NeedsStateRow(
                tick=self.advance_tick(),
                wall_time=datetime.now(UTC),
                sim_time=sim_time,
                actor_id=actor_id,
                payload=NeedsStatePayload(
                    hunger=hunger,
                    sleep=sleep,
                    energy=energy,
                    other=other or {},
                ),
            )
        )

    # ─── Lifecycle ─────────────────────────────────────────────────────

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
            finally:
                self._file.close()
                self._file = None

    def __enter__(self) -> DecisionLogger:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ─── Internal write ────────────────────────────────────────────────

    def _write(self, row: Any) -> None:
        if self._file is None:
            raise RuntimeError("DecisionLogger is closed; cannot write more rows")
        line = row.model_dump_json() + "\n"
        self._file.write(line)
        if self._fsync_per_tick:
            self._file.flush()


class DecisionLogReader:
    """Streaming reader that yields validated rows in order."""

    def __init__(
        self, sim_folder: str | Path, *, expected_schema_version: int = SCHEMA_VERSION
    ) -> None:
        self._sim_folder = Path(sim_folder)
        self._path = self._sim_folder / _DECISION_LOG_FILENAME
        if not self._path.is_file():
            raise FileNotFoundError(f"decision log not found: {self._path}")
        self._expected_schema_version = expected_schema_version

    @property
    def path(self) -> Path:
        return self._path

    def replay(self) -> Iterator[DecisionLogRow]:
        """Yield each row in file order, validating against the schema."""
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"decision log line {line_no}: invalid JSON: {exc}") from exc
                row_version = data.get("schema_version")
                if row_version != self._expected_schema_version:
                    raise ValueError(
                        f"decision log line {line_no}: schema_version {row_version!r} "
                        f"does not match expected {self._expected_schema_version}. "
                        "Migrate the log or pass a higher expected_schema_version."
                    )
                try:
                    row = _ROW_ADAPTER.validate_python(data)
                except ValidationError as exc:
                    raise ValueError(f"decision log line {line_no}: schema error: {exc}") from exc
                yield row


__all__ = [
    "DecisionLogReader",
    "DecisionLogger",
]
