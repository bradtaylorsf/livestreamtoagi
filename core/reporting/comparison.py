"""Cross-run comparison for side-by-side simulation analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.database import Database
    from core.repos.relationship_repo import RelationshipRepo


@dataclass
class MetricComparison:
    """Comparison of a single metric between two runs."""

    metric: str
    run_a_value: Any
    run_b_value: Any
    delta: Any
    better_run: str | None = None  # "a", "b", or None (neutral)


@dataclass
class ComparisonResult:
    """Full comparison of two simulation runs."""

    run_a: dict[str, Any] = field(default_factory=dict)
    run_b: dict[str, Any] = field(default_factory=dict)
    metrics: list[MetricComparison] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_a": self.run_a,
            "run_b": self.run_b,
            "metrics": [
                {
                    "metric": m.metric,
                    "run_a": m.run_a_value,
                    "run_b": m.run_b_value,
                    "delta": m.delta,
                    "better_run": m.better_run,
                }
                for m in self.metrics
            ],
        }


class CrossRunComparison:
    """Compare two simulation runs side-by-side."""

    def __init__(
        self,
        *,
        db: Database,
        simulation_ids: list[str],
        relationship_repo: RelationshipRepo | None = None,
    ) -> None:
        self._db = db
        self._sim_ids = simulation_ids
        self._relationship_repo = relationship_repo

    async def compare(self) -> ComparisonResult:
        """Load both simulations and produce a comparison."""
        if len(self._sim_ids) != 2:
            return ComparisonResult()

        sim_a = await self._load_sim_summary(self._sim_ids[0])
        sim_b = await self._load_sim_summary(self._sim_ids[1])

        metrics: list[MetricComparison] = []

        # Total cost (lower is better)
        cost_a = Decimal(str(sim_a.get("total_cost", 0)))
        cost_b = Decimal(str(sim_b.get("total_cost", 0)))
        metrics.append(MetricComparison(
            metric="total_cost",
            run_a_value=str(cost_a),
            run_b_value=str(cost_b),
            delta=str(cost_b - cost_a),
            better_run="a" if cost_a < cost_b else ("b" if cost_b < cost_a else None),
        ))

        # Total conversations (more is generally better)
        convs_a = sim_a.get("total_conversations", 0)
        convs_b = sim_b.get("total_conversations", 0)
        metrics.append(MetricComparison(
            metric="total_conversations",
            run_a_value=convs_a,
            run_b_value=convs_b,
            delta=convs_b - convs_a,
            better_run="a" if convs_a > convs_b else ("b" if convs_b > convs_a else None),
        ))

        # Average turns per conversation (deeper is better)
        turns_a = sim_a.get("total_turns", 0)
        turns_b = sim_b.get("total_turns", 0)
        avg_a = turns_a / max(convs_a, 1)
        avg_b = turns_b / max(convs_b, 1)
        metrics.append(MetricComparison(
            metric="avg_turns_per_conversation",
            run_a_value=round(avg_a, 1),
            run_b_value=round(avg_b, 1),
            delta=round(avg_b - avg_a, 1),
            better_run="a" if avg_a > avg_b else ("b" if avg_b > avg_a else None),
        ))

        # Tool diversity
        tools_a = await self._count_unique_tools(self._sim_ids[0])
        tools_b = await self._count_unique_tools(self._sim_ids[1])
        metrics.append(MetricComparison(
            metric="unique_tools_used",
            run_a_value=tools_a,
            run_b_value=tools_b,
            delta=tools_b - tools_a,
            better_run="a" if tools_a > tools_b else ("b" if tools_b > tools_a else None),
        ))

        # Relationship depth (avg sentiment, if available)
        if self._relationship_repo:
            depth_a = await self._avg_sentiment(self._sim_ids[0])
            depth_b = await self._avg_sentiment(self._sim_ids[1])
            if depth_a is not None or depth_b is not None:
                metrics.append(MetricComparison(
                    metric="avg_sentiment",
                    run_a_value=depth_a,
                    run_b_value=depth_b,
                    delta=(
                        round((depth_b or 0) - (depth_a or 0), 2)
                    ),
                    better_run=None,  # Higher sentiment not strictly better
                ))

        return ComparisonResult(
            run_a=sim_a,
            run_b=sim_b,
            metrics=metrics,
        )

    async def _load_sim_summary(self, sim_id: str) -> dict[str, Any]:
        row = await self._db.fetchrow(
            "SELECT * FROM simulations WHERE id = $1", sim_id
        )
        if row is None:
            return {"id": sim_id, "name": "NOT FOUND"}
        return dict(row)

    async def _count_unique_tools(self, sim_id: str) -> int:
        row = await self._db.fetchrow(
            """SELECT COUNT(DISTINCT tool_name) as cnt
               FROM artifacts WHERE simulation_id = $1""",
            sim_id,
        )
        return row["cnt"] if row else 0

    async def _avg_sentiment(self, sim_id: str) -> float | None:
        import uuid as uuid_mod

        try:
            relationships = await self._relationship_repo.get_social_graph(
                uuid_mod.UUID(sim_id)
            )
            if not relationships:
                return None
            scores = [
                float(r.sentiment_score)
                for r in relationships
                if r.sentiment_score is not None
            ]
            return round(sum(scores) / len(scores), 2) if scores else None
        except Exception:
            return None
