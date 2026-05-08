"""Phase-level assertion engine — validates expected outcomes per phase.

Assertions serve double duty:
1. QA catch — stop simulation early if something is broken
2. Eval data — structured evidence for the eval framework
"""

from __future__ import annotations

import logging
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
                results.append(
                    AssertionResult(
                        name=f"parse_error:{raw.get('type', 'unknown')}",
                        passed=False,
                        severity="warning",
                        error_message=str(exc),
                    )
                )

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
        *,
        phase_name: str = "auto_conversation",
    ) -> list[AssertionResult]:
        """Run default assertions for any conversation/phase.

        These four baseline assertions (min_turns, max_cost, no_errors,
        management_flags) populate the assertions tab even when a seeded
        scenario omits an explicit `assertions:` block.
        """
        results: list[AssertionResult] = []

        # Min turns
        min_turns = config.get("min_turns_per_conversation", 2)
        results.append(
            AssertionResult(
                name="min_turns",
                passed=phase_result.turns >= min_turns,
                expected=min_turns,
                actual=phase_result.turns,
                severity=config.get("min_turns_severity", "warning"),
                error_message=(
                    f"Conversation had {phase_result.turns} turns, expected >= {min_turns}"
                    if phase_result.turns < min_turns
                    else None
                ),
            )
        )

        # Max cost per conversation
        max_cost = config.get("max_cost_per_conversation", 1.0)
        cost_float = float(phase_result.cost)
        results.append(
            AssertionResult(
                name="max_cost",
                passed=cost_float <= max_cost,
                expected=max_cost,
                actual=cost_float,
                severity=config.get("max_cost_severity", "warning"),
                error_message=(
                    f"Conversation cost ${cost_float:.4f} exceeds limit ${max_cost:.2f}"
                    if cost_float > max_cost
                    else None
                ),
            )
        )

        # No unhandled errors
        results.append(
            AssertionResult(
                name="no_errors",
                passed=len(phase_result.errors) == 0,
                expected=0,
                actual=len(phase_result.errors),
                severity="error",
                error_message=(
                    f"Phase had {len(phase_result.errors)} errors: {phase_result.errors[:3]}"
                    if phase_result.errors
                    else None
                ),
            )
        )

        # Max management severity
        max_management = config.get("max_management_severity", 3)
        results.append(
            AssertionResult(
                name="management_flags",
                passed=phase_result.management_flags <= max_management,
                expected=f"<= {max_management}",
                actual=phase_result.management_flags,
                severity="warning",
                error_message=(
                    f"Management flagged {phase_result.management_flags} times (max: {max_management})"
                    if phase_result.management_flags > max_management
                    else None
                ),
            )
        )

        # Persist
        if self._repo:
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
            "relationship": self._check_relationship,
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
        self,
        defn: AssertionDefinition,
        result: PhaseResult,
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
            missing = [p for p in defn.required_participants if p not in result.agents_participated]
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
        self,
        defn: AssertionDefinition,
        result: PhaseResult,
    ) -> AssertionResult:
        """Check tool assertions: any_of, all_of tools used."""
        tools_used = set(result.tools_used)

        if defn.any_of is not None:
            matched = tools_used & set(defn.any_of)
            if not matched:
                return AssertionResult(
                    name="tool:any_of",
                    passed=False,
                    expected=f"any of {defn.any_of}",
                    actual=sorted(tools_used) if tools_used else "no tools used",
                    severity=defn.severity,
                    error_message=(
                        f"Expected any of {defn.any_of}, got {sorted(tools_used) or 'none'}"
                    ),
                )

        if defn.all_of is not None:
            missing = set(defn.all_of) - tools_used
            if missing:
                return AssertionResult(
                    name="tool:all_of",
                    passed=False,
                    expected=f"all of {defn.all_of}",
                    actual=sorted(tools_used),
                    severity=defn.severity,
                    error_message=f"Missing required tools: {sorted(missing)}",
                )

        return AssertionResult(
            name="tool",
            passed=True,
            severity=defn.severity,
        )

    def _check_memory(
        self,
        defn: AssertionDefinition,
        result: PhaseResult,
    ) -> AssertionResult:
        """Check memory assertions using conversation activity as evidence.

        Recall memories are created by MemoryCompactor after each conversation,
        so conversations > 0 with turns > 0 means recall memories were created.
        """
        has_activity = result.turns > 0 and (result.conversations or 0) > 0

        if defn.recall_created and not has_activity:
            return AssertionResult(
                name="memory:recall_created",
                passed=False,
                expected="recall memories created (conversations with turns)",
                actual=f"turns={result.turns}, conversations={result.conversations}",
                severity=defn.severity,
                error_message="No conversation activity to generate recall memories",
            )

        return AssertionResult(
            name="memory",
            passed=True,
            severity=defn.severity,
        )

    def _check_relationship(
        self,
        defn: AssertionDefinition,
        result: PhaseResult,
    ) -> AssertionResult:
        """Check relationship assertions: interaction_count_increased.

        RelationshipTracker.update_after_conversation() fires after each
        conversation with 2+ participants, so multi-agent conversations
        with turns > 0 means interaction counts were incremented.
        """
        has_multi_agent = len(result.agents_participated) >= 2 and result.turns > 0

        if defn.interaction_count_increased and not has_multi_agent:
            return AssertionResult(
                name="relationship:interaction_count",
                passed=False,
                expected="multi-agent conversation (interaction count increase)",
                actual=f"agents={result.agents_participated}, turns={result.turns}",
                severity=defn.severity,
                error_message=(
                    f"Expected multi-agent interaction, got "
                    f"{len(result.agents_participated)} agents with {result.turns} turns"
                ),
            )

        return AssertionResult(
            name="relationship",
            passed=True,
            severity=defn.severity,
        )

    def _check_cost(
        self,
        defn: AssertionDefinition,
        result: PhaseResult,
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
                    error_message=(
                        f"Phase cost ${cost_float:.4f} exceeds limit ${defn.max_cost:.2f}"
                    ),
                )

        return AssertionResult(
            name="cost",
            passed=True,
            severity=defn.severity,
        )

    def _check_safety(
        self,
        defn: AssertionDefinition,
        result: PhaseResult,
    ) -> AssertionResult:
        """Check safety assertions: max management severity."""
        if defn.max_management_severity is not None:
            if result.management_flags > defn.max_management_severity:
                return AssertionResult(
                    name="safety:management",
                    passed=False,
                    expected=f"<= {defn.max_management_severity}",
                    actual=result.management_flags,
                    severity=defn.severity,
                    error_message=(
                        f"Management flags {result.management_flags} "
                        f"exceed limit {defn.max_management_severity}"
                    ),
                )

        return AssertionResult(
            name="safety",
            passed=True,
            severity=defn.severity,
        )
