"""Embodied simulation supervisor lifecycle coverage (#710)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.models import ManagementPolicy, RunMode, SimulationStatus
from core.simulation.embodied_supervisor import (
    EmbodiedSimulationSupervisor,
    _preferred_runtime_path_prefixes,
    _prepend_runtime_paths,
)
from core.simulation.orchestrator import SimulationConfig


def _sim(sim_id: uuid.UUID, **overrides: Any) -> SimpleNamespace:
    base = {
        "id": sim_id,
        "name": "embodied-test",
        "status": SimulationStatus.running.value,
        "started_at": datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        "total_turns": 0,
        "total_artifacts": 0,
        "config": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _repo(sim: SimpleNamespace) -> SimpleNamespace:
    repo = SimpleNamespace()
    repo.create = AsyncMock(return_value=sim)
    repo.get = AsyncMock(return_value=sim)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.update_config = AsyncMock()
    repo.update_status = AsyncMock(return_value=sim)
    repo.update_durations = AsyncMock(return_value=sim)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("0"))
    repo.get_rolling_cost_from_events = AsyncMock(return_value=Decimal("0"))
    return repo


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True


def _experimental_config(**overrides: Any) -> SimulationConfig:
    kwargs: dict[str, Any] = {
        "name": "embodied-test",
        "agents": ["vera", "rex"],
        "run_mode": RunMode.experimental,
        "duration": timedelta(minutes=15),
        "conversation_mode": "embodied",
        "max_cost": 1,
    }
    kwargs.update(overrides)
    return SimulationConfig(**kwargs)


def test_runtime_path_prefers_installed_node20(tmp_path: Path) -> None:
    node20_bin = tmp_path / ".nvm" / "versions" / "node" / "v20.20.2" / "bin"
    node20_bin.mkdir(parents=True)

    prefixes = _preferred_runtime_path_prefixes(home=tmp_path, static_dirs=())
    path = _prepend_runtime_paths("/usr/bin", prefixes)

    assert prefixes == [str(node20_bin)]
    assert path.split(":")[:2] == [str(node20_bin), "/usr/bin"]


@pytest.mark.asyncio
async def test_alpha_is_regular_agent_without_implicit_town_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    captured: dict[str, Any] = {}
    monkeypatch.delenv("MC_SIM_ALPHA_TOWN_PLANNER", raising=False)
    monkeypatch.delenv("MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS", raising=False)

    async def runner(command, env, cwd, supervisor):
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(agents=["alpha", "vera", "rex"]),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    await supervisor.run()

    assert captured["env"]["SOAK_BOTS"] == "alpha vera rex"
    assert "MC_SIM_ALPHA_TOWN_PLANNER" not in captured["env"]
    assert "MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS" not in captured["env"]


@pytest.mark.asyncio
async def test_minecraft_easy_mode_aliases_soak_harness_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    captured: dict[str, Any] = {}
    monkeypatch.setenv("MC_SIM_EASY_MODE", "1")
    monkeypatch.setenv("MC_SIM_KEEP_SERVER_RUNNING", "1")
    monkeypatch.setenv("MC_SIM_MC_PORT", "25577")
    monkeypatch.delenv("SOAK_EASY_SPAWN", raising=False)
    monkeypatch.delenv("SERVER_DIR", raising=False)
    monkeypatch.delenv("WORLD_CONFIG", raising=False)
    monkeypatch.delenv("MC_PORT", raising=False)
    monkeypatch.delenv("SERVER_PORT", raising=False)

    async def runner(command, env, cwd, supervisor):
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(agents=["alpha", "vera", "rex"]),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    await supervisor.run()

    env = captured["env"]
    assert env["SOAK_EASY_SPAWN"] == "1"
    assert env["SERVER_DIR"] == str(tmp_path / "minecraft-server-easy")
    assert env["WORLD_CONFIG"] == str(tmp_path / "scripts" / "minecraft" / "world-easy.config")
    assert env["MC_HOST"] == "127.0.0.1"
    assert env["MC_PORT"] == "25577"
    assert env["SERVER_PORT"] == "25577"
    assert env["WHITELIST"] == "false"
    assert env["SOAK_KEEP_MINECRAFT_RUNNING"] == "1"


@pytest.mark.asyncio
async def test_settlement_easy_mode_defaults_to_large_open_meadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    captured: dict[str, Any] = {}
    monkeypatch.setenv("MC_SIM_EASY_MODE", "1")
    monkeypatch.setenv("MC_SIM_BUILD_MODE", "settlement")
    monkeypatch.delenv("EASY_SETUP_MEADOW_RADIUS", raising=False)
    monkeypatch.delenv("EASY_SETUP_BOUNDARY", raising=False)
    monkeypatch.delenv("EASY_SETUP_ANIMALS", raising=False)

    async def runner(command, env, cwd, supervisor):
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(agents=["alpha", "vera", "rex"]),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    await supervisor.run()

    assert captured["env"]["EASY_SETUP_MEADOW_RADIUS"] == "96"
    assert captured["env"]["EASY_SETUP_BOUNDARY"] == "none"
    assert captured["env"]["EASY_SETUP_ANIMALS"] == "1"
    assert captured["env"]["MC_SIM_SETTLEMENT_ORIGIN"] == "0,64,0"


@pytest.mark.asyncio
async def test_management_policy_propagates_to_minecraft_child_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    captured: dict[str, Any] = {}
    monkeypatch.setenv("MC_SIM_MANAGEMENT_POLICY", "shadow")
    monkeypatch.setenv("MINECRAFT_MANAGEMENT_REVIEW_MODE", "shadow")

    async def runner(command, env, cwd, supervisor):
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(management_policy=ManagementPolicy.off),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    await supervisor.run()

    assert captured["env"]["MC_SIM_MANAGEMENT_POLICY"] == "off"
    assert captured["env"]["MINECRAFT_MANAGEMENT_REVIEW_MODE"] == "off"


@pytest.mark.asyncio
async def test_experimental_run_propagates_one_id_to_minecraft_and_end_hooks(
    tmp_path: Path,
) -> None:
    sim_id = uuid.uuid4()
    sim = _sim(sim_id)
    repo = _repo(sim)
    captured: dict[str, Any] = {}
    hooks: list[str] = []

    async def runner(command, env, cwd, supervisor):
        captured["command"] = command
        captured["env"] = env
        captured["cwd"] = cwd
        assert supervisor.simulation_id == sim_id
        return 0

    async def eval_hook(supervisor):
        hooks.append(f"eval:{supervisor.simulation_id}")

    async def report_hook(supervisor):
        hooks.append(f"report:{supervisor.run_id}")

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        eval_hook=eval_hook,
        report_hook=report_hook,
        run_id="run-embodied-test",
        run_dir=tmp_path / "evidence",
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.completed
    assert result.simulation_id == sim_id
    assert result.run_id == "run-embodied-test"
    assert captured["env"]["LTAG_RUN_ID"] == "run-embodied-test"
    assert captured["env"]["LTAG_SIMULATION_ID"] == str(sim_id)
    assert captured["env"]["MC_RUN_DIR"] == str(tmp_path / "evidence")
    assert captured["env"]["SOAK_BOTS"] == "vera rex"
    assert captured["command"][:1] == [str(tmp_path / "scripts" / "minecraft" / "soak.sh")]
    assert "--duration-hours" in captured["command"]
    assert hooks == [f"eval:{sim_id}", "report:run-embodied-test"]
    repo.create.assert_awaited_once()
    repo.update_status.assert_awaited()


@pytest.mark.asyncio
async def test_settlement_mode_seeds_shared_objectives_and_init_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_id = uuid.uuid4()
    sim = _sim(sim_id)
    repo = _repo(sim)
    redis = _FakeRedis()
    captured: dict[str, Any] = {}

    monkeypatch.setenv("MC_SIM_BUILD_MODE", "settlement")
    monkeypatch.setenv(
        "MC_SIM_SETTLEMENT_OBJECTIVES",
        "starter cabin|perimeter wall|workshop station",
    )
    monkeypatch.setenv("SOAK_EASY_SPAWN", "1")
    monkeypatch.setenv("MC_SIM_SHARED_STATE_ENABLED", "1")
    monkeypatch.delenv("SOAK_INIT_MESSAGE", raising=False)
    monkeypatch.delenv("MC_SIM_ACTIVE_OBJECTIVE_JSON", raising=False)
    monkeypatch.delenv("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST", raising=False)
    monkeypatch.delenv("SOAK_PLAN_BUILD_BOTS", raising=False)

    async def runner(command, env, cwd, supervisor):
        captured["command"] = command
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(
            agents=["vera", "rex", "aurora"],
            conversation_mode="director_v2",
        ),
        simulation_repo=repo,
        redis_client=redis,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
        run_id="run-settlement",
        run_dir=tmp_path / "evidence",
    )

    await supervisor.run()

    env = captured["env"]
    assert env["SOAK_PROFILE"] == "director_v2"
    assert env["SOAK_BOTS"] == "vera rex aurora"
    assert "starter cabin|perimeter wall|workshop station" in env["SOAK_INIT_MESSAGE"]
    assert '!planAndBuild("small shared cabin")' in env["SOAK_INIT_MESSAGE"]
    active = json.loads(env["MC_SIM_ACTIVE_OBJECTIVE_JSON"])
    assert active == {
        "objective_id": "phase-1-starter-cabin",
        "phase_index": 0,
        "description": "starter cabin",
        "owner_agent_id": "rex",
        "status": "pending",
        "previous_owner_agent_ids": [],
        "owner_started_at_ms": None,
        "stale_after_ms": None,
        "cooldown_until_ms": None,
    }
    stored = json.loads(redis.store[f"sim:{sim_id}:shared:settlement_objectives"])
    assert [item["description"] for item in stored] == [
        "starter cabin",
        "perimeter wall",
        "workshop station",
    ]
    assert [item["objective_id"] for item in stored] == [
        "phase-1-starter-cabin",
        "phase-2-perimeter-wall",
        "phase-3-workshop-station",
    ]
    assert [item["owner_agent_id"] for item in stored] == ["rex", "aurora", "vera"]
    assert "--profile" in captured["command"]


@pytest.mark.asyncio
async def test_settlement_objective_owners_respect_plan_build_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_id = uuid.uuid4()
    sim = _sim(sim_id)
    repo = _repo(sim)
    redis = _FakeRedis()
    captured: dict[str, Any] = {}

    monkeypatch.setenv("MC_SIM_BUILD_MODE", "settlement")
    monkeypatch.setenv(
        "MC_SIM_SETTLEMENT_OBJECTIVES",
        "ember workshop|grove workshop|ember animal pen|grove route post",
    )
    monkeypatch.setenv(
        "MC_SIM_SETTLEMENT_OWNER_ORDER",
        "rex,fork,alpha,aurora,vera,pixel",
    )
    monkeypatch.setenv("SOAK_PLAN_BUILD_BOTS", "rex fork")
    monkeypatch.setenv("MC_SIM_SHARED_STATE_ENABLED", "1")
    monkeypatch.delenv("SOAK_INIT_MESSAGE", raising=False)
    monkeypatch.delenv("MC_SIM_ACTIVE_OBJECTIVE_JSON", raising=False)
    monkeypatch.delenv("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST", raising=False)

    async def runner(command, env, cwd, supervisor):
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(
            agents=["alpha", "vera", "rex", "aurora", "pixel", "fork"],
            conversation_mode="director_v2",
        ),
        simulation_repo=repo,
        redis_client=redis,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
        run_id="run-settlement-allowlist",
        run_dir=tmp_path / "evidence",
    )

    await supervisor.run()

    active = json.loads(captured["env"]["MC_SIM_ACTIVE_OBJECTIVE_JSON"])
    assert active["owner_agent_id"] == "rex"
    stored = json.loads(redis.store[f"sim:{sim_id}:shared:settlement_objectives"])
    assert [item["owner_agent_id"] for item in stored] == ["rex", "fork", "rex", "fork"]


@pytest.mark.asyncio
async def test_settlement_allowlist_all_is_unrestricted_not_literal_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sim_id = uuid.uuid4()
    sim = _sim(sim_id)
    repo = _repo(sim)
    redis = _FakeRedis()
    captured: dict[str, Any] = {}

    monkeypatch.setenv("MC_SIM_BUILD_MODE", "settlement")
    monkeypatch.setenv("MC_SIM_SETTLEMENT_OBJECTIVES", "crafting hall|garden")
    monkeypatch.setenv("MC_SIM_SETTLEMENT_OWNER_ORDER", "alpha,rex")
    monkeypatch.setenv("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST", "all")
    monkeypatch.setenv("MC_SIM_SHARED_STATE_ENABLED", "1")
    monkeypatch.delenv("SOAK_PLAN_BUILD_BOTS", raising=False)
    monkeypatch.delenv("SOAK_INIT_MESSAGE", raising=False)
    monkeypatch.delenv("MC_SIM_ACTIVE_OBJECTIVE_JSON", raising=False)

    async def runner(command, env, cwd, supervisor):
        captured["env"] = env
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(
            agents=["alpha", "rex", "vera"],
            conversation_mode="director_v2",
        ),
        simulation_repo=repo,
        redis_client=redis,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
        run_id="run-settlement-all",
        run_dir=tmp_path / "evidence",
    )

    await supervisor.run()

    active = json.loads(captured["env"]["MC_SIM_ACTIVE_OBJECTIVE_JSON"])
    assert active["owner_agent_id"] == "alpha"
    stored = json.loads(redis.store[f"sim:{sim_id}:shared:settlement_objectives"])
    assert [item["owner_agent_id"] for item in stored] == ["alpha", "rex"]


@pytest.mark.asyncio
async def test_experimental_run_delegates_duration_to_minecraft_harness(
    tmp_path: Path,
) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    captured: dict[str, Any] = {}

    async def runner(command, env, cwd, supervisor):
        supervisor.clock.advance(timedelta(minutes=20))
        assert await supervisor.should_stop() is False
        captured["command"] = command
        return 0

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(duration=timedelta(minutes=15)),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.completed
    assert result.stop_reason == "completed"
    assert "--duration-hours" in captured["command"]
    repo.update_status.assert_awaited()
    assert repo.update_status.await_args.args[1] == SimulationStatus.completed.value


@pytest.mark.asyncio
async def test_persistent_run_has_no_duration_and_honors_kill_switch(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    redis = SimpleNamespace(get=AsyncMock(return_value=KILL_SWITCH_ACTIVE_VALUE))

    async def runner(command, env, cwd, supervisor):
        raise AssertionError("kill switch should stop before launching Minecraft")

    config = SimulationConfig(
        name="live-embodied",
        agents=["vera"],
        run_mode=RunMode.persistent,
        conversation_mode="embodied",
        max_cost_rolling=Decimal("5"),
        rolling_window=timedelta(hours=1),
    )
    supervisor = EmbodiedSimulationSupervisor(
        config=config,
        simulation_repo=repo,
        redis_client=redis,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "kill_switch"
    redis.get.assert_awaited_with(KILL_SWITCH_KEY)


@pytest.mark.asyncio
async def test_cost_cap_stops_before_launch(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    repo.get_total_cost_from_events = AsyncMock(return_value=Decimal("2"))

    async def runner(command, env, cwd, supervisor):
        raise AssertionError("cost cap should stop before launching Minecraft")

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(max_cost=Decimal("1")),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        run_eval=False,
        run_report=False,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "cost_cap"


@pytest.mark.asyncio
async def test_cadence_tick_invokes_reflection_hook(tmp_path: Path) -> None:
    sim = _sim(uuid.uuid4())
    repo = _repo(sim)
    reflected: list[str] = []

    async def runner(command, env, cwd, supervisor):
        await supervisor.cadence_tick()
        await supervisor.cadence_tick()
        supervisor.cancel()
        return -15

    async def reflection_hook(supervisor):
        reflected.append(str(supervisor.simulation_id))

    supervisor = EmbodiedSimulationSupervisor(
        config=_experimental_config(),
        simulation_repo=repo,
        project_root=tmp_path,
        command_runner=runner,
        reflection_hook=reflection_hook,
        run_eval=False,
        run_report=False,
        poll_interval_seconds=1,
    )

    result = await supervisor.run()

    assert result.status == SimulationStatus.cancelled
    assert result.stop_reason == "cancelled"
    assert reflected == [str(sim.id), str(sim.id)]
