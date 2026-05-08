"""Tests for the simulation orchestrator: config, phases, display, and orchestration."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from core.models import Simulation, SimulationStatus
from core.simulation.display import SimulationDisplay
from core.simulation.orchestrator import (
    CostLimitExceededError,
    SimulationConfig,
    SimulationOrchestrator,
    parse_duration,
)
from core.simulation.phases import Phase, PhaseResult, PhaseRunner, PhaseType

# ── Helpers ─────────────────────────────────────────────────────


def make_seed_file(phases: list[dict[str, Any]]) -> str:
    """Write a temporary YAML seed file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump({"phases": phases}, f)
    return path


def make_simulation_row(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "test-sim",
        "description": "Test simulation",
        "config": {"agents": ["vera", "rex"]},
        "status": "running",
        "started_at": datetime(2026, 4, 3, 12, 0, tzinfo=UTC),
        "completed_at": None,
        "simulated_duration": None,
        "real_duration": None,
        "total_conversations": 0,
        "total_turns": 0,
        "total_tokens": 0,
        "total_cost": Decimal("0"),
        "total_artifacts": 0,
        "total_management_flags": 0,
        "agents_participated": ["vera", "rex"],
        "error_log": None,
        "model_versions": {},
        "created_at": datetime(2026, 4, 3, 12, 0, tzinfo=UTC),
        "hypothesis": None,
        "outcomes": {},
        "learnings": [],
        "factions": [],
    }
    base.update(overrides)
    return base


def _make_agent_registry() -> MagicMock:
    """Create an agent registry mock with proper string model fields."""
    registry = MagicMock()
    vera = MagicMock()
    vera.model_conversation = "claude-haiku-4-5"
    vera.model_building = "claude-sonnet-4-6"
    rex = MagicMock()
    rex.model_conversation = "claude-haiku-4-5"
    rex.model_building = "claude-sonnet-4-6"
    registry.get_agent.side_effect = lambda aid: {"vera": vera, "rex": rex}.get(aid)
    return registry


def make_mock_services() -> dict[str, Any]:
    """Create a full set of mocked services for the orchestrator."""
    sim_id = uuid.uuid4()
    sim = Simulation(**make_simulation_row(id=sim_id))

    sim_repo = MagicMock()
    sim_repo.create = AsyncMock(return_value=sim)
    sim_repo.get = AsyncMock(return_value=sim)
    sim_repo.increment_stats = AsyncMock(return_value=sim)
    sim_repo.update_status = AsyncMock(return_value=sim)
    sim_repo.update_durations = AsyncMock(return_value=sim)
    sim_repo.update_config = AsyncMock(return_value=sim)
    sim_repo.update_agents_participated = AsyncMock()

    redis_mock = MagicMock()
    redis_mock.get = AsyncMock(return_value=None)

    return {
        "db": MagicMock(),
        "redis_client": redis_mock,
        "simulation_repo": sim_repo,
        "config_loader": MagicMock(),
        "agent_registry": _make_agent_registry(),
        "event_bus": MagicMock(emit=AsyncMock()),
        "llm_client": MagicMock(),
        "management": MagicMock(),
        "context_assembler": MagicMock(),
        "conversation_repo": MagicMock(),
        "archival_memory": MagicMock(),
        "proximity": MagicMock(),
        "trigger_system": MagicMock(),
        "selection_logger": MagicMock(),
        "reflection_manager": MagicMock(),
        "display": SimulationDisplay(verbose=False),
        "sim_id": sim_id,
        "sim": sim,
    }


# ── SimulationConfig tests ──────────────────────────────────────


class TestSimulationConfig:
    def test_load_seed_file_parses_phases(self):
        phases = [
            {"name": "standup", "type": "scheduled", "trigger": "standup"},
            {"name": "chat", "type": "organic", "count": 2},
            {"name": "challenge", "type": "challenge", "challenge": {"title": "test"}},
        ]
        path = make_seed_file(phases)
        try:
            config = SimulationConfig(
                name="test",
                seed_file=path,
                agents=["vera", "rex"],
            )
            config.load_seed_file()

            assert len(config.phases) == 3
            assert config.phases[0].name == "standup"
            assert config.phases[0].type == PhaseType.scheduled
            assert config.phases[1].type == PhaseType.organic
            assert config.phases[2].type == PhaseType.challenge
        finally:
            os.unlink(path)

    def test_load_seed_file_unknown_type_defaults_to_organic(self):
        phases = [{"name": "mystery", "type": "unknown_type"}]
        path = make_seed_file(phases)
        try:
            config = SimulationConfig(name="test", seed_file=path, agents=["vera"])
            config.load_seed_file()
            assert config.phases[0].type == PhaseType.organic
        finally:
            os.unlink(path)

    def test_to_dict_serializes_config(self):
        phases = [{"name": "standup", "type": "scheduled"}]
        path = make_seed_file(phases)
        try:
            config = SimulationConfig(
                name="my-sim",
                description="A test",
                seed_file=path,
                agents=["vera", "rex"],
                max_cost=5.0,
            )
            config.load_seed_file()
            d = config.to_dict()
            assert d["name"] == "my-sim"
            assert d["max_cost"] == "5.0"
            assert d["phase_count"] == 1
            assert d["phase_names"] == ["standup"]
        finally:
            os.unlink(path)

    def test_required_agents_extracted_from_phase(self):
        phases = [
            {"name": "standup", "type": "scheduled", "required_agents": ["vera", "rex"]}
        ]
        path = make_seed_file(phases)
        try:
            config = SimulationConfig(name="test", seed_file=path, agents=["vera"])
            config.load_seed_file()
            assert config.phases[0].required_agents == ["vera", "rex"]
        finally:
            os.unlink(path)


