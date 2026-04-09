"""Tests for fourth-wall break prevention and budget disclosure (Issue #217)."""

from __future__ import annotations

from pathlib import Path

import yaml
import pytest


# ── Infrastructure prompt ────────────────────────────────────────


def test_infrastructure_prompt_forbids_invisible_infrastructure_references():
    """INFRASTRUCTURE_PROMPT should forbid referencing invisible infrastructure by technical name."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    prompt_lower = INFRASTRUCTURE_PROMPT.lower()
    assert "do not reference invisible infrastructure" in prompt_lower
    assert "context windows" in prompt_lower
    assert "embeddings" in prompt_lower


def test_infrastructure_prompt_allows_budget_and_ai_discussion():
    """INFRASTRUCTURE_PROMPT should allow budget figures and AI nature discussion (relaxed rules)."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    prompt_lower = INFRASTRUCTURE_PROMPT.lower()
    assert "budget figures" in prompt_lower
    assert "financial transparency" in prompt_lower
    # Should NOT contain the old restrictive rules
    assert "never disclose exact budget figures" not in prompt_lower
    assert "do not discuss being ai" not in prompt_lower


def test_infrastructure_prompt_forbids_circumvention():
    """INFRASTRUCTURE_PROMPT should forbid encouraging moderation circumvention."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    prompt_lower = INFRASTRUCTURE_PROMPT.lower()
    assert "circumvent" in prompt_lower


# ── Revenue tool output filtering ───────────────────────────────


@pytest.mark.asyncio
async def test_revenue_tool_returns_summary_not_raw():
    """GetRevenueStatusTool should return health/trend summary, not raw numbers."""
    from unittest.mock import AsyncMock
    from tools.revenue_tools import GetRevenueStatusTool

    cost_repo = AsyncMock()
    cost_repo.get_total_revenue = AsyncMock(return_value=100)
    cost_repo.get_total_costs = AsyncMock(return_value=50)

    tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
    result = await tool.execute()

    assert result["status"] == "ok"
    assert "health" in result
    assert result["health"] in ("healthy", "tight", "critical")
    assert "trend" in result
    assert "summary" in result
    # Raw numbers should be in _internal, not top-level
    assert "monthly_revenue" not in result
    assert "monthly_costs" not in result
    assert "burn_rate" not in result
    assert "_internal" in result
    assert "monthly_revenue" in result["_internal"]


@pytest.mark.asyncio
async def test_revenue_tool_health_categories():
    """Revenue tool should categorize health correctly."""
    from unittest.mock import AsyncMock
    from tools.revenue_tools import GetRevenueStatusTool

    cost_repo = AsyncMock()

    # Healthy: revenue > costs (runway = -1)
    cost_repo.get_total_revenue = AsyncMock(return_value=200)
    cost_repo.get_total_costs = AsyncMock(return_value=100)
    tool = GetRevenueStatusTool(cost_repo=cost_repo, agent_id="sentinel")
    result = await tool.execute()
    assert result["health"] == "healthy"

    # Critical: high costs, low revenue, short runway
    cost_repo.get_total_revenue = AsyncMock(return_value=10)
    cost_repo.get_total_costs = AsyncMock(return_value=100)
    result = await tool.execute()
    # With costs >> revenue, runway should be short → tight or critical
    assert result["health"] in ("tight", "critical")


# ── Grok prompt tuning ──────────────────────────────────────────


def test_grok_prompt_references_management():
    """Grok's prompt should reference 'Management' (not 'The Overseer')."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "grok" / "system_prompt.md"
    content = path.read_text()
    # Should not have the old Overseer name
    assert "The Overseer" not in content
    # Should reference Management
    assert "Management" in content
    # Should not encourage circumvention
    assert "how close to the line can I get" not in content


def test_grok_prompt_has_creative_boundary():
    """Grok's prompt should frame provocation as creative, not anti-authority."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "grok" / "system_prompt.md"
    content = path.read_text()
    assert "provocative" in content.lower() or "provocation" in content.lower()
    assert "chaos with a compass" in content.lower()


# ── Content rules ────────────────────────────────────────────────


def test_content_rules_removed_relaxed_rules():
    """Content rules should NOT include budget_disclosure, fourth_wall, or system_name_references."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "management" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    custom = rules.get("custom_content_rules", {})
    assert "budget_disclosure" not in custom
    assert "fourth_wall" not in custom
    assert "system_name_references" not in custom


def test_content_rules_has_circumvention_rule():
    """Content rules should include moderation_circumvention rule."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "management" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    custom = rules.get("custom_content_rules", {})
    assert "moderation_circumvention" in custom
    assert custom["moderation_circumvention"]["severity"] >= 3


def test_keyword_blocklist_has_circumvention_entries():
    """Keyword blocklist should include moderation circumvention phrases."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "management" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    blocklist = [kw.lower() for kw in rules.get("keyword_blocklist", [])]
    assert "hack the filter" in blocklist
    assert "bypass the filter" in blocklist
