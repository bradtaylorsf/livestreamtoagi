"""Tests for revenue tracking and marketing tools."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from tools.revenue_tools import DraftEmailTool, DraftSocialPostTool, GetRevenueStatusTool

# --- Fixtures ---


@pytest.fixture
def cost_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_total_revenue = AsyncMock(return_value=Decimal("0"))
    repo.get_total_costs = AsyncMock(return_value=Decimal("0"))
    return repo


@pytest.fixture
def redis_client() -> AsyncMock:
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    return client


# --- GetRevenueStatusTool ---


class TestGetRevenueStatus:
    async def test_correct_revenue_cost_aggregation(self, cost_repo: AsyncMock) -> None:
        # 30-day: revenue=500, costs=300. 60-day totals: revenue=800, costs=500
        # => prior: revenue=300, costs=200
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("500"), Decimal("800"), Decimal("1000")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("300"), Decimal("500"), Decimal("600")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
        result = await tool.execute()

        assert result["status"] == "ok"
        assert result["monthly_revenue"] == 500.0
        assert result["monthly_costs"] == 300.0

    async def test_burn_rate_computed_correctly(self, cost_repo: AsyncMock) -> None:
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("100"), Decimal("200"), Decimal("500")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("400"), Decimal("700"), Decimal("800")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
        result = await tool.execute()

        # burn_rate = (400 - 100) / 30 = 10.0
        assert result["burn_rate"] == 10.0

    async def test_runway_days_computed_correctly(self, cost_repo: AsyncMock) -> None:
        # Total balance = 500 - 800 = -300 (already negative)
        # burn_rate = (400 - 100) / 30 = 10
        # runway = max(0, -300 / 10) = 0
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("100"), Decimal("200"), Decimal("500")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("400"), Decimal("700"), Decimal("800")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="vera")
        result = await tool.execute()

        assert result["runway_days"] == 0

    async def test_runway_infinite_when_profitable(self, cost_repo: AsyncMock) -> None:
        # Revenue > costs => net positive => burn_rate <= 0
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("500"), Decimal("900"), Decimal("1000")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("200"), Decimal("400"), Decimal("300")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
        result = await tool.execute()

        assert result["runway_days"] == -1  # infinite

    async def test_trend_improving(self, cost_repo: AsyncMock) -> None:
        # Current: rev=500, costs=200 => net=+300
        # Prior (60d totals - 30d): rev=600-500=100, costs=400-200=200 => net=-100
        # 300 > -100 + 1 => improving
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("500"), Decimal("600"), Decimal("1000")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("200"), Decimal("400"), Decimal("500")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
        result = await tool.execute()

        assert result["trend"] == "improving"

    async def test_trend_declining(self, cost_repo: AsyncMock) -> None:
        # Current: rev=100, costs=400 => net=-300
        # Prior: rev=500-100=400, costs=500-400=100 => net=+300
        # -300 < 300 - 1 => declining
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("100"), Decimal("500"), Decimal("600")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("400"), Decimal("500"), Decimal("500")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
        result = await tool.execute()

        assert result["trend"] == "declining"

    async def test_trend_stable(self, cost_repo: AsyncMock) -> None:
        # Current: rev=200, costs=100 => net=+100
        # Prior: rev=400-200=200, costs=200-100=100 => net=+100
        # Equal => stable
        cost_repo.get_total_revenue = AsyncMock(
            side_effect=[Decimal("200"), Decimal("400"), Decimal("500")]
        )
        cost_repo.get_total_costs = AsyncMock(
            side_effect=[Decimal("100"), Decimal("200"), Decimal("300")]
        )

        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
        result = await tool.execute()

        assert result["trend"] == "stable"

    async def test_unauthorized_agent_rejected(self, cost_repo: AsyncMock) -> None:
        tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="rex")
        result = await tool.execute()

        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        cost_repo.get_total_revenue.assert_not_called()

    async def test_allowed_agents(self) -> None:
        assert {"sentinel", "vera"} == GetRevenueStatusTool.ALLOWED_AGENTS


# --- DraftSocialPostTool ---


class TestDraftSocialPost:
    async def test_draft_created_with_pending_status(self, redis_client: AsyncMock) -> None:
        tool = DraftSocialPostTool(redis_client=redis_client, agent_id="aurora")
        result = await tool.execute(platform="twitter", content="We just shipped v2!")

        assert result["status"] == "pending_human_review"
        assert "draft_id" in result

        # Verify stored in Redis
        redis_client.set.assert_called_once()
        call_args = redis_client.set.call_args
        key = call_args[0][0]
        assert key.startswith("drafts:social:")
        stored = json.loads(call_args[0][1])
        assert stored["status"] == "pending_human_review"
        assert stored["agent_id"] == "aurora"
        assert stored["platform"] == "twitter"
        assert stored["content"] == "We just shipped v2!"
        assert stored["media_urls"] == []

    async def test_media_urls_stored(self, redis_client: AsyncMock) -> None:
        tool = DraftSocialPostTool(redis_client=redis_client, agent_id="pixel")
        result = await tool.execute(
            platform="discord",
            content="Check this out!",
            media_urls=["https://example.com/img.png"],
        )

        assert result["status"] == "pending_human_review"
        stored = json.loads(redis_client.set.call_args[0][1])
        assert stored["media_urls"] == ["https://example.com/img.png"]

    async def test_invalid_platform_rejected(self, redis_client: AsyncMock) -> None:
        tool = DraftSocialPostTool(redis_client=redis_client, agent_id="aurora")
        result = await tool.execute(platform="tiktok", content="Hello!")

        assert result["status"] == "rejected"
        assert "Unsupported platform" in result["reason"]
        redis_client.set.assert_not_called()

    async def test_unauthorized_agent_rejected(self, redis_client: AsyncMock) -> None:
        tool = DraftSocialPostTool(redis_client=redis_client, agent_id="sentinel")
        result = await tool.execute(platform="twitter", content="Budget report")

        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        redis_client.set.assert_not_called()

    async def test_all_supported_platforms(self, redis_client: AsyncMock) -> None:
        tool = DraftSocialPostTool(redis_client=redis_client, agent_id="grok")
        for platform in ("twitter", "discord", "youtube_community"):
            redis_client.set.reset_mock()
            result = await tool.execute(platform=platform, content="Test")
            assert result["status"] == "pending_human_review"

    async def test_allowed_agents(self) -> None:
        assert {"aurora", "pixel", "grok"} == DraftSocialPostTool.ALLOWED_AGENTS


# --- DraftEmailTool ---


class TestDraftEmail:
    async def test_draft_created_with_pending_status(self, redis_client: AsyncMock) -> None:
        tool = DraftEmailTool(redis_client=redis_client, agent_id="vera")
        result = await tool.execute(
            to="sponsor@example.com",
            subject="Partnership Update",
            body="Here are this month's metrics...",
        )

        assert result["status"] == "pending_human_review"
        assert "draft_id" in result

        # Verify stored in Redis
        redis_client.set.assert_called_once()
        call_args = redis_client.set.call_args
        key = call_args[0][0]
        assert key.startswith("drafts:email:")
        stored = json.loads(call_args[0][1])
        assert stored["status"] == "pending_human_review"
        assert stored["agent_id"] == "vera"
        assert stored["to"] == "sponsor@example.com"
        assert stored["subject"] == "Partnership Update"
        assert stored["body"] == "Here are this month's metrics..."

    async def test_unauthorized_agent_rejected(self, redis_client: AsyncMock) -> None:
        tool = DraftEmailTool(redis_client=redis_client, agent_id="rex")
        result = await tool.execute(
            to="test@example.com", subject="Hi", body="Hello"
        )

        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        redis_client.set.assert_not_called()

    async def test_all_fields_stored(self, redis_client: AsyncMock) -> None:
        tool = DraftEmailTool(redis_client=redis_client, agent_id="pixel")
        await tool.execute(to="a@b.com", subject="Subj", body="Body text")

        stored = json.loads(redis_client.set.call_args[0][1])
        assert stored["to"] == "a@b.com"
        assert stored["subject"] == "Subj"
        assert stored["body"] == "Body text"
        assert stored["agent_id"] == "pixel"
        assert "draft_id" in stored
        assert "timestamp" in stored

    async def test_allowed_agents(self) -> None:
        assert {"aurora", "vera", "pixel"} == DraftEmailTool.ALLOWED_AGENTS