# ── Phase / PhaseResult tests ───────────────────────────────────


class TestPhaseDataclasses:
    def test_phase_defaults(self):
        p = Phase(name="test", type=PhaseType.organic)
        assert p.config == {}
        assert p.required_agents == []

    def test_phase_result_defaults(self):
        r = PhaseResult()
        assert r.status == "completed"
        assert r.turns == 0
        assert r.cost == Decimal("0")
        assert r.errors == []
        assert r.agents_participated == []

    def test_phase_type_values(self):
        assert PhaseType.scheduled == "scheduled"
        assert PhaseType.organic == "organic"
        assert PhaseType.challenge == "challenge"
        assert PhaseType.tool_exercise == "tool_exercise"
        assert PhaseType.reflection == "reflection"
        assert PhaseType.audience_sim == "audience_sim"


# ── PhaseRunner tests ───────────────────────────────────────────


class TestPhaseRunner:
    def _make_runner(self, *, dry_run: bool = False) -> PhaseRunner:
        return PhaseRunner(
            config_loader=MagicMock(),
            agent_registry=MagicMock(),
            event_bus=MagicMock(emit=AsyncMock()),
            llm_client=MagicMock(),
            management=MagicMock(),
            context_assembler=MagicMock(),
            conversation_repo=MagicMock(),
            archival_memory=MagicMock(),
            proximity=MagicMock(),
            trigger_system=MagicMock(),
            selection_logger=MagicMock(),
            reflection_manager=MagicMock(),
            simulation_id=uuid.uuid4(),
            agents=["vera", "rex", "aurora"],
            dry_run=dry_run,
        )

    @pytest.mark.asyncio
    async def test_run_phase_unknown_type_returns_skipped(self):
        runner = self._make_runner()
        # Manually create a phase with an invalid type string to test the fallback
        phase = Phase(name="bad", type=PhaseType.organic)
        # Monkey-patch to an unrecognized value
        phase.type = "nonexistent"  # type: ignore[assignment]
        result = await runner.run_phase(phase)
        assert result.status == "skipped"

    @pytest.mark.asyncio
    async def test_dry_run_reflection_logs_without_calling_llm(self):
        runner = self._make_runner(dry_run=True)
        phase = Phase(
            name="reflect",
            type=PhaseType.reflection,
            config={"reflection_type": "6hour"},
        )
        result = await runner.run_phase(phase)
        assert result.status == "completed"
        # Reflection manager should NOT have been called in dry-run
        runner._reflection.run_6hour_reflection.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_scheduled_logs_without_conversation(self):
        runner = self._make_runner(dry_run=True)
        phase = Phase(
            name="standup",
            type=PhaseType.scheduled,
            config={"trigger": "standup"},
            required_agents=["vera"],
        )
        result = await runner.run_phase(phase)
        assert result.status == "completed"
        assert result.turns == 0

    @pytest.mark.asyncio
    async def test_reflection_phase_calls_reflection_manager(self):
        runner = self._make_runner(dry_run=False)
        runner._reflection.run_6hour_reflection = AsyncMock(
            return_value=MagicMock(promoted_count=1, importance_updates=2)
        )
        phase = Phase(
            name="reflect",
            type=PhaseType.reflection,
            config={"reflection_type": "6hour", "agents": ["vera"]},
        )
        result = await runner.run_phase(phase)
        assert result.status == "completed"
        runner._reflection.run_6hour_reflection.assert_awaited_once_with("vera")

    @pytest.mark.asyncio
    async def test_reflection_weekly_calls_weekly_method(self):
        runner = self._make_runner(dry_run=False)
        runner._reflection.run_weekly_reflection = AsyncMock(
            return_value=MagicMock(promoted_count=0, importance_updates=0)
        )
        phase = Phase(
            name="weekly",
            type=PhaseType.reflection,
            config={"reflection_type": "weekly", "agents": ["rex"]},
        )
        await runner.run_phase(phase)
        runner._reflection.run_weekly_reflection.assert_awaited_once_with("rex")

    @pytest.mark.asyncio
    async def test_phase_runner_catches_exceptions(self):
        runner = self._make_runner(dry_run=False)
        runner._reflection.run_6hour_reflection = AsyncMock(
            side_effect=RuntimeError("LLM down")
        )
        phase = Phase(
            name="reflect",
            type=PhaseType.reflection,
            config={"reflection_type": "6hour", "agents": ["vera"]},
        )
        # Should not raise — errors are caught and logged
        result = await runner.run_phase(phase)
        assert result.status == "completed"  # reflection errors don't fail the phase


