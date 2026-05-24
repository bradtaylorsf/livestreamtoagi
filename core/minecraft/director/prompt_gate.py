"""Director V2 prompt gate for Mindcraft conversation prompts."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from collections import OrderedDict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.bridge.contract import Vec3
from core.minecraft.director.build_macro_scheduler import (
    BuildMacroAssignment,
    BuildMacroScheduler,
    SettlementObjectiveContext,
)
from core.minecraft.director.scene_inbox import Scene, SceneEventType, SceneInbox
from core.minecraft.director.spatial_hearing import (
    AgentPose,
    SpatialHearingAdapter,
    SpatialHearingConfig,
)
from core.minecraft.director.timeline import emit_director_timeline_event
from core.minecraft.director.turn_scheduler import (
    DirectorTurnScheduler,
    SchedulerCandidate,
    SchedulerConfig,
    SchedulerDecision,
    SchedulerTurn,
)

logger = logging.getLogger(__name__)

TurnKind = Literal["speaker", "planner"]
GateEventKind = Literal["chat", "action_result", "perception_event"]

_DECISION_TTL_MS = 30_000
_MAX_CACHED_DECISIONS = 256
_DEFAULT_SIM_AGENT_IDS = ("alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok")
_DEFAULT_MAX_SELECTED_AGENT_SCENE_RATIO = 0.5


class PromptDecision(BaseModel):
    """Prompt verdict returned to the Mindcraft bridge gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected: bool
    turn_kind: TurnKind | None
    reason: str
    suppression_reason: str | None
    scene_id: str
    scene_digest: str
    role: str
    local_observations: dict[str, Any] = Field(default_factory=dict)
    available_tools: list[str] = Field(default_factory=list)
    build_macro: BuildMacroAssignment | None = None
    suppressed_agents: list[str] = Field(default_factory=list)
    queue_depth: int = Field(ge=0)


@dataclass
class _AgentState:
    agent_id: str
    role: str
    chattiness: float = 0.5
    position: Vec3 | None = None
    dimension: str = "overworld"
    last_seen_ms: int = 0
    last_prompt_ms: int | None = None
    last_prompt_turn: int | None = None
    selected_turn_count: int = 0


@dataclass
class _CachedVerdict:
    event_key: str
    event_kind: GateEventKind
    event_text: str
    source_agent: str
    scene_hint: str | None
    scene: Scene
    scheduler_decision: SchedulerDecision
    selected_turns: dict[str, SchedulerTurn]
    available_tools: list[str]
    build_macros: dict[str, BuildMacroAssignment]
    active_objective: SettlementObjectiveContext | None
    provider: str | None
    model: str | None
    estimated_usd: float | None
    trace_id: str | None
    created_ms: int
    accounted_selected: set[str] = field(default_factory=set)


