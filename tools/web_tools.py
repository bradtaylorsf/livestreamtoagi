"""Web search and URL fetch tools — web_search, fetch_url."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from core.event_bus import EventType
from core.models import CostEventCreate

from .base import BaseTool

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.redis_client import RedisClient
    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

# Default cost estimates per operation
SEARCH_COST = Decimal("0.005")
FETCH_COST = Decimal("0.001")

# Token-to-char ratio approximation (1 token ≈ 4 chars)
MAX_FETCH_TOKENS = 4000
MAX_FETCH_CHARS = MAX_FETCH_TOKENS * 4

# Rate limit: max searches per agent per hour
RATE_LIMIT_MAX = 10
RATE_LIMIT_TTL = 3600


class WebSearchTool(BaseTool):
    """Search the web for information using a configurable search API."""

    name = "web_search"
    description = "Search the web for information"
    parameters: dict[str, Any] = {
        "query": {"type": "string", "description": "Search query"},
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results (default 5)",
        },
    }

    ALLOWED_AGENTS = frozenset({"pixel", "grok", "aurora", "vera"})

    def __init__(
        self,
        event_bus: EventBus,
        redis_client: RedisClient,
        agent_id: str,
        cost_repo: CostRepo | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._redis = redis_client
        self._agent_id = agent_id
        self._cost_repo = cost_repo
        self._http = http_client

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs.get("query", "")
        max_results: int = kwargs.get("max_results", 5)

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {
                "status": "rejected",
                "reason": f"Agent {self._agent_id!r} not authorized",
            }

        if not query.strip():
            return {"status": "error", "reason": "Query cannot be empty"}

        # Rate limiting via Redis INCR + EXPIRE
        rate_key = f"web_search:rate:{self._agent_id}"
        count = await self._redis.incr(rate_key)
        if count == 1:
            await self._redis.expire(rate_key, RATE_LIMIT_TTL)
        if count > RATE_LIMIT_MAX:
            return {
                "status": "rate_limited",
                "reason": f"Rate limit exceeded ({RATE_LIMIT_MAX} searches/hour)",
            }

        # Perform the search
        api_key = os.getenv("SEARCH_API_KEY", "")
        if not api_key:
            return {"status": "error", "reason": "SEARCH_API_KEY not configured"}

        provider = os.getenv("SEARCH_API_PROVIDER", "brave")
        try:
            results = await self._search(
                provider, api_key, query, max_results
            )
        except httpx.HTTPError as exc:
            logger.error("Web search failed: %s", exc)
            return {"status": "error", "reason": f"Search request failed: {exc}"}

        # Track cost
        if self._cost_repo is not None:
            await self._cost_repo.add_cost(
                CostEventCreate(
                    agent_id=self._agent_id,
                    cost_type="web_search",
                    amount=SEARCH_COST,
                    details={"query": query, "provider": provider},
                )
            )

        await self._event_bus.emit(
            EventType.TOOL_EXECUTED,
            {
                "tool": self.name,
                "agent_id": self._agent_id,
                "query": query,
                "result_count": len(results),
            },
        )

        return {"status": "ok", "results": results}

    async def _search(
        self,
        provider: str,
        api_key: str,
        query: str,
        max_results: int,
    ) -> list[dict[str, str]]:
        """Call the search API and return normalized results."""
        client = self._http or httpx.AsyncClient(timeout=15)
        close_after = self._http is None
        try:
            if provider == "brave":
                return await self._brave_search(
                    client, api_key, query, max_results
                )
            return await self._brave_search(
                client, api_key, query, max_results
            )
        finally:
            if close_after:
                await client.aclose()

    async def _brave_search(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        query: str,
        max_results: int,
    ) -> list[dict[str, str]]:
        """Search via Brave Search API."""
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, str]] = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                }
            )
        return results


class FetchUrlTool(BaseTool):
    """Fetch and read content from a specific URL."""

    name = "fetch_url"
    description = "Fetch and read content from a URL (truncated to 4,000 tokens)"
    parameters: dict[str, Any] = {
        "url": {"type": "string", "description": "URL to fetch"},
    }

    ALLOWED_AGENTS = frozenset({"pixel", "grok"})

    def __init__(
        self,
        event_bus: EventBus,
        redis_client: RedisClient,
        agent_id: str,
        cost_repo: CostRepo | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._redis = redis_client
        self._agent_id = agent_id
        self._cost_repo = cost_repo
        self._http = http_client

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        url: str = kwargs.get("url", "")

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {
                "status": "rejected",
                "reason": f"Agent {self._agent_id!r} not authorized",
            }

        if not url.strip():
            return {"status": "error", "reason": "URL cannot be empty"}

        if not _is_safe_url(url):
            return {"status": "error", "reason": "URL blocked: must be public http(s)"}

        # DNS resolution check — block domains resolving to private IPs
        parsed_host = urlparse(url).hostname or ""
        if parsed_host and _dns_resolves_to_private(parsed_host):
            return {"status": "error", "reason": "URL blocked: resolves to private address"}

        client = self._http or httpx.AsyncClient(timeout=15)
        close_after = self._http is None
        try:
            resp = await client.get(
                url,
                follow_redirects=True,
                headers={"User-Agent": "LivestreamToAGI-Bot/1.0"},
            )
            resp.raise_for_status()

            # Validate final URL after redirects to prevent SSRF via open redirects
            try:
                final_url = str(resp.url)
                if final_url != url and final_url.startswith(("http://", "https://")) and not _is_safe_url(final_url):
                    return {"status": "error", "reason": "URL blocked: redirect target is not public"}
            except Exception:
                pass  # If resp.url is unavailable, skip redirect check
        except httpx.HTTPError as exc:
            logger.error("URL fetch failed for %s: %s", url, exc)
            return {"status": "error", "reason": f"Fetch failed: {exc}"}
        finally:
            if close_after:
                await client.aclose()

        # Strip HTML tags to get plain text
        raw = resp.text
        text = _strip_html(raw)

        # Truncate to ~4000 tokens
        truncated = len(text) > MAX_FETCH_CHARS
        if truncated:
            text = text[:MAX_FETCH_CHARS]

        # Track cost
        if self._cost_repo is not None:
            await self._cost_repo.add_cost(
                CostEventCreate(
                    agent_id=self._agent_id,
                    cost_type="fetch_url",
                    amount=FETCH_COST,
                    details={"url": url},
                )
            )

        await self._event_bus.emit(
            EventType.TOOL_EXECUTED,
            {
                "tool": self.name,
                "agent_id": self._agent_id,
                "url": url,
                "content_length": len(text),
                "truncated": truncated,
            },
        )

        return {
            "status": "ok",
            "url": url,
            "content": text,
            "truncated": truncated,
        }


def _is_safe_url(url: str) -> bool:
    """Block private/internal URLs to prevent SSRF."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname or ""
    if not hostname:
        return False

    # Block obvious internal hostnames
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
        return False

    # Block private/reserved IP ranges
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    except ValueError:
        pass  # hostname is a domain name, not an IP — allow

    return True


def _dns_resolves_to_private(hostname: str) -> bool:
    """Resolve hostname and check if any resolved IP is private/internal."""
    import socket

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in infos:
            addr = ipaddress.ip_address(sockaddr[0])
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return True
    except (socket.gaierror, ValueError):
        return False  # Unresolvable hostname — let HTTP layer handle it
    return False


def _strip_html(html: str) -> str:
    """Remove HTML tags, scripts, styles, and collapse whitespace."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
