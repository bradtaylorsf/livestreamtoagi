"""Pure turn scheduler for Minecraft Director V2 scenes."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.minecraft.director.scene_inbox import Scene, SceneEventType

_MAX_SILENCE_SECONDS = 300.0
_EPSILON = 1e-9


@dataclass(frozen=True)
class SchedulerConfig:
    """Tunable Director V2 turn selection weights."""

    time_since_spoke: float = 0.30
    topic_relevance: float = 0.30
    chattiness: float = 0.15
    adjacency_fit: float = 0.15
    random_jitter: float = 0.10
    direct_address: float = 1.00
    danger_priority: float = 2.50
    stuck_priority: float = 2.25
    active_task: float = 0.55
    role_fit: float = 0.35
    open_commitment: float = 0.35
    selection_fairness: float = 2.00
    selection_starvation_threshold: float = 0.95
    overuse_penalty: float = 0.40
    participation_floor: float = 1.25
    max_turns_per_scene: int = 1
    consecutive_turn_block: int = 2
    silent_force_select_turns: int = 5
    fatigue_threshold_turns: int = 3
    urgent_event_types: frozenset[SceneEventType] = field(
        default_factory=lambda: frozenset(
            {
                SceneEventType.HEALTH_DANGER,
                SceneEventType.STUCK,
            }
        )
    )
    direct_address_bonus: float = 2.0


class SchedulerCandidate(BaseModel):
    """A scene agent that may be selected for one Director V2 turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    is_participant: bool
    is_observer: bool
    chattiness: float = Field(ge=0.0, le=1.0)
    role: str | None = None
    topic_relevance: float = Field(default=0.3, ge=0.0, le=1.0)
    seconds_since_spoke: float = Field(ge=0.0)
    turns_since_spoke: int = Field(ge=0)
    recent_turn_count: int = Field(ge=0)
    selection_count: int = Field(default=0, ge=0)
    total_selection_count: int = Field(default=0, ge=0)
    has_open_commitment: bool = False
    active_task_match: bool = False
    is_directly_addressed: bool = False
    is_in_danger: bool = False
    is_stuck: bool = False
    role_fit: float = Field(default=0.3, ge=0.0, le=1.0)


class SchedulerTurn(BaseModel):
    """A selected speaker or planner turn with explainable scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    kind: Literal["speaker", "planner"]
    score: float
    reason: str
    factor_breakdown: dict[str, float]


class SchedulerDecision(BaseModel):
    """Bounded scheduler output for one scene turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    selected: list[SchedulerTurn]
    suppressed_agents: list[str]
    suppression_reason: str | None
    was_urgent: bool
    seed: int

    @property
    def selected_planner_agent_id(self) -> str | None:
        """First selected planner agent, when this scene turn includes one."""

        for turn in self.selected:
            if turn.kind == "planner":
                return turn.agent_id
        return None


def score_candidate(
    candidate: SchedulerCandidate,
    config: SchedulerConfig,
    *,
    scene_event_type: SceneEventType,
    eligible_count: int,
    jitter: float,
) -> tuple[float, dict[str, float], str]:
    """Return the weighted scheduler score, raw factors, and dominant reason."""

    time_since_spoke = min(candidate.seconds_since_spoke / _MAX_SILENCE_SECONDS, 1.0)
    direct_address = 1.0 if candidate.is_directly_addressed else 0.0
    danger_priority = 1.0 if candidate.is_in_danger else 0.0
    stuck_priority = 1.0 if candidate.is_stuck else 0.0
    active_task = 1.0 if candidate.active_task_match else 0.0
    open_commitment = 1.0 if candidate.has_open_commitment else 0.0
    selection_deficit = _selection_deficit(candidate, eligible_count)
    participation_floor = (
        1.0 if candidate.turns_since_spoke >= config.silent_force_select_turns else 0.0
    )
    fatigue_penalty = config.overuse_penalty * max(
        0,
        candidate.recent_turn_count - config.fatigue_threshold_turns,
    )

    factors = {
        "time_since_spoke": time_since_spoke,
        "topic_relevance": candidate.topic_relevance,
        "chattiness": candidate.chattiness,
        "adjacency_fit": candidate.role_fit,
        "random_jitter": jitter,
        "direct_address": direct_address,
        "direct_address_bonus": config.direct_address_bonus
        if candidate.is_directly_addressed
        else 0.0,
        "danger_priority": danger_priority,
        "stuck_priority": stuck_priority,
        "active_task": active_task,
        "role_fit": candidate.role_fit,
        "open_commitment": open_commitment,
        "selection_deficit": selection_deficit,
        "participation_floor": participation_floor,
        "fatigue_penalty": -fatigue_penalty,
    }

    score = (
        factors["time_since_spoke"] * config.time_since_spoke
        + factors["topic_relevance"] * config.topic_relevance
        + factors["chattiness"] * config.chattiness
        + factors["adjacency_fit"] * config.adjacency_fit
        + factors["random_jitter"] * config.random_jitter
        + factors["direct_address"] * config.direct_address
        + factors["danger_priority"] * config.danger_priority
        + factors["stuck_priority"] * config.stuck_priority
        + factors["active_task"] * config.active_task
        + factors["role_fit"] * config.role_fit
        + factors["open_commitment"] * config.open_commitment
        + factors["selection_deficit"] * config.selection_fairness
        + factors["participation_floor"] * config.participation_floor
        + factors["direct_address_bonus"]
        - fatigue_penalty
    )
    score = max(0.0, score)

    return (
        score,
        factors,
        _reason_for(
            candidate,
            config,
            scene_event_type,
            selection_deficit=selection_deficit,
        ),
    )