@dataclass
class _GateState:
    inbox: SceneInbox
    scheduler: DirectorTurnScheduler
    build_scheduler: BuildMacroScheduler = field(default_factory=BuildMacroScheduler)
    agents: dict[str, _AgentState] = field(default_factory=dict)
    recent_speakers: deque[str] = field(default_factory=lambda: deque(maxlen=16))
    decisions: OrderedDict[str, _CachedVerdict] = field(default_factory=OrderedDict)
    scene_selected_agents: dict[str, set[str]] = field(default_factory=dict)
    event_sequence: int = 0
    turn_sequence: int = 0
    total_selected_turns: int = 0
    plan_mode_build_completed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DirectorPromptGate:
    """Evaluate Mindcraft prompt eligibility through Director V2 scheduling."""

    def __init__(
        self,
        *,
        scheduler_config: SchedulerConfig | None = None,
        hearing_config: SpatialHearingConfig | None = None,
    ) -> None:
        hearing = SpatialHearingAdapter(
            hearing_config or SpatialHearingConfig(max_participants_per_scene=16)
        )
        self._state = _GateState(
            inbox=SceneInbox(hearing=hearing),
            scheduler=DirectorTurnScheduler(scheduler_config),
        )

    def register_agent(
        self,
        agent_id: str,
        *,
        role: str | None = None,
        chattiness: float = 0.5,
        position: Vec3 | Mapping[str, Any] | None = None,
        dimension: str = "overworld",
        timestamp_ms: int | None = None,
    ) -> None:
        """Register or refresh a known scene agent for scheduler candidates."""

        canonical = _canonical_agent_id(agent_id)
        if not canonical:
            return
        now_ms = timestamp_ms if timestamp_ms is not None else _now_ms()
        parsed_position = _vec3(position)
        state = self._state
        previous = state.agents.get(canonical)
        state.agents[canonical] = _AgentState(
            agent_id=canonical,
            role=role or (previous.role if previous else _default_role(canonical)),
            chattiness=max(0.0, min(chattiness, 1.0)),
            position=parsed_position
            if parsed_position is not None
            else previous.position
            if previous
            else None,
            dimension=dimension or (previous.dimension if previous else "overworld"),
            last_seen_ms=now_ms,
            last_prompt_ms=previous.last_prompt_ms if previous else None,
            last_prompt_turn=previous.last_prompt_turn if previous else None,
            selected_turn_count=previous.selected_turn_count if previous else 0,
        )
        agent = state.agents[canonical]
        if agent.position is not None:
            state.inbox.hearing.update_pose(
                canonical,
                AgentPose(
                    agent_id=canonical,
                    position=agent.position,
                    dimension=agent.dimension,
                    last_seen_ts=agent.last_seen_ms,
                ),
            )

    async def evaluate(
        self,
        simulation_id: str,
        agent_id: str,
        event: Mapping[str, Any],
    ) -> PromptDecision:
        """Return whether one bot may enter the Mindcraft prompt path."""

        del simulation_id
        canonical_agent = _canonical_agent_id(agent_id)
        now_ms = _now_ms()
        async with self._state.lock:
            self._purge_decisions(now_ms)
            self._register_sim_agents(now_ms)
            self.register_agent(
                canonical_agent,
                position=event.get("position"),
                timestamp_ms=now_ms,
            )
            event_key = _event_key(event)
            cached = self._state.decisions.get(event_key)
            if cached is None:
                cached = await self._build_verdict(event_key, canonical_agent, event, now_ms)
                self._state.decisions[event_key] = cached
                while len(self._state.decisions) > _MAX_CACHED_DECISIONS:
                    self._state.decisions.popitem(last=False)
            else:
                self._state.decisions.move_to_end(event_key)
            return self._decision_for_agent(canonical_agent, cached, now_ms)

    async def _build_verdict(
        self,
        event_key: str,
        calling_agent: str,
        event: Mapping[str, Any],
        now_ms: int,
    ) -> _CachedVerdict:
        state = self._state
        state.event_sequence += 1
        event_kind = _event_kind(event.get("event_kind"))
        event_type = _scene_event_type(event_kind, event.get("event_text"))
        source_agent = _canonical_agent_id(event.get("source_agent")) or calling_agent
        origin = _event_origin(state, source_agent, calling_agent, event)
        scene_hint = _text(event.get("scene_hint"))
        event_text = _text(event.get("event_text")) or ""
        available_tools = _tool_list(event.get("available_tools"))
        active_objective = _settlement_objective_context(event)
        raw_event = {
            "event_id": f"director-gate-{event_key[:16]}",
            "type": event_type.value,
            "source_agent_id": source_agent,
            "origin": origin.model_dump(),
            "dimension": _dimension_for(state, source_agent, calling_agent),
            "timestamp_ms": now_ms,
            "direct_addressees": _agent_list(event.get("mentions")),
            "dedupe_key": event_key,
            "payload": {
                "message": event_text,
                "scene_hint": scene_hint,
                "available_tools": available_tools,
                "active_objective": active_objective.model_dump()
                if active_objective is not None
                else None,
            },
        }
        update = await state.inbox.ingest(raw_event)
        scene = update.scene or _fallback_scene(
            event_key=event_key,
            event_type=event_type,
            agent_ids=state.agents.keys() or [calling_agent],
            now_ms=now_ms,
        )
        candidates = self._build_candidates(
            scene,
            event_text=event_text,
            direct_addressees=_agent_list(event.get("mentions")),
            event_type=event_type,
            now_ms=now_ms,
            broadcast_to_all=source_agent == "system",
        )
        seed = _stable_seed(scene.scene_id, state.event_sequence)
        if _is_successful_build_plan_status_notice(event_text.lower()):
            state.plan_mode_build_completed = True
        if _should_quiesce_after_plan_build(state, event_type):
            scheduler_decision = _suppressed_scheduler_decision(
                scene=scene,
                candidates=candidates,
                seed=seed,
                reason="plan_mode_build_completed",
            )
        else:
            scheduler_decision = state.scheduler.select(
                scene=scene,
                candidates=candidates,
                scene_event_type=event_type,
                recent_speakers=list(state.recent_speakers),
                seed=seed,
            )
        scheduler_decision = _apply_explicit_build_owner(
            scheduler_decision,
            candidates=candidates,
            event_text=event_text,
            scene_event_type=event_type,
        )
        scheduler_decision = _apply_settlement_phase_owner(
            state.build_scheduler,
            scheduler_decision,
            active_objective=active_objective,
            candidates=candidates,
            scene_event_type=event_type,
            now_ms=now_ms,
        )
        scheduler_decision = self._limit_scene_selected_agents(
            scene=scene,
            scheduler_decision=scheduler_decision,
            candidates=candidates,
        )
        build_macros = self._build_macro_assignments(
            scene=scene,
            scheduler_decision=scheduler_decision,
            candidates=candidates,
            event_text=event_text,
            origin=origin,
            available_tools=available_tools,
            active_objective=active_objective,
            now_ms=now_ms,
        )
        return _CachedVerdict(
            event_key=event_key,
            event_kind=event_kind,
            event_text=event_text,
            source_agent=source_agent,
            scene_hint=scene_hint,
            scene=scene,
            scheduler_decision=scheduler_decision,
            selected_turns={turn.agent_id: turn for turn in scheduler_decision.selected},
            available_tools=available_tools,
            build_macros=build_macros,
            active_objective=active_objective,
            provider=_text(event.get("provider")),
            model=_text(event.get("model")),
            estimated_usd=_float_or_none(event.get("estimated_usd")),
            trace_id=_text(event.get("trace_id") or event.get("traceId")),
            created_ms=now_ms,
        )

    def _build_candidates(
        self,
        scene: Scene,
        *,
        event_text: str,
        direct_addressees: Sequence[str],
        event_type: SceneEventType,
        now_ms: int,
        broadcast_to_all: bool = False,
    ) -> list[SchedulerCandidate]:
        direct = set(direct_addressees)
        participants = set(scene.participants)
        observers = set(scene.observers)
        candidates: list[SchedulerCandidate] = []
        for agent in sorted(self._state.agents.values(), key=lambda item: item.agent_id):
            seconds_since_spoke = (
                300.0
                if agent.last_prompt_ms is None
                else max(0.0, (now_ms - agent.last_prompt_ms) / 1000.0)
            )
            turns_since_spoke = (
                1
                if agent.last_prompt_turn is None
                else max(0, self._state.turn_sequence - agent.last_prompt_turn)
            )
            agent_name_hit = agent.agent_id in event_text.lower()
            role_fit = _role_fit(agent.role, event_type)
            is_participant = agent.agent_id in participants or broadcast_to_all
            candidates.append(
                SchedulerCandidate(
                    agent_id=agent.agent_id,
                    is_participant=is_participant,
                    is_observer=agent.agent_id in observers,
                    chattiness=agent.chattiness,
                    role=agent.role,
                    topic_relevance=0.8 if agent.agent_id in direct or agent_name_hit else 0.35,
                    seconds_since_spoke=seconds_since_spoke,
                    turns_since_spoke=turns_since_spoke,
                    recent_turn_count=list(self._state.recent_speakers).count(agent.agent_id),
                    selection_count=agent.selected_turn_count,
                    total_selection_count=self._state.total_selected_turns,
                    has_open_commitment=False,
                    active_task_match=_active_task_match(agent.role, event_type, event_text),
                    is_directly_addressed=agent.agent_id in direct,
                    is_in_danger=event_type == SceneEventType.HEALTH_DANGER,
                    is_stuck=event_type == SceneEventType.STUCK,
                    role_fit=role_fit,
                )
            )
        return candidates

    def _register_sim_agents(self, now_ms: int) -> None:
        for agent_id in _configured_agent_ids():
            self.register_agent(agent_id, timestamp_ms=now_ms)

    def _build_macro_assignments(
        self,
        *,
        scene: Scene,
        scheduler_decision: SchedulerDecision,
        candidates: Sequence[SchedulerCandidate],
        event_text: str,
        origin: Vec3,
        available_tools: Sequence[str],
        active_objective: SettlementObjectiveContext | None,
        now_ms: int,
    ) -> dict[str, BuildMacroAssignment]:
        if _is_plan_mode_single_build_closed(self._state):
            return {}
        if not _is_build_macro_intent(event_text, available_tools):
            return {}
        selected = scheduler_decision.selected
        owner = scheduler_decision.selected_planner_agent_id
        if owner is None and selected:
            owner = selected[0].agent_id
        if owner is None:
            return {}

        acquisition = self._state.build_scheduler.try_acquire_plan(
            scene_id=scene.scene_id,
            agent_id=owner,
            description=_build_macro_description(event_text),
            origin=origin.model_dump(),
            scene=scene,
            candidates=candidates,
            active_objective=active_objective,
            now_ms=now_ms,
        )
        assignments = dict(acquisition.support_assignments)
        assignments[owner] = BuildMacroAssignment(
            scene_id=acquisition.scene_id,
            plan_id=acquisition.plan_id,
            owner=acquisition.owner,
            role="planner_owner",
            reason=acquisition.reason,
            granted=acquisition.granted,
            status=acquisition.status,
            cache_key=acquisition.cache_key,
            objective_id=acquisition.objective_id,
            phase_index=acquisition.phase_index,
            phase_owner=acquisition.phase_owner,
        )
        return assignments

    def _decision_for_agent(
        self,
        agent_id: str,
        cached: _CachedVerdict,
        now_ms: int,
    ) -> PromptDecision:
        selected_turn = cached.selected_turns.get(agent_id)
        selected = selected_turn is not None
        selected_ids = set(cached.selected_turns)
        known_agents = set(self._state.agents)
        suppressed_agents = sorted(known_agents - selected_ids)
        if not selected and agent_id not in suppressed_agents:
            suppressed_agents.append(agent_id)
            suppressed_agents.sort()

        role = self._state.agents.get(agent_id, _AgentState(agent_id, _default_role(agent_id))).role
        suppression_reason = None
        reason = "selected"
        turn_kind: TurnKind | None = None
        if selected_turn is not None:
            reason = selected_turn.reason
            turn_kind = selected_turn.kind
            if agent_id not in cached.accounted_selected:
                cached.accounted_selected.add(agent_id)
                self._state.turn_sequence += 1
                agent = self._state.agents.get(agent_id)
                if agent is not None:
                    agent.last_prompt_ms = now_ms
                    agent.last_prompt_turn = self._state.turn_sequence
                    agent.selected_turn_count += 1
                    self._state.total_selected_turns += 1
                self._state.recent_speakers.append(agent_id)
                self._state.scene_selected_agents.setdefault(cached.scene.scene_id, set()).add(
                    agent_id
                )
        else:
            reason = "suppressed"
            suppression_reason = cached.scheduler_decision.suppression_reason or "fanout_capped"

        queue_depth = (
            0
            if cached.scheduler_decision.suppression_reason == "plan_mode_build_completed"
            else len(self._state.decisions)
        )
        build_macro = cached.build_macros.get(agent_id)
        decision = PromptDecision(
            selected=selected,
            turn_kind=turn_kind,
            reason=reason,
            suppression_reason=suppression_reason,
            scene_id=cached.scene.scene_id,
            scene_digest=_scene_digest(cached),
            role=role,
            local_observations=_local_observations(self._state, agent_id, cached),
            available_tools=_available_tools_for_agent(
                cached.available_tools,
                selected=selected,
                build_macro=build_macro,
            ),
            build_macro=build_macro,
            suppressed_agents=suppressed_agents,
            queue_depth=queue_depth,
        )
        _log_prompt_decision(decision, agent_id=agent_id)
        _emit_prompt_decision(decision, agent_id=agent_id, cached=cached)
        return decision

    def _purge_decisions(self, now_ms: int) -> None:
        expired = [
            key
            for key, cached in self._state.decisions.items()
            if now_ms - cached.created_ms > _DECISION_TTL_MS
        ]
        for key in expired:
            self._state.decisions.pop(key, None)

    def _limit_scene_selected_agents(
        self,
        *,
        scene: Scene,
        scheduler_decision: SchedulerDecision,
        candidates: Sequence[SchedulerCandidate],
    ) -> SchedulerDecision:
        if scheduler_decision.was_urgent or not scheduler_decision.selected:
            return scheduler_decision

        cap = _selected_agent_scene_cap(len(self._state.agents))
        already_selected = self._state.scene_selected_agents.get(scene.scene_id, set())
        remaining_new_slots = max(0, cap - len(already_selected))
        allowed_turns: list[SchedulerTurn] = []
        allowed_agent_ids: set[str] = set()
        capped = False

        for turn in scheduler_decision.selected:
            if turn.agent_id in already_selected or turn.agent_id in allowed_agent_ids:
                allowed_turns.append(turn)
                allowed_agent_ids.add(turn.agent_id)
                continue
            if remaining_new_slots > 0:
                allowed_turns.append(turn)
                allowed_agent_ids.add(turn.agent_id)
                remaining_new_slots -= 1
                continue
            capped = True

        if not capped:
            return scheduler_decision

        selected_ids = {turn.agent_id for turn in allowed_turns}
        suppressed_agents = sorted(
            {
                candidate.agent_id
                for candidate in candidates
                if candidate.agent_id and candidate.agent_id not in selected_ids
            }
        )
        return scheduler_decision.model_copy(
            update={
                "selected": allowed_turns,
                "suppressed_agents": suppressed_agents,
                "suppression_reason": "scene_selected_agent_cap",
            }
        )


