"""Tests for web search and URL fetch tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tools.web_tools import (
    FETCH_COST,
    MAX_FETCH_CHARS,
    RATE_LIMIT_MAX,
    SEARCH_COST,
    FetchUrlTool,
    WebSearchTool,
    _is_safe_url,
    _strip_html,
)

# --- Fixtures ---


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def redis_client() -> AsyncMock:
    client = AsyncMock()
    client.incr = AsyncMock(return_value=1)
    client.expire = AsyncMock()
    return client


@pytest.fixture
def cost_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.add_cost = AsyncMock()
    return repo


@pytest.fixture
def mock_http_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


# --- WebSearchTool interface ---


class TestWebSearchInterface:
    def test_name_and_description(self, event_bus: AsyncMock, redis_client: AsyncMock) -> None:
        tool = WebSearchTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        assert tool.name == "web_search"
        assert "search" in tool.description.lower()

    def test_parameters_schema(self, event_bus: AsyncMock, redis_client: AsyncMock) -> None:
        tool = WebSearchTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        assert "query" in tool.parameters
        assert "max_results" in tool.parameters

    def test_allowed_agents(self) -> None:
        assert frozenset({"pixel", "grok", "aurora", "vera"}) == WebSearchTool.ALLOWED_AGENTS


# --- WebSearchTool access control ---


class TestWebSearchAccess:
    @pytest.mark.parametrize("agent_id", ["pixel", "grok", "aurora", "vera"])
    async def test_authorized_agents_accepted(
        self,
        agent_id: str,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        # Mock a successful search response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {"results": [{"title": "T", "url": "https://x.com", "description": "S"}]}
        }
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id=agent_id,
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "test-key"}):
            result = await tool.execute(query="test")
        assert result["status"] == "ok"

    @pytest.mark.parametrize("agent_id", ["rex", "sentinel", "fork", "alpha", "overseer"])
    async def test_unauthorized_agents_rejected(
        self,
        agent_id: str,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
    ) -> None:
        tool = WebSearchTool(event_bus=event_bus, redis_client=redis_client, agent_id=agent_id)
        result = await tool.execute(query="test")
        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]


# --- WebSearchTool functionality ---


class TestWebSearchFunctionality:
    async def test_returns_correct_format(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
        cost_repo: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {"title": "Result 1", "url": "https://a.com", "description": "Snippet 1"},
                    {"title": "Result 2", "url": "https://b.com", "description": "Snippet 2"},
                ]
            }
        }
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            cost_repo=cost_repo,
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key123"}):
            result = await tool.execute(query="AI news")

        assert result["status"] == "ok"
        assert len(result["results"]) == 2
        assert result["results"][0] == {
            "title": "Result 1",
            "url": "https://a.com",
            "snippet": "Snippet 1",
        }
        assert result["results"][1]["title"] == "Result 2"

    async def test_empty_query_rejected(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        tool = WebSearchTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        result = await tool.execute(query="   ")
        assert result["status"] == "error"
        assert "empty" in result["reason"].lower()

    async def test_missing_api_key_returns_error(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        tool = WebSearchTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        with patch.dict("os.environ", {"SEARCH_API_KEY": ""}, clear=False):
            result = await tool.execute(query="test")
        assert result["status"] == "error"
        assert "SEARCH_API_KEY" in result["reason"]

    async def test_cost_tracked(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
        cost_repo: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="grok",
            cost_repo=cost_repo,
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            await tool.execute(query="trending topics")

        cost_repo.add_cost.assert_called_once()
        cost_arg = cost_repo.add_cost.call_args[0][0]
        assert cost_arg.amount == SEARCH_COST
        assert cost_arg.cost_type == "web_search"
        assert cost_arg.agent_id == "grok"

    async def test_event_emitted(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            await tool.execute(query="test")

        event_bus.emit.assert_called_once()
        call_args = event_bus.emit.call_args
        assert call_args[0][0] == "tool_executed"
        assert call_args[0][1]["tool"] == "web_search"

    async def test_http_error_handled(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_http_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            result = await tool.execute(query="test")

        assert result["status"] == "error"
        assert "failed" in result["reason"].lower()


# --- WebSearchTool rate limiting ---


class TestWebSearchRateLimiting:
    async def test_under_limit_allowed(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        redis_client.incr = AsyncMock(return_value=5)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            result = await tool.execute(query="test")
        assert result["status"] == "ok"

    async def test_at_limit_allowed(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        redis_client.incr = AsyncMock(return_value=RATE_LIMIT_MAX)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            result = await tool.execute(query="test")
        assert result["status"] == "ok"

    async def test_over_limit_rejected(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        redis_client.incr = AsyncMock(return_value=RATE_LIMIT_MAX + 1)

        tool = WebSearchTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            result = await tool.execute(query="test")
        assert result["status"] == "rate_limited"
        assert "Rate limit" in result["reason"]

    async def test_first_request_sets_ttl(
        self, event_bus: AsyncMock, redis_client: AsyncMock, mock_http_client: AsyncMock
    ) -> None:
        redis_client.incr = AsyncMock(return_value=1)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            await tool.execute(query="test")

        redis_client.expire.assert_called_once_with(
            "web_search:rate:pixel", 3600
        )

    async def test_subsequent_request_no_ttl_reset(
        self, event_bus: AsyncMock, redis_client: AsyncMock, mock_http_client: AsyncMock
    ) -> None:
        redis_client.incr = AsyncMock(return_value=3)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        with patch.dict("os.environ", {"SEARCH_API_KEY": "key"}):
            await tool.execute(query="test")

        redis_client.expire.assert_not_called()


# --- FetchUrlTool interface ---


class TestFetchUrlInterface:
    def test_name_and_description(self, event_bus: AsyncMock, redis_client: AsyncMock) -> None:
        tool = FetchUrlTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        assert tool.name == "fetch_url"
        assert "url" in tool.description.lower()

    def test_parameters_schema(self, event_bus: AsyncMock, redis_client: AsyncMock) -> None:
        tool = FetchUrlTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        assert "url" in tool.parameters

    def test_allowed_agents(self) -> None:
        assert frozenset({"pixel", "grok"}) == FetchUrlTool.ALLOWED_AGENTS


# --- FetchUrlTool access control ---


class TestFetchUrlAccess:
    @pytest.mark.parametrize("agent_id", ["pixel", "grok"])
    async def test_authorized_agents_accepted(
        self,
        agent_id: str,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "<html><body>Hello world</body></html>"
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id=agent_id,
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://example.com")
        assert result["status"] == "ok"

    @pytest.mark.parametrize("agent_id", ["aurora", "vera", "rex", "sentinel", "fork"])
    async def test_unauthorized_agents_rejected(
        self,
        agent_id: str,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
    ) -> None:
        tool = FetchUrlTool(event_bus=event_bus, redis_client=redis_client, agent_id=agent_id)
        result = await tool.execute(url="https://example.com")
        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]


# --- FetchUrlTool functionality ---


class TestFetchUrlFunctionality:
    async def test_returns_correct_format(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "<html><body><p>Page content here</p></body></html>"
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://example.com")

        assert result["status"] == "ok"
        assert result["url"] == "https://example.com"
        assert "Page content here" in result["content"]
        assert isinstance(result["truncated"], bool)

    async def test_truncates_at_4000_tokens(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        # Generate content that exceeds MAX_FETCH_CHARS
        long_content = "word " * 10000  # ~50000 chars, well over 16000
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = long_content
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://example.com/long")

        assert result["truncated"] is True
        assert len(result["content"]) == MAX_FETCH_CHARS

    async def test_short_content_not_truncated(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "Short content"
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://example.com")

        assert result["truncated"] is False
        assert result["content"] == "Short content"

    async def test_html_tags_stripped(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        html = "<html><head><title>T</title></head><body><h1>Hello</h1><p>World</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="grok",
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://example.com")

        assert "<" not in result["content"]
        assert "Hello" in result["content"]
        assert "World" in result["content"]

    async def test_scripts_and_styles_removed(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        html = (
            "<html><script>alert('xss')</script>"
            "<style>body{color:red}</style>"
            "<p>Visible</p></html>"
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://example.com")

        assert "alert" not in result["content"]
        assert "color:red" not in result["content"]
        assert "Visible" in result["content"]

    async def test_empty_url_rejected(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        tool = FetchUrlTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        result = await tool.execute(url="")
        assert result["status"] == "error"
        assert "empty" in result["reason"].lower()

    async def test_http_error_handled(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_http_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        result = await tool.execute(url="https://down.example.com")

        assert result["status"] == "error"
        assert "failed" in result["reason"].lower()

    async def test_cost_tracked(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
        cost_repo: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "Content"
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            cost_repo=cost_repo,
            http_client=mock_http_client,
        )
        await tool.execute(url="https://example.com")

        cost_repo.add_cost.assert_called_once()
        cost_arg = cost_repo.add_cost.call_args[0][0]
        assert cost_arg.amount == FETCH_COST
        assert cost_arg.cost_type == "fetch_url"

    async def test_event_emitted(
        self,
        event_bus: AsyncMock,
        redis_client: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "Content"
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        tool = FetchUrlTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
            http_client=mock_http_client,
        )
        await tool.execute(url="https://example.com")

        event_bus.emit.assert_called_once()
        call_args = event_bus.emit.call_args
        assert call_args[0][0] == "tool_executed"
        assert call_args[0][1]["tool"] == "fetch_url"


# --- SSRF protection ---


class TestSafeUrl:
    def test_public_https_allowed(self) -> None:
        assert _is_safe_url("https://example.com") is True

    def test_public_http_allowed(self) -> None:
        assert _is_safe_url("http://example.com") is True

    def test_localhost_blocked(self) -> None:
        assert _is_safe_url("http://localhost:8000/secret") is False

    def test_127_0_0_1_blocked(self) -> None:
        assert _is_safe_url("http://127.0.0.1/admin") is False

    def test_private_ip_blocked(self) -> None:
        assert _is_safe_url("http://192.168.1.1") is False
        assert _is_safe_url("http://10.0.0.1") is False

    def test_link_local_blocked(self) -> None:
        assert _is_safe_url("http://169.254.169.254/latest/meta-data") is False

    def test_ftp_scheme_blocked(self) -> None:
        assert _is_safe_url("ftp://files.example.com/data") is False

    def test_file_scheme_blocked(self) -> None:
        assert _is_safe_url("file:///etc/passwd") is False

    def test_empty_url_blocked(self) -> None:
        assert _is_safe_url("") is False


class TestFetchUrlSsrfProtection:
    async def test_localhost_rejected(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        tool = FetchUrlTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        result = await tool.execute(url="http://localhost:8000/internal")
        assert result["status"] == "error"
        assert "blocked" in result["reason"].lower()

    async def test_metadata_endpoint_rejected(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        tool = FetchUrlTool(event_bus=event_bus, redis_client=redis_client, agent_id="pixel")
        result = await tool.execute(url="http://169.254.169.254/latest/meta-data")
        assert result["status"] == "error"
        assert "blocked" in result["reason"].lower()


# --- _strip_html helper ---


class TestStripHtml:
    def test_basic_tag_removal(self) -> None:
        assert "Hello" in _strip_html("<p>Hello</p>")

    def test_entity_decoding(self) -> None:
        result = _strip_html("A &amp; B &lt; C &gt; D")
        assert "A & B < C > D" in result

    def test_script_removal(self) -> None:
        result = _strip_html("<script>var x = 1;</script>Text")
        assert "var x" not in result
        assert "Text" in result

    def test_whitespace_collapse(self) -> None:
        result = _strip_html("<p>  Hello  </p>  <p>  World  </p>")
        assert "  " not in result
        assert "Hello" in result


# --- Integration test (requires real API key, skipped by default) ---


@pytest.mark.integration
class TestWebSearchIntegration:
    async def test_real_search_returns_results(self) -> None:
        """Integration test: performs a real web search (requires SEARCH_API_KEY)."""
        import os

        api_key = os.getenv("SEARCH_API_KEY", "")
        if not api_key:
            pytest.skip("SEARCH_API_KEY not set")

        event_bus = AsyncMock()
        event_bus.emit = AsyncMock()
        redis_client = AsyncMock()
        inner = AsyncMock()
        inner.incr = AsyncMock(return_value=1)
        inner.expire = AsyncMock()
        redis_client.client = inner

        tool = WebSearchTool(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="pixel",
        )
        result = await tool.execute(query="Python programming language", max_results=3)

        assert result["status"] == "ok"
        assert len(result["results"]) > 0
        assert "title" in result["results"][0]
        assert "url" in result["results"][0]
        assert "snippet" in result["results"][0]
