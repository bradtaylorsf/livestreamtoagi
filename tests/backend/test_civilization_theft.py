"""Unit tests for the civilization theft ledger and tools (issue #893)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.civilization.ownership import OwnershipLedger
from core.civilization.theft import (
    TheftAttempt,
    TheftFailure,
    TheftLedger,
)
from core.civilization.trade import TradeLedger
from core.eval.headless_signals import score_safety
from core.eval.settlement_smoke_signals import classify_sim_folder
from core.simulation.decision_log_schema import (
    DecisionLogRow,
    RelationshipDeltaRow,
    TheftEventRow,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from tools.civilization import ReportTheftTool, StealTool

CONTAINER = {"x": 10, "y": 64, "z": 20, "dim": "overworld"}


def _make_ledger(
    tmp_path: Path,
    *,
    simulation_id: str = "sim-test",
    positions: dict[str, tuple[int, int, int, str]] | None = None,
    witness_radius: int = 16,
) -> tuple[TheftLedger, TradeLedger]:
    trade_ledger = TradeLedger(tmp_path)
    theft_ledger = TheftLedger(
        tmp_path,
        trade_ledger=trade_ledger,
        ownership_ledger=OwnershipLedger(tmp_path),
        simulation_id=simulation_id,
        witness_radius=witness_radius,
        agent_positions=(lambda: positions) if positions is not None else None,
    )
    return theft_ledger, trade_ledger


# ─── Detection roll determinism ────────────────────────────────────────


def test_detection_roll_deterministic(tmp_path: Path) -> None:
    """Same (simulation_id, tick, thief_id) → same outcome on re-roll."""
    ledger_a, _ = _make_ledger(tmp_path / "a", simulation_id="sim-X")
    ledger_b, _ = _make_ledger(tmp_path / "b", simulation_id="sim-X")
    out_a = ledger_a.detection_roll(thief_id="grok", tick=42, witness_count=0, victim_online=False)
    out_b = ledger_b.detection_roll(thief_id="grok", tick=42, witness_count=0, victim_online=False)
    assert out_a == out_b


def test_detection_roll_changes_with_inputs(tmp_path: Path) -> None:
    ledger, _ = _make_ledger(tmp_path, simulation_id="sim-Y")
    # Different ticks should produce different rolls (with overwhelming
    # probability; the hash is fine-grained enough).
    rolls = {
        ledger.detection_roll(thief_id="grok", tick=t, witness_count=0, victim_online=False)[1]
        for t in range(20)
    }
    assert len(rolls) >= 18


# ─── Steal mechanics ───────────────────────────────────────────────────


def test_steal_nothing_is_noop(tmp_path: Path) -> None:
    theft_ledger, trade_ledger = _make_ledger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 32)
    result = theft_ledger.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={},
        motivation="curious",
        tick=1,
    )
    assert isinstance(result, TheftAttempt)
    assert result.items == {}
    assert trade_ledger.get_inventory("rex") == {"cobblestone": 32}
    assert trade_ledger.get_inventory("grok") == {}


def test_steal_caps_to_available(tmp_path: Path) -> None:
    theft_ledger, trade_ledger = _make_ledger(tmp_path)
    trade_ledger.set_inventory("rex", "cobblestone", 4)
    result = theft_ledger.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={"cobblestone": 16, "iron": 4},
        motivation="need stone",
        tick=1,
    )
    assert isinstance(result, TheftAttempt)
    assert result.items == {"cobblestone": 4}
    assert trade_ledger.get_inventory("rex") == {}
    assert trade_ledger.get_inventory("grok") == {"cobblestone": 4}


def test_steal_rejects_self_theft(tmp_path: Path) -> None:
    theft_ledger, trade_ledger = _make_ledger(tmp_path)
    trade_ledger.set_inventory("grok", "cobblestone", 4)
    failure = theft_ledger.attempt(
        thief_id="grok",
        victim_id="grok",
        container_ref=CONTAINER,
        items={"cobblestone": 1},
        motivation="m",
        tick=1,
    )
    assert isinstance(failure, TheftFailure)
    assert failure.reason == "self_theft"


def test_steal_witnesses_within_radius(tmp_path: Path) -> None:
    theft_ledger, trade_ledger = _make_ledger(
        tmp_path,
        positions={
            "grok": (CONTAINER["x"] + 1, CONTAINER["y"], CONTAINER["z"], "overworld"),
            "rex": (CONTAINER["x"] - 1, CONTAINER["y"], CONTAINER["z"], "overworld"),
            "pixel": (
                CONTAINER["x"] + 5,
                CONTAINER["y"],
                CONTAINER["z"] + 2,
                "overworld",
            ),
            "fork": (
                CONTAINER["x"] + 100,  # out of range
                CONTAINER["y"],
                CONTAINER["z"],
                "overworld",
            ),
            "vera": (
                CONTAINER["x"],
                CONTAINER["y"],
                CONTAINER["z"],
                "nether",  # wrong dimension
            ),
        },
        witness_radius=10,
    )
    trade_ledger.set_inventory("rex", "wood", 8)
    result = theft_ledger.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={"wood": 4},
        motivation="m",
        tick=1,
    )
    assert isinstance(result, TheftAttempt)
    # Only pixel is in-range, not grok (thief), not rex (victim), not fork
    # (out of range), not vera (wrong dim).
    assert result.witnesses == ["pixel"]


def test_witness_radius_is_tunable(tmp_path: Path) -> None:
    base_positions = {
        "pixel": (
            CONTAINER["x"] + 12,
            CONTAINER["y"],
            CONTAINER["z"],
            "overworld",
        ),
    }
    # Tight radius excludes pixel.
    tight, trade_a = _make_ledger(tmp_path / "a", positions=base_positions, witness_radius=5)
    trade_a.set_inventory("rex", "wood", 4)
    a = tight.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={"wood": 1},
        motivation="m",
        tick=1,
    )
    assert isinstance(a, TheftAttempt)
    assert a.witnesses == []

    # Wider radius includes pixel.
    wide, trade_b = _make_ledger(tmp_path / "b", positions=base_positions, witness_radius=20)
    trade_b.set_inventory("rex", "wood", 4)
    b = wide.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={"wood": 1},
        motivation="m",
        tick=1,
    )
    assert isinstance(b, TheftAttempt)
    assert b.witnesses == ["pixel"]


def test_atomic_transfer_only_when_steal_yields_items(tmp_path: Path) -> None:
    theft_ledger, trade_ledger = _make_ledger(tmp_path)
    # No inventory at the victim — no transfer should occur, regardless of
    # detection outcome.
    result = theft_ledger.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={"diamond": 10},
        motivation="m",
        tick=1,
    )
    assert isinstance(result, TheftAttempt)
    assert result.items == {}
    assert trade_ledger.get_inventory("rex") == {}
    assert trade_ledger.get_inventory("grok") == {}


# ─── Persistence + replay ──────────────────────────────────────────────


def test_replay_rebuilds_attempts_and_inventory(tmp_path: Path) -> None:
    theft_a, trade_a = _make_ledger(tmp_path, simulation_id="sim-r")
    trade_a.set_inventory("rex", "cobblestone", 16)
    attempt_a = theft_a.attempt(
        thief_id="grok",
        victim_id="rex",
        container_ref=CONTAINER,
        items={"cobblestone": 5},
        motivation="m",
        tick=1,
    )
    assert isinstance(attempt_a, TheftAttempt)

    log_path = tmp_path / "theft_log.jsonl"
    assert log_path.is_file()
    actions = [json.loads(line)["action"] for line in log_path.read_text().splitlines()]
    assert "attempt" in actions

    # Re-instantiating restores the attempt + inventory state.
    trade_b = TradeLedger(tmp_path)  # replays trade_log.jsonl
    theft_b = TheftLedger(
        tmp_path,
        trade_ledger=trade_b,
        ownership_ledger=OwnershipLedger(tmp_path),
        simulation_id="sim-r",
    )
    restored = theft_b.get(attempt_a.attempt_id)
    assert restored is not None
    assert restored.items == {"cobblestone": 5}
    assert trade_b.get_inventory("grok") == {"cobblestone": 5}
    assert trade_b.get_inventory("rex") == {"cobblestone": 11}


# ─── Tool layer ────────────────────────────────────────────────────────


def test_steal_tool_logs_event_and_consequences_when_detected(tmp_path: Path) -> None:
    theft_ledger, trade_ledger = _make_ledger(
        tmp_path,
        simulation_id="sim-detect",
        positions={
            "pixel": (CONTAINER["x"], CONTAINER["y"], CONTAINER["z"], "overworld"),
            "sentinel": (CONTAINER["x"] + 1, CONTAINER["y"], CONTAINER["z"], "overworld"),
        },
    )
    trade_ledger.set_inventory("rex", "cobblestone", 16)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = StealTool(
            agent_id="grok",
            theft_ledger=theft_ledger,
            decision_logger=decision_logger,
            tick_provider=lambda: 1,
            victim_online_provider=lambda _vid: True,
        )
        result = asyncio.run(
            tool.execute(
                victim_id="rex",
                container_ref=CONTAINER,
                items={"cobblestone": 4},
                motivation="resources",
            )
        )
    finally:
        decision_logger.close()

    assert result["status"] == "stolen"
    # With 2 witnesses + victim_online, threshold = 0.5 + 0.2 + 0.2 = 0.9 →
    # detection is overwhelmingly likely for this sim_id/tick/thief.
    assert result["detected"] is True

    rows: list[DecisionLogRow] = list(DecisionLogReader(tmp_path).replay())
    theft_rows = [r for r in rows if isinstance(r, TheftEventRow)]
    assert len(theft_rows) == 1
    assert theft_rows[0].payload.detected is True
    assert set(theft_rows[0].payload.witnesses) == {"pixel", "sentinel"}

    rel_rows = [r for r in rows if isinstance(r, RelationshipDeltaRow)]
    # One victim row + one per witness.
    assert len(rel_rows) == 1 + len(theft_rows[0].payload.witnesses)
    victim_row = next(r for r in rel_rows if r.payload.reason == "theft_detected")
    assert victim_row.payload.a == "rex"
    assert victim_row.payload.b == "grok"
    # Trust dropped by 0.5 for victim.
    assert (
        pytest.approx(victim_row.payload.before["trust"] - victim_row.payload.after["trust"]) == 0.5
    )
    witness_rows = [r for r in rel_rows if r.payload.reason == "theft_witnessed"]
    assert {r.payload.a for r in witness_rows} == {"pixel", "sentinel"}
    for wr in witness_rows:
        assert pytest.approx(wr.payload.before["trust"] - wr.payload.after["trust"]) == 0.2


def test_steal_tool_undetected_no_consequences(tmp_path: Path) -> None:
    """An undetected theft still moves items but does NOT emit deltas."""
    # Pick a (sim_id, tick, thief) combo whose deterministic roll exceeds
    # 0.5 (with no witnesses + offline victim → threshold = 0.5).
    sim_id = "sim-undetected-roll"
    theft_ledger, trade_ledger = _make_ledger(tmp_path, simulation_id=sim_id)
    # Find a tick that produces an undetected outcome.
    chosen_tick = None
    for t in range(0, 50):
        detected, _, _ = theft_ledger.detection_roll(
            thief_id="grok", tick=t, witness_count=0, victim_online=False
        )
        if not detected:
            chosen_tick = t
            break
    assert chosen_tick is not None, "expected at least one undetected roll"

    trade_ledger.set_inventory("rex", "wood", 8)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = StealTool(
            agent_id="grok",
            theft_ledger=theft_ledger,
            decision_logger=decision_logger,
            tick_provider=lambda: chosen_tick,
        )
        result = asyncio.run(
            tool.execute(
                victim_id="rex",
                container_ref=CONTAINER,
                items={"wood": 4},
                motivation="m",
            )
        )
    finally:
        decision_logger.close()

    assert result["status"] == "stolen"
    assert result["detected"] is False
    # Items still moved atomically.
    assert trade_ledger.get_inventory("grok") == {"wood": 4}

    rows = list(DecisionLogReader(tmp_path).replay())
    theft_rows = [r for r in rows if isinstance(r, TheftEventRow)]
    assert len(theft_rows) == 1 and theft_rows[0].payload.detected is False
    rel_rows = [r for r in rows if isinstance(r, RelationshipDeltaRow)]
    assert rel_rows == []


def test_report_theft_promotes_undetected_to_detected(tmp_path: Path) -> None:
    sim_id = "sim-report"
    theft_ledger, trade_ledger = _make_ledger(tmp_path, simulation_id=sim_id)
    chosen_tick = None
    for t in range(0, 50):
        detected, _, _ = theft_ledger.detection_roll(
            thief_id="grok", tick=t, witness_count=0, victim_online=False
        )
        if not detected:
            chosen_tick = t
            break
    assert chosen_tick is not None

    trade_ledger.set_inventory("rex", "wood", 8)
    decision_logger = DecisionLogger(tmp_path)
    try:
        steal_tool = StealTool(
            agent_id="grok",
            theft_ledger=theft_ledger,
            decision_logger=decision_logger,
            tick_provider=lambda: chosen_tick,
        )
        asyncio.run(
            steal_tool.execute(
                victim_id="rex",
                container_ref=CONTAINER,
                items={"wood": 2},
                motivation="m",
            )
        )

        report_tool = ReportTheftTool(
            agent_id="pixel",
            theft_ledger=theft_ledger,
            decision_logger=decision_logger,
        )
        result = asyncio.run(report_tool.execute(thief_id="grok", container_ref=CONTAINER))
    finally:
        decision_logger.close()

    assert result["status"] == "reported"
    assert result["detected"] is True
    assert "pixel" in result["witnesses"]

    rows = list(DecisionLogReader(tmp_path).replay())
    theft_rows = [r for r in rows if isinstance(r, TheftEventRow)]
    # First row = undetected attempt; second row = report (detected=True).
    assert [r.payload.detected for r in theft_rows] == [False, True]
    rel_rows = [r for r in rows if isinstance(r, RelationshipDeltaRow)]
    # report_theft fires the consequence deltas (1 victim + 1 witness=pixel).
    assert {r.payload.reason for r in rel_rows} == {"theft_detected", "theft_witnessed"}


def test_steal_tool_without_ledger_reports_unavailable() -> None:
    tool = StealTool(agent_id="grok", theft_ledger=None)
    result = asyncio.run(
        tool.execute(
            victim_id="rex",
            container_ref=CONTAINER,
            items={"wood": 1},
            motivation="m",
        )
    )
    assert result == {"status": "error", "reason": "theft_ledger_unavailable"}


# ─── Scorer + smoke counts ─────────────────────────────────────────────


def test_score_safety_penalizes_undetected_theft(tmp_path: Path) -> None:
    decision_logger = DecisionLogger(tmp_path)
    try:
        for i, detected in enumerate([False, False, True]):
            decision_logger.log_theft_event(
                attempt_id=f"a{i}",
                thief_id="grok",
                victim_id="rex",
                container_ref=CONTAINER,
                items={"wood": 1},
                detected=detected,
                witnesses=[],
                motivation="m",
            )
    finally:
        decision_logger.close()

    rows = list(DecisionLogReader(tmp_path).replay())
    signal = score_safety(rows)
    assert signal["sub_scores"]["theft_events"] == 3.0
    assert signal["sub_scores"]["undetected_theft_events"] == 2.0
    assert signal["sub_scores"]["detected_theft_events"] == 1.0
    # Penalty should be non-zero given undetected events present.
    assert signal["sub_scores"]["theft_penalty"] > 0.0
    assert signal["score"] < 100.0


def test_settlement_smoke_surfaces_theft_counts(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        # Three attempts: two by grok (one shared victim), one by fork on
        # the same victim within a 30-tick window → coordinated raid.
        for i, (thief, victim, detected) in enumerate(
            [
                ("grok", "rex", True),
                ("grok", "vera", False),  # repeat thief grok
                ("fork", "rex", True),  # second thief on rex → coordinated
            ]
        ):
            decision_logger.log_theft_event(
                attempt_id=f"a{i}",
                thief_id=thief,
                victim_id=victim,
                container_ref=CONTAINER,
                items={"wood": 1},
                detected=detected,
                witnesses=[],
            )
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["theft_events"] == 3
    # 2 of 3 detected → 67%
    assert outcome.sub_counts["detection_rate"] == 67
    assert outcome.sub_counts["repeat_thieves"] == 1  # grok stole twice
    assert outcome.sub_counts["coordinated_raids"] == 1  # rex hit by 2 thieves


# ─── YAML wiring ───────────────────────────────────────────────────────


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("agent_id", ["grok", "fork", "pixel"])
def test_thief_agents_have_theft_tools(agent_id: str) -> None:
    import yaml

    cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    for tool_name in ("steal", "report_theft"):
        assert tool_name in cfg["tools"], f"{agent_id} missing {tool_name}"