_GATES: dict[str, DirectorPromptGate] = {}


def get_prompt_gate(simulation_id: str) -> DirectorPromptGate:
    """Return the in-process Director prompt gate for a simulation."""

    key = _text(simulation_id) or "default"
    gate = _GATES.get(key)
    if gate is None:
        gate = DirectorPromptGate()
        _GATES[key] = gate
    return gate


def reset_prompt_gates() -> None:
    """Clear prompt-gate singleton state for tests."""

    _GATES.clear()


def _event_key(event: Mapping[str, Any]) -> str:
    payload = {
        "kind": _event_kind(event.get("event_kind")),
        "text": _text(event.get("event_text")) or "",
        "source": _canonical_agent_id(event.get("source_agent")),
        "mentions": sorted(_agent_list(event.get("mentions"))),
        "scene_hint": _text(event.get("scene_hint")) or "",
        "objective": _settlement_objective_key(event),
    }
    raw = "|".join(f"{key}={value}" for key, value in payload.items())
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


def _stable_seed(scene_id: str, event_sequence: int) -> int:
    digest = hashlib.sha1(
        f"{scene_id}|{event_sequence}".encode(), usedforsecurity=False
    ).hexdigest()
    return int(digest[:16], 16)


def _event_kind(value: Any) -> GateEventKind:
    text = _text(value)
    if text in {"chat", "action_result", "perception_event"}:
        return text  # type: ignore[return-value]
    return "chat"