# ── SimulationOrchestrator tests ────────────────────────────────


class TestSimulationOrchestrator:
    def _make_orchestrator(
        self, phases: list[dict[str, Any]], *, dry_run: bool = True, max_cost: float = 10.0
    ) -> tuple[SimulationOrchestrator, dict[str, Any]]:
        path = make_seed_file(phases)
        config = SimulationConfig(
            name="test-run",
            description="Test",
            seed_file=path,
            agents=["vera", "rex"],
            max_cost=max_cost,
            dry_run=dry_run,
        )
        config.load_seed_file()

        services = make_mock_services()
        orchestrator = SimulationOrchestrator(
            config=config,
            db=services["db"],
            redis_client=services["redis_client"],
            simulation_repo=services["simulation_repo"],
            config_loader=services["config_loader"],
            agent_registry=services["agent_registry"],
            event_bus=services["event_bus"],
            llm_client=services["llm_client"],
            management=services["management"],
            context_assembler=services["context_assembler"],
            conversation_repo=services["conversation_repo"],
            archival_memory=services["archival_memory"],
            proximity=services["proximity"],
            trigger_system=services["trigger_system"],
            selection_logger=services["selection_logger"],
            reflection_manager=services["reflection_manager"],
            display=services["display"],
        )
        return orchestrator, services

    @pytest.mark.asyncio
    async def test_dry_run_creates_simulation_record(self):
        orchestrator, services = self._make_orchestrator(
            [{"name": "standup", "type": "scheduled"}],
            dry_run=True,
        )
        await orchestrator.run()
        services["simulation_repo"].create.assert_awaited_once()
        call_args = services["simulation_repo"].create.call_args
        sim_create = call_args[0][0]
        assert sim_create.name == "test-run"
        assert sim_create.status == SimulationStatus.running

    @pytest.mark.asyncio
    async def test_existing_sim_id_attaches_instead_of_creating(self):
        """When the API pre-creates a sim row, the orchestrator must reuse it.

        This is what lets the dashboard launcher redirect to /simulations/[id]
        immediately on POST instead of waiting for the orchestrator to insert.
        """
        path = make_seed_file([{"name": "standup", "type": "scheduled"}])
        services = make_mock_services()
        existing_id = services["sim_id"]

        config = SimulationConfig(
            name="dashboard-test",
            seed_file=path,
            agents=["vera", "rex"],
            dry_run=True,
            existing_sim_id=str(existing_id),
        )
        config.load_seed_file()

        orchestrator = SimulationOrchestrator(
            config=config,
            db=services["db"],
            redis_client=services["redis_client"],
            simulation_repo=services["simulation_repo"],
            config_loader=services["config_loader"],
            agent_registry=services["agent_registry"],
            event_bus=services["event_bus"],
            llm_client=services["llm_client"],
            management=services["management"],
            context_assembler=services["context_assembler"],
            conversation_repo=services["conversation_repo"],
            archival_memory=services["archival_memory"],
            proximity=services["proximity"],
            trigger_system=services["trigger_system"],
            selection_logger=services["selection_logger"],
            reflection_manager=services["reflection_manager"],
            display=services["display"],
        )
        await orchestrator.run()

        # Must NOT create a new row — must fetch the pre-created one and
        # transition it to "running".
        services["simulation_repo"].create.assert_not_called()
        services["simulation_repo"].update_status.assert_any_await(
            existing_id, SimulationStatus.running
        )
        services["simulation_repo"].update_config.assert_awaited()
        services["simulation_repo"].update_agents_participated.assert_awaited()

    @pytest.mark.asyncio
    async def test_dry_run_finalizes_as_completed(self):
        orchestrator, services = self._make_orchestrator(
            [{"name": "standup", "type": "scheduled"}],
            dry_run=True,
        )
        await orchestrator.run()
        services["simulation_repo"].update_status.assert_awaited_once()
        status_call = services["simulation_repo"].update_status.call_args
        assert status_call[0][1] == SimulationStatus.completed.value

    @pytest.mark.asyncio
    async def test_cancel_sets_cancelled_status(self):
        orchestrator, services = self._make_orchestrator(
            [
                {"name": "phase1", "type": "scheduled"},
                {"name": "phase2", "type": "organic"},
            ],
            dry_run=True,
        )
        # Cancel before running
        orchestrator.cancel()
        await orchestrator.run()
        status_call = services["simulation_repo"].update_status.call_args
        assert status_call[0][1] == SimulationStatus.cancelled.value

    @pytest.mark.asyncio
    async def test_cost_limit_stops_simulation(self):
        orchestrator, services = self._make_orchestrator(
            [{"name": "phase1", "type": "scheduled"}],
            dry_run=False,
            max_cost=0.001,
        )
        # Simulate a phase that costs money by patching the phase runner
        with patch.object(
            PhaseRunner, "run_phase",
            new_callable=AsyncMock,
            return_value=PhaseResult(cost=Decimal("1.00"), turns=5),
        ):
            await orchestrator.run()

        # Should have updated status to cancelled due to cost
        status_call = services["simulation_repo"].update_status.call_args
        assert status_call[0][1] == SimulationStatus.cancelled.value

    @pytest.mark.asyncio
    async def test_exception_sets_failed_status(self):
        orchestrator, services = self._make_orchestrator(
            [{"name": "phase1", "type": "scheduled"}],
            dry_run=False,
        )
        with (
            patch.object(
                PhaseRunner, "run_phase",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await orchestrator.run()

        status_call = services["simulation_repo"].update_status.call_args
        assert status_call[0][1] == SimulationStatus.failed.value

    @pytest.mark.asyncio
    async def test_durations_updated_on_completion(self):
        orchestrator, services = self._make_orchestrator(
            [{"name": "p1", "type": "scheduled"}],
            dry_run=True,
        )
        await orchestrator.run()
        services["simulation_repo"].update_durations.assert_awaited_once()
        dur_call = services["simulation_repo"].update_durations.call_args
        assert dur_call[1]["simulated_duration"] is not None
        assert dur_call[1]["real_duration"] is not None

    @pytest.mark.asyncio
    async def test_real_duration_uses_wall_clock_not_tick_loop(self):
        """`real_duration` must reflect (completed_at - started_at), not tick-loop time.

        Issue #398: in fast/instant mode the orchestrator's tick loop runs in
        a few ms, but the simulation may have been scheduled hours earlier.
        The persisted `real_duration` must come from wall-clock timestamps.
        """
        orchestrator, services = self._make_orchestrator(
            [{"name": "p1", "type": "scheduled"}],
            dry_run=True,
        )
        # Pretend the simulation row was started 5 seconds ago.
        sim_started_at = datetime.now(UTC) - timedelta(seconds=5)
        sim_with_started = services["sim"].model_copy(update={"started_at": sim_started_at})
        services["simulation_repo"].create = AsyncMock(return_value=sim_with_started)

        await orchestrator.run()

        dur_call = services["simulation_repo"].update_durations.call_args
        assert dur_call[1]["real_duration"] >= timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_baseline_outcomes_written_on_finalize(self):
        """`_finalize` should populate a baseline outcomes dict via update_research_fields."""
        orchestrator, services = self._make_orchestrator(
            [{"name": "p1", "type": "scheduled"}],
            dry_run=True,
        )
        services["simulation_repo"].update_research_fields = AsyncMock(return_value=services["sim"])

        await orchestrator.run()

        services["simulation_repo"].update_research_fields.assert_awaited()
        call = services["simulation_repo"].update_research_fields.call_args
        outcomes = call.kwargs.get("outcomes")
        assert outcomes is not None
        assert "key_metrics" in outcomes
        assert "evals" in outcomes
        assert "surprises" in outcomes
        assert "failures" in outcomes
        assert outcomes["surprises"] == []

    @pytest.mark.asyncio
    async def test_auto_draft_learnings_off_by_default(self):
        """Without --auto-draft-learnings, no LLM call and no append_learning."""
        orchestrator, services = self._make_orchestrator(
            [{"name": "p1", "type": "scheduled"}],
            dry_run=False,
        )
        services["simulation_repo"].update_research_fields = AsyncMock(return_value=services["sim"])
        services["simulation_repo"].append_learning = AsyncMock(return_value=services["sim"])

        with patch.object(
            PhaseRunner,
            "run_phase",
            new_callable=AsyncMock,
            return_value=PhaseResult(turns=1),
        ):
            await orchestrator.run()

        services["simulation_repo"].append_learning.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_draft_learnings_invokes_llm_and_appends(self):
        path = make_seed_file([{"name": "p1", "type": "scheduled"}])
        services = make_mock_services()
        config = SimulationConfig(
            name="test-run",
            seed_file=path,
            agents=["vera", "rex"],
            dry_run=False,
            auto_draft_learnings=True,
        )
        config.load_seed_file()
        services["simulation_repo"].update_research_fields = AsyncMock(return_value=services["sim"])
        services["simulation_repo"].append_learning = AsyncMock(return_value=services["sim"])

        # Mock the LLM client to return a typed-ish response.
        llm_resp = MagicMock(content="agents formed cliques quickly")
        services["llm_client"].complete = AsyncMock(return_value=llm_resp)

        orchestrator = SimulationOrchestrator(
            config=config,
            db=services["db"],
            redis_client=services["redis_client"],
            simulation_repo=services["simulation_repo"],
            config_loader=services["config_loader"],
            agent_registry=services["agent_registry"],
            event_bus=services["event_bus"],
            llm_client=services["llm_client"],
            management=services["management"],
            context_assembler=services["context_assembler"],
            conversation_repo=services["conversation_repo"],
            archival_memory=services["archival_memory"],
            proximity=services["proximity"],
            trigger_system=services["trigger_system"],
            selection_logger=services["selection_logger"],
            reflection_manager=services["reflection_manager"],
            display=services["display"],
        )

        with patch.object(
            PhaseRunner,
            "run_phase",
            new_callable=AsyncMock,
            return_value=PhaseResult(turns=1),
        ):
            await orchestrator.run()

        services["llm_client"].complete.assert_awaited()
        services["simulation_repo"].append_learning.assert_awaited_once()
        call = services["simulation_repo"].append_learning.call_args
        assert call.kwargs["author"] == "system"
        assert "agents formed cliques quickly" in call.kwargs["text"]

    @pytest.mark.asyncio
    async def test_factions_persisted_via_simulation_create(self):
        """When factions are configured, they flow into SimulationCreate."""
        path = make_seed_file([{"name": "p1", "type": "scheduled"}])
        services = make_mock_services()
        from core.models import FactionConfig

        config = SimulationConfig(
            name="fact-test",
            seed_file=path,
            agents=["vera", "rex"],
            dry_run=True,
        )
        config.load_seed_file()
        config.factions = [
            FactionConfig(name="builders", members=["rex"], goal="ship", stance="bold"),
        ]

        orchestrator = SimulationOrchestrator(
            config=config,
            db=services["db"],
            redis_client=services["redis_client"],
            simulation_repo=services["simulation_repo"],
            config_loader=services["config_loader"],
            agent_registry=services["agent_registry"],
            event_bus=services["event_bus"],
            llm_client=services["llm_client"],
            management=services["management"],
            context_assembler=services["context_assembler"],
            conversation_repo=services["conversation_repo"],
            archival_memory=services["archival_memory"],
            proximity=services["proximity"],
            trigger_system=services["trigger_system"],
            selection_logger=services["selection_logger"],
            reflection_manager=services["reflection_manager"],
            display=services["display"],
        )
        await orchestrator.run()

        services["simulation_repo"].create.assert_awaited_once()
        sim_create = services["simulation_repo"].create.call_args[0][0]
        assert len(sim_create.factions) == 1
        assert sim_create.factions[0]["name"] == "builders"
        assert sim_create.factions[0]["goal"] == "ship"

    @pytest.mark.asyncio
    async def test_hypothesis_passed_to_simulation_create(self):
        path = make_seed_file([{"name": "p1", "type": "scheduled"}])
        services = make_mock_services()
        config = SimulationConfig(
            name="hyp-test",
            seed_file=path,
            agents=["vera", "rex"],
            dry_run=True,
            hypothesis="rex will lead the build phase",
        )
        config.load_seed_file()

        orchestrator = SimulationOrchestrator(
            config=config,
            db=services["db"],
            redis_client=services["redis_client"],
            simulation_repo=services["simulation_repo"],
            config_loader=services["config_loader"],
            agent_registry=services["agent_registry"],
            event_bus=services["event_bus"],
            llm_client=services["llm_client"],
            management=services["management"],
            context_assembler=services["context_assembler"],
            conversation_repo=services["conversation_repo"],
            archival_memory=services["archival_memory"],
            proximity=services["proximity"],
            trigger_system=services["trigger_system"],
            selection_logger=services["selection_logger"],
            reflection_manager=services["reflection_manager"],
            display=services["display"],
        )
        await orchestrator.run()

        services["simulation_repo"].create.assert_awaited_once()
        sim_create = services["simulation_repo"].create.call_args[0][0]
        assert sim_create.hypothesis == "rex will lead the build phase"

    @pytest.mark.asyncio
    async def test_completed_at_passed_once_to_update_status(self):
        """update_status should receive the same completed_at used for the duration calc."""
        orchestrator, services = self._make_orchestrator(
            [{"name": "p1", "type": "scheduled"}],
            dry_run=True,
        )
        await orchestrator.run()
        status_call = services["simulation_repo"].update_status.call_args
        assert "completed_at" in status_call.kwargs
        assert status_call.kwargs["completed_at"] is not None


# ── CostLimitExceededError tests ─────────────────────────────────────


class TestCostLimitExceededError:
    def test_cost_limit_exceeded_is_exception(self):
        exc = CostLimitExceededError("over budget")
        assert str(exc) == "over budget"
        assert isinstance(exc, Exception)


# ── SimulationDisplay tests ─────────────────────────────────────


class TestSimulationDisplay:
    def test_display_creates_without_error(self):
        d = SimulationDisplay(verbose=True)
        assert d._verbose is True

    def test_show_phase_start_no_crash(self, capsys):
        d = SimulationDisplay()
        d.show_phase_start("test_phase", 0, 5)
        # Just verify it doesn't crash — output goes to Rich console

    def test_show_phase_complete_no_crash(self):
        d = SimulationDisplay()
        result = PhaseResult(
            status="completed",
            duration_seconds=1.5,
            turns=10,
            cost=Decimal("0.05"),
            agents_participated=["vera", "rex"],
        )
        d.show_phase_complete(result, "test_phase")

    def test_show_phase_complete_with_errors(self):
        d = SimulationDisplay(verbose=True)
        result = PhaseResult(
            status="failed",
            errors=["Something went wrong"],
        )
        d.show_phase_complete(result, "failed_phase")

    def test_show_cost_update_no_crash(self):
        d = SimulationDisplay()
        d.show_cost_update(Decimal("3.50"), Decimal("10.00"))

    def test_show_cost_exceeded_no_crash(self):
        d = SimulationDisplay()
        d.show_cost_exceeded(Decimal("11.00"), Decimal("10.00"))

    def test_show_summary_no_crash(self):
        d = SimulationDisplay()
        sim = Simulation(**make_simulation_row(
            total_conversations=5,
            total_turns=42,
            total_tokens=12000,
            total_cost=Decimal("1.25"),
        ))
        d.show_summary(sim, timedelta(seconds=120))


# ── Seed file loading (full_day.yaml) ───────────────────────────


class TestFullDaySeedFile:
    def test_full_day_yaml_loads_15_phases(self):
        seed_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "full_day.yaml"
        )
        if not os.path.exists(seed_path):
            pytest.skip("scenarios/full_day.yaml not found")

        config = SimulationConfig(
            name="full-day-test",
            seed_file=seed_path,
            agents=["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"],
        )
        config.load_seed_file()
        assert len(config.phases) == 15

    def test_full_day_yaml_phase_types(self):
        seed_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "full_day.yaml"
        )
        if not os.path.exists(seed_path):
            pytest.skip("scenarios/full_day.yaml not found")

        config = SimulationConfig(
            name="test",
            seed_file=seed_path,
            agents=["vera"],
        )
        config.load_seed_file()

        types = [p.type for p in config.phases]
        assert PhaseType.scheduled in types
        assert PhaseType.organic in types
        assert PhaseType.challenge in types
        assert PhaseType.tool_exercise in types
        assert PhaseType.reflection in types
        assert PhaseType.audience_sim in types

    def test_full_day_yaml_phase_names(self):
        seed_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "full_day.yaml"
        )
        if not os.path.exists(seed_path):
            pytest.skip("scenarios/full_day.yaml not found")

        config = SimulationConfig(
            name="test",
            seed_file=seed_path,
            agents=["vera"],
        )
        config.load_seed_file()

        names = [p.name for p in config.phases]
        assert "morning_standup" in names
        assert "coding_challenge" in names
        assert "audience_simulation" in names
        assert "reflection_cycle" in names
        assert "end_of_day_journals" in names


