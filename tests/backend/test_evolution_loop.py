"""Tests for evolution loop orchestrator (#242)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import (
    AnalysisResult,
    CycleResult,
    EvolutionConfig,
    EvolutionCycle,
    EvolutionReport,
    ProposedChange,
)


# ── Model tests ──────────────────────────────────────────────


class TestEvolutionModels:
    def test_evolution_config_defaults(self) -> None:
        config = EvolutionConfig()
        assert config.max_cycles == 5
        assert config.auto_apply is False
        assert config.convergence_threshold == 2.0
        assert config.regression_threshold == 10.0

    def test_evolution_cycle(self) -> None:
        cycle = EvolutionCycle(
            id=uuid.uuid4(),
            loop_run_id=uuid.uuid4(),
            cycle_number=0,
            overall_score=Decimal("75.5"),
            status="completed",
        )
        assert cycle.cycle_number == 0
        assert float(cycle.overall_score) == 75.5

    def test_cycle_result(self) -> None:
        result = CycleResult(
            cycle_number=0,
            overall_score=80.0,
            changes_applied=3,
            issues_filed=1,
            cost=0.05,
        )
        assert result.changes_applied == 3

    def test_evolution_report(self) -> None:
        report = EvolutionReport(
            loop_run_id=uuid.uuid4(),
            cycles=[
                CycleResult(cycle_number=0, overall_score=60.0),
                CycleResult(cycle_number=1, overall_score=65.0),
            ],
            baseline_score=60.0,
            final_score=65.0,
            total_cost=0.10,
            total_cycles=2,
            stop_reason="completed",
        )
        assert report.total_cycles == 2
        assert report.stop_reason == "completed"


# ── Convergence detection tests ──────────────────────────────


class TestConvergenceDetection:
    def test_not_enough_cycles(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig(convergence_window=3)
        history = [
            CycleResult(cycle_number=0, overall_score=60.0),
            CycleResult(cycle_number=1, overall_score=61.0),
        ]
        assert EvolutionLoop._has_converged(history, config) is False

    def test_scores_plateaued(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig(convergence_threshold=2.0, convergence_window=3)
        history = [
            CycleResult(cycle_number=0, overall_score=70.0),
            CycleResult(cycle_number=1, overall_score=70.5),
            CycleResult(cycle_number=2, overall_score=71.0),
        ]
        # max - min = 1.0 < 2.0 threshold → converged
        assert EvolutionLoop._has_converged(history, config) is True

    def test_scores_still_improving(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig(convergence_threshold=2.0, convergence_window=3)
        history = [
            CycleResult(cycle_number=0, overall_score=60.0),
            CycleResult(cycle_number=1, overall_score=65.0),
            CycleResult(cycle_number=2, overall_score=70.0),
        ]
        # max - min = 10.0 > 2.0 → not converged
        assert EvolutionLoop._has_converged(history, config) is False


# ── Regression detection tests ───────────────────────────────


class TestRegressionDetection:
    def test_no_regression(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig(regression_threshold=10.0)
        history = [CycleResult(cycle_number=0, overall_score=65.0)]
        assert EvolutionLoop._has_regressed(history, 60.0, config) is False

    def test_regression_detected(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig(regression_threshold=10.0)
        history = [CycleResult(cycle_number=0, overall_score=45.0)]
        # baseline 60, latest 45 → delta 15 > 10 → regressed
        assert EvolutionLoop._has_regressed(history, 60.0, config) is True

    def test_no_baseline(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig()
        history = [CycleResult(cycle_number=0, overall_score=50.0)]
        assert EvolutionLoop._has_regressed(history, None, config) is False

    def test_no_history(self) -> None:
        from core.eval.evolution_loop import EvolutionLoop

        config = EvolutionConfig()
        assert EvolutionLoop._has_regressed([], 60.0, config) is False


# ── EvolutionLoop run tests ──────────────────────────────────


class TestEvolutionLoopRun:
    @pytest.mark.asyncio
    async def test_run_single_cycle_review_only(self) -> None:
        """Review-only mode: simulate → eval → analyze → propose (no apply)."""
        from core.eval.evolution_loop import EvolutionLoop
        from core.models import EvalRun

        sim_id = uuid.uuid4()
        eval_run_id = uuid.uuid4()

        mock_eval_engine = AsyncMock()
        mock_eval_engine.run.return_value = eval_run_id

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze.return_value = AnalysisResult(
            summary="Minor improvements needed",
            confidence=0.7,
            proposals=[
                ProposedChange(
                    type="param_change",
                    agent_id="rex",
                    param_path="chattiness",
                    current_value=0.4,
                    proposed_value=0.35,
                    reasoning="Rex talks too much",
                ),
            ],
        )
        mock_analyzer._eval_repo = AsyncMock()
        mock_analyzer._eval_repo.get_eval_run.return_value = EvalRun(
            id=eval_run_id,
            simulation_id=sim_id,
            eval_suite="quick",
            status="completed",
            started_at=datetime.now(UTC),
            overall_score=Decimal("72"),
            cost=Decimal("0.05"),
        )

        mock_change_applier = AsyncMock()
        mock_config_repo = AsyncMock()
        mock_evolution_repo = AsyncMock()
        mock_evolution_repo.insert_cycle.return_value = EvolutionCycle(
            id=uuid.uuid4(),
            loop_run_id=uuid.uuid4(),
            cycle_number=0,
            overall_score=Decimal("72"),
            status="completed",
        )
        mock_registry = AsyncMock()

        async def sim_runner():
            return sim_id

        loop = EvolutionLoop(
            eval_engine=mock_eval_engine,
            analyzer=mock_analyzer,
            change_applier=mock_change_applier,
            config_version_repo=mock_config_repo,
            evolution_repo=mock_evolution_repo,
            agent_registry=mock_registry,
            simulation_runner=sim_runner,
        )

        config = EvolutionConfig(max_cycles=1, auto_apply=False)
        report = await loop.run(config)

        assert report.total_cycles == 1
        assert report.baseline_score == 72.0
        assert report.stop_reason == "completed"
        # Should NOT apply changes in review-only mode
        mock_change_applier.apply.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_with_auto_apply(self) -> None:
        """Auto-apply mode: changes should be applied."""
        from core.eval.evolution_loop import EvolutionLoop
        from core.models import EvalRun

        sim_id = uuid.uuid4()
        eval_run_id = uuid.uuid4()

        mock_eval_engine = AsyncMock()
        mock_eval_engine.run.return_value = eval_run_id

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze.return_value = AnalysisResult(
            summary="Needs work",
            confidence=0.8,
            proposals=[
                ProposedChange(type="param_change", agent_id="rex", reasoning="test"),
            ],
        )
        mock_analyzer._eval_repo = AsyncMock()
        mock_analyzer._eval_repo.get_eval_run.return_value = EvalRun(
            id=eval_run_id,
            simulation_id=sim_id,
            eval_suite="quick",
            status="completed",
            started_at=datetime.now(UTC),
            overall_score=Decimal("65"),
            cost=Decimal("0.03"),
        )

        mock_change_applier = AsyncMock()
        mock_change_applier.apply.return_value = {"applied": 1, "skipped": 0, "details": []}
        mock_config_repo = AsyncMock()
        mock_evolution_repo = AsyncMock()
        mock_evolution_repo.insert_cycle.return_value = EvolutionCycle(
            id=uuid.uuid4(), loop_run_id=uuid.uuid4(),
            cycle_number=0, status="completed",
        )
        mock_registry = AsyncMock()

        async def sim_runner():
            return sim_id

        loop = EvolutionLoop(
            eval_engine=mock_eval_engine,
            analyzer=mock_analyzer,
            change_applier=mock_change_applier,
            config_version_repo=mock_config_repo,
            evolution_repo=mock_evolution_repo,
            agent_registry=mock_registry,
            simulation_runner=sim_runner,
        )

        config = EvolutionConfig(max_cycles=1, auto_apply=True)
        report = await loop.run(config)

        assert report.total_cycles == 1
        mock_change_applier.apply.assert_called_once()
        mock_registry.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_convergence_stops_early(self) -> None:
        """Loop should stop when scores converge."""
        from core.eval.evolution_loop import EvolutionLoop
        from core.models import EvalRun

        call_count = 0

        async def sim_runner():
            return uuid.uuid4()

        mock_eval_engine = AsyncMock()

        def make_eval_run(score: float):
            run_id = uuid.uuid4()
            mock_eval_engine.run.return_value = run_id
            return EvalRun(
                id=run_id, simulation_id=uuid.uuid4(), eval_suite="quick",
                status="completed", started_at=datetime.now(UTC),
                overall_score=Decimal(str(score)), cost=Decimal("0.01"),
            )

        # All cycles return similar scores → convergence
        mock_analyzer = AsyncMock()
        mock_analyzer.analyze.return_value = AnalysisResult(summary="OK", confidence=0.5)
        mock_analyzer._eval_repo = AsyncMock()
        mock_analyzer._eval_repo.get_eval_run.return_value = make_eval_run(70.0)

        mock_change_applier = AsyncMock()
        mock_config_repo = AsyncMock()
        mock_evolution_repo = AsyncMock()
        mock_evolution_repo.insert_cycle.return_value = EvolutionCycle(
            id=uuid.uuid4(), loop_run_id=uuid.uuid4(),
            cycle_number=0, status="completed",
        )
        mock_registry = AsyncMock()

        loop = EvolutionLoop(
            eval_engine=mock_eval_engine,
            analyzer=mock_analyzer,
            change_applier=mock_change_applier,
            config_version_repo=mock_config_repo,
            evolution_repo=mock_evolution_repo,
            agent_registry=mock_registry,
            simulation_runner=sim_runner,
        )

        config = EvolutionConfig(
            max_cycles=10,
            convergence_window=3,
            convergence_threshold=2.0,
        )
        report = await loop.run(config)

        # Should stop after convergence_window cycles since all scores = 70
        assert report.total_cycles <= 4  # 3 for convergence window + 1 possible
        assert report.stop_reason == "converged"


# ── EvolutionRepo tests ──────────────────────────────────────


class TestEvolutionRepo:
    @pytest.mark.asyncio
    async def test_get_cycle_not_found(self) -> None:
        from core.repos.evolution_repo import EvolutionRepo

        mock_db = AsyncMock()
        mock_db.fetchrow.return_value = None
        repo = EvolutionRepo(mock_db)
        result = await repo.get_cycle(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_compare_raises_on_missing(self) -> None:
        from core.repos.evolution_repo import EvolutionRepo

        mock_db = AsyncMock()
        mock_db.fetchrow.return_value = None
        repo = EvolutionRepo(mock_db)
        with pytest.raises(ValueError, match="not found"):
            await repo.compare_cycles(uuid.uuid4(), uuid.uuid4())