def _scene_event_type(kind: GateEventKind, event_text: Any) -> SceneEventType:
    text = (_text(event_text) or "").lower()
    if "danger" in text or "damage" in text or "health" in text:
        return SceneEventType.HEALTH_DANGER
    if "unstuck" in text:
        return SceneEventType.UNSTUCK
    if "stuck" in text:
        return SceneEventType.STUCK
    if _is_build_macro_intent(text, ()):
        return SceneEventType.BUILD_ACTION
    if kind == "chat":
        return SceneEventType.CHAT
    if any(word in text for word in ("build", "place", "break", "block", "dig")):
        return SceneEventType.BUILD_ACTION
    if kind == "perception_event":
        return SceneEventType.MOVEMENT_MILESTONE
    return SceneEventType.TOOL_RESULT


def _event_origin(
    state: _GateState,
    source_agent: str,
    calling_agent: str,
    event: Mapping[str, Any],
) -> Vec3:
    for candidate in (
        state.agents.get(source_agent),
        state.agents.get(calling_agent),
    ):
        if candidate and candidate.position is not None:
            return candidate.position
    return _vec3(event.get("position")) or Vec3(x=0, y=64, z=0)


def _dimension_for(state: _GateState, source_agent: str, calling_agent: str) -> str:
    for candidate in (
        state.agents.get(source_agent),
        state.agents.get(calling_agent),
    ):
        if candidate:
            return candidate.dimension
    return "overworld"