# ── parse_duration tests ──────────────────────────────────────


class TestParseDuration:
    def test_parse_days(self):
        assert parse_duration("7d") == timedelta(days=7)

    def test_parse_hours(self):
        assert parse_duration("12h") == timedelta(hours=12)

    def test_parse_minutes(self):
        assert parse_duration("90m") == timedelta(minutes=90)

    def test_parse_combined(self):
        assert parse_duration("1d12h") == timedelta(days=1, hours=12)

    def test_parse_full_combo(self):
        assert parse_duration("2d6h30m") == timedelta(days=2, hours=6, minutes=30)

    def test_parse_with_whitespace(self):
        assert parse_duration("  7d  ") == timedelta(days=7)

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("")


# ── SimulationConfig autonomous mode tests ─────────────────────


class TestSimulationConfigAutonomous:
    def test_mode_autonomous_when_no_seed_file(self):
        config = SimulationConfig(
            name="auto-test",
            agents=["vera", "rex"],
            duration=timedelta(days=1),
        )
        assert config.mode == "autonomous"

    def test_mode_seeded_when_seed_file_set(self):
        config = SimulationConfig(
            name="seed-test",
            seed_file="some/path.yaml",
            agents=["vera"],
        )
        assert config.mode == "seeded"

    def test_seed_file_optional(self):
        config = SimulationConfig(
            name="no-seed",
            agents=["vera"],
        )
        assert config.seed_file is None
        assert config.phases == []

    def test_load_seed_file_noop_when_no_file(self):
        config = SimulationConfig(name="auto", agents=["vera"])
        config.load_seed_file()  # Should not raise
        assert config.phases == []

    def test_to_dict_includes_mode_and_duration(self):
        config = SimulationConfig(
            name="auto",
            agents=["vera"],
            duration=timedelta(days=7),
        )
        d = config.to_dict()
        assert d["mode"] == "autonomous"
        assert d["duration_seconds"] == 7 * 86400
        assert "phase_count" not in d

    def test_to_dict_seeded_includes_phases(self):
        phases = [{"name": "standup", "type": "scheduled"}]
        path = make_seed_file(phases)
        try:
            config = SimulationConfig(
                name="seeded",
                seed_file=path,
                agents=["vera"],
            )
            config.load_seed_file()
            d = config.to_dict()
            assert d["mode"] == "seeded"
            assert d["phase_count"] == 1
        finally:
            os.unlink(path)


