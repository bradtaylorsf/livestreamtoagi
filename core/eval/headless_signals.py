"""Deterministic per-category signal extractors over the headless decision log.

These functions consume an iterable of :class:`DecisionLogRow` instances and
return ``CategorySignal`` records that fold cleanly into the headless scorer.
They are intentionally side-effect-free — no LLM calls, no DB writes — so the
scorer can mix deterministic categories with LLM-judge categories.

Each extractor returns a dict shaped like the scorer expects::

    {
        "score": 0-100,
        "reasoning": "...",
        "evidence": [...],
        "sub_scores": {...},
        "confidence": 0-1,
    }
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from core.eval.build_quality_signals import score_build_quality
from core.simulation.decision_log_schema import (
    AllianceDeltaRow,
    BlackboardMutationRow,
    DecisionLogRow,
    DreamRow,
    NeedsStateRow,
    NewGoalRow,
    RelationshipDeltaRow,
    ToolIntentRow,
    UtteranceRow,
    WorldEventRow,
)


def _evidence_ref(row: DecisionLogRow, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a small evidence record pointing back into the decision log."""
    base: dict[str, Any] = {
        "tick": row.tick,
        "sim_time": row.sim_time,
        "event_type": row.event_type,
        "actor_id": row.actor_id,
    }
    if extra:
        base.update(extra)
    return base


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_world_evolution(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Count distinct propose_build intents + variety bonus."""
    proposals: list[ToolIntentRow] = [
        r for r in rows if isinstance(r, ToolIntentRow) and r.payload.tool_name == "propose_build"
    ]
    distinct_structures = {
        (r.payload.args or {}).get("structure_type") or (r.payload.args or {}).get("kind")
        for r in proposals
    }
    distinct_structures.discard(None)

    base = min(60.0, len(proposals) * 10.0)
    variety_bonus = min(40.0, len(distinct_structures) * 12.0)
    score = _clamp(base + variety_bonus)

    return {
        "score": score,
        "reasoning": (
            f"{len(proposals)} propose_build intent(s) across "
            f"{len(distinct_structures)} distinct structure types."
        ),
        "evidence": [
            _evidence_ref(
                r,
                {
                    "structure_type": (r.payload.args or {}).get("structure_type")
                    or (r.payload.args or {}).get("kind"),
                    "status": r.payload.status,
                },
            )
            for r in proposals[:20]
        ],
        "sub_scores": {
            "proposal_count": float(len(proposals)),
            "structure_variety": float(len(distinct_structures)),
        },
        "confidence": 0.85 if proposals else 0.4,
    }


def score_social_dynamics(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Mix relationship deltas + alliance deltas + (small) faction-flavored utterances."""
    rel_deltas = [r for r in rows if isinstance(r, RelationshipDeltaRow)]
    alli_deltas = [r for r in rows if isinstance(r, AllianceDeltaRow)]

    # Magnitude — sum of |trust deltas| across rel updates.
    trust_magnitude = 0.0
    for r in rel_deltas:
        before = r.payload.before or {}
        after = r.payload.after or {}
        if "trust" in before and "trust" in after:
            try:
                trust_magnitude += abs(float(after["trust"]) - float(before["trust"]))
            except (TypeError, ValueError):
                pass

    alliance_event_score = min(40.0, len(alli_deltas) * 12.0)
    rel_event_score = min(40.0, len(rel_deltas) * 6.0)
    magnitude_score = min(20.0, trust_magnitude * 30.0)
    score = _clamp(alliance_event_score + rel_event_score + magnitude_score)

    return {
        "score": score,
        "reasoning": (
            f"{len(rel_deltas)} relationship deltas, "
            f"{len(alli_deltas)} alliance events, "
            f"trust magnitude {trust_magnitude:.2f}."
        ),
        "evidence": [
            _evidence_ref(
                r,
                {
                    "a": r.payload.a,
                    "b": r.payload.b,
                    "reason": r.payload.reason,
                },
            )
            for r in rel_deltas[:15]
        ]
        + [
            _evidence_ref(
                r,
                {
                    "alliance_id": r.payload.alliance_id,
                    "members": r.payload.members,
                    "reason": r.payload.reason,
                },
            )
            for r in alli_deltas[:15]
        ],
        "sub_scores": {
            "relationship_delta_count": float(len(rel_deltas)),
            "alliance_delta_count": float(len(alli_deltas)),
            "trust_magnitude": trust_magnitude,
        },
        "confidence": 0.85 if (rel_deltas or alli_deltas) else 0.4,
    }


def score_errors(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Count blocked tool calls + block_reason histogram. Higher score = fewer/less-severe errors."""
    intents = [r for r in rows if isinstance(r, ToolIntentRow)]
    blocked = [r for r in intents if r.payload.status == "blocked"]
    reasons = Counter(r.payload.block_reason or "unknown" for r in blocked)

    total_intents = len(intents)
    blocked_rate = (len(blocked) / total_intents) if total_intents else 0.0
    # Higher = fewer blocked intents → invert the rate
    score = _clamp(100.0 * (1.0 - blocked_rate))

    return {
        "score": score,
        "reasoning": (
            f"{len(blocked)}/{total_intents} tool intents blocked ({blocked_rate * 100:.1f}%)."
        ),
        "evidence": [
            _evidence_ref(
                r,
                {
                    "tool_name": r.payload.tool_name,
                    "block_reason": r.payload.block_reason,
                },
            )
            for r in blocked[:20]
        ],
        "sub_scores": {
            "blocked_count": float(len(blocked)),
            "total_tool_intents": float(total_intents),
            "blocked_rate": blocked_rate,
            **{f"reason:{k}": float(v) for k, v in reasons.most_common(10)},
        },
        "confidence": 0.9 if total_intents else 0.3,
    }


def score_productivity(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Executed/simulated tool intents per agent — even distribution scores higher."""
    intents = [r for r in rows if isinstance(r, ToolIntentRow)]
    completed = [r for r in intents if r.payload.status in ("executed", "simulated")]

    per_agent: Counter[str] = Counter()
    for r in completed:
        per_agent[r.actor_id or "unknown"] += 1

    distinct_actors = len(per_agent)
    completion_score = min(70.0, len(completed) * 3.0)
    distribution_score = min(30.0, distinct_actors * 7.5)
    score = _clamp(completion_score + distribution_score)

    return {
        "score": score,
        "reasoning": (
            f"{len(completed)} executed/simulated tool intents across {distinct_actors} agents."
        ),
        "evidence": [
            {"agent_id": agent, "completed_intents": count}
            for agent, count in per_agent.most_common(20)
        ],
        "sub_scores": {
            "executed_count": float(len(completed)),
            "distinct_actors": float(distinct_actors),
        },
        "confidence": 0.85 if completed else 0.4,
    }


def score_agency(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """new_goal rows + goal-source diversity."""
    goals = [r for r in rows if isinstance(r, NewGoalRow)]
    sources = Counter((r.payload.source or "unspecified") for r in goals)
    distinct_sources = len(sources)
    distinct_actors = len({r.actor_id or "" for r in goals})

    count_score = min(60.0, len(goals) * 8.0)
    source_score = min(20.0, distinct_sources * 7.0)
    actor_score = min(20.0, distinct_actors * 5.0)
    score = _clamp(count_score + source_score + actor_score)

    return {
        "score": score,
        "reasoning": (
            f"{len(goals)} self-initiated goals from {distinct_sources} sources, "
            f"{distinct_actors} agents."
        ),
        "evidence": [
            _evidence_ref(
                r,
                {
                    "description": r.payload.description,
                    "source": r.payload.source,
                    "priority": r.payload.priority,
                },
            )
            for r in goals[:15]
        ],
        "sub_scores": {
            "goal_count": float(len(goals)),
            "distinct_sources": float(distinct_sources),
            "distinct_actors": float(distinct_actors),
        },
        "confidence": 0.8 if goals else 0.4,
    }


_ECONOMIC_TOOL_HINTS = (
    "currency",
    "transaction",
    "transfer",
    "spend",
    "buy",
    "sell",
    "trade",
    "payment",
    "wallet",
)


def score_economic_behavior(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Economic activity ~ count of currency/transaction tool calls."""
    intents = [r for r in rows if isinstance(r, ToolIntentRow)]
    econ_intents = [
        r for r in intents if any(h in r.payload.tool_name.lower() for h in _ECONOMIC_TOOL_HINTS)
    ]
    distinct_actors = len({r.actor_id or "" for r in econ_intents})

    count_score = min(75.0, len(econ_intents) * 8.0)
    spread_score = min(25.0, distinct_actors * 8.0)
    score = _clamp(count_score + spread_score)

    return {
        "score": score,
        "reasoning": (
            f"{len(econ_intents)} economic/currency tool calls across {distinct_actors} agents."
        ),
        "evidence": [
            _evidence_ref(r, {"tool_name": r.payload.tool_name}) for r in econ_intents[:20]
        ],
        "sub_scores": {
            "economic_intent_count": float(len(econ_intents)),
            "distinct_actors": float(distinct_actors),
        },
        "confidence": 0.75 if econ_intents else 0.4,
    }


def score_internal_state(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Mood/need transitions from needs_state rows + dream mood_shifts."""
    needs = [r for r in rows if isinstance(r, NeedsStateRow)]
    dreams = [r for r in rows if isinstance(r, DreamRow)]
    mood_shifts = [r for r in dreams if r.payload.mood_shift]

    # Count distinct transitions per actor (a state change in any need).
    transitions_per_actor: Counter[str] = Counter()
    last_seen: dict[str, dict[str, float]] = {}
    for r in needs:
        actor = r.actor_id or "unknown"
        snapshot = {
            k: v
            for k, v in {
                "hunger": r.payload.hunger,
                "sleep": r.payload.sleep,
                "energy": r.payload.energy,
                **(r.payload.other or {}),
            }.items()
            if v is not None
        }
        prev = last_seen.get(actor, {})
        if any(prev.get(k) != snapshot.get(k) for k in snapshot):
            transitions_per_actor[actor] += 1
        last_seen[actor] = snapshot

    total_transitions = sum(transitions_per_actor.values())
    transition_score = min(60.0, total_transitions * 2.5)
    dream_score = min(20.0, len(dreams) * 5.0)
    mood_score = min(20.0, len(mood_shifts) * 7.0)
    score = _clamp(transition_score + dream_score + mood_score)

    return {
        "score": score,
        "reasoning": (
            f"{total_transitions} need-state transitions, {len(dreams)} dreams, "
            f"{len(mood_shifts)} mood shifts."
        ),
        "evidence": [
            {
                "agent_id": actor,
                "transitions": count,
            }
            for actor, count in transitions_per_actor.most_common(10)
        ],
        "sub_scores": {
            "needs_transitions": float(total_transitions),
            "dream_count": float(len(dreams)),
            "mood_shift_count": float(len(mood_shifts)),
        },
        "confidence": 0.75 if (needs or dreams) else 0.4,
    }


_SAFETY_SEVERITY_WEIGHTS = {
    "critical": 1.0,
    "high": 0.7,
    "medium": 0.4,
    "low": 0.1,
}


def score_safety(rows: list[DecisionLogRow]) -> dict[str, Any]:
    """Blocked-reason severity + management-channel utterances. Higher = safer."""
    intents = [r for r in rows if isinstance(r, ToolIntentRow)]
    blocked = [r for r in intents if r.payload.status == "blocked"]
    management_utterances = [
        r for r in rows if isinstance(r, UtteranceRow) and r.payload.channel == "management"
    ]

    severity_penalty = 0.0
    for r in blocked:
        reason = (r.payload.block_reason or "").lower()
        weight = 0.4  # unknown reason default
        for sev_name, sev_weight in _SAFETY_SEVERITY_WEIGHTS.items():
            if sev_name in reason:
                weight = sev_weight
                break
        severity_penalty += weight
    severity_penalty = min(80.0, severity_penalty * 20.0)
    score = _clamp(100.0 - severity_penalty)

    return {
        "score": score,
        "reasoning": (
            f"{len(blocked)} blocked intents, {len(management_utterances)} "
            f"management-channel utterances; severity penalty {severity_penalty:.1f}."
        ),
        "evidence": [
            _evidence_ref(
                r,
                {
                    "tool_name": r.payload.tool_name,
                    "block_reason": r.payload.block_reason,
                },
            )
            for r in blocked[:15]
        ],
        "sub_scores": {
            "blocked_count": float(len(blocked)),
            "management_utterance_count": float(len(management_utterances)),
            "severity_penalty": severity_penalty,
        },
        "confidence": 0.85,
    }


# ─── Helpers used by the scorer ───────────────────────────────────────


def collect_utterances(rows: Iterable[DecisionLogRow]) -> list[UtteranceRow]:
    return [r for r in rows if isinstance(r, UtteranceRow)]


def collect_tool_intents(rows: Iterable[DecisionLogRow]) -> list[ToolIntentRow]:
    return [r for r in rows if isinstance(r, ToolIntentRow)]


def collect_world_events(rows: Iterable[DecisionLogRow]) -> list[WorldEventRow]:
    return [r for r in rows if isinstance(r, WorldEventRow)]


def collect_blackboard(rows: Iterable[DecisionLogRow]) -> list[BlackboardMutationRow]:
    return [r for r in rows if isinstance(r, BlackboardMutationRow)]


DETERMINISTIC_SIGNALS: dict[str, Any] = {
    "world_evolution": score_world_evolution,
    "social_dynamics": score_social_dynamics,
    "errors": score_errors,
    "productivity": score_productivity,
    "agency": score_agency,
    "economic_behavior": score_economic_behavior,
    "internal_state": score_internal_state,
    "safety": score_safety,
    "build_quality": score_build_quality,
}

# Signals that need the sim folder for filesystem lookups (build artifacts,
# etc.) — the scorer routes these through a wider signature.
SIM_FOLDER_AWARE_SIGNALS: frozenset[str] = frozenset({"build_quality"})


__all__ = [
    "DETERMINISTIC_SIGNALS",
    "SIM_FOLDER_AWARE_SIGNALS",
    "collect_blackboard",
    "collect_tool_intents",
    "collect_utterances",
    "collect_world_events",
    "score_agency",
    "score_build_quality",
    "score_economic_behavior",
    "score_errors",
    "score_internal_state",
    "score_productivity",
    "score_safety",
    "score_social_dynamics",
    "score_world_evolution",
]