def _fallback_scene(
    *,
    event_key: str,
    event_type: SceneEventType,
    agent_ids: Sequence[str],
    now_ms: int,
) -> Scene:
    participants = sorted({agent_id for agent_id in agent_ids if agent_id})
    return Scene(
        scene_id=f"mcscene-gate-{event_key[:12]}",
        triggering_event_type=event_type,
        participants=participants,
        observers=[],
        event_ids=[f"director-gate-{event_key[:16]}"],
        opened_at_ms=now_ms,
        last_event_at_ms=now_ms,
    )


def _scene_digest(cached: _CachedVerdict) -> str:
    text = _clip(cached.event_text, 240)
    participants = ", ".join(cached.scene.participants) or "none"
    observers = ", ".join(cached.scene.observers) or "none"
    return (
        f"{cached.scene.triggering_event_type.value} from {cached.source_agent}: "
        f"{text or '<no text>'} | participants: {participants} | observers: {observers}"
    )


def _local_observations(
    state: _GateState,
    agent_id: str,
    cached: _CachedVerdict,
) -> dict[str, Any]:
    agent = state.agents.get(agent_id)
    return {
        "position": agent.position.model_dump() if agent and agent.position else None,
        "dimension": agent.dimension if agent else "overworld",
        "source_agent": cached.source_agent,
        "event_kind": cached.event_kind,
        "event_text": _clip(cached.event_text, 320),
        "scene_hint": cached.scene_hint,
        "scene_participants": cached.scene.participants,
        "scene_observers": cached.scene.observers,
        "recent_speakers": list(state.recent_speakers),
        "active_objective": cached.active_objective.model_dump()
        if cached.active_objective is not None
        else None,
    }