# ── Autonomous orchestrator tests ──────────────────────────────


class TestAutonomousOrchestrator:
    def _make_autonomous_orchestrator(
        self,
        *,
        duration: timedelta = timedelta(hours=1),
        dry_run: bool = True,
        max_cost: float = 10.0,
    ) -> tuple[SimulationOrchestrator, dict[str, Any]]:
        config = SimulationConfig(
            name="auto-test",
            description="Autonomous test",
            agents=["vera", "rex"],
            duration=duration,
            max_cost=max_cost,
            dry_run=dry_run,
        )

        services = make_mock_services()
        orchestrator = SimulationOrchestrator(
            config=config,
            db=services["db"],
            redis_client=services["redis_client"],
            simulation_repo=services["simulation_repo"],
            config_loader=services["config_loader"],
            agent_registry=services["agent_registry"],
            event_bus=services["event_bus"],
            llm_client=services["llm_client"],
            management=services["management"],
            context_assembler=services["context_assembler"],
            conversation_repo=services["conversation_repo"],
            archival_memory=services["archival_memory"],
            proximity=services["proximity"],
            trigger_system=services["trigger_system"],
            selection_logger=services["selection_logger"],
            reflection_manager=services["reflection_manager"],
            display=services["display"],
        )
        return orchestrator, services

    @pytest.mark.asyncio
    async def test_autonomous_creates_simulation_record(self):
        orchestrator, services = self._make_autonomous_orchestrator()
        # Make trigger system return None (no triggers) so loop terminates
        # after duration check (clock starts at 0, advance will exceed 1h)
        services["trigger_system"].check = AsyncMock(return_value=None)

        await orchestrator.run_autonomous()
        services["simulation_repo"].create.assert_awaited_once()
        call_args = services["simulation_repo"].create.call_args
        sim_create = call_args[0][0]
        assert sim_create.name == "auto-test"

    @pytest.mark.asyncio
    async def test_autonomous_terminates_on_duration(self):
        orchestrator, services = self._make_autonomous_orchestrator(
            duration=timedelta(hours=1),
        )
        # Trigger returns None -> clock advances by idle gap (~90s simulated)
        # After enough iterations, clock exceeds 1h and loop terminates
        services["trigger_system"].check = AsyncMock(return_value=None)

        await orchestrator.run_autonomous()
        # Should complete successfully
        status_call = services["simulation_repo"].update_status.call_args
        assert status_call[0][1] == SimulationStatus.completed.value

    @pytest.mark.asyncio
    async def test_autonomous_cancel_sets_cancelled(self):
        orchestrator, services = self._make_autonomous_orchestrator(
            duration=timedelta(days=999),
        )
        services["trigger_system"].check = AsyncMock(return_value=None)
        # Cancel immediately
        orchestrator.cancel()

        await orchestrator.run_autonomous()
        status_call = services["simulation_repo"].update_status.call_args
        assert status_call[0][1] == SimulationStatus.cancelled.value

    @pytest.mark.asyncio
    async def test_autonomous_runs_conversation_on_trigger(self):
        orchestrator, services = self._make_autonomous_orchestrator(
            duration=timedelta(minutes=5),
        )
        trigger = {
            "type": "idle",
            "starter_agent_id": "vera",
            "prompt_hint": "Start talking",
        }
        call_count = 0

        async def mock_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return trigger
            return None

        services["trigger_system"].check = AsyncMock(side_effect=mock_check)

        with patch.object(
            PhaseRunner, "run_phase",
            new_callable=AsyncMock,
            return_value=PhaseResult(
                turns=5, cost=Decimal("0.01"), duration_seconds=10.0
            ),
        ):
            await orchestrator.run_autonomous()

        # Should have run exactly 1 conversation phase
        assert call_count >= 1

    def test_trigger_to_phase_type_mapping(self):
        assert SimulationOrchestrator._trigger_to_phase_type("idle") == PhaseType.organic
        assert SimulationOrchestrator._trigger_to_phase_type("scheduled") == PhaseType.scheduled
        assert SimulationOrchestrator._trigger_to_phase_type("audience") == PhaseType.audience_sim
        assert SimulationOrchestrator._trigger_to_phase_type("memory") == PhaseType.organic
        assert SimulationOrchestrator._trigger_to_phase_type("unknown") == PhaseType.organic


