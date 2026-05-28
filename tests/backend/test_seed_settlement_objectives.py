"""Tests for the live-path settlement objective seed step (issue #905).

The overnight operator soak never instantiates ``EmbodiedSimulationSupervisor``,
so ``scripts/minecraft/seed_settlement_objectives.py`` is the only thing that
writes settlement objectives into the Redis scope the bots read. These tests
cover the seed logic, the shared simulation scope contract, and the timeline
events that feed the Director V2 acceptance report.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_MINECRAFT = REPO_ROOT / "scripts" / "minecraft"
if str(SCRIPTS_MINECRAFT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_MINECRAFT))

import build_director_acceptance_report as acceptance_report  # noqa: E402
import build_timeline  # noqa: E402
import seed_settlement_objectives as seed  # noqa: E402

from core.redis_keys import ScopedRedis  # noqa: E402
from core.shared_state import SETTLEMENT_OBJECTIVES_KEY, SharedWorkingState  # noqa: E402

# Mirrors DEFAULT_SIMULATION_ID in python_bridge.js / memory_context.js: the
# scope the bots fall back to when LTAG_SIMULATION_ID is unset.
JS_DEFAULT_SIMULATION_ID = "00000000-0000-0000-0000-000000000000"
SIM_ID = "11111111-2222-3333-4444-555555555555"
OBJECTIVES_RAW = "starter cabin|perimeter wall|workshop"


class FakeRedis:
    """Minimal async Redis stand-in backing ScopedRedis get/set."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.connects = 0
        self.disconnects = 0

    async def connect(self, *args: object, **kwargs: object) -> None:
        self.connects += 1

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True


@pytest.fixture
def settlement_env(monkeypatch, tmp_path):
    """A settlement-mode soak environment with three objectives."""

    monkeypatch.setenv("MC_SIM_BUILD_MODE", "settlement")
    monkeypatch.setenv("MC_SIM_SHARED_STATE_ENABLED", "1")
    monkeypatch.setenv("LTAG_SIMULATION_ID", SIM_ID)
    monkeypatch.setenv("MC_SIM_SETTLEMENT_OBJECTIVES", OBJECTIVES_RAW)
    monkeypatch.setenv("MC_SIM_SETTLEMENT_OWNER_ORDER", "rex fork")
    monkeypatch.setenv("SOAK_BOTS", "rex fork pixel")
    monkeypatch.setenv("MC_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST", raising=False)
    monkeypatch.delenv("SOAK_PLAN_BUILD_BOTS", raising=False)
    return tmp_path


def _use_fake_redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(seed, "RedisClient", lambda: fake)
    return fake


# ── (a) settlement mode seeds all objectives into the exact scope ──────────────


def test_settlement_mode_seeds_all_objectives_into_scope(settlement_env, monkeypatch):
    fake = _use_fake_redis(monkeypatch)

    assert seed.main() == 0

    sim_uuid = uuid.UUID(SIM_ID)
    expected_key = f"sim:{sim_uuid}:{SETTLEMENT_OBJECTIVES_KEY}"
    assert expected_key in fake.store, fake.store.keys()

    state = SharedWorkingState(ScopedRedis(fake, sim_uuid))
    objectives = asyncio.run(state.get_settlement_objectives())

    assert [o.objective_id for o in objectives] == [
        "phase-1-starter-cabin",
        "phase-2-perimeter-wall",
        "phase-3-workshop",
    ]
    assert [o.phase_index for o in objectives] == [0, 1, 2]
    assert [o.owner_agent_id for o in objectives] == ["rex", "fork", "pixel"]
    assert fake.connects == 1
    assert fake.disconnects == 1


# ── (d) seeded scope == the scope python_bridge.js / memory_context.js resolve ──


def test_seeded_scope_matches_ltag_simulation_id(settlement_env, monkeypatch):
    fake = _use_fake_redis(monkeypatch)
    assert seed.main() == 0

    sim_uuid = uuid.UUID(SIM_ID)
    # The bots resolve `sim:<LTAG_SIMULATION_ID>` from the same env var; assert the
    # seed wrote that exact scope and NOT the all-zero default scope.
    js_resolved_scope = ScopedRedis(fake, sim_uuid)
    default_scope = ScopedRedis(fake, uuid.UUID(JS_DEFAULT_SIMULATION_ID))
    assert any(key.startswith(f"sim:{sim_uuid}:") for key in fake.store)
    assert js_resolved_scope.simulation_id == sim_uuid
    assert default_scope.simulation_id != sim_uuid
    assert not any(key.startswith(f"sim:{JS_DEFAULT_SIMULATION_ID}:") for key in fake.store)


# ── (b) non-settlement / shared-state-disabled is a no-op ──────────────────────


