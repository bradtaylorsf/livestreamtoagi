"""Tests for fourth-wall break prevention and budget disclosure (Issue #217)."""

from __future__ import annotations

from pathlib import Path

import yaml
import pytest


# ── Infrastructure prompt ────────────────────────────────────────


def test_infrastructure_prompt_forbids_system_references():
    """INFRASTRUCTURE_PROMPT should forbid referencing internal system names."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    prompt_lower = INFRASTRUCTURE_PROMPT.lower()
    assert "never reference internal system components" in prompt_lower
    assert "transcripts" in prompt_lower
    assert "context windows" in prompt_lower


def test_infrastructure_prompt_forbids_budget_disclosure():
    """INFRASTRUCTURE_PROMPT should forbid disclosing exact budget figures."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    prompt_lower = INFRASTRUCTURE_PROMPT.lower()
    assert "never disclose exact budget figures" in prompt_lower
    assert "dollar amounts" in prompt_lower


def test_infrastructure_prompt_forbids_ai_discussion():
    """INFRASTRUCTURE_PROMPT should forbid discussing being AI."""
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    prompt_lower = INFRASTRUCTURE_PROMPT.lower()
    assert "do not discuss being ai" in prompt_lower


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


def test_grok_prompt_no_overseer_reference():
    """Grok's prompt should not reference 'The Overseer' by name."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "grok" / "system_prompt.md"
    content = path.read_text()
    # Should not have the old catchphrase
    assert "The Overseer isn't going to like this" not in content
    # Should not encourage circumvention
    assert "how close to the line can I get" not in content


def test_grok_prompt_has_creative_boundary():
    """Grok's prompt should frame provocation as creative, not anti-authority."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "grok" / "system_prompt.md"
    content = path.read_text()
    assert "creative" in content.lower() or "provocation" in content.lower()
    assert "never by encouraging others to break rules" in content.lower()


# ── Content rules ────────────────────────────────────────────────


def test_content_rules_has_system_name_rule():
    """Content rules should include system_name_references rule."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "overseer" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    custom = rules.get("custom_content_rules", {})
    assert "system_name_references" in custom
    assert custom["system_name_references"]["severity"] >= 2


def test_content_rules_has_circumvention_rule():
    """Content rules should include moderation_circumvention rule."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "overseer" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    custom = rules.get("custom_content_rules", {})
    assert "moderation_circumvention" in custom
    assert custom["moderation_circumvention"]["severity"] >= 3


def test_content_rules_budget_severity_increased():
    """Budget disclosure rule should be severity 2+."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "overseer" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    custom = rules.get("custom_content_rules", {})
    assert custom["budget_disclosure"]["severity"] >= 2


def test_content_rules_fourth_wall_severity_increased():
    """Fourth wall rule should be severity 2+ (up from 1)."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "overseer" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    custom = rules.get("custom_content_rules", {})
    assert custom["fourth_wall"]["severity"] >= 2


def test_keyword_blocklist_has_circumvention_entries():
    """Keyword blocklist should include moderation circumvention phrases."""
    path = Path(__file__).resolve().parent.parent.parent / "agents" / "overseer" / "content_rules.yaml"
    with open(path) as f:
        rules = yaml.safe_load(f)
    blocklist = [kw.lower() for kw in rules.get("keyword_blocklist", [])]
    assert "hack the filter" in blocklist
    assert "bypass the filter" in blocklist