# ── Display new methods tests ──────────────────────────────────


class TestSimulationDisplayNew:
    def test_show_day_boundary_no_crash(self):
        d = SimulationDisplay()
        d.show_day_boundary(1, {"conversations": 5, "cost": Decimal("1.23"), "tools": 3})

    def test_show_day_boundary_empty_stats(self):
        d = SimulationDisplay()
        d.show_day_boundary(2, {})

    def test_show_autonomous_status_no_crash(self):
        d = SimulationDisplay()
        d.show_autonomous_status("idle", 42)

    def test_show_reflection_triggered_no_crash(self):
        d = SimulationDisplay()
        d.show_reflection_triggered("vera", "6hour", datetime(2026, 1, 5, 15, 0))


# ── Awakening seed file tests ─────────────────────────────────


class TestAwakeningSeedFile:
    def _load_awakening(self) -> SimulationConfig:
        seed_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "awakening.yaml"
        )
        if not os.path.exists(seed_path):
            pytest.skip("scenarios/awakening.yaml not found")
        config = SimulationConfig(
            name="awakening-test",
            seed_file=seed_path,
            agents=["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"],
        )
        config.load_seed_file()
        return config

    def test_awakening_has_9_phases(self):
        config = self._load_awakening()
        assert len(config.phases) == 9

    def test_awakening_phase_names(self):
        config = self._load_awakening()
        names = [p.name for p in config.phases]
        assert names == [
            "first_hello",
            "introductions",
            "explore_space",
            "creative_vision",
            "audience_welcome",
            "promotion_chat",
            "first_team_chat",
            "first_reflection",
            "evening_hangout",
        ]

    def test_awakening_phase_types(self):
        config = self._load_awakening()
        types = [p.type for p in config.phases]
        assert types == [
            PhaseType.organic,
            PhaseType.organic,
            PhaseType.organic,
            PhaseType.organic,
            PhaseType.audience_sim,
            PhaseType.organic,
            PhaseType.scheduled,
            PhaseType.reflection,
            PhaseType.organic,
        ]

    def test_awakening_first_hello_requires_vera(self):
        config = self._load_awakening()
        first_hello = config.phases[0]
        assert "vera" in first_hello.required_agents

    def test_awakening_creative_vision_requires_key_agents(self):
        config = self._load_awakening()
        creative = config.phases[3]
        assert set(creative.required_agents) == {"aurora", "rex"}

    def test_awakening_audience_sim_has_messages(self):
        config = self._load_awakening()
        audience = config.phases[4]
        messages = audience.config.get("messages", [])
        assert len(messages) == 2

    def test_awakening_team_chat_requires_vera(self):
        config = self._load_awakening()
        team_chat = config.phases[6]
        assert "vera" in team_chat.required_agents

    def test_awakening_reflection_is_6hour(self):
        config = self._load_awakening()
        reflection = config.phases[7]
        assert reflection.config.get("reflection_type") == "6hour"