def _role_fit(role: str, event_type: SceneEventType) -> float:
    lowered = role.lower()
    if event_type == SceneEventType.BUILD_ACTION and any(
        token in lowered for token in ("builder", "architect", "engineer", "maker")
    ):
        return 0.9
    if event_type == SceneEventType.HEALTH_DANGER and any(
        token in lowered for token in ("safety", "sentinel", "moderator")
    ):
        return 0.85
    return 0.35


def _active_task_match(role: str, event_type: SceneEventType, event_text: str) -> bool:
    del event_text
    lowered = role.lower()
    return event_type == SceneEventType.BUILD_ACTION and any(
        token in lowered for token in ("builder", "architect", "engineer", "maker", "planner")
    )


def _configured_agent_ids() -> list[str]:
    raw = os.environ.get("LTAG_SIM_AGENTS") or os.environ.get("MINECRAFT_DIRECTOR_AGENTS")
    if not raw:
        return list(_DEFAULT_SIM_AGENT_IDS)
    parsed = [
        _canonical_agent_id(item) for item in re.split(r"[\s,]+", raw) if _canonical_agent_id(item)
    ]
    return parsed or list(_DEFAULT_SIM_AGENT_IDS)


def _selected_agent_scene_cap(agent_count: int) -> int:
    ratio = _float_or_none(os.environ.get("MINECRAFT_DIRECTOR_MAX_SELECTED_AGENT_RATIO"))
    if ratio is None:
        ratio = _float_or_none(os.environ.get("SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO"))
    if ratio is None:
        ratio = _DEFAULT_MAX_SELECTED_AGENT_SCENE_RATIO
    ratio = max(0.01, min(ratio, 1.0))
    return max(1, int(max(1, agent_count) * ratio))


def _suppressed_scheduler_decision(
    *,
    scene: Scene,
    candidates: Sequence[SchedulerCandidate],
    seed: int,
    reason: str,
) -> SchedulerDecision:
    return SchedulerDecision(
        scene_id=scene.scene_id,
        selected=[],
        suppressed_agents=sorted(candidate.agent_id for candidate in candidates),
        suppression_reason=reason,
        was_urgent=False,
        seed=seed,
    )


def _apply_explicit_build_owner(
    scheduler_decision: SchedulerDecision,
    *,
    candidates: Sequence[SchedulerCandidate],
    event_text: str,
    scene_event_type: SceneEventType,
) -> SchedulerDecision:
    if scene_event_type != SceneEventType.BUILD_ACTION:
        return scheduler_decision
    owner = _explicit_build_owner(event_text, candidates)
    if owner is None:
        return scheduler_decision
    if scheduler_decision.selected_planner_agent_id == owner:
        return scheduler_decision

    suppressed_agents = sorted(
        candidate.agent_id for candidate in candidates if candidate.agent_id != owner
    )
    return scheduler_decision.model_copy(
        update={
            "selected": [
                SchedulerTurn(
                    agent_id=owner,
                    kind="planner",
                    score=1.0,
                    reason="explicit_build_owner",
                    factor_breakdown={"explicit_build_owner": 1.0},
                )
            ],
            "suppressed_agents": suppressed_agents,
            "suppression_reason": "explicit_build_owner" if suppressed_agents else None,
        }
    )


def _apply_settlement_phase_owner(
    scheduler: BuildMacroScheduler,
    scheduler_decision: SchedulerDecision,
    *,
    active_objective: SettlementObjectiveContext | None,
    candidates: Sequence[SchedulerCandidate],
    scene_event_type: SceneEventType,
    now_ms: int,
) -> SchedulerDecision:
    if active_objective is None or scene_event_type != SceneEventType.BUILD_ACTION:
        return scheduler_decision
    owner, reason = scheduler.select_phase_owner(
        active_objective=active_objective,
        candidates=candidates,
        fallback_owner=scheduler_decision.selected_planner_agent_id,
        now_ms=now_ms,
    )
    if owner is None:
        return scheduler_decision
    if scheduler_decision.selected_planner_agent_id == owner:
        return scheduler_decision

    suppressed_agents = sorted(
        candidate.agent_id for candidate in candidates if candidate.agent_id != owner
    )
    return scheduler_decision.model_copy(
        update={
            "selected": [
                SchedulerTurn(
                    agent_id=owner,
                    kind="planner",
                    score=1.0,
                    reason=reason,
                    factor_breakdown={"settlement_phase_owner": 1.0},
                )
            ],
            "suppressed_agents": suppressed_agents,
            "suppression_reason": reason if suppressed_agents else None,
        }
    )


