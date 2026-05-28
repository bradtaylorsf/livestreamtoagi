"""Unit tests for the civilization diplomacy ledger and tools (issue #894)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.civilization.diplomacy import (
    DiplomacyFailure,
    DiplomacyLedger,
    Faction,
    Treaty,
)
from core.civilization.ownership import OwnershipLedger
from core.civilization.theft import TheftLedger
from core.civilization.trade import TradeLedger
from core.eval.headless_signals import score_social_dynamics
from core.eval.settlement_smoke_signals import classify_sim_folder
from core.models import FactionConfig
from core.simulation.decision_log_schema import (
    DecisionLogRow,
    DiplomacyEventRow,
    NewGoalRow,
    RelationshipDeltaRow,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from tools.civilization import (
    BreakTreatyTool,
    DefectFactionTool,
    ListActiveTreatiesTool,
    ProposeTreatyTool,
    SignTreatyTool,
    StealTool,
)

CONTAINER = {"x": 10, "y": 64, "z": 20, "dim": "overworld"}

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


def _make_ledger(
    tmp_path: Path,
    *,
    factions: list[FactionConfig] | None = None,
    simulation_id: str = "sim-test",
) -> DiplomacyLedger:
    return DiplomacyLedger(
        tmp_path,
        simulation_id=simulation_id,
        factions=factions if factions is not None else _DEFAULT_FACTIONS,
    )


# ─── Ledger lifecycle ──────────────────────────────────────────────────


def test_seeds_factions_from_config(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    builder = ledger.get_faction("planner_builders")
    assert isinstance(builder, Faction)
    assert builder.members == {"vera", "rex"}
    assert ledger.get_faction("support") is not None


def test_propose_sign_lifecycle(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    proposed = ledger.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True, "trade_preference": True},
        motivation="reduce conflict",
    )
    assert isinstance(proposed, Treaty)
    assert proposed.status == "proposed"

    signed = ledger.sign(
        proposed.treaty_id,
        signer_id="fork",
        signer_faction_id="support",
    )
    assert isinstance(signed, Treaty)
    assert signed.status == "active"
    assert signed.signed_at is not None
    active = ledger.list_active_treaties("support")
    assert [t.treaty_id for t in active] == [signed.treaty_id]


def test_double_sign_rejected(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    proposed = ledger.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    first = ledger.sign(proposed.treaty_id, signer_id="fork")
    assert isinstance(first, Treaty)
    second = ledger.sign(proposed.treaty_id, signer_id="fork")
    assert isinstance(second, DiplomacyFailure)
    assert second.reason == "already_signed"


def test_proposer_faction_cannot_self_sign(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    proposed = ledger.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    result = ledger.sign(
        proposed.treaty_id,
        signer_id="rex",
        signer_faction_id="planner_builders",
    )
    assert isinstance(result, DiplomacyFailure)
    assert result.reason == "not_a_party"


def test_break_treaty(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    proposed = ledger.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    ledger.sign(proposed.treaty_id, signer_id="fork")
    broken = ledger.break_(proposed.treaty_id, breaker_id="vera", reason="lost interest")
    assert isinstance(broken, Treaty)
    assert broken.status == "broken"
    assert broken.breaker_id == "vera"
    # Cannot break twice.
    again = ledger.break_(proposed.treaty_id, breaker_id="vera", reason="nope")
    assert isinstance(again, DiplomacyFailure)
    assert again.reason == "not_active"


def test_defection_moves_member(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    result = ledger.defect(
        agent_id="fork",
        target_faction_id="planner_builders",
        motivation="ideological shift",
    )
    assert isinstance(result, tuple)
    old, new = result
    assert old == "support"
    assert new == "planner_builders"
    assert "fork" in ledger.get_faction("planner_builders").members
    assert "fork" not in ledger.get_faction("support").members


def test_replay_preserves_state(tmp_path: Path) -> None:
    ledger_a = _make_ledger(tmp_path)
    proposed = ledger_a.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True, "mutual_defense": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    signed = ledger_a.sign(proposed.treaty_id, signer_id="fork")
    assert isinstance(signed, Treaty)
    ledger_a.defect(agent_id="pixel", target_faction_id="planner_builders", motivation="m")

    log_path = tmp_path / "diplomacy_log.jsonl"
    actions = [json.loads(line)["action"] for line in log_path.read_text().splitlines()]
    assert actions == ["proposed", "signed", "defected"]

    ledger_b = _make_ledger(tmp_path)
    restored = ledger_b.get_treaty(signed.treaty_id)
    assert restored is not None
    assert restored.status == "active"
    assert "pixel" in ledger_b.get_faction("planner_builders").members
    assert ledger_b.list_active_treaties("support") == ledger_a.list_active_treaties("support")


def test_invalid_terms_rejected(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    failure = ledger.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"world_domination": True},
        motivation="m",
    )
    assert isinstance(failure, DiplomacyFailure)
    assert failure.reason == "invalid_terms"


# ─── Tool layer ────────────────────────────────────────────────────────


def test_propose_and_sign_tools(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    decision_logger = DecisionLogger(tmp_path)
    try:
        prop_tool = ProposeTreatyTool(
            agent_id="vera", ledger=ledger, decision_logger=decision_logger
        )
        sign_tool = SignTreatyTool(
            agent_id="fork", ledger=ledger, decision_logger=decision_logger
        )
        proposed = asyncio.run(
            prop_tool.execute(
                other_faction_id="support",
                terms={"non_aggression": True},
                motivation="reduce friction",
            )
        )
        assert proposed["status"] == "proposed"
        signed = asyncio.run(sign_tool.execute(treaty_id=proposed["treaty_id"]))
        assert signed["status"] == "signed"
    finally:
        decision_logger.close()

    rows: list[DecisionLogRow] = list(DecisionLogReader(tmp_path).replay())
    dip_rows = [r for r in rows if isinstance(r, DiplomacyEventRow)]
    actions = [r.payload.action for r in dip_rows]
    assert actions == ["proposed", "signed"]


def test_break_treaty_tool_applies_trust_hits(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    proposed = ledger.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    signed = ledger.sign(proposed.treaty_id, signer_id="fork")
    assert isinstance(signed, Treaty)

    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = BreakTreatyTool(
            agent_id="vera", ledger=ledger, decision_logger=decision_logger
        )
        result = asyncio.run(
            tool.execute(treaty_id=proposed.treaty_id, reason="changed mind")
        )
    finally:
        decision_logger.close()

    assert result["status"] == "broken"

    rows = list(DecisionLogReader(tmp_path).replay())
    rel_rows = [r for r in rows if isinstance(r, RelationshipDeltaRow)]
    # Every non-breaker member of the *other* faction takes a hit.
    affected_a = {r.payload.a for r in rel_rows if r.payload.reason == "treaty_broken"}
    assert affected_a == {"fork", "pixel"}
    for r in rel_rows:
        if r.payload.reason == "treaty_broken":
            assert r.payload.b == "vera"
            assert (
                pytest.approx(r.payload.before["trust"] - r.payload.after["trust"]) == 2.0
            )


def test_defect_faction_tool_logs_event(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = DefectFactionTool(
            agent_id="pixel", ledger=ledger, decision_logger=decision_logger
        )
        result = asyncio.run(
            tool.execute(target_faction_id="planner_builders", motivation="m")
        )
    finally:
        decision_logger.close()

    assert result == {
        "status": "defected",
        "agent_id": "pixel",
        "from_faction_id": "support",
        "to_faction_id": "planner_builders",
        "motivation": "m",
    }

    rows = list(DecisionLogReader(tmp_path).replay())
    dip_rows = [r for r in rows if isinstance(r, DiplomacyEventRow)]
    assert len(dip_rows) == 1
    assert dip_rows[0].payload.action == "defected"
    assert dip_rows[0].payload.defector_id == "pixel"
    assert dip_rows[0].payload.from_faction == "support"
    assert dip_rows[0].payload.to_faction == "planner_builders"


def test_list_active_treaties_tool_authoritative(tmp_path: Path) -> None:
    ledger_a = _make_ledger(tmp_path)
    proposed = ledger_a.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"non_aggression": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    ledger_a.sign(proposed.treaty_id, signer_id="fork")

    # A second ledger built from the same folder must see the same treaty.
    ledger_b = _make_ledger(tmp_path)
    tool_a = ListActiveTreatiesTool(agent_id="vera", ledger=ledger_a)
    tool_b = ListActiveTreatiesTool(agent_id="fork", ledger=ledger_b)
    out_a = asyncio.run(tool_a.execute())
    out_b = asyncio.run(tool_b.execute())
    assert out_a["count"] == out_b["count"] == 1
    assert {t["treaty_id"] for t in out_a["treaties"]} == {
        t["treaty_id"] for t in out_b["treaties"]
    }


def test_propose_tool_without_ledger_reports_unavailable() -> None:
    tool = ProposeTreatyTool(agent_id="vera", ledger=None)
    result = asyncio.run(
        tool.execute(other_faction_id="support", terms={"non_aggression": True}, motivation="m")
    )
    assert result == {"status": "error", "reason": "diplomacy_ledger_unavailable"}


# ─── Theft interaction ─────────────────────────────────────────────────


def test_non_aggression_breach_auto_breaks_and_extra_trust_hit(tmp_path: Path) -> None:
    # Setup: factions + active non-aggression treaty
    factions = [
        FactionConfig(name="planner_builders", members=["vera", "rex"], goal="g"),
        FactionConfig(name="support", members=["fork", "pixel"], goal="g"),
    ]
    diplomacy = _make_ledger(tmp_path, factions=factions, simulation_id="sim-theft")
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

    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 8)
    theft_ledger = TheftLedger(
        tmp_path,
        trade_ledger=trade_ledger,
        ownership_ledger=OwnershipLedger(tmp_path),
        simulation_id="sim-theft",
    )

    decision_logger = DecisionLogger(tmp_path)
    try:
        steal_tool = StealTool(
            agent_id="fork",
            theft_ledger=theft_ledger,
            decision_logger=decision_logger,
            diplomacy_ledger=diplomacy,
            tick_provider=lambda: 1,
            victim_online_provider=lambda _vid: True,  # boost detection
        )
        result = asyncio.run(
            steal_tool.execute(
                victim_id="rex",
                container_ref=CONTAINER,
                items={"cobblestone": 4},
                motivation="opportunity",
            )
        )
    finally:
        decision_logger.close()

    assert result["status"] == "stolen"
    assert result["detected"] is True

    # Treaty auto-broke
    treaty_after = diplomacy.get_treaty(proposed.treaty_id)
    assert treaty_after is not None
    assert treaty_after.status == "broken"
    assert treaty_after.breaker_id == "fork"

    rows = list(DecisionLogReader(tmp_path).replay())
    dip_rows = [r for r in rows if isinstance(r, DiplomacyEventRow)]
    assert any(
        r.payload.action == "broken"
        and r.payload.breaker_id == "fork"
        and r.payload.reason == "theft_non_aggression_breach"
        for r in dip_rows
    )

    rel_rows = [r for r in rows if isinstance(r, RelationshipDeltaRow)]
    breach_rows = [r for r in rel_rows if r.payload.reason == "theft_non_aggression_breach"]
    assert len(breach_rows) == 1
    # 0.5 victim + 2.0 breaker = 2.5 trust drop.
    assert (
        pytest.approx(breach_rows[0].payload.before["trust"] - breach_rows[0].payload.after["trust"])
        == 2.5
    )


class _StubGoalManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def add_goal(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


def test_mutual_defense_injects_defense_goal(tmp_path: Path) -> None:
    factions = [
        FactionConfig(name="planner_builders", members=["vera", "rex"], goal="g"),
        FactionConfig(name="support", members=["fork", "pixel"], goal="g"),
        FactionConfig(name="raiders", members=["grok"], goal="take"),
    ]
    diplomacy = _make_ledger(tmp_path, factions=factions, simulation_id="sim-md")
    proposed = diplomacy.propose(
        proposer_id="vera",
        proposer_faction_id="planner_builders",
        other_faction_id="support",
        terms={"mutual_defense": True},
        motivation="m",
    )
    assert isinstance(proposed, Treaty)
    signed = diplomacy.sign(proposed.treaty_id, signer_id="fork")
    assert isinstance(signed, Treaty)

    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "wood", 8)
    theft_ledger = TheftLedger(
        tmp_path,
        trade_ledger=trade_ledger,
        ownership_ledger=OwnershipLedger(tmp_path),
        simulation_id="sim-md",
    )

    goal_manager = _StubGoalManager()
    decision_logger = DecisionLogger(tmp_path)
    try:
        steal_tool = StealTool(
            agent_id="grok",
            theft_ledger=theft_ledger,
            decision_logger=decision_logger,
            diplomacy_ledger=diplomacy,
            goal_manager=goal_manager,
            tick_provider=lambda: 1,
            victim_online_provider=lambda _vid: True,
        )
        result = asyncio.run(
            steal_tool.execute(
                victim_id="rex",
                container_ref=CONTAINER,
                items={"wood": 4},
                motivation="raid",
            )
        )
    finally:
        decision_logger.close()

    assert result["status"] == "stolen"
    assert result["detected"] is True

    # Mutual defenders (members of support faction) should get a defense goal.
    targets = {call["agent_id"] for call in goal_manager.calls}
    assert targets == {"fork", "pixel"}
    for call in goal_manager.calls:
        assert call["source"] == "treaty_mutual_defense"
        assert call["category"] == "defense"
        assert "defend rex" in call["goal_text"]

    rows = list(DecisionLogReader(tmp_path).replay())
    goal_rows = [r for r in rows if isinstance(r, NewGoalRow)]
    assert {r.actor_id for r in goal_rows} == {"fork", "pixel"}


# ─── Scorer + smoke counts ─────────────────────────────────────────────


def test_social_dynamics_counts_treaty_activity(tmp_path: Path) -> None:
    decision_logger = DecisionLogger(tmp_path)
    try:
        decision_logger.log_diplomacy_event(
            treaty_id="t1",
            parties=["planner_builders", "support"],
            action="proposed",
            terms={"non_aggression": True},
            motivation="m",
        )
        decision_logger.log_diplomacy_event(
            treaty_id="t1",
            parties=["planner_builders", "support"],
            action="signed",
            terms={"non_aggression": True},
        )
        decision_logger.log_diplomacy_event(
            treaty_id=None,
            parties=[],
            action="defected",
            defector_id="pixel",
            from_faction="support",
            to_faction="planner_builders",
        )
    finally:
        decision_logger.close()

    rows = list(DecisionLogReader(tmp_path).replay())
    signal = score_social_dynamics(rows)
    assert signal["sub_scores"]["treaty_proposals"] == 1.0
    assert signal["sub_scores"]["treaty_signings"] == 1.0
    assert signal["sub_scores"]["faction_defections"] == 1.0
    assert signal["sub_scores"]["treaty_density"] == 1.0
    assert signal["score"] > 0


def test_settlement_smoke_surfaces_diplomacy_counts(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        decision_logger.log_diplomacy_event(
            treaty_id="t1",
            parties=["planner_builders", "support"],
            action="proposed",
            terms={"non_aggression": True},
        )
        decision_logger.log_diplomacy_event(
            treaty_id="t1",
            parties=["planner_builders", "support"],
            action="signed",
            terms={"non_aggression": True},
        )
        decision_logger.log_diplomacy_event(
            treaty_id="t1",
            parties=["planner_builders", "support"],
            action="broken",
            terms={"non_aggression": True},
            breaker_id="vera",
            reason="changed mind",
        )
        decision_logger.log_diplomacy_event(
            treaty_id=None,
            parties=[],
            action="defected",
            defector_id="pixel",
            from_faction="support",
            to_faction="planner_builders",
        )
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["treaty_proposals"] == 1
    assert outcome.sub_counts["treaty_signings"] == 1
    assert outcome.sub_counts["treaty_breaks"] == 1
    assert outcome.sub_counts["active_treaties"] == 0  # 1 signed - 1 broken
    assert outcome.sub_counts["faction_defections"] == 1


def test_settlement_smoke_zero_diplomacy_when_no_events(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        decision_logger.log_utterance(actor_id="vera", text="hello world")
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["treaty_proposals"] == 0
    assert outcome.sub_counts["treaty_signings"] == 0
    assert outcome.sub_counts["active_treaties"] == 0
    assert outcome.sub_counts["faction_defections"] == 0


# ─── YAML wiring ───────────────────────────────────────────────────────


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("agent_id", ["vera", "fork"])
def test_diplomat_agents_have_diplomacy_tools(agent_id: str) -> None:
    import yaml

    cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    for tool_name in (
        "propose_treaty",
        "sign_treaty",
        "break_treaty",
        "defect_faction",
        "list_active_treaties",
    ):
        assert tool_name in cfg["tools"], f"{agent_id} missing {tool_name}"