# ── Tool coverage seed file tests ─────────────────────────────


class TestToolCoverageSeedFile:
    # All 30 tools that the scenario should exercise
    ALL_TOOLS = {
        "send_message", "get_world_state", "get_audience_status",
        "send_chat_message", "create_poll", "get_poll_results",
        "recall_memory", "retrieve_transcript", "update_core_memory",
        "execute_code", "generate_tilemap",
        "web_search", "fetch_url", "draft_social_post", "draft_email",
        "get_revenue_status", "check_post_performance", "check_email_responses",
        "transfer_budget", "view_account",
        "propose_alliance", "vote_alliance", "leave_alliance", "view_alliances",
        "manage_task",
        "propose_character", "vote_character",
        "dispatch_alpha", "propose_self_modification", "view_evolution_log",
    }

    def _load_tool_coverage(self) -> SimulationConfig:
        seed_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scenarios", "tool_coverage.yaml"
        )
        if not os.path.exists(seed_path):
            pytest.skip("scenarios/tool_coverage.yaml not found")
        config = SimulationConfig(
            name="tool-coverage-test",
            seed_file=seed_path,
            agents=["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"],
        )
        config.load_seed_file()
        return config

    def test_tool_coverage_has_38_phases(self):
        config = self._load_tool_coverage()
        assert len(config.phases) == 38

    def test_tool_coverage_exercises_all_tools(self):
        config = self._load_tool_coverage()
        tool_exercise_phases = [
            p for p in config.phases if p.type == PhaseType.tool_exercise
        ]
        exercised_tools = {p.config.get("tool") for p in tool_exercise_phases}
        missing = self.ALL_TOOLS - exercised_tools
        assert not missing, f"Missing tools: {missing}"

    def test_tool_coverage_has_organic_breaks(self):
        config = self._load_tool_coverage()
        organic_phases = [p for p in config.phases if p.type == PhaseType.organic]
        assert len(organic_phases) >= 3

    def test_tool_coverage_has_reflection_phases(self):
        config = self._load_tool_coverage()
        reflection_phases = [p for p in config.phases if p.type == PhaseType.reflection]
        assert len(reflection_phases) == 2
        types = {p.config.get("reflection_type") for p in reflection_phases}
        assert types == {"6hour", "dream"}

    def test_tool_coverage_agent_assignments(self):
        """Verify tools are assigned to the most appropriate agents."""
        config = self._load_tool_coverage()
        tool_agents = {}
        for p in config.phases:
            if p.type == PhaseType.tool_exercise:
                tool_agents[p.config.get("tool")] = p.config.get("agent")

        assert tool_agents["execute_code"] == "rex"
        assert tool_agents["get_revenue_status"] == "sentinel"
        assert tool_agents["dispatch_alpha"] == "vera"
        assert tool_agents["generate_tilemap"] == "aurora"
        assert tool_agents["send_chat_message"] == "pixel"
        assert tool_agents["propose_alliance"] == "grok"
        assert tool_agents["transfer_budget"] == "vera"
        assert tool_agents["view_account"] == "sentinel"
        assert tool_agents["manage_task"] == "vera"

    def test_tool_coverage_ends_with_wrapup(self):
        config = self._load_tool_coverage()
        last_phase = config.phases[-1]
        assert last_phase.type == PhaseType.organic
        assert last_phase.name == "wrapup"
