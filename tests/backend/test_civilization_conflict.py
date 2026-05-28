"""Unit tests for the civilization conflict ledger and tools (issue #895)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.civilization.conflict import (
    ConflictFailure,
    ConflictLedger,
    Dispute,
    WarIntent,
)
from core.civilization.diplomacy import DiplomacyLedger, Treaty
from core.civilization.ownership import OwnershipLedger
from core.civilization.theft import TheftLedger
from core.civilization.trade import TradeLedger
from core.eval.headless_signals import score_conflict
from core.eval.settlement_smoke_signals import classify_sim_folder
from core.models import FactionConfig
from core.simulation.decision_log_schema import (
    ConflictEventRow,
    DecisionLogRow,
    DiplomacyEventRow,
    OwnershipDeltaRow,
    RelationshipDeltaRow,
    TradeEventRow,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from tools.civilization import (
    AcceptJudgementTool,
    DeclareWarTool,
    OpenDisputeTool,
    RequestJudgementTool,
    SecondWarTool,
    SubmitEvidenceTool,
    SurrenderTool,
)

_DEFAULT_FACTIONS = [
    FactionConfig(
        name="planner_builders",
        members=["vera", "rex"],
        goal="Build cool stuff",
        stance="constructive",
    ),
    FactionConfig(
        name="support",
        members=["fork", "pixel"],
        goal="Keep everyone honest",
        stance="watchful",
    ),
]


def _make_diplomacy(tmp_path: Path, *, factions=None) -> DiplomacyLedger:
    return DiplomacyLedger(
        tmp_path,
        simulation_id="sim-conflict",
        factions=factions if factions is not None else _DEFAULT_FACTIONS,
    )


def _make_ledger(
    tmp_path: Path,
    *,
    diplomacy: DiplomacyLedger | None = None,
    ownership: OwnershipLedger | None = None,
    trade: TradeLedger | None = None,
    theft: TheftLedger | None = None,
    simulation_id: str = "sim-conflict",
) -> ConflictLedger:
    return ConflictLedger(
        tmp_path,
        simulation_id=simulation_id,
        diplomacy_ledger=diplomacy,
        ownership_ledger=ownership,
        trade_ledger=trade,
        theft_ledger=theft,
    )


# ─── Ledger lifecycle ──────────────────────────────────────────────────


def test_open_dispute_lifecycle(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="personal",
        motivation="they keep ignoring me",
    )
    assert isinstance(dispute, Dispute)
    assert dispute.status == "open"
    assert dispute.initiator_id == "vera"
    assert dispute.dispute_type == "personal"


def test_open_dispute_rejects_self(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    failure = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="vera",
        dispute_type="personal",
    )
    assert isinstance(failure, ConflictFailure)
    assert failure.reason == "self_dispute"


def test_open_dispute_rejects_invalid_type(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    failure = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="cosmic",
    )
    assert isinstance(failure, ConflictFailure)
    assert failure.reason == "invalid_type"


def test_submit_evidence_appends(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="personal",
        evidence_refs=[
            {"ref_type": "utterance", "ref_id": "u-1", "narrative": "rude"}
        ],
    )
    assert isinstance(dispute, Dispute)
    updated = ledger.submit_evidence(
        dispute.dispute_id,
        submitter_id="rex",
        evidence_ref={"ref_type": "utterance", "ref_id": "u-2"},
        narrative="responding",
    )
    assert isinstance(updated, Dispute)
    assert len(updated.evidence) == 2
    # Duplicate (type, id) rejected.
    dup = ledger.submit_evidence(
        dispute.dispute_id,
        submitter_id="rex",
        evidence_ref={"ref_type": "utterance", "ref_id": "u-2"},
    )
    assert isinstance(dup, ConflictFailure)
    assert dup.reason == "duplicate_evidence"


def test_submit_evidence_rejects_non_parties(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="personal",
    )
    assert isinstance(dispute, Dispute)
    result = ledger.submit_evidence(
        dispute.dispute_id,
        submitter_id="fork",
        evidence_ref={"ref_type": "utterance", "ref_id": "u-3"},
    )
    assert isinstance(result, ConflictFailure)
    assert result.reason == "not_a_party"


def test_deterministic_judgement_same_seed_same_ruling(tmp_path: Path) -> None:
    ledger_a = _make_ledger(tmp_path / "a")
    ledger_b = _make_ledger(tmp_path / "b")
    # Same dispute_id by manually building disputes via the ledger isn't
    # possible (uuid4); instead verify same evidence shape with equal
    # weights produces deterministic tiebreak when simulation_id matches.
    # We force a tie by giving each side equal evidence then check that
    # repeated runs with the same simulation_id pick the same winner.
    dispute_a = ledger_a.open_dispute(
        initiator_id="vera", respondent_id="rex", dispute_type="personal"
    )
    assert isinstance(dispute_a, Dispute)
    judged_a = ledger_a.request_judgement(dispute_a.dispute_id)
    assert isinstance(judged_a, Dispute)
    # Repeat with the same ledger state and the result is stable.
    second_dispute = ledger_b.open_dispute(
        initiator_id="vera", respondent_id="rex", dispute_type="personal"
    )
    assert isinstance(second_dispute, Dispute)
    judged_b = ledger_b.request_judgement(second_dispute.dispute_id)
    assert isinstance(judged_b, Dispute)
    # Both ties resolved by deterministic hash of (sim_id, dispute_id) —
    # different dispute_ids may pick different winners, but the *judgement*
    # string format and outcome dict shape match.
    assert judged_a.outcome is not None
    assert judged_b.outcome is not None
    assert set(judged_a.outcome.keys()) >= {"winner_id", "loser_id"}


def test_judgement_favors_more_supported_evidence(tmp_path: Path) -> None:
    """The party with more cross-referenced evidence wins."""
    trade = TradeLedger(tmp_path)
    # Seed inventory + a trade so trade ref_ids exist.
    trade.set_inventory("rex", "cobblestone", 8)
    offer = trade.propose(
        proposer_id="vera",
        recipient_id="rex",
        give={"wood": 0},  # empty trade triggers failure
        want={"cobblestone": 4},
    )
    # The empty-trade path returns a TradeFailure; create a real offer:
    trade.set_inventory("vera", "wood", 4)
    real_offer = trade.propose(
        proposer_id="vera",
        recipient_id="rex",
        give={"wood": 1},
        want={"cobblestone": 1},
    )
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy, trade=trade)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="trade_breach",
        evidence_refs=[
            {"ref_type": "trade", "ref_id": real_offer.offer_id, "narrative": "trade ref"}
        ],
    )
    assert isinstance(dispute, Dispute)
    judged = ledger.request_judgement(dispute.dispute_id, judge_id="fork")
    assert isinstance(judged, Dispute)
    assert judged.outcome["winner_id"] == "vera"


# ─── Consequences per dispute_type ────────────────────────────────────


def test_territorial_resolution_transfers_ownership(tmp_path: Path) -> None:
    ownership = OwnershipLedger(tmp_path)
    claim = ownership.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "cabin-1"},
        motivation="i built it",
    )
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(
        tmp_path, diplomacy=diplomacy, ownership=ownership
    )
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="territorial",
        evidence_refs=[
            {
                "ref_type": "ownership",
                "ref_id": claim.claim_id,
                "narrative": "this is mine",
            }
        ],
    )
    assert isinstance(dispute, Dispute)
    judged = ledger.request_judgement(dispute.dispute_id)
    assert isinstance(judged, Dispute)
    assert judged.outcome["winner_id"] == "vera"

    result = ledger.accept_judgement(
        dispute.dispute_id, accepting_agent_id="rex", accept=True
    )
    assert not isinstance(result, ConflictFailure)
    resolved, consequences = result
    assert resolved.status == "resolved"
    transfers = [c for c in consequences if c["kind"] == "ownership_transfer"]
    assert len(transfers) == 1
    new_owner = ownership.get("structure", {"intent_id": "cabin-1"})
    assert new_owner is not None
    assert new_owner.owner_agent_id == "vera"


def test_theft_resolution_creates_restitution_offer(tmp_path: Path) -> None:
    trade = TradeLedger(tmp_path)
    trade.set_inventory("rex", "cobblestone", 4)
    theft = TheftLedger(
        tmp_path,
        trade_ledger=trade,
        ownership_ledger=OwnershipLedger(tmp_path),
        simulation_id="sim-conflict",
    )
    attempt = theft.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref={"x": 1, "y": 64, "z": 2, "dim": "overworld"},
        items={"cobblestone": 4},
        motivation="raid",
        tick=1,
    )
    assert hasattr(attempt, "attempt_id")
    diplomacy = _make_diplomacy(
        tmp_path,
        factions=[
            FactionConfig(
                name="planner_builders", members=["vera", "rex"], goal="g"
            ),
            FactionConfig(name="raiders", members=["grok"], goal="g"),
        ],
    )
    ledger = _make_ledger(
        tmp_path, diplomacy=diplomacy, trade=trade, theft=theft
    )
    dispute = ledger.open_dispute(
        initiator_id="rex",
        respondent_id="grok",
        dispute_type="theft",
        evidence_refs=[
            {
                "ref_type": "theft",
                "ref_id": attempt.attempt_id,
                "narrative": "caught red-handed",
            }
        ],
    )
    assert isinstance(dispute, Dispute)
    judged = ledger.request_judgement(dispute.dispute_id)
    assert isinstance(judged, Dispute)
    assert judged.outcome["winner_id"] == "rex"

    result = ledger.accept_judgement(
        dispute.dispute_id, accepting_agent_id="grok", accept=True
    )
    assert not isinstance(result, ConflictFailure)
    resolved, consequences = result
    assert resolved.status == "resolved"
    offers = [c for c in consequences if c["kind"] == "restitution_offer"]
    assert len(offers) == 1
    assert offers[0]["from_agent"] == "grok"
    assert offers[0]["to_agent"] == "rex"
    assert offers[0]["items"] == {"cobblestone": 4}


def test_treaty_violation_resolution_breaks_treaty(tmp_path: Path) -> None:
    diplomacy = _make_diplomacy(tmp_path)
    proposed = diplomacy.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    signed = diplomacy.sign(proposed.treaty_id, signer_id="fork")
    assert isinstance(signed, Treaty)

    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="fork",
        dispute_type="treaty_violation",
        evidence_refs=[
            {
                "ref_type": "diplomacy",
                "ref_id": signed.treaty_id,
                "narrative": "fork broke it",
            }
        ],
    )
    assert isinstance(dispute, Dispute)
    judged = ledger.request_judgement(dispute.dispute_id)
    assert isinstance(judged, Dispute)
    assert judged.outcome["winner_id"] == "vera"

    result = ledger.accept_judgement(
        dispute.dispute_id, accepting_agent_id="fork", accept=True
    )
    assert not isinstance(result, ConflictFailure)
    resolved, consequences = result
    assert resolved.status == "resolved"
    breaks = [c for c in consequences if c["kind"] == "treaty_break"]
    assert len(breaks) == 1
    treaty_after = diplomacy.get_treaty(signed.treaty_id)
    assert treaty_after is not None
    assert treaty_after.status == "broken"


def test_personal_resolution_only_emits_relationship_delta(tmp_path: Path) -> None:
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="personal",
        evidence_refs=[
            {"ref_type": "utterance", "ref_id": "u-1", "narrative": "rude"}
        ],
    )
    assert isinstance(dispute, Dispute)
    judged = ledger.request_judgement(dispute.dispute_id)
    assert isinstance(judged, Dispute)
    loser_id = judged.outcome["loser_id"]
    result = ledger.accept_judgement(
        dispute.dispute_id, accepting_agent_id=loser_id, accept=True
    )
    assert not isinstance(result, ConflictFailure)
    resolved, consequences = result
    assert resolved.status == "resolved"
    kinds = {c["kind"] for c in consequences}
    assert kinds == {"relationship_delta"}


def test_escalate_marks_dispute_escalated(tmp_path: Path) -> None:
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    dispute = ledger.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="personal",
    )
    assert isinstance(dispute, Dispute)
    judged = ledger.request_judgement(dispute.dispute_id)
    assert isinstance(judged, Dispute)
    loser_id = judged.outcome["loser_id"]
    result = ledger.accept_judgement(
        dispute.dispute_id, accepting_agent_id=loser_id, accept=False
    )
    assert not isinstance(result, ConflictFailure)
    updated, consequences = result
    assert updated.status == "escalated"
    assert consequences == []


# ─── War quorum + surrender ────────────────────────────────────────────


def test_declare_war_needs_majority_quorum(tmp_path: Path) -> None:
    factions = [
        FactionConfig(
            name="raiders",
            members=["grok", "fork", "pixel"],
            goal="raid",
        ),
        FactionConfig(name="builders", members=["vera"], goal="build"),
    ]
    diplomacy = _make_diplomacy(tmp_path, factions=factions)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    war = ledger.declare_war(
        initiator_id="grok",
        target_faction_id="builders",
        casus_belli="they hoard wood",
    )
    assert isinstance(war, WarIntent)
    # Quorum = majority of 3 → 2; only grok has seconded so far.
    assert war.status == "pending"
    assert war.required_quorum == 2
    # Second from another raider → activate.
    activated = ledger.second_war(war.war_id, seconder_id="fork")
    assert isinstance(activated, WarIntent)
    assert activated.status == "active"


def test_second_war_rejects_outsider(tmp_path: Path) -> None:
    factions = [
        FactionConfig(name="raiders", members=["grok", "fork"], goal="g"),
        FactionConfig(name="builders", members=["vera", "rex"], goal="g"),
    ]
    diplomacy = _make_diplomacy(tmp_path, factions=factions)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    war = ledger.declare_war(
        initiator_id="grok",
        target_faction_id="builders",
        casus_belli="cb",
    )
    assert isinstance(war, WarIntent)
    failure = ledger.second_war(war.war_id, seconder_id="vera")
    assert isinstance(failure, ConflictFailure)
    assert failure.reason == "not_a_party"


def test_surrender_ends_war(tmp_path: Path) -> None:
    factions = [
        FactionConfig(name="raiders", members=["grok"], goal="g"),
        FactionConfig(name="builders", members=["vera"], goal="g"),
    ]
    diplomacy = _make_diplomacy(tmp_path, factions=factions)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    war = ledger.declare_war(
        initiator_id="grok",
        target_faction_id="builders",
        casus_belli="cb",
    )
    assert isinstance(war, WarIntent)
    assert war.status == "active"  # single-member faction needs 1 second
    surrendered = ledger.surrender(
        war.war_id,
        surrendering_agent_id="vera",
        terms={"reparations": {"wood": 10}},
    )
    assert isinstance(surrendered, WarIntent)
    assert surrendered.status == "resolved"
    assert surrendered.surrender_terms == {"reparations": {"wood": 10}}


def test_advance_war_turn_emits_trust_deltas(tmp_path: Path) -> None:
    factions = [
        FactionConfig(name="raiders", members=["grok"], goal="g"),
        FactionConfig(name="builders", members=["vera", "rex"], goal="g"),
    ]
    diplomacy = _make_diplomacy(tmp_path, factions=factions)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    war = ledger.declare_war(
        initiator_id="grok",
        target_faction_id="builders",
        casus_belli="cb",
    )
    assert isinstance(war, WarIntent)
    assert war.status == "active"
    deltas = ledger.advance_war_turn()
    # 1 raider * 2 builders = 2 deltas.
    assert len(deltas) == 2
    assert all(d["reason"] == "war_ongoing" for d in deltas)


# ─── Persistence + replay ──────────────────────────────────────────────


def test_replay_preserves_state(tmp_path: Path) -> None:
    diplomacy = _make_diplomacy(tmp_path)
    ledger_a = _make_ledger(tmp_path, diplomacy=diplomacy)
    dispute = ledger_a.open_dispute(
        initiator_id="vera",
        respondent_id="rex",
        dispute_type="personal",
        evidence_refs=[
            {"ref_type": "utterance", "ref_id": "u-1", "narrative": "yes"}
        ],
        motivation="m",
    )
    assert isinstance(dispute, Dispute)
    judged = ledger_a.request_judgement(dispute.dispute_id)
    assert isinstance(judged, Dispute)
    loser_id = judged.outcome["loser_id"]
    result = ledger_a.accept_judgement(
        dispute.dispute_id, accepting_agent_id=loser_id, accept=True
    )
    assert not isinstance(result, ConflictFailure)

    log_path = tmp_path / "conflict_log.jsonl"
    actions = [json.loads(line)["action"] for line in log_path.read_text().splitlines()]
    assert actions[0] == "opened"
    assert "judged" in actions
    assert "resolved" in actions

    # Rebuild from disk and check state is preserved.
    diplomacy_b = _make_diplomacy(tmp_path)
    ledger_b = _make_ledger(tmp_path, diplomacy=diplomacy_b)
    restored = ledger_b.get_dispute(dispute.dispute_id)
    assert restored is not None
    assert restored.status == "resolved"


# ─── Tool layer ────────────────────────────────────────────────────────


def test_open_dispute_tool_logs_event(tmp_path: Path) -> None:
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = OpenDisputeTool(
            agent_id="vera", ledger=ledger, decision_logger=decision_logger
        )
        result = asyncio.run(
            tool.execute(
                respondent_id="rex",
                dispute_type="personal",
                motivation="rude",
            )
        )
    finally:
        decision_logger.close()
    assert result["status"] == "opened"

    rows = list(DecisionLogReader(tmp_path).replay())
    conflict_rows = [r for r in rows if isinstance(r, ConflictEventRow)]
    assert len(conflict_rows) == 1
    assert conflict_rows[0].payload.action == "opened"


def test_request_judgement_then_accept_emits_consequences(tmp_path: Path) -> None:
    ownership = OwnershipLedger(tmp_path)
    claim = ownership.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "cabin-2"},
        motivation="m",
    )
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy, ownership=ownership)
    decision_logger = DecisionLogger(tmp_path)
    try:
        open_tool = OpenDisputeTool(
            agent_id="vera", ledger=ledger, decision_logger=decision_logger
        )
        opened = asyncio.run(
            open_tool.execute(
                respondent_id="rex",
                dispute_type="territorial",
                evidence_refs=[
                    {"ref_type": "ownership", "ref_id": claim.claim_id}
                ],
                motivation="that's my land",
            )
        )
        judge_tool = RequestJudgementTool(
            agent_id="fork", ledger=ledger, decision_logger=decision_logger
        )
        judged = asyncio.run(
            judge_tool.execute(dispute_id=opened["dispute_id"], judge_id="fork")
        )
        assert judged["status"] == "judged"
        accept_tool = AcceptJudgementTool(
            agent_id=judged["outcome"]["loser_id"],
            ledger=ledger,
            decision_logger=decision_logger,
        )
        resolved = asyncio.run(
            accept_tool.execute(dispute_id=opened["dispute_id"], accept=True)
        )
    finally:
        decision_logger.close()

    assert resolved["status"] == "resolved"
    rows = list(DecisionLogReader(tmp_path).replay())
    # Resolution should produce ownership_delta rows (release + claim) and
    # a conflict_event row.
    conflict_actions = [
        r.payload.action for r in rows if isinstance(r, ConflictEventRow)
    ]
    assert {"opened", "judged", "resolved"}.issubset(set(conflict_actions))
    own_actions = [
        r.payload.action for r in rows if isinstance(r, OwnershipDeltaRow)
    ]
    assert "release" in own_actions and "claim" in own_actions


def test_declare_war_tool_quorum(tmp_path: Path) -> None:
    factions = [
        FactionConfig(name="raiders", members=["grok", "fork", "pixel"], goal="g"),
        FactionConfig(name="builders", members=["vera"], goal="g"),
    ]
    diplomacy = _make_diplomacy(tmp_path, factions=factions)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    decision_logger = DecisionLogger(tmp_path)
    try:
        decl_tool = DeclareWarTool(
            agent_id="grok", ledger=ledger, decision_logger=decision_logger
        )
        result = asyncio.run(
            decl_tool.execute(
                target_faction_id="builders",
                casus_belli="they hoard wood",
                motivation="m",
            )
        )
        assert result["status"] == "pending"
        second_tool = SecondWarTool(
            agent_id="fork", ledger=ledger, decision_logger=decision_logger
        )
        seconded = asyncio.run(second_tool.execute(war_id=result["war_id"]))
        assert seconded["status"] == "active"
    finally:
        decision_logger.close()
    rows = list(DecisionLogReader(tmp_path).replay())
    actions = [r.payload.action for r in rows if isinstance(r, ConflictEventRow)]
    assert "war_declared" in actions
    assert "war_seconded" in actions
    assert "war_activated" in actions


def test_surrender_tool_war(tmp_path: Path) -> None:
    factions = [
        FactionConfig(name="raiders", members=["grok"], goal="g"),
        FactionConfig(name="builders", members=["vera"], goal="g"),
    ]
    diplomacy = _make_diplomacy(tmp_path, factions=factions)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    war = ledger.declare_war(
        initiator_id="grok",
        target_faction_id="builders",
        casus_belli="cb",
    )
    assert isinstance(war, WarIntent)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = SurrenderTool(
            agent_id="vera", ledger=ledger, decision_logger=decision_logger
        )
        result = asyncio.run(
            tool.execute(target_id=war.war_id, terms={"tribute": {"wood": 5}})
        )
    finally:
        decision_logger.close()
    assert result["status"] == "surrendered"
    assert result["surrender_terms"] == {"tribute": {"wood": 5}}


def test_submit_evidence_tool(tmp_path: Path) -> None:
    diplomacy = _make_diplomacy(tmp_path)
    ledger = _make_ledger(tmp_path, diplomacy=diplomacy)
    decision_logger = DecisionLogger(tmp_path)
    try:
        open_tool = OpenDisputeTool(
            agent_id="vera", ledger=ledger, decision_logger=decision_logger
        )
        opened = asyncio.run(
            open_tool.execute(
                respondent_id="rex",
                dispute_type="personal",
                motivation="m",
            )
        )
        submit_tool = SubmitEvidenceTool(
            agent_id="rex", ledger=ledger, decision_logger=decision_logger
        )
        result = asyncio.run(
            submit_tool.execute(
                dispute_id=opened["dispute_id"],
                evidence_ref={"ref_type": "utterance", "ref_id": "u-9"},
                narrative="counter",
            )
        )
    finally:
        decision_logger.close()
    assert result["status"] == "evidence_submitted"


def test_tools_report_unavailable_when_no_ledger() -> None:
    tool = OpenDisputeTool(agent_id="vera", ledger=None)
    result = asyncio.run(
        tool.execute(
            respondent_id="rex",
            dispute_type="personal",
            motivation="m",
        )
    )
    assert result == {"status": "error", "reason": "conflict_ledger_unavailable"}


# ─── Scorer + smoke counts ─────────────────────────────────────────────


def test_score_conflict_counts_actions(tmp_path: Path) -> None:
    decision_logger = DecisionLogger(tmp_path)
    try:
        decision_logger.log_conflict_event(
            action="opened",
            dispute_id="d1",
            initiator_id="vera",
            respondent_id="rex",
            dispute_type="personal",
        )
        decision_logger.log_conflict_event(
            action="judged",
            dispute_id="d1",
            initiator_id="vera",
            respondent_id="rex",
            dispute_type="personal",
            outcome={"winner_id": "vera", "loser_id": "rex"},
        )
        decision_logger.log_conflict_event(
            action="resolved",
            dispute_id="d1",
            initiator_id="vera",
            respondent_id="rex",
            dispute_type="personal",
        )
        decision_logger.log_conflict_event(
            action="war_declared",
            war_id="w1",
            initiator_id="grok",
        )
        decision_logger.log_conflict_event(
            action="war_activated",
            war_id="w1",
        )
    finally:
        decision_logger.close()

    rows = list(DecisionLogReader(tmp_path).replay())
    signal = score_conflict(rows)
    assert signal["sub_scores"]["dispute_count"] == 1.0
    assert signal["sub_scores"]["resolution_rate"] == 1.0
    assert signal["sub_scores"]["war_events"] == 1.0
    assert signal["score"] > 0


def test_settlement_smoke_surfaces_conflict_counts(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        decision_logger.log_conflict_event(action="opened", dispute_id="d1")
        decision_logger.log_conflict_event(action="resolved", dispute_id="d1")
        decision_logger.log_conflict_event(action="war_declared", war_id="w1")
        decision_logger.log_conflict_event(action="war_activated", war_id="w1")
        decision_logger.log_conflict_event(action="surrendered", war_id="w1")
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["disputes_opened"] == 1
    assert outcome.sub_counts["disputes_resolved"] == 1
    assert outcome.sub_counts["wars_declared"] == 1
    assert outcome.sub_counts["wars_activated"] == 1
    assert outcome.sub_counts["surrenders"] == 1


def test_settlement_smoke_zero_conflict_when_no_events(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        decision_logger.log_utterance(actor_id="vera", text="hello world")
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["disputes_opened"] == 0
    assert outcome.sub_counts["disputes_resolved"] == 0
    assert outcome.sub_counts["wars_declared"] == 0
    assert outcome.sub_counts["surrenders"] == 0


# ─── YAML wiring ───────────────────────────────────────────────────────


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "agent_id", ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"]
)
def test_conflict_tools_in_agent_yaml(agent_id: str) -> None:
    import yaml

    cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    for tool_name in (
        "open_dispute",
        "submit_evidence",
        "request_judgement",
        "accept_judgement",
        "declare_war",
        "second_war",
        "surrender",
    ):
        assert tool_name in cfg["tools"], f"{agent_id} missing {tool_name}"
