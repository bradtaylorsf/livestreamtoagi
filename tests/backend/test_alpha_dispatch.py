"""Tests for Alpha dispatch tool."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.models import LLMResponse
from tools.alpha_dispatch import (
    ALLOWED_AGENTS,
    ALPHA_MODEL,
    DispatchAlphaTool,
)

# --- Fixtures ---


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def llm_client() -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(
        return_value=LLMResponse(
            content="The answer is 42",
            model=ALPHA_MODEL,
            input_tokens=50,
            output_tokens=20,
            estimated_cost=Decimal("0.001"),
            latency_ms=500,
        )
    )
    return client


@pytest.fixture
def cost_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.add_cost = AsyncMock()
    return repo


def _make_tool(
    event_bus: AsyncMock,
    llm_client: AsyncMock,
    agent_id: str = "vera",
    cost_repo: AsyncMock | None = None,
) -> DispatchAlphaTool:
    return DispatchAlphaTool(
        event_bus=event_bus,
        agent_id=agent_id,
        llm_client=llm_client,
        cost_repo=cost_repo,
    )


# --- Interface ---


class TestDispatchAlphaInterface:
    def test_name_and_description(
        self, event_bus: AsyncMock, llm_client: AsyncMock
    ) -> None:
        tool = _make_tool(event_bus, llm_client)
        assert tool.name == "dispatch_alpha"
        assert "alpha" in tool.description.lower()

    def test_parameters_schema(
        self, event_bus: AsyncMock, llm_client: AsyncMock
    ) -> None:
        tool = _make_tool(event_bus, llm_client)
        assert "task" in tool.parameters
        assert "urgency" in tool.parameters

    def test_allowed_agents_excludes_alpha(self) -> None:
        assert "alpha" not in ALLOWED_AGENTS
        assert len(ALLOWED_AGENTS) == 7


# --- Dispatch event ---


class TestDispatchEvent:
    async def test_dispatch_emits_dispatch_event(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client)
        await tool.execute(task="look up the weather")

        # First emit call should be alpha_dispatch
        calls = event_bus.emit.call_args_list
        assert len(calls) >= 1
        event_type, event_data = calls[0].args
        assert event_type == "alpha_dispatch"
        assert event_data["from"] == "vera"
        assert event_data["task"] == "look up the weather"
        assert event_data["status"] == "running"
        assert "task_id" in event_data


# --- Success ---


class TestSuccessfulDispatch:
    async def test_successful_task_emits_return_event(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client)
        result = await tool.execute(task="what is 2+2")

        assert result["status"] == "success"
        assert result["result"] == "The answer is 42"
        assert "task_id" in result

        # Second emit should be alpha_return with success
        calls = event_bus.emit.call_args_list
        assert len(calls) == 2
        event_type, event_data = calls[1].args
        assert event_type == "alpha_return"
        assert event_data["status"] == "success"
        assert event_data["result"] == "The answer is 42"

    async def test_llm_called_with_correct_model(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client)
        await tool.execute(task="search for something")

        llm_client.complete.assert_called_once()
        call_kwargs = llm_client.complete.call_args
        actual_model = call_kwargs.kwargs.get("model", call_kwargs[1].get("model"))
        assert actual_model == ALPHA_MODEL


# --- Timeout ---


class TestTimeout:
    async def test_timeout_produces_confused_status(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        llm_client.complete = AsyncMock(side_effect=asyncio.TimeoutError)
        tool = _make_tool(event_bus, llm_client)
        result = await tool.execute(task="something slow")

        assert result["status"] == "confused"
        assert "took too long" in result["result"]

        # Return event should have confused status
        calls = event_bus.emit.call_args_list
        return_call = calls[1]
        event_type, event_data = return_call.args
        assert event_type == "alpha_return"
        assert event_data["status"] == "confused"

    async def test_generic_error_produces_confused_status(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        llm_client.complete = AsyncMock(side_effect=RuntimeError("connection lost"))
        tool = _make_tool(event_bus, llm_client)
        result = await tool.execute(task="broken task")

        assert result["status"] == "confused"
        assert "confused" in result["result"].lower()


# --- Access control ---


class TestAccessControl:
    async def test_alpha_cannot_dispatch_itself(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client, agent_id="alpha")
        result = await tool.execute(task="do something")

        assert result["status"] == "rejected"
        assert "cannot dispatch itself" in result["reason"].lower()
        # No events should be emitted
        event_bus.emit.assert_not_called()
        # No LLM call
        llm_client.complete.assert_not_called()

    @pytest.mark.parametrize("agent_id", sorted(ALLOWED_AGENTS))
    async def test_all_allowed_agents_can_dispatch(
        self,
        agent_id: str,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client, agent_id=agent_id)
        result = await tool.execute(task="fetch data")
        assert result["status"] == "success"

    async def test_unknown_agent_rejected(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client, agent_id="unknown_agent")
        result = await tool.execute(task="something")
        assert result["status"] == "rejected"

    async def test_empty_task_rejected(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        tool = _make_tool(event_bus, llm_client)
        result = await tool.execute(task="  ")
        assert result["status"] == "error"
        assert "empty" in result["reason"].lower()


# --- Cost tracking ---


class TestCostTracking:
    """Cost is tracked automatically by LLMClient.complete() — no manual cost_repo needed."""

    async def test_cost_tracked_via_llm_client(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        """LLM client complete() is called on success, which auto-tracks cost."""
        tool = _make_tool(event_bus, llm_client)
        result = await tool.execute(task="search for info")

        assert result["status"] == "success"
        llm_client.complete.assert_called_once()

    async def test_no_duplicate_cost_tracking(
        self,
        event_bus: AsyncMock,
        llm_client: AsyncMock,
        cost_repo: AsyncMock,
    ) -> None:
        """Passing cost_repo should NOT result in any manual add_cost calls."""
        tool = _make_tool(event_bus, llm_client, cost_repo=cost_repo)
        await tool.execute(task="search for info")

        cost_repo.add_cost.assert_not_called()
