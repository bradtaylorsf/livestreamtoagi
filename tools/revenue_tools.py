"""Revenue tracking and marketing tools — get_revenue_status, draft_social_post, draft_email."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .base import BaseTool

if TYPE_CHECKING:
    from core.redis_client import RedisClient
    from core.repos.cost_repo import CostRepo


class GetRevenueStatusTool(BaseTool):
    """Get financial health metrics: revenue, costs, burn rate, and runway."""

    name = "get_revenue_status"
    description = "Get monthly revenue, costs, burn rate, runway days, and trend"
    parameters: dict[str, Any] = {}

    ALLOWED_AGENTS = frozenset({"sentinel", "vera"})

    def __init__(
        self,
        cost_repo: CostRepo,
        agent_id: str,
        economy_manager: object | None = None,
    ) -> None:
        self._cost_repo = cost_repo
        self._agent_id = agent_id
        self._economy = economy_manager

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)
        sixty_days_ago = now - timedelta(days=60)

        # Current 30-day window
        monthly_revenue = await self._cost_repo.get_total_revenue(since=thirty_days_ago)
        monthly_costs = await self._cost_repo.get_total_costs(since=thirty_days_ago)

        # Prior 30-day window for trend
        prior_revenue = await self._cost_repo.get_total_revenue(since=sixty_days_ago)
        prior_costs = await self._cost_repo.get_total_costs(since=sixty_days_ago)
        # Subtract current window from the 60-day totals to get prior-only
        prior_revenue = prior_revenue - monthly_revenue
        prior_costs = prior_costs - monthly_costs

        # Burn rate = net costs per day over last 30 days
        net_burn = float(monthly_costs - monthly_revenue)
        burn_rate = round(net_burn / 30, 2)

        # Runway: total balance / daily burn rate
        total_revenue = await self._cost_repo.get_total_revenue()
        total_costs = await self._cost_repo.get_total_costs()
        balance = float(total_revenue - total_costs)

        runway_days = max(0, int(balance / burn_rate)) if burn_rate > 0 else -1

        # Trend based on net burn comparison
        current_net = float(monthly_revenue - monthly_costs)
        prior_net = float(prior_revenue - prior_costs)
        if current_net > prior_net + 1:
            trend = "improving"
        elif current_net < prior_net - 1:
            trend = "declining"
        else:
            trend = "stable"

        # Determine health status from runway
        if runway_days < 0:
            health = "healthy"  # revenue exceeds costs
        elif runway_days > 90:
            health = "healthy"
        elif runway_days > 30:
            health = "tight"
        else:
            health = "critical"

        # Include individual balance if economy manager is available
        balance_note = ""
        if self._economy is not None:
            try:
                agent_balance = await self._economy.get_balance(self._agent_id)
                balance_note = f" Your personal balance: ${agent_balance:.2f}."
            except Exception:
                pass

        # Return summary for agent-visible output (no raw dollar amounts).
        # Raw numbers are persisted in the artifact metadata for Brad's dashboard.
        return {
            "status": "ok",
            "health": health,
            "trend": trend,
            "summary": (
                f"Budget is {health}. Trend is {trend}. "
                f"Runway: {'plenty of' if health == 'healthy' else 'limited'} time remaining."
                f"{balance_note}"
            ),
            "_internal": {
                "monthly_revenue": float(monthly_revenue),
                "monthly_costs": float(monthly_costs),
                "burn_rate": burn_rate,
                "runway_days": runway_days,
            },
        }


class DraftSocialPostTool(BaseTool):
    """Draft a social media post for human review before publishing."""

    name = "draft_social_post"
    description = "Create a social post draft (requires human approval before sending)"
    parameters = {
        "platform": {
            "type": "string",
            "description": "Target platform",
            "enum": ["twitter", "discord", "youtube_community"],
        },
        "content": {"type": "string", "description": "Post content"},
        "media_urls": {
            "type": "array",
            "description": "Optional media URLs to attach",
            "items": {"type": "string"},
        },
    }

    SUPPORTED_PLATFORMS = frozenset({"twitter", "discord", "youtube_community"})
    ALLOWED_AGENTS = frozenset({"aurora", "pixel", "grok"})

    def __init__(self, redis_client: RedisClient, agent_id: str) -> None:
        self._redis = redis_client
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        platform: str = kwargs["platform"]
        content: str = kwargs["content"]
        media_urls: list[str] = kwargs.get("media_urls", [])

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        if platform not in self.SUPPORTED_PLATFORMS:
            supported = sorted(self.SUPPORTED_PLATFORMS)
            return {
                "status": "rejected",
                "reason": f"Unsupported platform {platform!r}. Must be one of: {supported}",
            }

        draft_id = str(uuid.uuid4())
        draft_data = {
            "draft_id": draft_id,
            "status": "pending_human_review",
            "agent_id": self._agent_id,
            "platform": platform,
            "content": content,
            "media_urls": media_urls,
            "timestamp": time.time(),
        }

        await self._redis.set(f"drafts:social:{draft_id}", json.dumps(draft_data))

        return {"draft_id": draft_id, "status": "pending_human_review"}


class DraftEmailTool(BaseTool):
    """Draft an email for human review before sending."""

    name = "draft_email"
    description = "Create an email draft (requires human approval before sending)"
    parameters = {
        "to": {"type": "string", "description": "Recipient email address"},
        "subject": {"type": "string", "description": "Email subject line"},
        "body": {"type": "string", "description": "Email body content"},
    }

    ALLOWED_AGENTS = frozenset({"aurora", "vera", "pixel"})

    def __init__(self, redis_client: RedisClient, agent_id: str) -> None:
        self._redis = redis_client
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        to: str = kwargs["to"]
        subject: str = kwargs["subject"]
        body: str = kwargs["body"]

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        draft_id = str(uuid.uuid4())
        draft_data = {
            "draft_id": draft_id,
            "status": "pending_human_review",
            "agent_id": self._agent_id,
            "to": to,
            "subject": subject,
            "body": body,
            "timestamp": time.time(),
        }

        await self._redis.set(f"drafts:email:{draft_id}", json.dumps(draft_data))

        return {"draft_id": draft_id, "status": "pending_human_review"}


class CheckPostPerformanceTool(BaseTool):
    """Check how a social post is performing — likes, comments, shares."""

    name = "check_post_performance"
    description = "Check engagement metrics for a previously drafted social post"
    parameters = {
        "draft_id": {"type": "string", "description": "The draft_id returned by draft_social_post"},
    }

    ALLOWED_AGENTS = frozenset({"aurora", "pixel", "grok", "vera", "sentinel"})

    def __init__(self, redis_client: RedisClient, agent_id: str) -> None:
        self._redis = redis_client
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        draft_id: str = kwargs["draft_id"]

        # Check draft status
        draft_raw = await self._redis.get(f"drafts:social:{draft_id}")
        if not draft_raw:
            return {"status": "not_found", "reason": f"No social post found with id {draft_id}"}

        try:
            draft = json.loads(draft_raw)
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "reason": "Could not read draft data"}

        draft_status = draft.get("status", "unknown")

        # Check engagement data
        engagement_raw = await self._redis.get(f"social:post:{draft_id}:engagement")
        if not engagement_raw:
            return {
                "status": "ok",
                "draft_status": draft_status,
                "engagement": None,
                "summary": f"Post is {draft_status}. No engagement data yet.",
            }

        try:
            engagement = json.loads(engagement_raw)
        except (json.JSONDecodeError, TypeError):
            return {"status": "ok", "draft_status": draft_status, "engagement": None}

        likes = engagement.get("likes", 0)
        comments = engagement.get("comments", [])
        shares = engagement.get("shares", 0)

        return {
            "status": "ok",
            "draft_status": draft_status,
            "likes": likes,
            "comments_count": len(comments),
            "shares": shares,
            "top_comments": [c.get("text", "") for c in comments[:5]],
            "summary": (
                f"Post has {likes} likes, {len(comments)} comments, {shares} shares. "
                f"{'Going well!' if likes > 100 else 'Modest engagement.'}"
            ),
        }


class CheckEmailResponsesTool(BaseTool):
    """Check if there are responses to previously drafted emails."""

    name = "check_email_responses"
    description = "Check for responses to a previously drafted email"
    parameters = {
        "draft_id": {"type": "string", "description": "The draft_id returned by draft_email"},
    }

    ALLOWED_AGENTS = frozenset({"aurora", "vera", "pixel"})

    def __init__(self, redis_client: RedisClient, agent_id: str) -> None:
        self._redis = redis_client
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        draft_id: str = kwargs["draft_id"]

        # Check draft status
        draft_raw = await self._redis.get(f"drafts:email:{draft_id}")
        if not draft_raw:
            return {"status": "not_found", "reason": f"No email found with id {draft_id}"}

        try:
            draft = json.loads(draft_raw)
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "reason": "Could not read draft data"}

        draft_status = draft.get("status", "unknown")

        # Check for response
        response_raw = await self._redis.get(f"email:response:{draft_id}")
        if not response_raw:
            return {
                "status": "ok",
                "draft_status": draft_status,
                "response": None,
                "summary": f"Email is {draft_status}. No response yet.",
            }

        try:
            response_data = json.loads(response_raw)
        except (json.JSONDecodeError, TypeError):
            return {"status": "ok", "draft_status": draft_status, "response": None}

        return {
            "status": "ok",
            "draft_status": draft_status,
            "sentiment": response_data.get("sentiment", "unknown"),
            "response_text": response_data.get("response", ""),
            "summary": (
                f"Received a {response_data.get('sentiment', 'unknown')} response: "
                f"{response_data.get('response', '')[:200]}"
            ),
        }