def _explicit_build_owner(
    event_text: str,
    candidates: Sequence[SchedulerCandidate],
) -> str | None:
    lowered = str(event_text or "").lower()
    if not lowered:
        return None
    candidate_ids = {candidate.agent_id for candidate in candidates}
    for pattern in (
        r"\b(?P<agent>[a-z][a-z0-9_-]*)\s+is\s+the\s+build\s+owner\b",
        r"\b(?P<agent>[a-z][a-z0-9_-]*)\s+should\s+be\s+the\s+build\s+owner\b",
        r"\b(?P<agent>[a-z][a-z0-9_-]*)\s+will\s+be\s+the\s+build\s+owner\b",
        r"\bbuild\s+owner\s*(?:is|:)\s*(?P<agent>[a-z][a-z0-9_-]*)\b",
    ):
        match = re.search(pattern, lowered)
        if match:
            owner = _canonical_agent_id(match.group("agent"))
            if owner in candidate_ids:
                return owner
    return None


def _is_build_macro_intent(event_text: str, available_tools: Sequence[str]) -> bool:
    lowered = str(event_text or "").lower()
    if (
        lowered.startswith("autonomous heartbeat:")
        or _is_build_plan_status_notice(lowered)
        or _is_build_completion_chatter(lowered)
    ):
        return False
    if "!planandbuild" in lowered or "planandbuild" in lowered:
        return True
    return _has_build_request_intent(lowered)


def _has_build_request_intent(lowered: str) -> bool:
    return any(
        pattern in lowered
        for pattern in (
            "build a ",
            "build an ",
            "build the ",
            "build us ",
            "build me ",
            "build one ",
            "build our ",
            "build this ",
            "build from plan",
            "builder plan",
            "construct a ",
            "construct an ",
            "construct the ",
            "make a ",
            "make an ",
            "make the ",
            "need a cabin",
            "need a hut",
            "need a shelter",
            "plan a cabin",
            "plan a house",
            "plan a shelter",
            "plan and build",
            "should build",
            "storage corner",
            "let's build",
            "lets build",
        )
    )


def _is_build_plan_status_notice(lowered: str) -> bool:
    return "build-from-plan" in lowered and any(
        status in lowered for status in (" success:", " partial:", " failed:")
    )


def _is_successful_build_plan_status_notice(lowered: str) -> bool:
    return "build-from-plan" in lowered and " success:" in lowered


def _is_plan_mode_single_build_closed(state: _GateState) -> bool:
    if not state.plan_mode_build_completed:
        return False
    if os.environ.get("MC_SIM_BUILD_MODE") != "plan":
        return False
    max_per_agent = _int_or_none(os.environ.get("MC_SIM_BUILD_MAX_PER_AGENT"))
    return max_per_agent is None or max_per_agent <= 1


def _should_quiesce_after_plan_build(
    state: _GateState,
    event_type: SceneEventType,
) -> bool:
    if not _is_plan_mode_single_build_closed(state):
        return False
    return event_type not in {
        SceneEventType.HEALTH_DANGER,
        SceneEventType.STUCK,
        SceneEventType.UNSTUCK,
    }


def _is_build_completion_chatter(lowered: str) -> bool:
    return any(
        done in lowered
        for done in ("done", "finished", "complete", "completed", "nice job", "good job")
    ) and any(
        target in lowered for target in ("build", "cabin", "house", "hut", "shelter", "structure")
    )


def _build_macro_description(event_text: str) -> str:
    text = " ".join(str(event_text or "").split())
    match = re.search(r"!?planAndBuild\s*\((?P<arg>.*?)\)", text, flags=re.IGNORECASE)
    if match:
        text = match.group("arg").strip().strip("\"'")
    return _clip(text, 180) or "scene build"


def _settlement_objective_context(
    event: Mapping[str, Any],
) -> SettlementObjectiveContext | None:
    raw = event.get("active_objective") or event.get("settlement_objective")
    if not isinstance(raw, Mapping):
        return None
    try:
        return SettlementObjectiveContext.model_validate(raw)
    except ValueError:
        return None


def _settlement_objective_key(event: Mapping[str, Any]) -> str:
    objective = _settlement_objective_context(event)
    if objective is None:
        return ""
    return (
        f"{objective.objective_id}:{objective.phase_index}:"
        f"{objective.owner_agent_id or ''}:{objective.status or ''}"
    )


