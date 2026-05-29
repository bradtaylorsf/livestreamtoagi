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
    ConflictEventRow,
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

# Tick window for the ``claim_then_build`` heuristic: a world-changing intent by
# the same agent within this many logged events AFTER a ``claim_task`` is read as
# "this build fired FROM the claim", not a first-shouter race. The DecisionLogger
# tick is a global per-event counter, so the window spans interleaved turns from
# other agents — kept generous so a real claim→build is not missed (#909).
_CLAIM_THEN_BUILD_WINDOW_TICKS = 50

# Bare tool-name aliases for the task-board lifecycle, accepted alongside the
# canonical ``manage_task`` (action-in-args) surface for forward-compat if the
# tool is ever split into discrete create/claim/update tools.
_TASK_ACTION_ALIASES: dict[str, str] = {
    "createtask": "create_task",
    "claimtask": "claim_task",
    "updatestatus": "update_status",
    "listtasks": "list_tasks",
}


@dataclass(frozen=True)
class EvidenceRef:
    tick: int
    actor_id: str | None
    event_type: str
    note: str = ""


@dataclass(frozen=True)
class TaskLifecycleSummary:
    """Task-board lifecycle counts derived from ``manage_task`` tool intents.

    Emergent collaboration (#907/#908/#909) is mediated by the shared task board,
    not by chat: agents ``create_task`` to post work, ``claim_task`` to take it
    (first-claim-wins), and ``update_status -> done`` to finish. Surfacing this
    lifecycle as a first-class signal lets the classifier read a healthy emergent
    run as ``collaborative`` instead of misfiling it as ``idle_chat`` or
    ``scattered`` just because no build-ish tool or chat regex fired.

    ``claim_then_build`` counts claims followed by a world-changing intent from
    the same agent within :data:`_CLAIM_THEN_BUILD_WINDOW_TICKS` ticks — evidence
    that a build fired FROM a claim rather than from a first-shouter race.
    """

    created_task_count: int = 0
    distinct_task_creators: int = 0
    claimed_task_count: int = 0
    distinct_task_claimers: int = 0
    completed_task_count: int = 0
    claim_then_build: int = 0
    creator_ids: tuple[str, ...] = ()
    claimer_ids: tuple[str, ...] = ()


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


def _is_manage_task(intent: ToolIntentRow) -> bool:
    """A successful ``manage_task`` tool intent (task-board lifecycle action)."""
    if intent.payload.status not in {"executed", "simulated"}:
        return False
    name = intent.payload.tool_name.lower().replace("-", "").replace("!", "").replace("_", "")
    return name == "managetask"


def _manage_task_action(intent: ToolIntentRow) -> str | None:
    action = (intent.payload.args or {}).get("action")
    return action.lower() if isinstance(action, str) else None


def _task_board_objective(intents: list[ToolIntentRow]) -> EvidenceRef | None:
    """A ``create_task`` posts a shared objective onto the board."""
    for i in intents:
        if _manage_task_action(i) == "create_task":
            return EvidenceRef(
                tick=i.tick,
                actor_id=i.actor_id,
                event_type="tool_intent",
                note="manage_task:create_task",
            )
    return None


def _task_board_role_actors(intents: list[ToolIntentRow]) -> set[str]:
    """Agents who took a role on the board — created (auto-owns) or claimed a task."""
    actors: set[str] = set()
    for i in intents:
        if _manage_task_action(i) in {"create_task", "claim_task"} and i.actor_id:
            actors.add(i.actor_id)
    return actors


def _task_board_completion_events(intents: list[ToolIntentRow]) -> int:
    """``update_status`` to ``done``/``blocked`` is a completion/review signal."""
    count = 0
    for i in intents:
        if _manage_task_action(i) == "update_status":
            status = (i.payload.args or {}).get("status")
            if isinstance(status, str) and status.lower() in {"done", "blocked"}:
                count += 1
    return count


def _task_lifecycle_action(intent: ToolIntentRow) -> str | None:
    """The task-board lifecycle action for a successful tool intent, or None.

    Recognizes both the canonical ``manage_task`` tool (action carried in
    ``args["action"]``) and bare-named aliases (``create_task`` etc.) for
    forward-compat. Returns None for non-task or unsuccessful intents.
    """
    if intent.payload.status not in {"executed", "simulated"}:
        return None
    if _is_manage_task(intent):
        return _manage_task_action(intent)
    name = intent.payload.tool_name.lower().replace("-", "").replace("!", "").replace("_", "")
    return _TASK_ACTION_ALIASES.get(name)


