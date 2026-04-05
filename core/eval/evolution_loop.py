"""Evolution loop orchestrator — simulate → eval → improve → repeat.

Chains simulation, evaluation, analysis, and change application into
an automated loop that allows agents to self-improve over multiple
cycles without human intervention.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.models import (
    CycleResult,
    EvolutionConfig,
    EvolutionReport,
    ProposedChange,
)

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry
    from core.eval.analyzer import EvalAnalyzer
    from core.eval.change_applier import ChangeApplier
    from core.eval.engine import EvalEngine
    from core.eval.issue_generator import EvalIssueGenerator
    from core.repos.config_version_repo import ConfigVersionRepo
    from core.repos.evolution_repo import EvolutionRepo
    from core.simulation.orchestrator import SimulationOrchestrator

logger = logging.getLogger(__name__)


class EvolutionLoop:
    """Orchestrates the simulate → eval → analyze → apply cycle."""

    def __init__(
        self,
        *,
        eval_engine: EvalEngine,
        analyzer: EvalAnalyzer,
        change_applier: ChangeApplier,
        config_version_repo: ConfigVersionRepo,
        evolution_repo: EvolutionRepo,
        agent_registry: AgentRegistry,
        simulation_runner: Any = None,
        issue_generator_factory: Any = None,
    ) -> None:
        self._eval_engine = eval_engine
        self._analyzer = analyzer
        self._change_applier = change_applier
        self._config_repo = config_version_repo
        self._evolution_repo = evolution_repo
        self._registry = agent_registry
        self._sim_runner = simulation_runner
        self._issue_generator_factory = issue_generator_factory

    async def run(self, config: EvolutionConfig) -> EvolutionReport:
        """Run the evolution loop for up to max_cycles."""
        loop_run_id = uuid_mod.uuid4()
        baseline_score: float | None = None
        history: list[CycleResult] = []
        total_cost = 0.0
        stop_reason = "completed"

        logger.info(
            "Starting evolution loop %s: max_cycles=%d, auto_apply=%s",
            loop_run_id, config.max_cycles, config.auto_apply,
        )

        for cycle_num in range(config.max_cycles):
            logger.info("=== Evolution cycle %d/%d ===", cycle_num + 1, config.max_cycles)

            try:
                cycle_result = await self._run_cycle(
                    loop_run_id=loop_run_id,
                    cycle_number=cycle_num,
                    config=config,
                    baseline_score=baseline_score,
                    history=history,
                )
            except Exception:
                logger.exception("Cycle %d failed", cycle_num)
                cycle_result = CycleResult(
                    cycle_number=cycle_num,
                    status="failed",
                )

            history.append(cycle_result)
            total_cost += cycle_result.cost

            if baseline_score is None and cycle_result.overall_score is not None:
                baseline_score = cycle_result.overall_score

            # Check cost cap
            if total_cost >= config.cost_cap_per_cycle * config.max_cycles:
                logger.info("Cost cap reached: $%.2f", total_cost)
                stop_reason = "cost_cap"
                break

            # Check convergence
            if self._has_converged(history, config):
                logger.info("Scores converged — stopping early")
                stop_reason = "converged"
                break

            # Check regression
            if self._has_regressed(history, baseline_score, config):
                logger.warning("Scores regressed — rolling back and stopping")
                stop_reason = "regressed"
                break

        final_score = history[-1].overall_score if history else None

        report = EvolutionReport(
            loop_run_id=loop_run_id,
            cycles=history,
            baseline_score=baseline_score,
            final_score=final_score,
            total_cost=total_cost,
            total_cycles=len(history),
            stop_reason=stop_reason,
        )

        logger.info(
            "Evolution loop complete: %d cycles, $%.4f total, %s → %s (%s)",
            len(history), total_cost,
            f"{baseline_score:.1f}" if baseline_score else "N/A",
            f"{final_score:.1f}" if final_score else "N/A",
            stop_reason,
        )

        return report

    async def _run_cycle(
        self,
        *,
        loop_run_id: uuid_mod.UUID,
        cycle_number: int,
        config: EvolutionConfig,
        baseline_score: float | None,
        history: list[CycleResult],
    ) -> CycleResult:
        """Run a single evolution cycle."""
        sim_id: uuid_mod.UUID | None = None
        eval_run_id: uuid_mod.UUID | None = None
        changes_applied = 0
        issues_filed = 0
        cycle_cost = 0.0

        # 1. Run simulation (if runner is available)
        if self._sim_runner is not None:
            sim_id = await self._sim_runner()
        else:
            logger.info("No simulation runner — skipping simulation step")

        # 2. Run eval suite (if we have a simulation)
        if sim_id is not None:
            eval_run_id = await self._eval_engine.run(sim_id, suite="quick")

        # 3. Analyze results
        if eval_run_id is not None:
            analysis = await self._analyzer.analyze(eval_run_id)

            # 4. Separate technical issues from tunable changes
            technical_issues = [
                p for p in analysis.proposals if p.type == "technical_issue"
            ]
            tunable_changes = [
                p for p in analysis.proposals if p.type != "technical_issue"
            ]

            # 5. File GitHub issues for technical problems
            if technical_issues and self._issue_generator_factory:
                try:
                    issue_gen = self._issue_generator_factory(eval_run_id)
                    result = await issue_gen.generate_and_create()
                    issues_filed = sum(1 for i in result if i.get("status") == "created")
                except Exception:
                    logger.warning("Failed to file GitHub issues", exc_info=True)

            # 6. Apply prompt/param changes
            if config.auto_apply and tunable_changes:
                apply_result = await self._change_applier.apply(
                    tunable_changes, eval_run_id
                )
                changes_applied = apply_result.get("applied", 0)
                # Hot-swap configs
                await self._registry.reload()
            elif tunable_changes:
                logger.info(
                    "Review-only mode: %d changes proposed, not auto-applied",
                    len(tunable_changes),
                )

        # Get overall score
        overall_score: float | None = None
        if eval_run_id is not None:
            run = await self._analyzer._eval_repo.get_eval_run(eval_run_id)
            if run and run.overall_score is not None:
                overall_score = float(run.overall_score)
                cycle_cost = float(run.cost)

        # Compute delta
        score_delta: Decimal | None = None
        if overall_score is not None and history:
            prev_score = history[-1].overall_score
            if prev_score is not None:
                score_delta = Decimal(str(overall_score - prev_score))

        # Store cycle in DB
        try:
            await self._evolution_repo.insert_cycle(
                loop_run_id=loop_run_id,
                cycle_number=cycle_number,
                simulation_id=sim_id,
                eval_run_id=eval_run_id,
                overall_score=Decimal(str(overall_score)) if overall_score is not None else None,
                score_delta=score_delta,
                changes_applied=changes_applied,
                issues_filed=issues_filed,
                status="completed",
                cost=Decimal(str(cycle_cost)),
            )
        except Exception:
            logger.warning("Failed to store cycle record", exc_info=True)

        return CycleResult(
            cycle_number=cycle_number,
            simulation_id=sim_id,
            eval_run_id=eval_run_id,
            overall_score=overall_score,
            changes_applied=changes_applied,
            issues_filed=issues_filed,
            cost=cycle_cost,
            status="completed",
        )

    @staticmethod
    def _has_converged(
        history: list[CycleResult], config: EvolutionConfig
    ) -> bool:
        """Stop if scores plateau (< threshold improvement over window cycles)."""
        if len(history) < config.convergence_window:
            return False
        recent = history[-config.convergence_window:]
        scores = [c.overall_score for c in recent if c.overall_score is not None]
        if len(scores) < config.convergence_window:
            return False
        improvement = max(scores) - min(scores)
        return improvement < config.convergence_threshold

    @staticmethod
    def _has_regressed(
        history: list[CycleResult],
        baseline_score: float | None,
        config: EvolutionConfig,
    ) -> bool:
        """Emergency stop if scores drop significantly from baseline."""
        if baseline_score is None or not history:
            return False
        latest = history[-1].overall_score
        if latest is None:
            return False
        return (baseline_score - latest) > config.regression_threshold
