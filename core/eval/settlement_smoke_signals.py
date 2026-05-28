"""Settlement smoke classifier for the open-ended collaboration run (#821).

Reads a sim folder's ``decision_log.jsonl`` and classifies the run as one of:

- ``collaborative`` — group chose a shared objective, took >= 2 distinct
  roles, produced >= 1 embodied world-changing action, and ran a
  review/repair turn.
- ``partial`` — shared objective + role assignments but no embodied action.
- ``idle_chat`` — utterances only; zero successful tool intents.
- ``scattered`` — world-changing actions without a shared objective or role
  consensus.
- ``command_loop_churn`` — agents repeated identical failed commands.

The classifier is pure (no LLM calls, no DB writes) so it can be invoked
from the report builder and tests in seconds.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.eval.headless_signals import (
    collect_tool_intents,
    collect_utterances,
    collect_world_events,
)
from core.simulation.decision_log_schema import (
    DecisionLogRow,
    DiplomacyEventRow,
    OwnershipDeltaRow,
    TheftEventRow,
    ToolIntentRow,
    TradeEventRow,
    UtteranceRow,
)
from core.simulation.decision_logger import DecisionLogReader

Classification = Literal[
    "collaborative",
    "partial",
    "idle_chat",
    "scattered",
    "command_loop_churn",
]

_WORLD_CHANGING_TOOL_HINTS: frozenset[str] = frozenset(
    {
        "buildfromplan",
        "build_from_plan",
        "planandbuild",
        "plan_and_build",
        "propose_build",
        "propose_new_building",
        "placehere",
        "place_here",
        "collectblock",
        "collect_block",
        "harvest",
        "craft",
        "smelt",
        "buildplan",
        "build_plan",
    }
)

_OBJECTIVE_HINT_RE = re.compile(
    r"\b(let'?s build|we should build|how about (we|a)|"
    r"plan (is|to|for)|i'?ll (build|gather|scout)|"
    r"agreed|sounds good|decided|objective|goal:|"
    r"start (with|by) (a|the))\b",
    re.IGNORECASE,
)

_ROLE_HINT_RE = re.compile(
    r"\b(i'?ll (build|gather|scout|cook|cut|mine|farm|plant|guard|lead|design|review|repair)|"
    r"you (build|gather|scout|cook|cut|mine|farm|plant|guard|review|repair)|"
    r"can you (build|gather|scout|review|repair)|"
    r"(rex|fork|vera|aurora|pixel|sentinel|grok|alpha) (handle|cover|take|do))\b",
    re.IGNORECASE,
)

_REVIEW_HINT_RE = re.compile(
    r"\b(review|check (it|that|the build)|looks (good|off|wrong)|"
    r"needs (a )?(repair|fix)|let'?s fix|missing|broken|"
    r"redo|patch|tear down)\b",
    re.IGNORECASE,
)

_COMMAND_LOOP_THRESHOLD = 4  # same agent + same tool + same args + blocked


@dataclass(frozen=True)
class EvidenceRef:
    tick: int
    actor_id: str | None
    event_type: str
    note: str = ""


@dataclass
class SettlementSmokeOutcome:
    """Classification result over a single sim folder."""

    classification: Classification
    shared_objective_chosen: bool
    shared_objective_evidence: EvidenceRef | None
    distinct_role_count: int
    distinct_role_actors: list[str]
    world_changing_action_count: int
    world_changing_first_events: list[EvidenceRef]
    discussion_turns: int
    delegation_events: int
    review_repair_events: int
    command_loop_signatures: list[str]
    failure_class: str | None
    summary: str
    sub_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.shared_objective_evidence is not None:
            data["shared_objective_evidence"] = asdict(self.shared_objective_evidence)
        data["world_changing_first_events"] = [asdict(e) for e in self.world_changing_first_events]
        return data


def _is_world_changing(intent: ToolIntentRow) -> bool:
    if intent.payload.status not in {"executed", "simulated"}:
        return False
    name = intent.payload.tool_name.lower().replace("-", "").replace("!", "")
    return any(
        hint.replace("_", "") in name.replace("_", "") for hint in _WORLD_CHANGING_TOOL_HINTS
    )


def _count_objective_signals(utterances: list[UtteranceRow]) -> EvidenceRef | None:
    for u in utterances:
        text = u.payload.text or ""
        if _OBJECTIVE_HINT_RE.search(text):
            return EvidenceRef(
                tick=u.tick,
                actor_id=u.actor_id,
                event_type="utterance",
                note=text.strip()[:160],
            )
    return None


def _count_distinct_roles(utterances: list[UtteranceRow]) -> tuple[int, list[str]]:
    role_actors: set[str] = set()
    for u in utterances:
        text = u.payload.text or ""
        if _ROLE_HINT_RE.search(text) and u.actor_id:
            role_actors.add(u.actor_id)
    return len(role_actors), sorted(role_actors)


def _count_review_turns(utterances: list[UtteranceRow]) -> int:
    return sum(1 for u in utterances if _REVIEW_HINT_RE.search(u.payload.text or ""))


def _find_command_loops(intents: list[ToolIntentRow]) -> list[str]:
    blocked = [i for i in intents if i.payload.status == "blocked"]
    signatures: dict[str, int] = defaultdict(int)
    for r in blocked:
        # Stable signature: actor + tool + sorted arg keys/values
        args = r.payload.args or {}
        arg_repr = ",".join(f"{k}={args[k]}" for k in sorted(args))
        sig = f"{r.actor_id}|{r.payload.tool_name}|{arg_repr}|{r.payload.block_reason or ''}"
        signatures[sig] += 1
    return [sig for sig, count in signatures.items() if count >= _COMMAND_LOOP_THRESHOLD]


def _classify(
    shared_objective_chosen: bool,
    distinct_role_count: int,
    world_changing_action_count: int,
    review_repair_events: int,
    command_loops: list[str],
    executed_tool_intent_count: int,
    discussion_turns: int,
) -> tuple[Classification, str | None]:
    if command_loops:
        return "command_loop_churn", "repeated_blocked_tool_intents"
    if (
        shared_objective_chosen
        and distinct_role_count >= 2
        and world_changing_action_count >= 1
        and review_repair_events >= 1
    ):
        return "collaborative", None
    if shared_objective_chosen and distinct_role_count >= 2 and world_changing_action_count == 0:
        return "partial", "no_world_changing_action"
    if discussion_turns > 0 and executed_tool_intent_count == 0:
        return "idle_chat", "zero_successful_tool_intents"
    if world_changing_action_count >= 1 and (
        not shared_objective_chosen or distinct_role_count < 2
    ):
        return "scattered", "world_change_without_consensus"
    return "partial", "insufficient_signals"


def classify_rows(rows: Iterable[DecisionLogRow]) -> SettlementSmokeOutcome:
    """Classify a sequence of decision-log rows. Pure function — easy to test."""
    rows = list(rows)
    utterances = collect_utterances(rows)
    intents = collect_tool_intents(rows)
    world_events = collect_world_events(rows)

    objective_evidence = _count_objective_signals(utterances)
    shared_objective = objective_evidence is not None

    distinct_role_count, role_actors = _count_distinct_roles(utterances)

    world_changing_intents = [i for i in intents if _is_world_changing(i)]
    world_changing_count = len(world_changing_intents) + len(world_events)
    first_events = [
        EvidenceRef(
            tick=i.tick,
            actor_id=i.actor_id,
            event_type="tool_intent",
            note=i.payload.tool_name,
        )
        for i in world_changing_intents[:5]
    ]

    review_turns = _count_review_turns(utterances)
    command_loops = _find_command_loops(intents)
    executed_count = sum(1 for i in intents if i.payload.status in {"executed", "simulated"})
    delegation_events = sum(1 for u in utterances if _ROLE_HINT_RE.search(u.payload.text or ""))

    ownership_deltas = [r for r in rows if isinstance(r, OwnershipDeltaRow)]
    ownership_events = len(ownership_deltas)
    distinct_owner_ids = {
        r.payload.owner_agent_id
        for r in ownership_deltas
        if r.payload.action == "claim"
    }

    trade_rows = [r for r in rows if isinstance(r, TradeEventRow)]
    trade_events = len(trade_rows)
    distinct_trading_pairs = {
        tuple(sorted((r.payload.proposer_id, r.payload.recipient_id)))
        for r in trade_rows
        if r.payload.action == "accepted"
    }

    # Theft counts (#893). Group by attempt_id so a witness-report row that
    # promotes an undetected attempt doesn't double-count.
    theft_rows = [r for r in rows if isinstance(r, TheftEventRow)]
    theft_by_attempt: dict[str, TheftEventRow] = {}
    for r in theft_rows:
        prev = theft_by_attempt.get(r.payload.attempt_id)
        if prev is None or (r.payload.detected and not prev.payload.detected):
            theft_by_attempt[r.payload.attempt_id] = r
    unique_theft = list(theft_by_attempt.values())
    theft_events_count = len(unique_theft)
    detected_count = sum(1 for ev in unique_theft if ev.payload.detected)
    detection_rate_pct = int(
        round((detected_count / theft_events_count) * 100)
    ) if theft_events_count else 0
    thief_attempts: dict[str, int] = defaultdict(int)
    for ev in unique_theft:
        thief_attempts[ev.payload.thief_id] += 1
    repeat_thieves = sum(1 for n in thief_attempts.values() if n >= 2)
    # Coordinated raid: ≥2 distinct thieves hit the same victim within 30 ticks.
    coordinated_raids = 0
    by_victim: dict[str, list[TheftEventRow]] = defaultdict(list)
    for ev in unique_theft:
        by_victim[ev.payload.victim_id].append(ev)
    for events in by_victim.values():
        events.sort(key=lambda e: e.tick)
        for i, ev in enumerate(events):
            window_thieves = {ev.payload.thief_id}
            for other in events[i + 1 :]:
                if other.tick - ev.tick > 30:
                    break
                window_thieves.add(other.payload.thief_id)
            if len(window_thieves) >= 2:
                coordinated_raids += 1
                break

    # Diplomacy counts (#894). Treaty lifecycle plus faction defections —
    # ``active_treaties`` reflects signed minus broken so the report shows
    # the *current* count, while ``treaty_breaks`` and ``faction_defections``
    # surface the volume of churn.
    diplomacy_rows = [r for r in rows if isinstance(r, DiplomacyEventRow)]
    treaty_proposals = sum(1 for r in diplomacy_rows if r.payload.action == "proposed")
    treaty_signings = sum(1 for r in diplomacy_rows if r.payload.action == "signed")
    treaty_breaks = sum(1 for r in diplomacy_rows if r.payload.action == "broken")
    faction_defections = sum(1 for r in diplomacy_rows if r.payload.action == "defected")
    active_treaties = max(0, treaty_signings - treaty_breaks)

    classification, failure_class = _classify(
        shared_objective_chosen=shared_objective,
        distinct_role_count=distinct_role_count,
        world_changing_action_count=world_changing_count,
        review_repair_events=review_turns,
        command_loops=command_loops,
        executed_tool_intent_count=executed_count,
        discussion_turns=len(utterances),
    )

    summary = (
        f"classification={classification}; "
        f"objective={'yes' if shared_objective else 'no'}; "
        f"roles={distinct_role_count}; "
        f"world_actions={world_changing_count}; "
        f"review_turns={review_turns}; "
        f"command_loops={len(command_loops)}"
    )

    return SettlementSmokeOutcome(
        classification=classification,
        shared_objective_chosen=shared_objective,
        shared_objective_evidence=objective_evidence,
        distinct_role_count=distinct_role_count,
        distinct_role_actors=role_actors,
        world_changing_action_count=world_changing_count,
        world_changing_first_events=first_events,
        discussion_turns=len(utterances),
        delegation_events=delegation_events,
        review_repair_events=review_turns,
        command_loop_signatures=command_loops,
        failure_class=failure_class,
        summary=summary,
        sub_counts={
            "utterances": len(utterances),
            "tool_intents": len(intents),
            "executed_or_simulated_intents": executed_count,
            "world_events": len(world_events),
            "world_changing_intents": len(world_changing_intents),
            "delegation_events": delegation_events,
            "ownership_events": ownership_events,
            "distinct_owners": len(distinct_owner_ids),
            "trade_events": trade_events,
            "distinct_trading_pairs": len(distinct_trading_pairs),
            "theft_events": theft_events_count,
            "detection_rate": detection_rate_pct,
            "repeat_thieves": repeat_thieves,
            "coordinated_raids": coordinated_raids,
            "treaty_proposals": treaty_proposals,
            "treaty_signings": treaty_signings,
            "active_treaties": active_treaties,
            "treaty_breaks": treaty_breaks,
            "faction_defections": faction_defections,
        },
    )


def classify_sim_folder(sim_folder: str | Path) -> SettlementSmokeOutcome:
    """Load ``<sim_folder>/decision_log.jsonl`` and classify the run."""
    reader = DecisionLogReader(sim_folder)
    return classify_rows(reader.replay())


__all__ = [
    "Classification",
    "EvidenceRef",
    "SettlementSmokeOutcome",
    "classify_rows",
    "classify_sim_folder",
]
