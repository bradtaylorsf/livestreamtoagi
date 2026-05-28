"""Unit tests for the civilization ownership ledger and tools (issue #891)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.civilization.ownership import (
    OwnershipClaim,
    OwnershipConflict,
    OwnershipLedger,
    canonical_target_ref,
    normalize_region_ref,
)
from core.eval.headless_signals import score_ownership
from core.eval.settlement_smoke_signals import classify_sim_folder
from core.simulation.decision_log_schema import (
    DecisionLogRow,
    OwnershipDeltaRow,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from tools.civilization import (
    ClaimOwnershipTool,
    GetOwnershipTool,
    ListMyClaimsTool,
    ReleaseOwnershipTool,
)

# ─── Ledger ────────────────────────────────────────────────────────────


def test_ledger_happy_path_structure_claim(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    result = ledger.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "build-abc"},
        motivation="my workshop",
    )
    assert isinstance(result, OwnershipClaim)
    assert result.owner_agent_id == "rex"
    assert result.target_type == "structure"
    assert result.target_ref == {"intent_id": "build-abc"}
    assert result.released_at is None

    fetched = ledger.get("structure", {"intent_id": "build-abc"})
    assert fetched is not None
    assert fetched.claim_id == result.claim_id


def test_ledger_second_claim_returns_conflict(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    first = ledger.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "build-abc"},
        motivation="my workshop",
    )
    assert isinstance(first, OwnershipClaim)
    second = ledger.claim(
        owner_agent_id="aurora",
        target_type="structure",
        target_ref={"intent_id": "build-abc"},
        motivation="creative space",
    )
    assert isinstance(second, OwnershipConflict)
    assert second.existing_owner_agent_id == "rex"
    assert second.existing_claim_id == first.claim_id


def test_ledger_overlapping_region_is_conflict(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    first = ledger.claim(
        owner_agent_id="vera",
        target_type="region",
        target_ref={"x1": 0, "z1": 0, "x2": 32, "z2": 32},
        motivation="north of spawn",
    )
    assert isinstance(first, OwnershipClaim)

    # Fully contained smaller box overlaps → conflict
    contained = ledger.claim(
        owner_agent_id="rex",
        target_type="region",
        target_ref={"x1": 5, "z1": 5, "x2": 10, "z2": 10},
        motivation="want a corner",
    )
    assert isinstance(contained, OwnershipConflict)
    assert contained.existing_owner_agent_id == "vera"

    # Disjoint box succeeds
    elsewhere = ledger.claim(
        owner_agent_id="rex",
        target_type="region",
        target_ref={"x1": 100, "z1": 100, "x2": 110, "z2": 110},
        motivation="my own spot",
    )
    assert isinstance(elsewhere, OwnershipClaim)


def test_ledger_release_then_reclaim(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    claim = ledger.claim(
        owner_agent_id="rex",
        target_type="container",
        target_ref={"x": 1, "y": 64, "z": 2},
        motivation="ore chest",
    )
    assert isinstance(claim, OwnershipClaim)
    released = ledger.release(claim.claim_id, reason="gifted to aurora")
    assert released is not None
    assert released.released_at is not None
    assert released.release_reason == "gifted to aurora"

    # Released slot is reclaimable by anyone (including a new agent)
    reclaim = ledger.claim(
        owner_agent_id="aurora",
        target_type="container",
        target_ref={"x": 1, "y": 64, "z": 2},
        motivation="gift accepted",
    )
    assert isinstance(reclaim, OwnershipClaim)
    assert reclaim.owner_agent_id == "aurora"
    assert reclaim.claim_id != claim.claim_id


def test_ledger_list_owned_by_introspection(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    a = ledger.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "a"},
        motivation="first",
    )
    b = ledger.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "b"},
        motivation="second",
    )
    ledger.claim(
        owner_agent_id="aurora",
        target_type="structure",
        target_ref={"intent_id": "c"},
        motivation="hers",
    )
    rex_claims = ledger.list_owned_by("rex")
    assert {c.claim_id for c in rex_claims} == {a.claim_id, b.claim_id}  # type: ignore[union-attr]


def test_ledger_persists_and_replays(tmp_path: Path) -> None:
    ledger_a = OwnershipLedger(tmp_path)
    claim = ledger_a.claim(
        owner_agent_id="rex",
        target_type="structure",
        target_ref={"intent_id": "build-abc"},
        motivation="workshop",
    )
    assert isinstance(claim, OwnershipClaim)
    aurora_attempt = ledger_a.claim(
        owner_agent_id="aurora",
        target_type="structure",
        target_ref={"intent_id": "build-abc"},
        motivation="contested",
    )
    assert isinstance(aurora_attempt, OwnershipConflict)
    ledger_a.release(claim.claim_id, reason="moving on")

    log_path = tmp_path / "ownership_log.jsonl"
    assert log_path.is_file()
    lines = log_path.read_text().strip().splitlines()
    actions = [json.loads(line)["action"] for line in lines]
    assert actions == ["claim", "conflict", "release"]

    # Fresh ledger replays the log — the released claim should NOT be
    # in the active index, so a new claim succeeds.
    ledger_b = OwnershipLedger(tmp_path)
    after_replay = ledger_b.get("structure", {"intent_id": "build-abc"})
    assert after_replay is None
    reclaim = ledger_b.claim(
        owner_agent_id="vera",
        target_type="structure",
        target_ref={"intent_id": "build-abc"},
        motivation="new owner",
    )
    assert isinstance(reclaim, OwnershipClaim)
    assert reclaim.owner_agent_id == "vera"


def test_canonical_region_normalizes_swapped_bounds() -> None:
    ref = normalize_region_ref({"x1": 10, "z1": 20, "x2": 0, "z2": 5})
    assert ref == {"x1": 0, "z1": 5, "x2": 10, "z2": 20, "dim": "overworld"}


def test_canonical_target_ref_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        canonical_target_ref("structure", {"foo": "bar"})


# ─── Tool layer ────────────────────────────────────────────────────────


def test_claim_tool_returns_claim_and_writes_decision_log(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    decision_logger = DecisionLogger(tmp_path)
    try:
        tool = ClaimOwnershipTool(
            agent_id="rex",
            ledger=ledger,
            decision_logger=decision_logger,
        )
        result = asyncio.run(
            tool.execute(
                target_type="structure",
                target_ref={"intent_id": "build-abc"},
                motivation="my workshop",
            )
        )
    finally:
        decision_logger.close()
    assert result["status"] == "claimed"
    assert result["owner_agent_id"] == "rex"
    assert result["target_type"] == "structure"
    assert result["target_ref"] == {"intent_id": "build-abc"}

    rows: list[DecisionLogRow] = list(DecisionLogReader(tmp_path).replay())
    deltas = [r for r in rows if isinstance(r, OwnershipDeltaRow)]
    assert len(deltas) == 1
    assert deltas[0].payload.action == "claim"
    assert deltas[0].payload.owner_agent_id == "rex"
    assert deltas[0].payload.target_ref == {"intent_id": "build-abc"}


def test_claim_tool_conflict_path_logs_conflict_row(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    decision_logger = DecisionLogger(tmp_path)
    try:
        rex_tool = ClaimOwnershipTool(
            agent_id="rex", ledger=ledger, decision_logger=decision_logger
        )
        aurora_tool = ClaimOwnershipTool(
            agent_id="aurora", ledger=ledger, decision_logger=decision_logger
        )
        first = asyncio.run(
            rex_tool.execute(
                target_type="structure",
                target_ref={"intent_id": "shared"},
                motivation="workshop",
            )
        )
        second = asyncio.run(
            aurora_tool.execute(
                target_type="structure",
                target_ref={"intent_id": "shared"},
                motivation="studio",
            )
        )
    finally:
        decision_logger.close()
    assert first["status"] == "claimed"
    assert second["status"] == "conflict"
    assert second["existing_owner_agent_id"] == "rex"

    deltas = [
        r
        for r in DecisionLogReader(tmp_path).replay()
        if isinstance(r, OwnershipDeltaRow)
    ]
    actions = [d.payload.action for d in deltas]
    assert actions == ["claim", "conflict"]


def test_release_tool_round_trip(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    decision_logger = DecisionLogger(tmp_path)
    try:
        claim_tool = ClaimOwnershipTool(
            agent_id="rex", ledger=ledger, decision_logger=decision_logger
        )
        release_tool = ReleaseOwnershipTool(
            agent_id="rex", ledger=ledger, decision_logger=decision_logger
        )
        claimed = asyncio.run(
            claim_tool.execute(
                target_type="structure",
                target_ref={"intent_id": "to-let-go"},
                motivation="for now",
            )
        )
        released = asyncio.run(
            release_tool.execute(
                claim_id=claimed["claim_id"],
                reason="no longer needed",
            )
        )
    finally:
        decision_logger.close()
    assert released["status"] == "released"
    assert released["release_reason"] == "no longer needed"


def test_get_and_list_tools(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    decision_logger = DecisionLogger(tmp_path)
    try:
        rex_claim = ClaimOwnershipTool(
            agent_id="rex", ledger=ledger, decision_logger=decision_logger
        )
        asyncio.run(
            rex_claim.execute(
                target_type="structure",
                target_ref={"intent_id": "mine"},
                motivation="mine",
            )
        )

        get_tool = GetOwnershipTool(agent_id="aurora", ledger=ledger)
        owned = asyncio.run(
            get_tool.execute(
                target_type="structure",
                target_ref={"intent_id": "mine"},
            )
        )
        assert owned["owned"] is True
        assert owned["owner_agent_id"] == "rex"
        none_yet = asyncio.run(
            get_tool.execute(
                target_type="structure",
                target_ref={"intent_id": "ghost"},
            )
        )
        assert none_yet == {"status": "ok", "owned": False}

        list_tool = ListMyClaimsTool(agent_id="rex", ledger=ledger)
        listing = asyncio.run(list_tool.execute())
        assert listing["count"] == 1
        assert listing["claims"][0]["target_ref"] == {"intent_id": "mine"}
    finally:
        decision_logger.close()


def test_claim_tool_rejects_missing_motivation(tmp_path: Path) -> None:
    ledger = OwnershipLedger(tmp_path)
    tool = ClaimOwnershipTool(agent_id="rex", ledger=ledger)
    result = asyncio.run(
        tool.execute(
            target_type="structure",
            target_ref={"intent_id": "x"},
            motivation="   ",
        )
    )
    assert result["status"] == "error"
    assert "motivation" in result["reason"]


def test_tool_without_ledger_reports_unavailable() -> None:
    tool = ClaimOwnershipTool(agent_id="rex", ledger=None)
    result = asyncio.run(
        tool.execute(
            target_type="structure",
            target_ref={"intent_id": "x"},
            motivation="m",
        )
    )
    assert result == {"status": "error", "reason": "ownership_ledger_unavailable"}


# ─── Scorer + smoke counts ─────────────────────────────────────────────


def test_score_ownership_picks_up_deltas(tmp_path: Path) -> None:
    decision_logger = DecisionLogger(tmp_path)
    try:
        decision_logger.log_ownership_delta(
            claim_id="c1",
            owner_agent_id="rex",
            target_type="structure",
            target_ref={"intent_id": "a"},
            action="claim",
            motivation="m",
        )
        decision_logger.log_ownership_delta(
            claim_id="c2",
            owner_agent_id="aurora",
            target_type="structure",
            target_ref={"intent_id": "b"},
            action="claim",
            motivation="m",
        )
        decision_logger.log_ownership_delta(
            claim_id="c1",
            owner_agent_id="aurora",
            target_type="structure",
            target_ref={"intent_id": "a"},
            action="conflict",
            motivation="contested",
        )
    finally:
        decision_logger.close()

    rows = list(DecisionLogReader(tmp_path).replay())
    signal = score_ownership(rows)
    assert signal["sub_scores"]["distinct_things_owned"] == 2.0
    assert signal["sub_scores"]["distinct_owners"] == 2.0
    assert signal["sub_scores"]["ownership_diversity"] == 1.0
    assert signal["sub_scores"]["conflict_count"] == 1.0
    assert signal["score"] > 0


def test_settlement_smoke_sub_counts_include_ownership(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    decision_logger = DecisionLogger(sim_folder)
    try:
        decision_logger.log_ownership_delta(
            claim_id="c1",
            owner_agent_id="rex",
            target_type="structure",
            target_ref={"intent_id": "a"},
            action="claim",
            motivation="m",
        )
        decision_logger.log_ownership_delta(
            claim_id="c2",
            owner_agent_id="aurora",
            target_type="structure",
            target_ref={"intent_id": "b"},
            action="claim",
            motivation="m",
        )
        decision_logger.log_ownership_delta(
            claim_id="c1",
            owner_agent_id="aurora",
            target_type="structure",
            target_ref={"intent_id": "a"},
            action="conflict",
            motivation="contested",
        )
    finally:
        decision_logger.close()

    outcome = classify_sim_folder(sim_folder)
    assert outcome.sub_counts["ownership_events"] == 3
    assert outcome.sub_counts["distinct_owners"] == 2


# ─── YAML wiring ───────────────────────────────────────────────────────


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("agent_id", ["vera", "rex", "aurora"])
def test_builder_agents_have_ownership_tools(agent_id: str) -> None:
    import yaml

    cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    for tool_name in (
        "claim_ownership",
        "release_ownership",
        "get_ownership",
        "list_my_claims",
    ):
        assert tool_name in cfg["tools"], f"{agent_id} missing {tool_name}"