class DirectorTurnScheduler:
    """Select bounded, fair Director V2 turns from a Minecraft scene."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()

    def select(
        self,
        *,
        scene: Scene,
        candidates: list[SchedulerCandidate],
        scene_event_type: SceneEventType,
        recent_speakers: list[str] | None = None,
        seed: int,
    ) -> SchedulerDecision:
        """Pick at most ``max_turns_per_scene`` speakers/planners for a scene."""

        rng = random.Random(seed)
        recent = recent_speakers or []
        base_eligible = self._eligible_candidates(scene, candidates)
        was_urgent = scene_event_type in self.config.urgent_event_types or any(
            candidate.is_in_danger or candidate.is_stuck for candidate in base_eligible
        )

        if not base_eligible:
            return SchedulerDecision(
                scene_id=scene.scene_id,
                selected=[],
                suppressed_agents=[],
                suppression_reason="no_candidates",
                was_urgent=was_urgent,
                seed=seed,
            )

        scored: dict[str, _ScoredCandidate] = {}
        for candidate in base_eligible:
            jitter = rng.random()
            score, factors, reason = score_candidate(
                candidate,
                self.config,
                scene_event_type=scene_event_type,
                eligible_count=len(base_eligible),
                jitter=jitter,
            )
            if _is_consecutive_blocked(candidate.agent_id, recent, self.config):
                score = 0.0
                factors = {**factors, "consecutive_turn_block": 1.0}
                reason = "consecutive_turn_block"
            scored[candidate.agent_id] = _ScoredCandidate(
                candidate=candidate,
                score=score,
                factors=factors,
                reason=reason,
            )

        blocked_ids = {
            agent_id
            for agent_id, scored_candidate in scored.items()
            if scored_candidate.reason == "consecutive_turn_block"
        }
        selectable = [
            scored_candidate
            for scored_candidate in scored.values()
            if scored_candidate.candidate.agent_id not in blocked_ids
        ]
        selected: list[_ScoredCandidate]
        suppression_reason: str | None = None

        urgent_candidates = [
            scored_candidate
            for scored_candidate in selectable
            if scored_candidate.candidate.is_in_danger or scored_candidate.candidate.is_stuck
        ]
        if urgent_candidates:
            selected = self._sample(urgent_candidates, rng)
            suppression_reason = "urgent_priority"
        else:
            direct_candidates = [
                scored_candidate
                for scored_candidate in selectable
                if scored_candidate.candidate.is_directly_addressed
            ]
            if len(direct_candidates) == 1:
                selected = [direct_candidates[0]]
                suppression_reason = "direct_addressee_priority"
            else:
                force_candidates = [
                    scored_candidate
                    for scored_candidate in selectable
                    if scored_candidate.candidate.turns_since_spoke
                    >= self.config.silent_force_select_turns
                ]
                starvation_candidates = [
                    scored_candidate
                    for scored_candidate in selectable
                    if scored_candidate.factors.get("selection_deficit", 0.0)
                    >= self.config.selection_starvation_threshold
                ]
                planner_candidates = [
                    scored_candidate
                    for scored_candidate in selectable
                    if _turn_kind(scored_candidate.candidate, scene_event_type) == "planner"
                ]
                if starvation_candidates:
                    selected = [_most_starved(starvation_candidates)]
                    suppression_reason = "selection_starvation"
                elif scene_event_type == SceneEventType.BUILD_ACTION and planner_candidates:
                    selected = _top_scored(
                        planner_candidates,
                        max(self.config.max_turns_per_scene, 0),
                    )
                    suppression_reason = "fanout_capped"
                elif force_candidates:
                    selected = [_highest_scored(force_candidates)]
                    suppression_reason = "fanout_capped"
                else:
                    selected = self._sample(selectable, rng)

        selected_ids = {scored_candidate.candidate.agent_id for scored_candidate in selected}
        suppressed_agents = [
            scored_candidate.candidate.agent_id
            for scored_candidate in scored.values()
            if scored_candidate.candidate.agent_id not in selected_ids
        ]
        if suppressed_agents and suppression_reason is None:
            suppression_reason = "consecutive_turn_block" if blocked_ids else "fanout_capped"
        if blocked_ids and not selected:
            suppression_reason = "consecutive_turn_block"

        return SchedulerDecision(
            scene_id=scene.scene_id,
            selected=[
                SchedulerTurn(
                    agent_id=scored_candidate.candidate.agent_id,
                    kind=_turn_kind(scored_candidate.candidate, scene_event_type),
                    score=scored_candidate.score,
                    reason=scored_candidate.reason,
                    factor_breakdown=scored_candidate.factors,
                )
                for scored_candidate in selected
            ],
            suppressed_agents=suppressed_agents,
            suppression_reason=suppression_reason if suppressed_agents else None,
            was_urgent=was_urgent,
            seed=seed,
        )

    def _eligible_candidates(
        self,
        scene: Scene,
        candidates: list[SchedulerCandidate],
    ) -> list[SchedulerCandidate]:
        scene_participants = set(scene.participants)
        participant_candidates = [
            candidate
            for candidate in candidates
            if candidate.is_participant or candidate.agent_id in scene_participants
        ]
        has_participants = bool(participant_candidates)

        eligible = []
        for candidate in candidates:
            is_participant = candidate.is_participant or candidate.agent_id in scene_participants
            if is_participant or candidate.is_directly_addressed or not has_participants:
                eligible.append(candidate)
        return sorted(eligible, key=lambda candidate: candidate.agent_id)

    def _sample(
        self,
        candidates: list[_ScoredCandidate],
        rng: random.Random,
    ) -> list[_ScoredCandidate]:
        turn_limit = max(self.config.max_turns_per_scene, 0)
        return _weighted_sample_without_replacement(candidates, turn_limit, rng)


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: SchedulerCandidate
    score: float
    factors: dict[str, float]
    reason: str


def _reason_for(
    candidate: SchedulerCandidate,
    config: SchedulerConfig,
    scene_event_type: SceneEventType,
    *,
    selection_deficit: float = 0.0,
) -> str:
    if candidate.is_in_danger:
        return "danger_priority"
    if candidate.is_stuck:
        return "stuck_priority"
    if candidate.is_directly_addressed:
        return "direct_address"
    if selection_deficit >= config.selection_starvation_threshold:
        return "selection_starvation"
    if candidate.turns_since_spoke >= config.silent_force_select_turns:
        return "participation_floor"
    if candidate.active_task_match:
        return "active_task_match"
    if candidate.has_open_commitment:
        return "open_commitment"
    if _role_is_planner(candidate, scene_event_type):
        return "role_fit"
    return "weighted_scene_fit"


def _is_consecutive_blocked(
    agent_id: str,
    recent_speakers: list[str],
    config: SchedulerConfig,
) -> bool:
    if config.consecutive_turn_block <= 0:
        return False
    if len(recent_speakers) < config.consecutive_turn_block:
        return False
    return all(speaker == agent_id for speaker in recent_speakers[-config.consecutive_turn_block :])


def _highest_scored(candidates: list[_ScoredCandidate]) -> _ScoredCandidate:
    return max(candidates, key=lambda item: (item.score, item.candidate.agent_id))


def _top_scored(candidates: list[_ScoredCandidate], turn_limit: int) -> list[_ScoredCandidate]:
    if turn_limit <= 0:
        return []
    return sorted(
        candidates,
        key=lambda item: (item.score, item.candidate.agent_id),
        reverse=True,
    )[:turn_limit]


def _most_starved(candidates: list[_ScoredCandidate]) -> _ScoredCandidate:
    return max(
        candidates,
        key=lambda item: (
            item.factors.get("selection_deficit", 0.0),
            item.score,
            -item.candidate.selection_count,
            item.candidate.agent_id,
        ),
    )


def _selection_deficit(candidate: SchedulerCandidate, eligible_count: int) -> float:
    if eligible_count <= 0 or candidate.total_selection_count <= 0:
        return 0.0
    expected_selections = candidate.total_selection_count / eligible_count
    if expected_selections <= _EPSILON:
        return 0.0
    deficit = expected_selections - candidate.selection_count
    if deficit <= 0:
        return 0.0
    return max(0.0, min(deficit / max(expected_selections, 1.0), 1.0))


def _weighted_sample_without_replacement(
    candidates: list[_ScoredCandidate],
    turn_limit: int,
    rng: random.Random,
) -> list[_ScoredCandidate]:
    if turn_limit <= 0:
        return []

    pool = list(candidates)
    selected: list[_ScoredCandidate] = []
    for _ in range(min(turn_limit, len(pool))):
        total = sum(max(item.score, 0.0) for item in pool)
        if total <= _EPSILON:
            index = rng.randrange(len(pool))
        else:
            threshold = rng.random() * total
            cumulative = 0.0
            index = len(pool) - 1
            for idx, item in enumerate(pool):
                cumulative += max(item.score, 0.0)
                if cumulative >= threshold:
                    index = idx
                    break
        selected.append(pool.pop(index))
    return selected


def _turn_kind(
    candidate: SchedulerCandidate, scene_event_type: SceneEventType
) -> Literal["speaker", "planner"]:
    if candidate.active_task_match or _role_is_planner(candidate, scene_event_type):
        return "planner"
    return "speaker"


def _role_is_planner(candidate: SchedulerCandidate, scene_event_type: SceneEventType) -> bool:
    if scene_event_type != SceneEventType.BUILD_ACTION or candidate.role is None:
        return False
    role = candidate.role.lower()
    return any(
        token in role
        for token in (
            "architect",
            "builder",
            "engineer",
            "planner",
        )
    )
