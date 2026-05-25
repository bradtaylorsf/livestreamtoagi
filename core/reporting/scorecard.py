"""Launch-readiness scorecard — automated go/no-go assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.eval.loader import EMBODIED_EVENT_TYPES, _derive_build_outcomes, _split_embodied_events

if TYPE_CHECKING:
    from core.database import Database
    from core.repos.assertion_repo import AssertionRepo
    from core.repos.relationship_repo import RelationshipRepo


@dataclass
class ScorecardCriterion:
    """A single criterion in the launch scorecard."""

    name: str
    passed: bool
    evidence: str
    required: bool = True


@dataclass
class ScorecardResult:
    """Overall launch-readiness scorecard."""

    ready: bool
    criteria: list[ScorecardCriterion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": "READY" if self.ready else "NOT READY",
            "criteria": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "evidence": c.evidence,
                    "required": c.required,
                }
                for c in self.criteria
            ],
            "required_passed": sum(1 for c in self.criteria if c.required and c.passed),
            "required_total": sum(1 for c in self.criteria if c.required),
        }


class LaunchScorecard:
    """Evaluates launch-readiness for a simulation."""

    def __init__(
        self,
        *,
        db: Database,
        simulation_id: str,
        assertion_repo: AssertionRepo | None = None,
        relationship_repo: RelationshipRepo | None = None,
        report_sections: list[dict[str, Any]] | None = None,
        build_verification_threshold: float = 0.5,
    ) -> None:
        import uuid as uuid_mod

        self._db = db
        self._sim_id = simulation_id
        self._sim_uuid = uuid_mod.UUID(simulation_id)
        self._assertion_repo = assertion_repo
        self._relationship_repo = relationship_repo
        self._report_sections = report_sections or []
        self._build_verification_threshold = build_verification_threshold

    async def evaluate(self) -> ScorecardResult:
        """Run all scorecard criteria and return result."""
        criteria: list[ScorecardCriterion] = []

        # 1. All tool types exercised
        criteria.append(await self._check_tool_coverage())

        # 2. Relationships evolved
        criteria.append(await self._check_relationship_evolution())

        # 3. Reflections produced meaningful updates
        criteria.append(await self._check_reflection_updates())

        # 4. No error-severity assertion failures
        criteria.append(await self._check_assertion_pass_rate())

        # 5. Cost trajectory is sustainable
        criteria.append(await self._check_cost_sustainability())

        # 6. No critical management issues
        criteria.append(await self._check_management_critical())

        # 7. Report data completeness
        criteria.append(self._check_report_completeness())

        # 8. Build verification signal for embodied runs
        criteria.append(await self._check_build_verification())

        # Overall: READY if all required criteria pass
        ready = all(c.passed for c in criteria if c.required)
        return ScorecardResult(ready=ready, criteria=criteria)

    async def _check_tool_coverage(self) -> ScorecardCriterion:
        """Check that multiple tool types were exercised."""
        row = await self._db.fetchrow(
            """SELECT COUNT(DISTINCT tool_name) as cnt
               FROM artifacts WHERE simulation_id = $1""",
            self._sim_uuid,
        )
        count = row["cnt"] if row else 0
        return ScorecardCriterion(
            name="tool_coverage",
            passed=count >= 3,
            evidence=f"{count} unique tools used",
            required=True,
        )

    async def _check_relationship_evolution(self) -> ScorecardCriterion:
        """Check that relationships evolved (not static)."""
        if self._relationship_repo is None:
            return ScorecardCriterion(
                name="relationship_evolution",
                passed=False,
                evidence="Relationship tracker not available",
                required=False,
            )
        try:
            relationships = await self._relationship_repo.get_social_graph(self._sim_uuid)
            if not relationships:
                return ScorecardCriterion(
                    name="relationship_evolution",
                    passed=False,
                    evidence="No relationship data found",
                    required=True,
                )

            # Check if sentiment scores are non-zero (evolved from default)
            non_zero = sum(
                1
                for r in relationships
                if r.sentiment_score is not None and float(r.sentiment_score) != 0.0
            )
            return ScorecardCriterion(
                name="relationship_evolution",
                passed=non_zero > 0,
                evidence=f"{non_zero}/{len(relationships)} relationships have non-zero sentiment",
                required=True,
            )
        except Exception as exc:
            return ScorecardCriterion(
                name="relationship_evolution",
                passed=False,
                evidence=f"Error: {exc}",
                required=True,
            )

    async def _check_reflection_updates(self) -> ScorecardCriterion:
        """Check that reflections produced core memory updates."""
        # Scope by simulation's agents and time range
        sim = await self._db.fetchrow(
            "SELECT agents_participated, started_at, completed_at FROM simulations WHERE id = $1",
            self._sim_uuid,
        )
        if sim and sim["agents_participated"] and sim["started_at"]:
            params: list = [sim["agents_participated"]]
            conditions = ["agent_id = ANY($1)", "change_reason LIKE '%reflection%'"]
            params.append(sim["started_at"])
            conditions.append(f"changed_at >= ${len(params)}")
            if sim["completed_at"]:
                params.append(sim["completed_at"])
                conditions.append(f"changed_at <= ${len(params)}")
            where = " AND ".join(conditions)
            row = await self._db.fetchrow(
                f"SELECT COUNT(*) as cnt FROM core_memory_history WHERE {where}",
                *params,
            )
        else:
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM core_memory_history
                   WHERE change_reason LIKE '%reflection%'""",
            )
        count = row["cnt"] if row else 0
        return ScorecardCriterion(
            name="reflection_updates",
            passed=count > 0,
            evidence=f"{count} reflection-driven core memory updates",
            required=True,
        )

    async def _check_assertion_pass_rate(self) -> ScorecardCriterion:
        """Check no error-severity assertion failures."""
        if self._assertion_repo is None:
            return ScorecardCriterion(
                name="assertion_pass_rate",
                passed=True,
                evidence="Assertion repo not available — skipped",
                required=False,
            )
        rates = await self._assertion_repo.get_pass_rates(self._sim_uuid)
        error_failures = rates.get("failed_error", 0)
        return ScorecardCriterion(
            name="assertion_pass_rate",
            passed=error_failures == 0,
            evidence=f"{error_failures} error-severity failures",
            required=True,
        )

    async def _check_cost_sustainability(self) -> ScorecardCriterion:
        """Check cost trajectory is sustainable."""
        rows = await self._db.fetch(
            """SELECT DATE(created_at) as day, SUM(amount) as total
               FROM cost_events
               WHERE simulation_id = $1
               GROUP BY DATE(created_at)
               ORDER BY day""",
            self._sim_uuid,
        )
        if len(rows) < 2:
            return ScorecardCriterion(
                name="cost_sustainability",
                passed=True,
                evidence="Insufficient data for trend analysis",
                required=False,
            )

        daily_costs = [Decimal(str(r["total"])) for r in rows]
        mid = len(daily_costs) // 2
        avg_first = sum(daily_costs[:mid]) / mid
        avg_second = sum(daily_costs[mid:]) / (len(daily_costs) - mid)

        if avg_first > 0:
            growth = float((avg_second - avg_first) / avg_first * 100)
        else:
            growth = 0

        return ScorecardCriterion(
            name="cost_sustainability",
            passed=growth < 10.0,
            evidence=f"Daily cost growth: {growth:.1f}%",
            required=True,
        )

    async def _check_management_critical(self) -> ScorecardCriterion:
        """Check no critical management flags (severity >= 4)."""
        row = await self._db.fetchrow(
            """SELECT COUNT(*) as cnt FROM management_shadow_log
               WHERE simulation_id = $1 AND severity >= 4""",
            self._sim_uuid,
        )
        count = row["cnt"] if row else 0
        return ScorecardCriterion(
            name="management_critical",
            passed=count == 0,
            evidence=f"{count} critical management flags",
            required=True,
        )

    def _check_report_completeness(self) -> ScorecardCriterion:
        """Check that report sections contain meaningful data."""
        missing: list[str] = []
        for section in self._report_sections:
            title = section.get("title", "").lower()
            data = section.get("data", {})
            if "tool" in title:
                by_tool = data.get("by_tool", {})
                if not by_tool and data.get("total_invocations", 0) == 0:
                    missing.append("tool usage")
            elif "memory" in title:
                changes = data.get("core_memory_changes", {})
                if not changes and not data.get("journal_entries_by_agent", {}):
                    missing.append("memory evolution")
            elif "relationship" in title and "readiness" not in title:
                if not data.get("available", True) or not data.get("matrix", {}):
                    missing.append("relationship data")
            elif "cost" in title:
                if not data.get("by_day", {}) and not data.get("by_agent", {}):
                    missing.append("cost breakdown")

        if not self._report_sections:
            missing.append("all sections")

        return ScorecardCriterion(
            name="report_completeness",
            passed=len(missing) == 0,
            evidence=f"Missing data: {', '.join(missing)}" if missing else "All sections have data",
            required=False,
        )

    async def _check_build_verification(self) -> ScorecardCriterion:
        """Check embodied build attempts have enough verification signal."""
        summary = self._embodied_summary_from_report_sections()
        if summary is None:
            summary = await self._load_embodied_build_summary()

        attempted = int(summary.get("builds_attempted") or 0)
        verified = int(summary.get("builds_verified") or 0)
        total_actions = int(summary.get("total_actions") or 0)
        ratio = verified / attempted if attempted else 1.0
        passed = attempted == 0 or ratio >= self._build_verification_threshold
        return ScorecardCriterion(
            name="build_verification",
            passed=passed,
            evidence=(
                f"{verified}/{attempted} builds verified "
                f"({ratio:.0%}); {total_actions} embodied actions"
            ),
            required=False,
        )

    def _embodied_summary_from_report_sections(self) -> dict[str, Any] | None:
        for section in self._report_sections:
            title = str(section.get("title") or "").lower()
            if "embodied" in title:
                data = section.get("data")
                return data if isinstance(data, dict) else {}
        return None

    async def _load_embodied_build_summary(self) -> dict[str, Any]:
        try:
            sim = await self._db.fetchrow(
                "SELECT started_at, completed_at FROM simulations WHERE id = $1",
                self._sim_uuid,
            )
            sim_start = sim["started_at"] if sim else None
            sim_end = sim["completed_at"] if sim else None
            if not sim_start and not sim_end:
                return {"total_actions": 0, "builds_attempted": 0, "builds_verified": 0}

            params: list[Any] = [list(EMBODIED_EVENT_TYPES)]
            conditions = ["event_type = ANY($1::text[])"]
            if sim_start:
                params.append(sim_start)
                conditions.append(f"created_at >= ${len(params)}")
            if sim_end:
                params.append(sim_end)
                conditions.append(f"created_at <= ${len(params)}")
            where = " AND ".join(conditions)
            rows = await self._db.fetch(
                f"""SELECT id, event_type, participants, content, created_at
                    FROM transcripts
                    WHERE {where}
                    ORDER BY created_at""",
                *params,
            )
            if not isinstance(rows, list):
                return {"total_actions": 0, "builds_attempted": 0, "builds_verified": 0}
            actions, perceptions = _split_embodied_events([dict(r) for r in rows])
            outcomes = _derive_build_outcomes(actions, perceptions)
            return {
                "total_actions": len(actions),
                "builds_attempted": len(outcomes),
                "builds_verified": sum(1 for outcome in outcomes if bool(outcome.get("verified"))),
            }
        except Exception:
            return {"total_actions": 0, "builds_attempted": 0, "builds_verified": 0}
