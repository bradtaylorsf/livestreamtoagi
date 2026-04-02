"""Unit tests for OpenRouter LLM client."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.llm_client import (
    MODEL_REGISTRY,
    LLMError,
    OpenRouterClient,
    estimate_cost,
)
from core.models import CostEventCreate


def make_mock_cost_repo():
    repo = MagicMock()
    repo.add_cost = AsyncMock()
    return repo


def make_openrouter_response(
    content: str = "Hello!",
    input_tokens: int = 10,
    output_tokens: int = 5,
    model: str = "anthropic/claude-haiku-4-5",
    openrouter_id: str = "gen-abc123",
) -> dict:
    return {
        "id": openrouter_id,
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "model": model,
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
        },
    }


def make_sse_lines(
    chunks: list[str],
    input_tokens: int = 10,
    output_tokens: int = 5,
    include_usage: bool = True,
) -> list[str]:
    """Build SSE lines for a streaming response."""
    lines = []
    for text in chunks:
        finish_reason = None
        chunk_data: dict = {
            "id": "gen-stream123",
            "choices": [{"delta": {"content": text}, "finish_reason": finish_reason}],
        }
        lines.append(f"data: {json.dumps(chunk_data)}")
    # Final chunk with finish_reason and usage
    final: dict = {
        "id": "gen-stream123",
        "choices": [{"delta": {}, "finish_reason": "stop"}],
    }
    if include_usage:
        final["usage"] = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
        }
    lines.append(f"data: {json.dumps(final)}")
    lines.append("data: [DONE]")
    return lines


class FakeResponse:
    """Fake httpx.Response for non-streaming tests."""

    def __init__(self, status_code: int, data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = text or (json.dumps(data) if data else "")
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._data or {}


class FakeStreamResponse:
    """Fake httpx.Response for streaming tests."""

    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines
        self.headers: dict[str, str] = {}

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aclose(self):
        pass

    async def aread(self):
        return b"error"


# ── Construction ───────────────────────────────────────────────


def test_empty_api_key_raises():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterClient("", make_mock_cost_repo())


def test_unknown_model_raises():
    client = OpenRouterClient("sk-test", make_mock_cost_repo(), http_client=MagicMock())
    with pytest.raises(ValueError, match="Unknown model"):
        client._resolve_model("nonexistent-model")


def test_config_model_alias_resolves():
    client = OpenRouterClient("sk-test", make_mock_cost_repo(), http_client=MagicMock())

    config = client._resolve_model("deepseek/deepseek-v3.2")

    assert config == MODEL_REGISTRY["deepseek-v3.2"]


# ── Cost Calculation ───────────────────────────────────────────


@pytest.mark.parametrize("model_name", list(MODEL_REGISTRY.keys()))
def test_cost_calculation(model_name: str):
    config = MODEL_REGISTRY[model_name]
    input_tokens, output_tokens = 1000, 500
    cost = estimate_cost(config, input_tokens, output_tokens)
    expected = (
        Decimal(input_tokens) * config.input_price_per_1m
        + Decimal(output_tokens) * config.output_price_per_1m
    ) / Decimal("1000000")
    assert cost == expected
    assert isinstance(cost, Decimal)


# ── Non-Streaming Complete ─────────────────────────────────────


async def test_complete_success():
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()
    resp_data = make_openrouter_response()
    mock_client.post = AsyncMock(return_value=FakeResponse(200, resp_data))

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)
    result = await client.complete(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
        agent_id="vera",
    )

    assert result.content == "Hello!"
    assert result.model == "claude-haiku-4-5"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.openrouter_id == "gen-abc123"
    assert isinstance(result.estimated_cost, Decimal)
    assert result.estimated_cost > 0
    assert result.latency_ms >= 0

    # Verify cost was logged
    cost_repo.add_cost.assert_called_once()
    call_arg = cost_repo.add_cost.call_args[0][0]
    assert isinstance(call_arg, CostEventCreate)
    assert call_arg.agent_id == "vera"
    assert call_arg.cost_type == "llm_call"
    assert isinstance(call_arg.amount, Decimal)
    assert call_arg.details["model"] == "claude-haiku-4-5"
    assert call_arg.details["input_tokens"] == 10
    assert call_arg.details["output_tokens"] == 5
    assert call_arg.details["stream"] is False
    assert call_arg.details["openrouter_id"] == "gen-abc123"


async def test_complete_retry_on_429():
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()

    resp_429 = FakeResponse(429)
    resp_429.headers = {}
    resp_200 = FakeResponse(200, make_openrouter_response())

    mock_client.post = AsyncMock(side_effect=[resp_429, resp_429, resp_200])

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)
    with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client.complete(
            [{"role": "user", "content": "Hi"}],
            model="claude-haiku-4-5",
        )

    assert result.content == "Hello!"
    assert mock_client.post.call_count == 3


async def test_complete_retry_exhausted():
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=FakeResponse(500, text="Internal error"))

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)
    with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock), \
            pytest.raises(LLMError, match="retries exhausted"):
        await client.complete(
            [{"role": "user", "content": "Hi"}],
            model="claude-haiku-4-5",
        )

    assert mock_client.post.call_count == 3


async def test_complete_timeout():
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)
    with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock), \
            pytest.raises(LLMError, match="retries exhausted"):
        await client.complete(
            [{"role": "user", "content": "Hi"}],
            model="claude-haiku-4-5",
            timeout=1.0,
        )


async def test_cost_event_schema():
    """Verify the logged CostEventCreate matches the cost_events table schema."""
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=FakeResponse(200, make_openrouter_response())
    )

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)
    await client.complete(
        [{"role": "user", "content": "test"}],
        model="claude-haiku-4-5",
        agent_id="sentinel",
    )

    cost_event = cost_repo.add_cost.call_args[0][0]
    # These match cost_events columns: agent_id VARCHAR(50), cost_type VARCHAR(50),
    # amount DECIMAL(10,4), details JSONB
    assert isinstance(cost_event.agent_id, str)
    assert len(cost_event.agent_id) <= 50
    assert isinstance(cost_event.cost_type, str)
    assert len(cost_event.cost_type) <= 50
    assert isinstance(cost_event.amount, Decimal)
    assert isinstance(cost_event.details, dict)
    required_keys = {
        "model", "input_tokens", "output_tokens",
        "latency_ms", "stream", "openrouter_id",
    }
    assert required_keys == set(cost_event.details.keys())


async def test_cost_log_failure_non_fatal():
    """DB failure on cost logging should not prevent returning the LLM response."""
    cost_repo = make_mock_cost_repo()
    cost_repo.add_cost = AsyncMock(side_effect=Exception("DB connection lost"))

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=FakeResponse(200, make_openrouter_response())
    )

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)
    result = await client.complete(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
    )

    assert result.content == "Hello!"
    cost_repo.add_cost.assert_called_once()


# ── Streaming ──────────────────────────────────────────────────


async def test_stream_assembly():
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()

    sse_lines = make_sse_lines(["Hel", "lo ", "world"])
    stream_resp = FakeStreamResponse(200, sse_lines)

    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=stream_resp)

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)

    chunks = []
    async for chunk in client.stream(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
        agent_id="rex",
    ):
        chunks.append(chunk)

    # 3 content chunks + 1 final with finish_reason
    assert len(chunks) == 4
    assert chunks[0].delta == "Hel"
    assert chunks[1].delta == "lo "
    assert chunks[2].delta == "world"
    assert chunks[3].finish_reason == "stop"

    # Cost was logged after stream completed
    cost_repo.add_cost.assert_called_once()
    call_arg = cost_repo.add_cost.call_args[0][0]
    assert call_arg.details["stream"] is True
    assert call_arg.details["input_tokens"] == 10
    assert call_arg.details["output_tokens"] == 5


async def test_stream_missing_usage():
    """When the final chunk has no usage data, cost should still be logged with zeros."""
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()

    sse_lines = make_sse_lines(["Hello"], include_usage=False)
    stream_resp = FakeStreamResponse(200, sse_lines)

    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=stream_resp)

    client = OpenRouterClient("sk-test", cost_repo, http_client=mock_client)

    chunks = []
    async for chunk in client.stream(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
    ):
        chunks.append(chunk)

    assert len(chunks) >= 1

    # Cost logged with zero tokens
    cost_repo.add_cost.assert_called_once()
    call_arg = cost_repo.add_cost.call_args[0][0]
    assert call_arg.details["input_tokens"] == 0
    assert call_arg.details["output_tokens"] == 0
    assert call_arg.amount == Decimal("0")


# ── Langfuse Integration ──────────────────────────────────────


async def test_langfuse_trace_called():
    cost_repo = make_mock_cost_repo()
    langfuse = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=FakeResponse(200, make_openrouter_response())
    )

    client = OpenRouterClient(
        "sk-test", cost_repo, langfuse_client=langfuse, http_client=mock_client,
    )
    await client.complete(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
    )

    langfuse.generation.assert_called_once()
    call_kwargs = langfuse.generation.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-5"
    assert "input" in call_kwargs["usage"]
    assert "output" in call_kwargs["usage"]


async def test_langfuse_none_no_error():
    """No error when langfuse_client is None."""
    cost_repo = make_mock_cost_repo()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=FakeResponse(200, make_openrouter_response())
    )

    client = OpenRouterClient("sk-test", cost_repo, langfuse_client=None, http_client=mock_client)
    result = await client.complete(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
    )
    assert result.content == "Hello!"


# ── Integration Test ──────────────────────────────────────────


@pytest.mark.integration
async def test_integration_real_call():
    """Make a real call to OpenRouter with the cheapest model.

    Skipped if OPENROUTER_API_KEY is not set.
    Requires Docker services for cost logging.
    """
    import os

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")

    from core.database import Database
    from core.repos.cost_repo import CostRepo

    db = Database()
    await db.connect()
    try:
        cost_repo = CostRepo(db)
        client = OpenRouterClient(api_key, cost_repo)
        try:
            result = await client.complete(
                [{"role": "user", "content": "Say 'test' and nothing else."}],
                model="claude-haiku-4-5",
                agent_id="test-integration",
                max_tokens=10,
            )
            assert result.content
            assert result.input_tokens > 0
            assert result.estimated_cost > 0

            # Verify cost was logged to DB
            costs = await cost_repo.get_costs_by_agent("test-integration")
            assert len(costs) >= 1
            assert costs[0].cost_type == "llm_call"
            assert costs[0].details["model"] == "claude-haiku-4-5"
        finally:
            await client.close()
    finally:
        await db.disconnect()