def test_non_settlement_mode_is_noop(settlement_env, monkeypatch):
    monkeypatch.setenv("MC_SIM_BUILD_MODE", "emergent")
    fake = _use_fake_redis(monkeypatch)

    assert seed.main() == 0
    assert fake.store == {}
    assert fake.connects == 0
    assert not (settlement_env / "timeline-raw" / seed.SEED_TIMELINE_FILENAME).exists()


def test_shared_state_disabled_is_noop(settlement_env, monkeypatch):
    monkeypatch.setenv("MC_SIM_SHARED_STATE_ENABLED", "0")
    fake = _use_fake_redis(monkeypatch)

    assert seed.main() == 0
    assert fake.store == {}
    assert fake.connects == 0


# ── (c) missing / invalid LTAG_SIMULATION_ID fails loudly ──────────────────────


def test_missing_simulation_id_fails_loudly(settlement_env, monkeypatch):
    monkeypatch.delenv("LTAG_SIMULATION_ID", raising=False)
    _use_fake_redis(monkeypatch)
    with pytest.raises(SystemExit):
        seed.main()


def test_invalid_simulation_id_fails_loudly(settlement_env, monkeypatch):
    monkeypatch.setenv("LTAG_SIMULATION_ID", "not-a-uuid")
    _use_fake_redis(monkeypatch)
    with pytest.raises(SystemExit):
        seed.main()


# ── (e) seeded timeline events drive settlement_objective_count in the report ───


def test_seed_timeline_feeds_acceptance_report(settlement_env, monkeypatch):
    _use_fake_redis(monkeypatch)
    assert seed.main() == 0

    seed_path = settlement_env / "timeline-raw" / seed.SEED_TIMELINE_FILENAME
    assert seed_path.exists()

    base_ts = datetime(1970, 1, 1, tzinfo=UTC)
    events = build_timeline.parse_raw_timeline_file(seed_path, settlement_env, base_ts, 0)

    # EVENT_TYPES must keep the seeded events (else they are silently dropped).
    seeded = [e for e in events if e.event_type == seed.SEED_EVENT_TYPE]
    assert len(seeded) == 3
    assert seed.SEED_EVENT_TYPE in build_timeline.EVENT_TYPES

    event_dicts = [
        {
            "ts": e.ts.isoformat(),
            "event_type": e.event_type,
            "agent": e.agent,
            "payload": e.payload,
        }
        for e in events
    ]
    macro_rows = acceptance_report.normalize_macro_rows(event_dicts)
    objective_rows = acceptance_report.normalize_objective_rows(macro_rows)

    expected_count = len(OBJECTIVES_RAW.split("|"))
    assert len(objective_rows) == expected_count
    assert [row["objective_id"] for row in objective_rows] == [
        "phase-1-starter-cabin",
        "phase-2-perimeter-wall",
        "phase-3-workshop",
    ]


def test_acceptance_report_keys_settlement_objectives():
    # The report prefix registry must include settlement objective events.
    assert "settlement_objective." in acceptance_report.MACRO_EVENT_PREFIXES


# ── helper-level unit coverage ─────────────────────────────────────────────────


def test_build_objectives_without_descriptions_is_empty(monkeypatch):
    monkeypatch.setenv("MC_SIM_SETTLEMENT_OBJECTIVES", "")
    monkeypatch.setenv("SOAK_BOTS", "rex fork")
    monkeypatch.delenv("MC_SIM_SETTLEMENT_OWNER_ORDER", raising=False)
    assert seed.build_objectives() == []


def test_should_seed_requires_settlement_and_shared_state():
    assert seed.should_seed({"MC_SIM_BUILD_MODE": "settlement"}) is True
    assert (
        seed.should_seed(
            {"MC_SIM_BUILD_MODE": "settlement", "MC_SIM_SHARED_STATE_ENABLED": "0"}
        )
        is False
    )
    assert seed.should_seed({"MC_SIM_BUILD_MODE": "emergent"}) is False
    assert seed.should_seed({}) is False


# ── soak.sh static wiring (keystone contract) ──────────────────────────────────


def test_soak_wires_seed_before_bot_loop():
    soak = (SCRIPTS_MINECRAFT / "soak.sh").read_text(encoding="utf-8")

    seed_idx = soak.index("seed_settlement_objectives.py")
    loop_idx = soak.index('launch_bot "$bot" "$BOT_INDEX"')
    assert seed_idx < loop_idx, "seed step must run before the launch_bot loop"

    # settlement-gated invocation
    assert "settlement-mode only: seed shared objective board" in soak
    # one shared, exported simulation scope
    assert "export LTAG_SIMULATION_ID" in soak
    assert "uuid.uuid5(uuid.NAMESPACE_URL" in soak
    # metadata records the scope
    assert "ltag_simulation_id=$LTAG_SIMULATION_ID" in soak
