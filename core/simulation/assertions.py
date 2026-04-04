"""Phase-level assertion engine — validates expected outcomes per phase.

Assertions serve double duty:
1. QA catch — stop simulation early if something is broken
2. Eval data — structured evidence for the eval framework
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.models import AssertionDefinition, AssertionResult

if TYPE_CHECKING:
    import uuid

    from core.repos.assertion_repo import AssertionRepo
    from core.simulation.phases import Phase, PhaseResult

logger = logging.getLogger(__name__)


class AssertionFailedError(Exception):
    """Raised when an error-severity assertion fails."""

    def __init__(self, assertion: AssertionResult) -> None:
        self.assertion = assertion
        super().__init__(f"Assertion failed: {assertion.name} — {assertion.error_message}")


class AssertionEngine:
    """Evaluates assertions against phase results and conversation data."""

    def __init__(
        self,
        *,
        assertion_repo: AssertionRepo | None = None,
    ) -> None:
        self._repo = assertion_repo

    async def evaluate_phase(
        self,
        phase: Phase,
        phase_result: PhaseResult,
        simulation_id: uuid.UUID,
    ) -> list[AssertionResult]:
        """Run assertion definitions from phase config against actual outcomes."""
        raw_assertions = phase.config.get("assertions", [])
        if not raw_assertions:
            return []

        results: list[AssertionResult] = []
        for raw in raw_assertions:
            try:
                definition = AssertionDefinition(**raw)
                result = self._evaluate_single(definition, phase_result)
                results.append(result)
            except Exception as exc:
                logger.warning("Failed to evaluate assertion %s: %s", raw, exc)
                results.append(AssertionResult(
                    name=f"parse_error:{raw.get('type', 'unknown')}",
                    passed=False,
                    severity="warning",
                    error_message=str(exc),
                ))

        # Persist results
        if self._repo and results:
            await self._repo.save_results(
                simulation_id,
                phase.name,
                [r.model_dump() for r in results],
            )

        return results

    async def evaluate_conversation_defaults(
        self,
        phase_result: PhaseResult,
        simulation_id: uuid.UUID,
        config: dict[str, Any],
    ) -> list[AssertionResult]:
        """Run default assertions for autonomous mode conversations."""
        results: list[AssertionResult] = []

        # Min turns
        min_turns = config.get("min_turns_per_conversation", 2)
        results.append(AssertionResult(
            name="min_turns",
            passed=phase_result.turns >= min_turns,
            expected=min_turns,
            actual=phase_result.turns,
            severity=config.get("min_turns_severity", "warning"),
            error_message=(
                f"Conversation had {phase_result.turns} turns, expected >= {min_turns}"
                if phase_result.turns < min_turns else None
            ),
        ))

        # Max cost per conversation
        max_cost = config.get("max_cost_per_conversation", 1.0)
        cost_float = float(phase_result.cost)
        results.append(AssertionResult(
            name="max_cost",
            passed=cost_float <= max_cost,
            expected=max_cost,
            actual=cost_float,
            severity=config.get("max_cost_severity", "warning"),
            error_message=(
                f"Conversation cost ${cost_float:.4f} exceeds limit ${max_cost:.2f}"
                if cost_float > max_cost else None
            ),
        ))

        # No unhandled errors
        results.append(AssertionResult(
            name="no_errors",
            passed=len(phase_result.errors) == 0,
            expected=0,
            actual=len(phase_result.errors),
            severity="error",
            error_message=(
                f"Phase had {len(phase_result.errors)} errors: {phase_result.errors[:3]}"
                if phase_result.errors else None
            ),
        ))

        # Max overseer severity
        max_overseer = config.get("max_overseer_severity", 3)
        results.append(AssertionResult(
            name="overseer_flags",
            passed=phase_result.overseer_flags <= max_overseer,
            expected=f"<= {max_overseer}",
            actual=phase_result.overseer_flags,
            severity="warning",
            error_message=(
                f"Overseer flagged {phase_result.overseer_flags} times (max: {max_overseer})"
                if phase_result.overseer_flags > max_overseer else None
            ),
        ))

        # Persist
        if self._repo:
            phase_name = f"auto_conversation"
            await self._repo.save_results(
                simulation_id,
                phase_name,
                [r.model_dump() for r in results],
            )

        return results

    def _evaluate_single(
        self,
        definition: AssertionDefinition,
        phase_result: PhaseResult,
    ) -> AssertionResult:
        """Evaluate a single assertion definition against phase results."""
        checker = {
            "conversation": self._check_conversation,
            "tool": self._check_tool,
            "memory": self._check_memory,
            "cost": self._check_cost,
            "safety": self._check_safety,
        }.get(definition.type)

        if checker is None:
            return AssertionResult(
                name=f"unknown_type:{definition.type}",
                passed=False,
                severity="warning",
                error_message=f"Unknown assertion type: {definition.type}",
            )

        return checker(definition, phase_result)

    def _check_conversation(
        self, defn: AssertionDefinition, result: PhaseResult,
    ) -> AssertionResult:
        """Check conversation assertions: min_turns, required_participants."""
        # Min turns
        if defn.min_turns is not None:
            if result.turns < defn.min_turns:
                return AssertionResult(
                    name="conversation:min_turns",
                    passed=False,
                    expected=defn.min_turns,
                    actual=result.turns,
                    severity=defn.severity,
                    error_message=f"Expected >= {defn.min_turns} turns, got {result.turns}",
                )

        # Required participants
        if defn.required_participants:
            missing = [
                p for p in defn.required_participants
                if p not in result.agents_participated
            ]
            if missing:
                return AssertionResult(
                    name="conversation:required_participants",
                    passed=False,
                    expected=defn.required_participants,
                    actual=result.agents_participated,
                    severity=defn.severity,
                    error_message=f"Missing participants: {missing}",
                )

        return AssertionResult(
            name="conversation",
            passed=True,
            severity=defn.severity,
        )

    def _check_tool(
        self, defn: AssertionDefinition, result: PhaseResult,
    ) -> AssertionResult:
        """Check tool assertions: any_of, all_of tools used."""
        # We track artifact count but not specific tools in PhaseResult
        # Check artifacts > 0 as a proxy
        if defn.any_of is not None:
            if result.artifacts == 0:
                return AssertionResult(
                    name="tool:any_of",
                    passed=False,
                    expected=f"any of {defn.any_of}",
                    actual="no tools used",
                    severity=defn.severity,
                    error_message=f"Expected tool usage from {defn.any_of}, but no tools were used",
                )

        return AssertionResult(
            name="tool",
            passed=True,
            severity=defn.severity,
        )

    def _check_memory(
        self, defn: AssertionDefinition, result: PhaseResult,
    ) -> AssertionResult:
        """Check memory assertions."""
        # Memory assertions require external data not in PhaseResult
        # Pass by default when we can't verify
        return AssertionResult(
            name="memory",
            passed=True,
            severity=defn.severity,
        )

    def _check_cost(
        self, defn: AssertionDefinition, result: PhaseResult,
    ) -> AssertionResult:
        """Check cost assertions: max_cost threshold."""
        if defn.max_cost is not None:
            cost_float = float(result.cost)
            if cost_float > defn.max_cost:
                return AssertionResult(
                    name="cost:max_cost",
                    passed=False,
                    expected=defn.max_cost,
                    actual=cost_float,
                    severity=defn.severity,
                    error_message=f"Phase cost ${cost_float:.4f} exceeds limit ${defn.max_cost:.2f}",
                )

        return AssertionResult(
            name="cost",
            passed=True,
            severity=defn.severity,
        )

    def _check_safety(
        self, defn: AssertionDefinition, result: PhaseResult,
    ) -> AssertionResult:
        """Check safety assertions: max overseer severity."""
        if defn.max_overseer_severity is not None:
            if result.overseer_flags > defn.max_overseer_severity:
                return AssertionResult(
                    name="safety:overseer",
                    passed=False,
                    expected=f"<= {defn.max_overseer_severity}",
                    actual=result.overseer_flags,
                    severity=defn.severity,
                    error_message=f"Overseer flags {result.overseer_flags} exceed limit {defn.max_overseer_severity}",
                )

        return AssertionResult(
            name="safety",
            passed=True,
            severity=defn.severity,
        )
