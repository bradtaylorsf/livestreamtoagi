"""Tests for simulation_id propagation to LLM calls (issue #254)."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.memory.compaction import MemoryCompactor
from core.models import LLMResponse


def _make_llm_response(content: str = "summary") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="anthropic/claude-haiku-4.5",
        input_tokens=100,
        output_tokens=50,
        estimated_cost=Decimal("0.001"),
        latency_ms=200,
        openrouter_id="test-123",
    )


def _make_chat_response(content: str = "ok") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 5},
        },
    )


def _make_stream_response() -> httpx.Response:
    chunks = [
        {
            "id": "chatcmpl-stream-test",
            "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-stream-test",
            "usage": {"prompt_tokens": 25, "completion_tokens": 5},
            "choices": [{"delta": {}, "finish_reason": "stop"}],
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    body += "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode())


def _make_cost_tracking_client() -> tuple[Any, AsyncMock]:
    from core.llm_client import OpenRouterClient

    cost_repo = AsyncMock()
    client = OpenRouterClient(
        api_key="test-key",
        cost_repo=cost_repo,
        http_client=AsyncMock(),
    )
    client._request_with_retry = AsyncMock(return_value=_make_chat_response())
    return client, cost_repo


# ── MemoryCompactor simulation_id passthrough ─────────────────


class TestCompactorSimulationId:
    """Verify compaction LLM calls pass simulation_id."""

    @pytest.mark.asyncio
    async def test_compact_interaction_passes_simulation_id(self) -> None:
        sim_id = uuid.uuid4()
        llm_mock = AsyncMock()
        llm_mock.complete.return_value = _make_llm_response()

        compactor = MemoryCompactor(
            archival=AsyncMock(store_transcript=AsyncMock(
                return_value=MagicMock(id=1)
            )),
            recall=AsyncMock(store_recall_memory=AsyncMock(
                return_value=MagicMock(id=1)
            )),
            llm_client=llm_mock,
            http_client=AsyncMock(),
            openrouter_api_key="test-key",
            simulation_id=sim_id,
        )

        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=[0.1] * 1536,
        ):
            await compactor.compact_interaction(
                agent_id="vera",
                interaction="Test transcript",
                event_type="conversation",
            )

        call_kwargs = llm_mock.complete.call_args.kwargs
        assert call_kwargs["simulation_id"] == sim_id

    @pytest.mark.asyncio
    async def test_compact_recall_only_passes_simulation_id(self) -> None:
        sim_id = uuid.uuid4()
        llm_mock = AsyncMock()
        llm_mock.complete.return_value = _make_llm_response()

        compactor = MemoryCompactor(
            archival=AsyncMock(),
            recall=AsyncMock(store_recall_memory=AsyncMock(
                return_value=MagicMock(id=1)
            )),
            llm_client=llm_mock,
            http_client=AsyncMock(),
            openrouter_api_key="test-key",
            simulation_id=sim_id,
        )

        with patch(
            "core.memory.compaction.generate_embedding",
            return_value=[0.1] * 1536,
        ):
            await compactor.compact_recall_only(
                agent_id="rex",
                interaction="Test transcript",
                event_type="conversation",
                transcript_id=42,
            )

        call_kwargs = llm_mock.complete.call_args.kwargs
        assert call_kwargs["simulation_id"] == sim_id


# ── LLM client fallback ─────────────────────────────────────


class TestLLMClientSimulationIdFallback:
    """Verify the LLM client uses _simulation_id as fallback."""

    def test_simulation_id_attribute_settable(self) -> None:
        """LLM client accepts external _simulation_id assignment."""
        from core.llm_client import OpenRouterClient

        cost_repo = MagicMock()
        client = OpenRouterClient(
            api_key="test-key",
            cost_repo=cost_repo,
            http_client=AsyncMock(),
        )
        sim_id = uuid.uuid4()
        client._simulation_id = sim_id
        assert client._simulation_id == sim_id


# ── Skill cost attribution ─────────────────────────────────────


class TestSkillCostAttribution:
    """Verify skill-triggered LLM calls inherit the executing agent."""

    @pytest.mark.asyncio
    async def test_context_agent_attributes_llm_call_without_explicit_agent_id(self) -> None:
        from core.llm_client import agent_cost_context

        client, cost_repo = _make_cost_tracking_client()

        with agent_cost_context("rex"):
            await client.complete(
                messages=[{"role": "user", "content": "Generate code"}],
                model="gpt-4o-mini",
            )

        cost_repo.add_cost.assert_awaited_once()
        event = cost_repo.add_cost.await_args.args[0]
        assert event.agent_id == "rex"

    @pytest.mark.asyncio
    async def test_explicit_agent_id_overrides_context_agent(self) -> None:
        from core.llm_client import agent_cost_context

        client, cost_repo = _make_cost_tracking_client()

        with agent_cost_context("rex"):
            await client.complete(
                messages=[{"role": "user", "content": "Generate code"}],
                model="gpt-4o-mini",
                agent_id="fork",
            )

        event = cost_repo.add_cost.await_args.args[0]
        assert event.agent_id == "fork"

    @pytest.mark.asyncio
    async def test_context_agent_attributes_stream_call_without_explicit_agent_id(self) -> None:
        from core.llm_client import agent_cost_context

        client, cost_repo = _make_cost_tracking_client()
        client._request_with_retry = AsyncMock(return_value=_make_stream_response())

        with agent_cost_context("pixel"):
            chunks = [
                chunk
                async for chunk in client.stream(
                    messages=[{"role": "user", "content": "Stream code"}],
                    model="gpt-4o-mini",
                )
            ]

        assert chunks[-1].finish_reason == "stop"
        event = cost_repo.add_cost.await_args.args[0]
        assert event.agent_id == "pixel"

    def test_agent_cost_context_resets_after_exit(self) -> None:
        from core.llm_client import agent_cost_context, current_agent_id

        assert current_agent_id.get() is None
        with agent_cost_context("rex"):
            assert current_agent_id.get() == "rex"
        assert current_agent_id.get() is None

    @pytest.mark.asyncio
    async def test_tool_execution_context_attributes_internal_llm_call(self) -> None:
        from core.models import ToolCall
        from core.tool_executor import execute_tool_calls

        client, cost_repo = _make_cost_tracking_client()

        class LLMBackedCodegenTool:
            name = "codegen"

            async def run(self, **kwargs: Any) -> dict[str, str]:
                await client.complete(
                    messages=[{"role": "user", "content": kwargs["prompt"]}],
                    model="gpt-4o-mini",
                )
                return {"status": "ok"}

        tool_call = ToolCall(
            id="call_codegen",
            name="codegen",
            arguments={"prompt": "write a tiny function"},
        )

        results = await execute_tool_calls(
            [tool_call],
            {"codegen": LLMBackedCodegenTool()},
            "sentinel",
        )

        assert json.loads(results[0]["content"]) == {"status": "ok"}
        event = cost_repo.add_cost.await_args.args[0]
        assert event.agent_id == "sentinel"


# ── SimulationRepo.get_total_cost_from_events ────────────────


class TestSimulationRepoTotalCost:
    """Verify cost derivation from cost_events table."""

    @pytest.mark.asyncio
    async def test_get_total_cost_from_events(self) -> None:
        from core.repos.simulation_repo import SimulationRepo

        db = AsyncMock()
        db.fetchval.return_value = Decimal("1.40")
        repo = SimulationRepo(db)

        sim_id = uuid.uuid4()
        result = await repo.get_total_cost_from_events(sim_id)
        assert result == Decimal("1.40")
        db.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_total_cost_from_events_empty(self) -> None:
        from core.repos.simulation_repo import SimulationRepo

        db = AsyncMock()
        db.fetchval.return_value = Decimal("0")
        repo = SimulationRepo(db)

        result = await repo.get_total_cost_from_events(uuid.uuid4())
        assert result == Decimal("0")


class TestCostRepoSimulationBreakdown:
    """Verify simulation cost breakdowns include image generation cost types."""

    @pytest.mark.asyncio
    async def test_get_costs_by_simulation_includes_by_type(self) -> None:
        from core.repos.cost_repo import CostRepo

        db = AsyncMock()
        db.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "agent_id": "vera",
                        "total": Decimal("0.03"),
                        "input_tokens": 100,
                        "output_tokens": 20,
                    },
                    {
                        "agent_id": "system",
                        "total": Decimal("0.02"),
                        "input_tokens": 0,
                        "output_tokens": 0,
                    },
                ],
                [
                    {"cost_type": "llm_call", "total": Decimal("0.03"), "tokens": 120},
                    {"cost_type": "imagen_generation", "total": Decimal("0.02"), "tokens": 0},
                ],
            ]
        )
        repo = CostRepo(db)

        result = await repo.get_costs_by_simulation(uuid.uuid4())

        assert result["total"] == "0.05"
        assert result["total_input_tokens"] == 100
        assert result["total_output_tokens"] == 20
        assert result["by_type"] == [
            {"type": "llm_call", "cost": "0.03", "tokens": 120},
            {"type": "imagen_generation", "cost": "0.02", "tokens": 0},
        ]
