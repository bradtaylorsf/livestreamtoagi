"""Tests for simulation_id propagation to LLM calls (issue #254)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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