def collect_task_events(rows: Iterable[DecisionLogRow]) -> TaskLifecycleSummary:
    """Summarize the ``manage_task`` lifecycle over a sequence of decision rows.

    Pure function — no LLM, no DB. Buckets successful task-board intents by
    action and computes the distinct-actor counts plus the ``claim_then_build``
    coupling used by the emergent-mode acceptance gate (#909).
    """
    intents = [r for r in rows if isinstance(r, ToolIntentRow)]
    world_changing = [(i.tick, i.actor_id) for i in intents if _is_world_changing(i)]

    creators: set[str] = set()
    claimers: set[str] = set()
    created = claimed = completed = claim_then_build = 0
    for intent in intents:
        action = _task_lifecycle_action(intent)
        if action == "create_task":
            created += 1
            if intent.actor_id:
                creators.add(intent.actor_id)
        elif action == "claim_task":
            claimed += 1
            if intent.actor_id:
                claimers.add(intent.actor_id)
                if any(
                    actor == intent.actor_id
                    and intent.tick <= tick <= intent.tick + _CLAIM_THEN_BUILD_WINDOW_TICKS
                    for tick, actor in world_changing
                ):
                    claim_then_build += 1
        elif action == "update_status":
            status = (intent.payload.args or {}).get("status")
            if isinstance(status, str) and status.lower() == "done":
                completed += 1

    return TaskLifecycleSummary(
        created_task_count=created,
        distinct_task_creators=len(creators),
        claimed_task_count=claimed,
        distinct_task_claimers=len(claimers),
        completed_task_count=completed,
        claim_then_build=claim_then_build,
        creator_ids=tuple(sorted(creators)),
        claimer_ids=tuple(sorted(claimers)),
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
    task_summary: TaskLifecycleSummary,
) -> tuple[Classification, str | None]:
    if command_loops:
        return "command_loop_churn", "repeated_blocked_tool_intents"
    # Task-lifecycle collaboration path (#909). A run where >= 2 distinct agents
    # post work, >= 2 distinct agents claim it, and >= 1 task reaches done is
    # genuine emergent collaboration even with zero world-changing tools and no
    # objective/role chat regex match. Placed before the collaborative/partial
    # chat heuristics so a no-build task run upgrades from partial to
    # collaborative; it never downgrades an existing classification.
    if (
        task_summary.distinct_task_creators >= 2
        and task_summary.distinct_task_claimers >= 2
        and task_summary.completed_task_count >= 1
    ):
        return "collaborative", None
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

    # Task-board lifecycle signals (#908). A run that organizes via ``manage_task``
    # rather than chat-declared ownership should still classify as collaboration:
    # create_task → objective, create/claim actors → roles, update_status
    # done/blocked → completion/review. These are additive to the chat heuristics,
    # never subtractive, so the existing settlement/regression cases are unchanged.
    manage_task_intents = [i for i in intents if _is_manage_task(i)]

    objective_evidence = _count_objective_signals(utterances)
    if objective_evidence is None:
        objective_evidence = _task_board_objective(manage_task_intents)
    shared_objective = objective_evidence is not None

    _, utt_role_actors = _count_distinct_roles(utterances)
    role_actor_set = set(utt_role_actors) | _task_board_role_actors(manage_task_intents)
    distinct_role_count = len(role_actor_set)
    role_actors = sorted(role_actor_set)

    task_summary = collect_task_events(rows)

    world_changing_intents = [i for i in intents if _is_world_changing(i)]
    distinct_world_changing_actors = len({i.actor_id for i in world_changing_intents if i.actor_id})
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

    task_completion_events = _task_board_completion_events(manage_task_intents)
    review_turns = _count_review_turns(utterances) + task_completion_events
    command_loops = _find_command_loops(intents)
    executed_count = sum(1 for i in intents if i.payload.status in {"executed", "simulated"})
    delegation_events = sum(1 for u in utterances if _ROLE_HINT_RE.search(u.payload.text or ""))

    ownership_deltas = [r for r in rows if isinstance(r, OwnershipDeltaRow)]
    ownership_events = len(ownership_deltas)
    distinct_owner_ids = {
        r.payload.owner_agent_id for r in ownership_deltas if r.payload.action == "claim"
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
    detection_rate_pct = (
        int(round((detected_count / theft_events_count) * 100)) if theft_events_count else 0
    )
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

    # Conflict counts (#895). Dispute lifecycle plus war declarations.
    # ``disputes_opened``/``disputes_resolved`` cover the resolution rate;
    # ``wars_declared``/``surrenders`` cover the escalation path.
    conflict_rows = [r for r in rows if isinstance(r, ConflictEventRow)]
    disputes_opened = sum(1 for r in conflict_rows if r.payload.action == "opened")
    disputes_resolved = sum(1 for r in conflict_rows if r.payload.action == "resolved")
    disputes_escalated = sum(1 for r in conflict_rows if r.payload.action == "escalated")
    wars_declared = sum(1 for r in conflict_rows if r.payload.action == "war_declared")
    wars_activated = sum(1 for r in conflict_rows if r.payload.action == "war_activated")
    surrenders = sum(1 for r in conflict_rows if r.payload.action == "surrendered")

    classification, failure_class = _classify(
        shared_objective_chosen=shared_objective,
        distinct_role_count=distinct_role_count,
        world_changing_action_count=world_changing_count,
        review_repair_events=review_turns,
        command_loops=command_loops,
        executed_tool_intent_count=executed_count,
        discussion_turns=len(utterances),
        task_summary=task_summary,
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
            "distinct_world_changing_actors": distinct_world_changing_actors,
            "task_board_intents": len(manage_task_intents),
            "task_create_events": sum(
                1 for i in manage_task_intents if _manage_task_action(i) == "create_task"
            ),
            "task_claim_events": sum(
                1 for i in manage_task_intents if _manage_task_action(i) == "claim_task"
            ),
            "task_completion_events": task_completion_events,
            # Task-lifecycle summary (#909) — the keys the emergent gate reads.
            "created_task_count": task_summary.created_task_count,
            "distinct_task_creators": task_summary.distinct_task_creators,
            "claimed_task_count": task_summary.claimed_task_count,
            "distinct_task_claimers": task_summary.distinct_task_claimers,
            "completed_task_count": task_summary.completed_task_count,
            "claim_then_build": task_summary.claim_then_build,
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
            "disputes_opened": disputes_opened,
            "disputes_resolved": disputes_resolved,
            "disputes_escalated": disputes_escalated,
            "wars_declared": wars_declared,
            "wars_activated": wars_activated,
            "surrenders": surrenders,
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
    "TaskLifecycleSummary",
    "classify_rows",
    "classify_sim_folder",
    "collect_task_events",
]
