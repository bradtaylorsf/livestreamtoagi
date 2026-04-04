"""TimelineReporter — post-simulation evolution report.

Generates a comprehensive timeline showing how agents, memories,
relationships, tools, and costs evolved across a simulation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.reporting.sections.cost_analysis import generate_cost_analysis
from core.reporting.sections.daily_breakdown import generate_daily_breakdown
from core.reporting.sections.executive_summary import generate_executive_summary
from core.reporting.sections.key_moments import generate_key_moments
from core.reporting.sections.memory_evolution import generate_memory_evolution
from core.reporting.sections.relationship_evolution import generate_relationship_evolution
from core.reporting.sections.tool_usage import generate_tool_usage

if TYPE_CHECKING:
    from core.database import Database
    from core.repos.relationship_repo import RelationshipRepo

logger = logging.getLogger(__name__)


@dataclass
class ReportSection:
    """A single section of the timeline report."""

    title: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    """Complete simulation timeline report."""

    simulation_id: str
    simulation_name: str
    sections: list[ReportSection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "simulation_name": self.simulation_name,
            "sections": [
                {"title": s.title, "data": s.data} for s in self.sections
            ],
        }


@dataclass
class ComparisonReport:
    """Side-by-side comparison of two simulation runs."""

    simulation_a: dict[str, Any] = field(default_factory=dict)
    simulation_b: dict[str, Any] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_a": self.simulation_a,
            "simulation_b": self.simulation_b,
            "comparison": self.comparison,
        }


class TimelineReporter:
    """Generates post-simulation timeline reports."""

    def __init__(
        self,
        *,
        db: Database,
        simulation_id: str,
        relationship_repo: RelationshipRepo | None = None,
    ) -> None:
        import uuid as uuid_mod
        self._db = db
        self._simulation_id = simulation_id
        self._simulation_uuid = uuid_mod.UUID(simulation_id)
        self._relationship_repo = relationship_repo

    async def generate(
        self,
        *,
        days: list[int] | None = None,
        format: str = "terminal",
    ) -> Report:
        """Generate the full timeline report."""
        sim = await self._load_simulation()
        if sim is None:
            return Report(
                simulation_id=self._simulation_id,
                simulation_name="NOT FOUND",
            )

        report = Report(
            simulation_id=self._simulation_id,
            simulation_name=sim.get("name", "Unknown"),
        )

        conversations = await self._load_conversations()
        cost_events = await self._load_cost_events()
        artifacts = await self._load_artifacts()
        overseer_log = await self._load_overseer_log()

        # Filter by requested days
        if days:
            sim_start = sim.get("started_at") or sim.get("created_at")
            conversations = self._filter_by_days(conversations, days, sim_start)
            cost_events = self._filter_cost_by_days(cost_events, days, sim_start)

        # 1. Executive Summary
        report.sections.append(ReportSection(
            title="Executive Summary",
            data=generate_executive_summary(
                sim, conversations, cost_events, artifacts, overseer_log,
            ),
        ))

        # 2. Daily Breakdown
        report.sections.append(ReportSection(
            title="Day-by-Day Breakdown",
            data=generate_daily_breakdown(conversations, cost_events, artifacts),
        ))

        # 3. Memory Evolution (scoped to simulation agents and time range)
        sim_agents = sim.get("agents_participated", [])
        sim_start = sim.get("started_at") or sim.get("created_at")
        sim_end = sim.get("completed_at")
        core_memory_history = await self._load_core_memory_history(sim_agents, sim_start, sim_end)
        recall_counts = await self._load_recall_memory_counts(sim_agents)
        journal_entries = await self._load_journal_entries(sim_agents, sim_start, sim_end)
        report.sections.append(ReportSection(
            title="Memory Evolution",
            data=generate_memory_evolution(
                core_memory_history, recall_counts, journal_entries,
                sim.get("agents_participated", []),
            ),
        ))

        # 4. Relationship Evolution
        relationship_data = None
        if self._relationship_repo:
            try:
                relationships = await self._relationship_repo.get_social_graph(
                    self._simulation_uuid
                )
                relationship_data = [r.model_dump(mode="json") for r in relationships]
            except Exception:
                logger.warning("Failed to load relationship data", exc_info=True)

        report.sections.append(ReportSection(
            title="Relationship Evolution",
            data=generate_relationship_evolution(relationship_data),
        ))

        # 5. Tool Usage
        report.sections.append(ReportSection(
            title="Tool Usage",
            data=generate_tool_usage(artifacts, cost_events),
        ))

        # 6. Cost Analysis
        report.sections.append(ReportSection(
            title="Cost Analysis",
            data=generate_cost_analysis(cost_events, sim),
        ))

        # 7. Key Moments
        report.sections.append(ReportSection(
            title="Key Moments",
            data=generate_key_moments(conversations, overseer_log, artifacts),
        ))

        return report

    async def compare(self, other_simulation_id: str) -> ComparisonReport:
        """Generate a side-by-side comparison of two simulations.

        Delegates to CrossRunComparison for the richer metric analysis,
        then adapts the result to the ComparisonReport format used by CLI.
        """
        from core.reporting.comparison import CrossRunComparison

        cross = CrossRunComparison(
            db=self._db,
            simulation_ids=[self._simulation_id, other_simulation_id],
            relationship_repo=self._relationship_repo,
        )
        result = await cross.compare()

        # Adapt CrossRunComparison result to ComparisonReport format
        # Build flat comparison dict from metrics for backward compatibility
        comparison: dict[str, Any] = {}
        for m in result.metrics:
            comparison[m.metric] = {
                "run_a": m.run_a_value,
                "run_b": m.run_b_value,
                "delta": m.delta,
                "better_run": m.better_run,
            }

        # Also include legacy flat keys for existing formatters
        cost_m = next((m for m in result.metrics if m.metric == "total_cost"), None)
        conv_m = next((m for m in result.metrics if m.metric == "total_conversations"), None)
        turns_m = next(
            (m for m in result.metrics if m.metric == "avg_turns_per_conversation"),
            None,
        )
        if cost_m:
            comparison["cost_delta"] = cost_m.delta
        if conv_m:
            comparison["conversation_delta"] = conv_m.delta
        if turns_m:
            comparison["turns_delta"] = turns_m.delta

        return ComparisonReport(
            simulation_a={
                **result.run_a,
                "id": self._simulation_id,
                "total_cost": cost_m.run_a_value if cost_m else "0",
                "total_conversations": conv_m.run_a_value if conv_m else 0,
                "avg_turns": turns_m.run_a_value if turns_m else 0,
            },
            simulation_b={
                **result.run_b,
                "id": other_simulation_id,
                "total_cost": cost_m.run_b_value if cost_m else "0",
                "total_conversations": conv_m.run_b_value if conv_m else 0,
                "avg_turns": turns_m.run_b_value if turns_m else 0,
            },
            comparison=comparison,
        )

    # ── Data loading helpers ──────────────────────────────────

    async def _load_simulation(self) -> dict[str, Any] | None:
        row = await self._db.fetchrow(
            "SELECT * FROM simulations WHERE id = $1",
            self._simulation_uuid,
        )
        if row is None:
            return None
        return dict(row)

    async def _load_conversations(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch(
            """SELECT * FROM conversations
               WHERE simulation_id = $1
               ORDER BY started_at""",
            self._simulation_uuid,
        )
        return [dict(r) for r in rows]

    async def _load_cost_events(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch(
            """SELECT * FROM cost_events
               WHERE simulation_id = $1
               ORDER BY created_at""",
            self._simulation_uuid,
        )
        return [dict(r) for r in rows]

    async def _load_artifacts(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch(
            """SELECT * FROM artifacts
               WHERE simulation_id = $1
               ORDER BY created_at""",
            self._simulation_uuid,
        )
        return [dict(r) for r in rows]

    async def _load_overseer_log(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch(
            """SELECT * FROM overseer_shadow_log
               WHERE simulation_id = $1
               ORDER BY created_at""",
            self._simulation_uuid,
        )
        return [dict(r) for r in rows]

    async def _load_core_memory_history(
        self,
        agents: list[str] | None = None,
        sim_start: Any = None,
        sim_end: Any = None,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if agents:
            params.append(agents)
            conditions.append(f"agent_id = ANY(${len(params)})")
        if sim_start:
            params.append(sim_start)
            conditions.append(f"changed_at >= ${len(params)}")
        if sim_end:
            params.append(sim_end)
            conditions.append(f"changed_at <= ${len(params)}")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._db.fetch(
            f"SELECT * FROM core_memory_history{where} ORDER BY changed_at",
            *params,
        )
        return [dict(r) for r in rows]

    async def _load_recall_memory_counts(
        self, agents: list[str] | None = None,
    ) -> dict[str, int]:
        if agents:
            rows = await self._db.fetch(
                """SELECT agent_id, COUNT(*) as cnt
                   FROM recall_memory
                   WHERE agent_id = ANY($1)
                   GROUP BY agent_id""",
                agents,
            )
        else:
            rows = await self._db.fetch(
                """SELECT agent_id, COUNT(*) as cnt
                   FROM recall_memory
                   GROUP BY agent_id""",
            )
        return {r["agent_id"]: r["cnt"] for r in rows}

    async def _load_journal_entries(
        self,
        agents: list[str] | None = None,
        sim_start: Any = None,
        sim_end: Any = None,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if agents:
            params.append(agents)
            conditions.append(f"agent_id = ANY(${len(params)})")
        if sim_start:
            params.append(sim_start)
            conditions.append(f"created_at >= ${len(params)}")
        if sim_end:
            params.append(sim_end)
            conditions.append(f"created_at <= ${len(params)}")

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._db.fetch(
            f"SELECT * FROM journal_entries{where} ORDER BY created_at",
            *params,
        )
        return [dict(r) for r in rows]

    @staticmethod
    def _filter_by_days(
        conversations: list[dict],
        days: list[int],
        sim_start: Any = None,
    ) -> list[dict]:
        """Filter conversations to only include specified simulated days.

        Day numbering is 1-based: day 1 = first 24h from simulation start.
        """
        if not sim_start or not hasattr(sim_start, "timetuple"):
            return conversations

        filtered = []
        for conv in conversations:
            started = conv.get("started_at")
            if started and hasattr(started, "timetuple"):
                delta = started - sim_start
                conv_day = delta.days + 1  # 1-based day number
                if conv_day in days:
                    filtered.append(conv)
            # Skip conversations without valid timestamps
        return filtered

    @staticmethod
    def _filter_cost_by_days(
        costs: list[dict],
        days: list[int],
        sim_start: Any = None,
    ) -> list[dict]:
        """Filter cost events to only include specified simulated days."""
        if not sim_start or not hasattr(sim_start, "timetuple"):
            return costs

        filtered = []
        for cost in costs:
            created = cost.get("created_at")
            if created and hasattr(created, "timetuple"):
                delta = created - sim_start
                cost_day = delta.days + 1
                if cost_day in days:
                    filtered.append(cost)
        return filtered