def _available_tools_for_agent(
    available_tools: Sequence[str],
    *,
    selected: bool,
    build_macro: BuildMacroAssignment | None,
) -> list[str]:
    if not selected:
        return []
    tools = [tool for tool in available_tools if tool != "!planAndBuild"]
    if build_macro is not None and build_macro.role == "planner_owner" and build_macro.granted:
        tools.append("!planAndBuild")
    return sorted(set(tools))


def _default_role(agent_id: str) -> str:
    return {
        "alpha": "quiet errand runner",
        "vera": "host facilitator",
        "rex": "builder",
        "aurora": "explorer",
        "pixel": "artist",
        "fork": "architect engineer",
        "sentinel": "safety moderator",
        "grok": "analyst",
        "management": "management reviewer",
    }.get(agent_id, "scene participant")


def _tool_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        return []
    tools = {_text(item) for item in value}
    return sorted(tool for tool in tools if tool is not None)


def _agent_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_canonical_agent_id(value)] if _canonical_agent_id(value) else []
    if isinstance(value, list | tuple | set | frozenset):
        agents = {_canonical_agent_id(item) for item in value}
        return sorted(agent for agent in agents if agent)
    return []


def _vec3(value: Vec3 | Mapping[str, Any] | None) -> Vec3 | None:
    if isinstance(value, Vec3):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        return Vec3.model_validate(value)
    except ValueError:
        return None


def _canonical_agent_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clip(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)].rstrip()}..."


def _now_ms() -> int:
    return int(time.time() * 1000)


def _log_prompt_decision(decision: PromptDecision, *, agent_id: str) -> None:
    logger.info(
        "director_gate_decision",
        extra={
            "director_gate": {
                "agent_id": agent_id,
                "scene_id": decision.scene_id,
                "selected": decision.selected,
                "turn_kind": decision.turn_kind,
                "reason": decision.reason,
                "suppression_reason": decision.suppression_reason,
                "build_plan_id": decision.build_macro.plan_id if decision.build_macro else None,
                "build_owner": decision.build_macro.owner if decision.build_macro else None,
                "build_role": decision.build_macro.role if decision.build_macro else None,
                "objective_id": decision.build_macro.objective_id
                if decision.build_macro
                else None,
                "phase_index": decision.build_macro.phase_index
                if decision.build_macro
                else None,
                "queue_depth": decision.queue_depth,
                "suppressed_agents_count": len(decision.suppressed_agents),
            }
        },
    )


def _emit_prompt_decision(
    decision: PromptDecision,
    *,
    agent_id: str,
    cached: _CachedVerdict,
) -> None:
    build_macro = decision.build_macro
    selected_turn = cached.selected_turns.get(agent_id)
    payload: dict[str, Any] = {
        "scene_id": decision.scene_id,
        "agent_id": agent_id,
        "selected": decision.selected,
        "selected_speaker": agent_id
        if decision.selected and decision.turn_kind == "speaker"
        else None,
        "selected_action_owner": agent_id
        if decision.selected and decision.turn_kind == "planner"
        else None,
        "turn_kind": decision.turn_kind,
        "reason": decision.reason,
        "reason_code": decision.reason if decision.selected else decision.suppression_reason,
        "suppression_reason": decision.suppression_reason,
        "suppressed_agents": decision.suppressed_agents,
        "suppressed_candidates": decision.suppressed_agents,
        "queue_depth": decision.queue_depth,
        "scene_event_type": cached.scene.triggering_event_type.value,
        "source_agent": cached.source_agent,
        "scene_hint": cached.scene_hint,
        "available_tools": decision.available_tools,
        "llm_prompt_count": 1 if decision.selected else 0,
        "avoided_prompt_count": 0 if decision.selected else 1,
        "build_plan_id": build_macro.plan_id if build_macro else None,
        "build_owner": build_macro.owner if build_macro else None,
        "build_role": build_macro.role if build_macro else None,
        "build_support_role": build_macro.support_role if build_macro else None,
        "objective_id": build_macro.objective_id if build_macro else None,
        "phase_index": build_macro.phase_index if build_macro else None,
        "phase_owner": build_macro.phase_owner if build_macro else None,
        "provider": cached.provider,
        "model": cached.model,
        "estimated_usd": cached.estimated_usd,
        "score": selected_turn.score if selected_turn is not None else None,
        "factor_breakdown": selected_turn.factor_breakdown if selected_turn is not None else {},
    }
    emit_director_timeline_event(
        "director.gate.decision",
        payload,
        agent_id=agent_id,
        trace_id=cached.trace_id,
    )
