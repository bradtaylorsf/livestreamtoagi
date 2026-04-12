"""Tests for the diagnostics endpoint and LLM cost tracking improvements."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm_client import OpenRouterClient


def _make_client(cost_repo: AsyncMock | None = None) -> OpenRouterClient:
    """Create an OpenRouterClient with a mock cost_repo."""
    repo = cost_repo or AsyncMock()
    return OpenRouterClient(
        api_key="test-key",
        cost_repo=repo,
        http_client=AsyncMock(),
    )


# ── diagnostics() method ────────────────────────────────────


class TestDiagnostics:
    def test_initial_state_all_zeros(self) -> None:
        client = _make_client()
        diag = client.diagnostics()

        assert diag["lost_cost_events"] == 0
        assert diag["last_failure_ts"] is None
        assert diag["total_cost_calls"] == 0
        assert diag["loss_rate"] == 0.0

    async def test_tracks_total_calls(self) -> None:
        repo = AsyncMock()
        client = _make_client(cost_repo=repo)

        await client._log_cost(
            agent_id="rex", model="test", input_tokens=10,
            output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
            stream=False, openrouter_id="or-1",
        )

        diag = client.diagnostics()
        assert diag["total_cost_calls"] == 1
        assert diag["lost_cost_events"] == 0

    async def test_tracks_lost_events_after_all_retries_fail(self) -> None:
        repo = AsyncMock()
        repo.add_cost.side_effect = RuntimeError("DB down")
        client = _make_client(cost_repo=repo)

        with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-1",
            )

        diag = client.diagnostics()
        assert diag["lost_cost_events"] == 1
        assert diag["total_cost_calls"] == 1
        assert diag["last_failure_ts"] is not None
        assert diag["loss_rate"] == 1.0

    async def test_loss_rate_calculation(self) -> None:
        repo = AsyncMock()
        call_count = 0

        async def _alternating_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:  # First call's 4 attempts all fail
                raise RuntimeError("fail")

        repo.add_cost.side_effect = _alternating_fail
        client = _make_client(cost_repo=repo)

        with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
            # First call: all 4 attempts fail → lost
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-1",
            )
            # Second call: succeeds
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-2",
            )

        diag = client.diagnostics()
        assert diag["total_cost_calls"] == 2
        assert diag["lost_cost_events"] == 1
        assert diag["loss_rate"] == 0.5


# ── _log_cost retry behavior ────────────────────────────────


class TestLogCostRetry:
    async def test_retries_3_times_with_backoff(self) -> None:
        repo = AsyncMock()
        repo.add_cost.side_effect = RuntimeError("DB down")
        client = _make_client(cost_repo=repo)

        sleep_calls: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with patch("core.llm_client.asyncio.sleep", side_effect=mock_sleep):
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-1",
            )

        # 4 attempts: initial + 3 retries, 3 sleeps between them
        assert repo.add_cost.call_count == 4
        assert len(sleep_calls) == 3
        # Exponential backoff: 0.5, 1.0, 2.0
        assert sleep_calls == [0.5, 1.0, 2.0]

    async def test_succeeds_on_second_attempt(self) -> None:
        repo = AsyncMock()
        repo.add_cost.side_effect = [RuntimeError("fail"), None]
        client = _make_client(cost_repo=repo)

        with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-1",
            )

        assert repo.add_cost.call_count == 2
        assert client.diagnostics()["lost_cost_events"] == 0

    async def test_sets_last_failure_timestamp(self) -> None:
        repo = AsyncMock()
        repo.add_cost.side_effect = RuntimeError("DB down")
        client = _make_client(cost_repo=repo)

        before = time.time()
        with patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-1",
            )
        after = time.time()

        ts = client.diagnostics()["last_failure_ts"]
        assert ts is not None
        assert before <= ts <= after


# ── Persistent warning ──────────────────────────────────────


class TestPersistentWarning:
    async def test_warns_on_subsequent_calls_after_loss(self) -> None:
        repo = AsyncMock()
        client = _make_client(cost_repo=repo)

        # Simulate a prior loss
        client._lost_cost_events = 1

        with patch("core.llm_client.logger") as mock_logger:
            await client._log_cost(
                agent_id="rex", model="test", input_tokens=10,
                output_tokens=5, cost=Decimal("0.001"), latency_ms=100,
                stream=False, openrouter_id="or-1",
            )

            # Should have logged a warning about existing losses
            warning_calls = [
                c for c in mock_logger.warning.call_args_list
                if "loss detected" in str(c)
            ]
            assert len(warning_calls) >= 1
