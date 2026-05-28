"""Unit tests for the civilization trade ledger and tools (issue #892)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.civilization.ownership import OwnershipClaim, OwnershipLedger
from core.civilization.trade import TradeFailure, TradeLedger, TradeOffer
from core.eval.headless_signals import score_economic_behavior
from core.eval.settlement_smoke_signals import classify_sim_folder
from core.simulation.decision_log_schema import (
    DecisionLogRow,
    TradeEventRow,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from tools.civilization import (
    AcceptTradeTool,
    ListPendingTradesTool,
    ProposeTradeTool,
    RejectTradeTool,
)

# ─── Ledger ────────────────────────────────────────────────────────────


def test_ledger_propose_then_accept_swaps_inventories(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    ledger.set_inventory("rex", "cobblestone", 64)
    ledger.set_inventory("vera", "wood", 32)

    offer = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 16},
        want={"wood": 8},
        motivation="need wood for the roof",
    )
    assert isinstance(offer, TradeOffer)
    assert offer.status == "pending"

    accepted = ledger.accept(offer.offer_id, accepting_agent_id="vera")
    assert isinstance(accepted, TradeOffer)
    assert accepted.status == "accepted"
    assert accepted.resolved_at is not None

    assert ledger.get_inventory("rex") == {"cobblestone": 48, "wood": 8}
    assert ledger.get_inventory("vera") == {"wood": 24, "cobblestone": 16}


def test_ledger_insufficient_inventory_at_accept_returns_failure(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    ledger.set_inventory("rex", "cobblestone", 4)
    ledger.set_inventory("vera", "wood", 32)

    offer = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 16},
        want={"wood": 8},
        motivation="want wood",
    )
    assert isinstance(offer, TradeOffer)

    failure = ledger.accept(offer.offer_id, accepting_agent_id="vera")
    assert isinstance(failure, TradeFailure)
    assert failure.reason == "insufficient_inventory"

    # No state change — pending offer remains, both inventories untouched.
    assert ledger.get(offer.offer_id).status == "pending"  # type: ignore[union-attr]
    assert ledger.get_inventory("rex") == {"cobblestone": 4}
    assert ledger.get_inventory("vera") == {"wood": 32}


def test_ledger_reject_records_reason(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    ledger.set_inventory("rex", "cobblestone", 64)
    ledger.set_inventory("vera", "wood", 32)

    offer = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 16},
        want={"wood": 8},
        motivation="want wood",
    )
    assert isinstance(offer, TradeOffer)

    rejected = ledger.reject(
        offer.offer_id, accepting_agent_id="vera", reason="too steep"
    )
    assert isinstance(rejected, TradeOffer)
    assert rejected.status == "rejected"
    assert rejected.reject_reason == "too steep"
    # Inventories unchanged.
    assert ledger.get_inventory("rex") == {"cobblestone": 64}
    assert ledger.get_inventory("vera") == {"wood": 32}


def test_ledger_double_accept_blocked(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    ledger.set_inventory("rex", "cobblestone", 64)
    ledger.set_inventory("vera", "wood", 32)

    offer = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 16},
        want={"wood": 8},
        motivation="m",
    )
    assert isinstance(offer, TradeOffer)
    first = ledger.accept(offer.offer_id, accepting_agent_id="vera")
    assert isinstance(first, TradeOffer)

    second = ledger.accept(offer.offer_id, accepting_agent_id="vera")
    assert isinstance(second, TradeFailure)
    assert second.reason == "already_resolved"


def test_ledger_wrong_recipient_cannot_accept(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    ledger.set_inventory("rex", "cobblestone", 64)
    ledger.set_inventory("vera", "wood", 32)
    offer = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 16},
        want={"wood": 8},
        motivation="m",
    )
    assert isinstance(offer, TradeOffer)

    bad = ledger.accept(offer.offer_id, accepting_agent_id="pixel")
    assert isinstance(bad, TradeFailure)
    assert bad.reason == "wrong_recipient"


def test_ledger_list_pending_filters_to_recipient(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    ledger.set_inventory("rex", "cobblestone", 64)
    ledger.set_inventory("vera", "wood", 32)
    ledger.set_inventory("pixel", "food", 12)

    a = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 4},
        want={"wood": 2},
        motivation="m",
    )
    b = ledger.propose(
        proposer_id="rex",
        recipient_id="pixel",
        give={"cobblestone": 2},
        want={"food": 1},
        motivation="m",
    )
    assert isinstance(a, TradeOffer) and isinstance(b, TradeOffer)
    vera_pending = ledger.list_pending("vera")
    assert {o.offer_id for o in vera_pending} == {a.offer_id}
    pixel_pending = ledger.list_pending("pixel")
    assert {o.offer_id for o in pixel_pending} == {b.offer_id}


def test_ledger_rejects_self_trade_and_empty_trade(tmp_path: Path) -> None:
    ledger = TradeLedger(tmp_path)
    self_trade = ledger.propose(
        proposer_id="rex",
        recipient_id="rex",
        give={"cobblestone": 1},
        want={"wood": 1},
        motivation="m",
    )
    assert isinstance(self_trade, TradeFailure)
    assert self_trade.reason == "self_trade"

    empty = ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={},
        want={},
        motivation="m",
    )
    assert isinstance(empty, TradeFailure)
    assert empty.reason == "empty_trade"


def test_ledger_replay_restores_state(tmp_path: Path) -> None:
    ledger_a = TradeLedger(tmp_path)
    ledger_a.set_inventory("rex", "cobblestone", 64)
    ledger_a.set_inventory("vera", "wood", 32)
    offer = ledger_a.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={"cobblestone": 16},
        want={"wood": 8},
        motivation="m",
    )
    assert isinstance(offer, TradeOffer)
    accepted = ledger_a.accept(offer.offer_id, accepting_agent_id="vera")
    assert isinstance(accepted, TradeOffer)

    log_path = tmp_path / "trade_log.jsonl"
    assert log_path.is_file()
    lines = log_path.read_text().strip().splitlines()
    actions = [json.loads(line).get("action") for line in lines]
    assert "proposed" in actions
    assert "accepted" in actions

    ledger_b = TradeLedger(tmp_path)
    restored = ledger_b.get(offer.offer_id)
    assert restored is not None
    assert restored.status == "accepted"
    assert ledger_b.get_inventory("rex") == {"cobblestone": 48, "wood": 8}
    assert ledger_b.get_inventory("vera") == {"wood": 24, "cobblestone": 16}


def test_container_owned_items_transfer_ownership(tmp_path: Path) -> None:
    """Accepting a trade with container refs releases + re-claims via OwnershipLedger."""
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    trade_ledger = TradeLedger(sim_folder)
    ownership_ledger = OwnershipLedger(sim_folder)

    container_ref = {"x": 10, "y": 64, "z": 20, "dim": "overworld"}
    initial = ownership_ledger.claim(
        owner_agent_id="rex",
        target_type="container",
        target_ref=container_ref,
        motivation="ore chest",
    )
    assert isinstance(initial, OwnershipClaim)

    trade_ledger.set_inventory("vera", "food", 16)
    offer = trade_ledger.propose(
        proposer_id="rex",
        recipient_id="vera",
        give={},
        want={"food": 8},
        give_containers=[container_ref],
        motivation="ore chest for food",
    )
    assert isinstance(offer, TradeOffer)

    accepted = trade_ledger.accept(
        offer.offer_id,
        accepting_agent_id="vera",
        ownership_ledger=ownership_ledger,
    )
    assert isinstance(accepted, TradeOffer)

    # Container ownership now belongs to vera.
    new_owner = ownership_ledger.get("container", container_ref)
    assert new_owner is not None
    assert new_owner.owner_agent_id == "vera"


# ─── Tool layer ────────────────────────────────────────────────────────


def test_propose_tool_records_pending_offer_and_decision_log(tmp_path: Path) -> None:
    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 64)
    trade_ledger.set_inventory("vera", "wood", 32)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = ProposeTradeTool(
            agent_id="rex",
            ledger=trade_ledger,
            decision_logger=decision_logger,
        )
        result = asyncio.run(
            tool.execute(
                recipient_id="vera",
                give={"cobblestone": 16},
                want={"wood": 8},
                motivation="want wood",
            )
        )
    finally:
        decision_logger.close()

    assert result["status"] == "proposed"
    assert result["proposer_id"] == "rex"

    rows: list[DecisionLogRow] = list(DecisionLogReader(tmp_path).replay())
    trade_rows = [r for r in rows if isinstance(r, TradeEventRow)]
    assert len(trade_rows) == 1
    assert trade_rows[0].payload.action == "proposed"
    assert trade_rows[0].payload.proposer_id == "rex"


def test_accept_tool_swaps_and_logs(tmp_path: Path) -> None:
    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 64)
    trade_ledger.set_inventory("vera", "wood", 32)
    decision_logger = DecisionLogger(tmp_path)
    try:
        propose_tool = ProposeTradeTool(
            agent_id="rex", ledger=trade_ledger, decision_logger=decision_logger
        )
        proposed = asyncio.run(
            propose_tool.execute(
                recipient_id="vera",
                give={"cobblestone": 16},
                want={"wood": 8},
                motivation="m",
            )
        )
        accept_tool = AcceptTradeTool(
            agent_id="vera",
            ledger=trade_ledger,
            decision_logger=decision_logger,
        )
        accepted = asyncio.run(accept_tool.execute(offer_id=proposed["offer_id"]))
    finally:
        decision_logger.close()

    assert accepted["status"] == "accepted"
    assert trade_ledger.get_inventory("rex") == {"cobblestone": 48, "wood": 8}

    trade_actions = [
        r.payload.action
        for r in DecisionLogReader(tmp_path).replay()
        if isinstance(r, TradeEventRow)
    ]
    assert trade_actions == ["proposed", "accepted"]


def test_accept_tool_insufficient_inventory_returns_error(tmp_path: Path) -> None:
    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 4)
    trade_ledger.set_inventory("vera", "wood", 32)
    propose_tool = ProposeTradeTool(agent_id="rex", ledger=trade_ledger)
    proposed = asyncio.run(
        propose_tool.execute(
            recipient_id="vera",
            give={"cobblestone": 16},
            want={"wood": 8},
            motivation="m",
        )
    )
    accept_tool = AcceptTradeTool(agent_id="vera", ledger=trade_ledger)
    failed = asyncio.run(accept_tool.execute(offer_id=proposed["offer_id"]))
    assert failed["status"] == "error"
    assert failed["reason"] == "insufficient_inventory"
    # No state change.
    assert trade_ledger.get_inventory("rex") == {"cobblestone": 4}
    assert trade_ledger.get_inventory("vera") == {"wood": 32}


def test_reject_tool_records_reason(tmp_path: Path) -> None:
    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 64)
    trade_ledger.set_inventory("vera", "wood", 32)
    decision_logger = DecisionLogger(tmp_path)
    try:
        propose_tool = ProposeTradeTool(
            agent_id="rex", ledger=trade_ledger, decision_logger=decision_logger
        )
        proposed = asyncio.run(
            propose_tool.execute(
                recipient_id="vera",
                give={"cobblestone": 16},
                want={"wood": 8},
                motivation="m",
            )
        )
        reject_tool = RejectTradeTool(
            agent_id="vera", ledger=trade_ledger, decision_logger=decision_logger
        )
        rejected = asyncio.run(
            reject_tool.execute(offer_id=proposed["offer_id"], reason="too steep")
        )
    finally:
        decision_logger.close()
    assert rejected["status"] == "rejected"
    assert rejected["reject_reason"] == "too steep"


def test_list_pending_tool_filters_to_caller(tmp_path: Path) -> None:
    trade_ledger = TradeLedger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 64)
    trade_ledger.set_inventory("vera", "wood", 32)
    trade_ledger.set_inventory("pixel", "food", 12)
    propose_tool = ProposeTradeTool(agent_id="rex", ledger=trade_ledger)
    asyncio.run(
        propose_tool.execute(
            recipient_id="vera",
            give={"cobblestone": 4},
            want={"wood": 2},
            motivation="m",
        )
    )
    asyncio.run(
        propose_tool.execute(
            recipient_id="pixel",
            give={"cobblestone": 2},
            want={"food": 1},
            motivation="m",
        )
    )

    list_tool_vera = ListPendingTradesTool(agent_id="vera", ledger=trade_ledger)
    listing_vera = asyncio.run(list_tool_vera.execute())
    assert listing_vera["count"] == 1
    assert listing_vera["offers"][0]["recipient_id"] == "vera"

    list_tool_pixel = ListPendingTradesTool(agent_id="pixel", ledger=trade_ledger)
    listing_pixel = asyncio.run(list_tool_pixel.execute())
    assert listing_pixel["count"] == 1
    assert listing_pixel["offers"][0]["recipient_id"] == "pixel"


def test_tool_without_ledger_reports_unavailable() -> None:
    tool = ProposeTradeTool(agent_id="rex", ledger=None)
    result = asyncio.run(
        tool.execute(
            recipient_id="vera",
            give={"cobblestone": 1},
            want={"wood": 1},
            motivation="m",
        )
    )
    assert result == {"status": "error", "reason": "trade_ledger_unavailable"}


def test_accept_tool_with_container_transfers_ownership(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    trade_ledger = TradeLedger(sim_folder)
    ownership_ledger = OwnershipLedger(sim_folder)
    container_ref = {"x": 1, "y": 64, "z": 2, "dim": "overworld"}
    rex_claim = ownership_ledger.claim(
        owner_agent_id="rex",
        target_type="container",
        target_ref=container_ref,
        motivation="initial",
    )
    assert isinstance(rex_claim, OwnershipClaim)
    trade_ledger.set_inventory("vera", "food", 16)

    propose_tool = ProposeTradeTool(agent_id="rex", ledger=trade_ledger)
    proposed = asyncio.run(
        propose_tool.execute(
            recipient_id="vera",
            give={},
            want={"food": 8},
            give_containers=[container_ref],
            motivation="container for food",
        )
    )
    assert proposed["status"] == "proposed"

    accept_tool = AcceptTradeTool(
        agent_id="vera",
        ledger=trade_ledger,
        ownership_ledger=ownership_ledger,
    )
    accepted = asyncio.run(accept_tool.execute(offer_id=proposed["offer_id"]))
    assert accepted["status"] == "accepted"

    owner = ownership_ledger.get("container", container_ref)
    assert owner is not None
    assert owner.owner_agent_id == "vera"


# ─── Scorer + smoke counts ─────────────────────────────────────────────


def test_score_economic_behavior_picks_up_trade_events(tmp_path: Path) -> None:
    decision_logger = DecisionLogger(tmp_path)
    try:
        decision_logger.log_trade_event(
            offer_id="o1",
            proposer_id="rex",
            recipient_id="vera",
            give={"cobblestone": 16},
            want={"wood": 8},
            action="proposed",
            motivation="m",
        )
        decision_logger.log_trade_event(
            offer_id="o1",
            proposer_id="rex",
            recipient_id="vera",
            give={"cobblestone": 16},
            want={"wood": 8},
            action="accepted",
            motivation="m",
        )
        decision_logger.log_trade_event(
            offer_id="o2",
            proposer_id="pixel",
            recipient_id="sentinel",
            give={"food": 4},
            want={"cobblestone": 2},
            action="accepted",
            motivation="m",
        )
    finally:
        decision_logger.close()

    rows = list(DecisionLogReader(tmp_path).replay())
    signal = score_economic_behavior(rows)
    assert signal["sub_scores"]["accepted_trade_count"] == 2.0
    assert signal["sub_scores"]["distinct_trading_pairs"] == 2.0
    assert signal["trade"]["accepted_trade_count"] == 2
    # Price index aggregates the cobblestone→wood ratio (16/8 = 2.0).
    assert signal["trade"]["price_index"]["cobblestone"]["wood"] == pytest.approx(2.0)


def test_settlement_smoke_sub_counts_include_trade(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        decision_logger.log_trade_event(
            offer_id="o1",
            proposer_id="rex",
            recipient_id="vera",
            give={"cobblestone": 16},
            want={"wood": 8},
            action="proposed",
        )
        decision_logger.log_trade_event(
            offer_id="o1",
            proposer_id="rex",
            recipient_id="vera",
            give={"cobblestone": 16},
            want={"wood": 8},
            action="accepted",
        )
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["trade_events"] == 2
    assert outcome.sub_counts["distinct_trading_pairs"] == 1


# ─── YAML wiring ───────────────────────────────────────────────────────


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("agent_id", ["vera", "rex", "pixel", "sentinel", "fork"])
def test_trader_agents_have_trade_tools(agent_id: str) -> None:
    import yaml

    cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    for tool_name in (
        "propose_trade",
        "accept_trade",
        "reject_trade",
        "list_pending_trades",
    ):
        assert tool_name in cfg["tools"], f"{agent_id} missing {tool_name}"
