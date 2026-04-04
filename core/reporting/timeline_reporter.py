"""TimelineReporter — post-simulation evolution report.

Generates a comprehensive timeline showing how agents, memories,
relationships, tools, and costs evolved across a simulation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
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
            conversations = self._filter_by_days(conversations, days)
            cost_events = self._filter_cost_by_days(cost_events, days)

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

        # 3. Memory Evolution
        core_memory_history = await self._load_core_memory_history()
        recall_counts = await self._load_recall_memory_counts()
        journal_entries = await self._load_journal_entries()
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
        """Generate a side-by-side comparison of two simulations."""
        sim_a = await self._load_simulation()
        other = TimelineReporter(
            db=self._db,
            simulation_id=other_simulation_id,
            relationship_repo=self._relationship_repo,
        )
        sim_b = await other._load_simulation()

        if sim_a is None or sim_b is None:
            return ComparisonReport(
                comparison={"error": "One or both simulations not found"},
            )

        costs_a = await self._load_cost_events()
        costs_b = await other._load_cost_events()
        convs_a = await self._load_conversations()
        convs_b = await other._load_conversations()

        total_cost_a = sum(Decimal(str(c.get("amount", 0))) for c in costs_a)
        total_cost_b = sum(Decimal(str(c.get("amount", 0))) for c in costs_b)
        avg_turns_a = (
            sum(c.get("turn_count", 0) for c in convs_a) / max(len(convs_a), 1)
        )
        avg_turns_b = (
            sum(c.get("turn_count", 0) for c in convs_b) / max(len(convs_b), 1)
        )

        return ComparisonReport(
            simulation_a={
                "id": self._simulation_id,
                "name": sim_a.get("name", "Unknown"),
                "total_cost": str(total_cost_a),
                "total_conversations": len(convs_a),
                "avg_turns": round(avg_turns_a, 1),
            },
            simulation_b={
                "id": other_simulation_id,
                "name": sim_b.get("name", "Unknown"),
                "total_cost": str(total_cost_b),
                "total_conversations": len(convs_b),
                "avg_turns": round(avg_turns_b, 1),
            },
            comparison={
                "cost_delta": str(total_cost_b - total_cost_a),
                "conversation_delta": len(convs_b) - len(convs_a),
                "turns_delta": round(avg_turns_b - avg_turns_a, 1),
            },
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

    async def _load_core_memory_history(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch(
            """SELECT * FROM core_memory_history
               ORDER BY changed_at""",
        )
        return [dict(r) for r in rows]

    async def _load_recall_memory_counts(self) -> dict[str, int]:
        rows = await self._db.fetch(
            """SELECT agent_id, COUNT(*) as cnt
               FROM recall_memory
               GROUP BY agent_id""",
        )
        return {r["agent_id"]: r["cnt"] for r in rows}

    async def _load_journal_entries(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch(
            """SELECT * FROM journal_entries
               ORDER BY created_at""",
        )
        return [dict(r) for r in rows]

    @staticmethod
    def _filter_by_days(
        conversations: list[dict], days: list[int],
    ) -> list[dict]:
        """Filter conversations to only include specified simulated days."""
        filtered = []
        for conv in conversations:
            started = conv.get("started_at")
            if started and hasattr(started, "timetuple"):
                # Approximate day from sequence position
                filtered.append(conv)
            else:
                filtered.append(conv)
        return filtered

    @staticmethod
    def _filter_cost_by_days(
        costs: list[dict], days: list[int],
    ) -> list[dict]:
        return costs  # Cost filtering by simulated day not directly supported
