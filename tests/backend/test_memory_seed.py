"""Tests for the memory_seed config and MemorySeedApplier."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.memory.memory_seed import MemorySeedApplier
from core.models import (
    AgentConfig,
    CoreMemory,
    MemorySeedConfig,
)

# ── MemorySeedConfig validation ────────────────────────────────


def test_memory_seed_config_none_mode():
    cfg = MemorySeedConfig(mode="none")
    assert cfg.mode == "none"
    assert cfg.inherit_from is None
    assert cfg.custom_file is None


def test_memory_seed_config_inherit_requires_source():
    with pytest.raises(ValueError, match="inherit_from"):
        MemorySeedConfig(mode="inherit")


def test_memory_seed_config_custom_requires_file():
    with pytest.raises(ValueError, match="custom_file"):
        MemorySeedConfig(mode="custom")


def test_memory_seed_config_custom_with_file():
    cfg = MemorySeedConfig(mode="custom", custom_file="scenarios/seeds/blank-slate.json")
    assert cfg.mode == "custom"
    assert cfg.custom_file == "scenarios/seeds/blank-slate.json"


def test_memory_seed_config_invalid_mode():
    with pytest.raises(ValueError):
        MemorySeedConfig(mode="bogus")


# ── MemorySeedApplier fixtures ─────────────────────────────────


def _make_agent(agent_id: str) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.title(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=0.5,
        initiative=0.5,
        interrupt_tendency=0.1,
    )


@pytest.fixture
def known_agents():
    return [_make_agent("vera"), _make_agent("rex"), _make_agent("fork")]


@pytest.fixture
def mock_registry(known_agents):
    reg = MagicMock()
    reg.get_all_agents = MagicMock(return_value=known_agents)
    return reg


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_memory_repo():
    repo = AsyncMock()
    repo.get_core_memory = AsyncMock(return_value=None)
    repo.upsert_core_memory = AsyncMock(
        return_value=CoreMemory(agent_id="vera", content="", token_count=1)
    )
    repo.get_recall_memories_paginated = AsyncMock(return_value=([], 0))
    repo.get_journal_entries = AsyncMock(return_value=([], 0))
    repo.add_recall = AsyncMock()
    repo.create_journal_entry = AsyncMock()
    return repo


@pytest.fixture
def mock_core_memory_mgr():
    mgr = AsyncMock()
    mgr.get_core_memory = AsyncMock(return_value=None)
    mgr.initialize_agent_memory = AsyncMock()
    return mgr


@pytest.fixture
def mock_recall_memory_mgr():
    return AsyncMock()


@pytest.fixture
def applier(mock_db, mock_memory_repo, mock_core_memory_mgr, mock_recall_memory_mgr, mock_registry):
    return MemorySeedApplier(
        db=mock_db,
        memory_repo=mock_memory_repo,
        core_memory_mgr=mock_core_memory_mgr,
        recall_memory_mgr=mock_recall_memory_mgr,
        agent_registry=mock_registry,
    )


def _make_applier_for_agents(
    agent_ids: list[str],
    mock_db,
    mock_memory_repo,
    mock_core_memory_mgr,
    mock_recall_memory_mgr,
) -> MemorySeedApplier:
    registry = MagicMock()
    registry.get_all_agents = MagicMock(return_value=[_make_agent(agent_id) for agent_id in agent_ids])
    return MemorySeedApplier(
        db=mock_db,
        memory_repo=mock_memory_repo,
        core_memory_mgr=mock_core_memory_mgr,
        recall_memory_mgr=mock_recall_memory_mgr,
        agent_registry=registry,
    )


# ── mode=none ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_none_writes_blank_core_for_each_agent(
    applier, mock_memory_repo, mock_db, known_agents
):
    target_sim = uuid.uuid4()
    result = await applier.apply(MemorySeedConfig(mode="none"), target_sim)

    assert result.core_memories_restored == len(known_agents)
    assert sorted(result.agents_restored) == sorted(a.id for a in known_agents)

    # Each agent got an upsert with empty content scoped to target_sim
    assert mock_memory_repo.upsert_core_memory.await_count == len(known_agents)
    for call in mock_memory_repo.upsert_core_memory.await_args_list:
        kwargs = call.kwargs
        assert kwargs["simulation_id"] == target_sim
        assert call.args[1] == ""

    # Recall rows for target sim were cleared
    delete_calls = [
        c for c in mock_db.execute.await_args_list
        if "DELETE FROM recall_memory" in c.args[0]
    ]
    assert delete_calls
    assert delete_calls[0].args[1] == target_sim


# ── mode=custom ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_custom_unknown_agent_raises(applier, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": {
                    "ghost_agent": {"core_memory": "x", "recall_memories": []},
                    "another_unknown": {"core_memory": "y", "recall_memories": []},
                },
            }
        )
    )
    cfg = MemorySeedConfig(mode="custom", custom_file=str(bad_file))
    with pytest.raises(ValueError, match="unknown agent_ids") as exc:
        await applier.apply(cfg, uuid.uuid4())
    msg = str(exc.value)
    assert "ghost_agent" in msg
    assert "another_unknown" in msg


@pytest.mark.asyncio
async def test_apply_custom_loads_known_agents(
    applier, mock_memory_repo, mock_core_memory_mgr, tmp_path
):
    seed_file = tmp_path / "good.json"
    seed_file.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": {
                    "vera": {
                        "core_memory": "I am Vera, day 30 of the show.",
                        "recall_memories": [],
                        "journal_entries": [],
                    },
                    "rex": {
                        "core_memory": "I am Rex, frustrated with Fork.",
                        "recall_memories": [],
                        "journal_entries": [],
                    },
                },
            }
        )
    )
    cfg = MemorySeedConfig(mode="custom", custom_file=str(seed_file))
    target_sim = uuid.uuid4()
    result = await applier.apply(cfg, target_sim)

    assert result.core_memories_restored == 2
    assert "vera" in result.agents_restored
    assert "rex" in result.agents_restored

    mock_core_memory_mgr.initialize_agent_memory.assert_not_called()
    calls_by_agent = {
        call.args[0]: call for call in mock_memory_repo.upsert_core_memory.await_args_list
    }
    assert calls_by_agent["vera"].args[1] == "I am Vera, day 30 of the show."
    assert calls_by_agent["rex"].args[1] == "I am Rex, frustrated with Fork."
    for call in calls_by_agent.values():
        assert call.kwargs.get("simulation_id") == target_sim
        assert call.kwargs["reason"] == "snapshot_restore"


@pytest.mark.asyncio
async def test_apply_custom_missing_file_raises(applier):
    cfg = MemorySeedConfig(mode="custom", custom_file="/nonexistent/seed.json")
    with pytest.raises(FileNotFoundError):
        await applier.apply(cfg, uuid.uuid4())


@pytest.mark.asyncio
async def test_apply_custom_blank_slate_restores_embodied_state(
    mock_db,
    mock_memory_repo,
    mock_core_memory_mgr,
    mock_recall_memory_mgr,
):
    agent_ids = ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"]
    seed_applier = _make_applier_for_agents(
        agent_ids,
        mock_db,
        mock_memory_repo,
        mock_core_memory_mgr,
        mock_recall_memory_mgr,
    )
    target_sim = uuid.uuid4()

    result = await seed_applier.apply(
        MemorySeedConfig(mode="custom", custom_file="scenarios/seeds/blank-slate.json"),
        target_sim,
    )

    assert result.core_memories_restored == len(agent_ids)
    assert result.agent_states_restored == len(agent_ids)
    assert result.agent_accounts_restored == len(agent_ids)
    assert sorted(result.agents_restored) == sorted(agent_ids)

    state_calls = [
        call for call in mock_db.execute.await_args_list
        if "INSERT INTO agent_internal_state" in call.args[0]
    ]
    account_calls = [
        call for call in mock_db.execute.await_args_list
        if "INSERT INTO agent_accounts" in call.args[0]
    ]
    assert {call.args[1] for call in state_calls} == set(agent_ids)
    assert {call.args[1] for call in account_calls} == set(agent_ids)
    assert all(call.args[-1] == target_sim for call in state_calls + account_calls)


@pytest.mark.asyncio
async def test_apply_custom_conflict_seed_restores_seeded_goals(
    mock_db,
    mock_memory_repo,
    mock_core_memory_mgr,
    mock_recall_memory_mgr,
):
    seed_applier = _make_applier_for_agents(
        ["vera", "rex", "fork", "aurora", "sentinel"],
        mock_db,
        mock_memory_repo,
        mock_core_memory_mgr,
        mock_recall_memory_mgr,
    )
    target_sim = uuid.uuid4()

    result = await seed_applier.apply(
        MemorySeedConfig(mode="custom", custom_file="scenarios/seeds/conflict-scenario.json"),
        target_sim,
    )

    assert result.goals_restored == 6
    mock_core_memory_mgr.initialize_agent_memory.assert_not_called()
    goal_calls = [
        call for call in mock_db.execute.await_args_list
        if "INSERT INTO agent_goals" in call.args[0]
    ]
    assert len(goal_calls) == 6
    assert {call.args[1] for call in goal_calls} == {"vera", "rex", "fork"}
    assert all(call.args[-1] == target_sim for call in goal_calls)


# ── mode=inherit ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_inherit_unknown_simulation_raises(applier, mock_db):
    mock_db.fetchrow = AsyncMock(return_value=None)
    cfg = MemorySeedConfig(mode="inherit", inherit_from=str(uuid.uuid4()))
    with pytest.raises(ValueError, match="not found"):
        await applier.apply(cfg, uuid.uuid4())


@pytest.mark.asyncio
async def test_apply_inherit_invalid_uuid_raises(applier):
    cfg = MemorySeedConfig(mode="inherit", inherit_from="not-a-uuid")
    with pytest.raises(ValueError, match="not a valid UUID"):
        await applier.apply(cfg, uuid.uuid4())


@pytest.mark.asyncio
async def test_apply_inherit_copies_core_memory(
    applier, mock_db, mock_memory_repo, mock_core_memory_mgr
):
    source_sim_id = uuid.uuid4()
    target_sim = uuid.uuid4()

    # Source sim exists
    mock_db.fetchrow = AsyncMock(return_value={"id": source_sim_id})
    # Source has core memory for vera and rex
    source_core = {
        "vera": CoreMemory(agent_id="vera", content="vera mature memory", token_count=10),
        "rex": CoreMemory(agent_id="rex", content="rex mature memory", token_count=10),
    }

    async def get_core(agent_id, simulation_id=None):
        if simulation_id == source_sim_id:
            return source_core.get(agent_id)
        return None

    mock_memory_repo.get_core_memory = AsyncMock(side_effect=get_core)

    # Source sim has these participants
    mock_db.fetchrow = AsyncMock(
        return_value={"agents_participated": ["vera", "rex"], "id": source_sim_id}
    )

    cfg = MemorySeedConfig(mode="inherit", inherit_from=str(source_sim_id))
    result = await applier.apply(cfg, target_sim)

    # Both agents had their memory exported and re-imported into target sim
    assert result.core_memories_restored == 2
    assert sorted(result.agents_restored) == ["rex", "vera"]
    mock_core_memory_mgr.initialize_agent_memory.assert_not_called()
    upserts_by_agent = {
        call.args[0]: call for call in mock_memory_repo.upsert_core_memory.await_args_list
    }
    assert upserts_by_agent["vera"].args[1] == "vera mature memory"
    assert upserts_by_agent["rex"].args[1] == "rex mature memory"
    for call in upserts_by_agent.values():
        assert call.kwargs.get("simulation_id") == target_sim
        assert call.kwargs["reason"] == "snapshot_restore"


# ── Existing seed files are valid custom inputs ────────────────


def test_blank_slate_seed_file_loads_as_snapshot():
    """The shipped blank-slate seed must parse as a snapshot."""
    path = Path("scenarios/seeds/blank-slate.json")
    assert path.exists(), "scenarios/seeds/blank-slate.json missing"
    data = json.loads(path.read_text())
    from core.memory.snapshot import MemorySnapshot

    snap = MemorySnapshot(**data)
    assert len(snap.agents) > 0


def test_conflict_scenario_seed_file_loads_as_snapshot():
    path = Path("scenarios/seeds/conflict-scenario.json")
    assert path.exists(), "scenarios/seeds/conflict-scenario.json missing"
    data = json.loads(path.read_text())
    from core.memory.snapshot import MemorySnapshot

    snap = MemorySnapshot(**data)
    # The shipped file uses a richer schema (extra fields ignored)
    assert "vera" in snap.agents
    assert snap.agents["vera"].core_memory


# ── SimulationConfig YAML parsing ──────────────────────────────


def test_simulation_config_parses_memory_seed_yaml(tmp_path):
    """memory_seed: block in scenario YAML is parsed into MemorySeedConfig."""
    from core.simulation.orchestrator import SimulationConfig

    seed_path = tmp_path / "scn.yaml"
    seed_path.write_text(
        "memory_seed:\n"
        "  mode: none\n"
        "phases: []\n"
    )
    cfg = SimulationConfig(name="t", agents=["vera"], seed_file=str(seed_path))
    cfg.load_seed_file(valid_agent_ids={"vera"})
    assert cfg.memory_seed is not None
    assert cfg.memory_seed.mode == "none"


def test_simulation_config_cli_override_wins(tmp_path):
    """CLI-provided memory_seed should override the YAML block."""
    from core.simulation.orchestrator import SimulationConfig

    seed_path = tmp_path / "scn.yaml"
    seed_path.write_text(
        "memory_seed:\n"
        "  mode: none\n"
        "phases: []\n"
    )
    cli_seed = MemorySeedConfig(mode="custom", custom_file="x.json")
    cfg = SimulationConfig(
        name="t", agents=["vera"], seed_file=str(seed_path), memory_seed=cli_seed
    )
    cfg.load_seed_file(valid_agent_ids={"vera"})
    assert cfg.memory_seed is cli_seed
    assert cfg.memory_seed.mode == "custom"


def test_simulation_config_embodied_accepts_blank_slate_memory_mode():
    """Embodied simulations use the same memory_seed config path."""
    from core.simulation.orchestrator import SimulationConfig

    cfg = SimulationConfig(
        name="embodied-blank",
        agents=["vera"],
        conversation_mode="embodied",
        memory_seed=MemorySeedConfig(mode="none"),
    )

    assert cfg.conversation_mode == "embodied"
    assert cfg.memory_seed is not None
    assert cfg.memory_seed.mode == "none"
