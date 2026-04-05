"""Cost projection and sustainability analysis."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass
class CostProjection:
    """Cost projection based on daily trends."""

    weekly_estimate: Decimal
    monthly_estimate: Decimal
    cost_per_1k_conversations: Decimal | None
    growth_rate: float  # daily cost growth rate as percentage
    is_sustainable: bool
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekly_estimate": str(self.weekly_estimate),
            "monthly_estimate": str(self.monthly_estimate),
            "cost_per_1k_conversations": (
                str(self.cost_per_1k_conversations) if self.cost_per_1k_conversations else None
            ),
            "growth_rate_pct": round(self.growth_rate, 1),
            "is_sustainable": self.is_sustainable,
            "warnings": self.warnings,
        }


def project_costs(
    daily_costs: list[Decimal],
    total_conversations: int = 0,
    daily_token_counts: list[dict[str, int]] | None = None,
) -> CostProjection:
    """Project costs based on daily cost trends.

    Args:
        daily_costs: List of daily cost totals, in chronological order.
        total_conversations: Total conversation count for cost-per-1k calculation.
        daily_token_counts: Optional list of {"input": N, "output": M} per day.

    Returns:
        CostProjection with estimates and sustainability flag.
    """
    warnings: list[str] = []

    if not daily_costs:
        return CostProjection(
            weekly_estimate=Decimal("0"),
            monthly_estimate=Decimal("0"),
            cost_per_1k_conversations=None,
            growth_rate=0.0,
            is_sustainable=True,
            warnings=["No cost data available"],
        )

    total = sum(daily_costs)
    num_days = len(daily_costs)
    avg_daily = total / num_days

    weekly = avg_daily * 7
    monthly = avg_daily * 30

    # Growth rate: compare first half to second half
    growth_rate = 0.0
    if num_days >= 2:
        mid = num_days // 2
        first_half = daily_costs[:mid]
        second_half = daily_costs[mid:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        if avg_first > 0:
            growth_rate = float((avg_second - avg_first) / avg_first * 100)

    # Sustainability: flag if growth > 10% per day-half
    is_sustainable = growth_rate < 10.0
    if not is_sustainable:
        warnings.append(
            f"Cost growth rate of {growth_rate:.1f}% is above 10% threshold"
        )

    # Token growth check
    if daily_token_counts and len(daily_token_counts) >= 2:
        first_tokens = sum(
            d.get("input", 0) + d.get("output", 0)
            for d in daily_token_counts[: len(daily_token_counts) // 2]
        )
        second_tokens = sum(
            d.get("input", 0) + d.get("output", 0)
            for d in daily_token_counts[len(daily_token_counts) // 2 :]
        )
        if first_tokens > 0:
            token_growth = (second_tokens - first_tokens) / first_tokens * 100
            if token_growth > 20:
                warnings.append(
                    f"Token usage growing at {token_growth:.1f}% — context windows may be expanding"
                )

    # Cost per 1000 conversations
    cost_per_1k = None
    if total_conversations > 0:
        cost_per_conv = total / total_conversations
        cost_per_1k = cost_per_conv * 1000

    return CostProjection(
        weekly_estimate=round(weekly, 4),
        monthly_estimate=round(monthly, 4),
        cost_per_1k_conversations=round(cost_per_1k, 4) if cost_per_1k else None,
        growth_rate=growth_rate,
        is_sustainable=is_sustainable,
        warnings=warnings,
    )
