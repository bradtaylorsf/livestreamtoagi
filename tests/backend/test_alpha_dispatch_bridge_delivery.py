"""Alpha dispatch should deliver the errand to the bridge queue (E7-2, #566)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.bridge.errand_queue import errand_queue
from core.models import LLMResponse
from tools.alpha_dispatch import ALPHA_MODEL, DispatchAlphaTool


@pytest.fixture(autouse=True)
def clear_errands() -> Iterator[None]:
    errand_queue.clear()
    yield
    errand_queue.clear()


async def test_dispatch_alpha_enqueues_errand_for_bridge_poll() -> None:
    event_bus = AsyncMock()
    event_bus.emit = AsyncMock()
    llm_client = AsyncMock()
    llm_client.complete = AsyncMock(
        return_value=LLMResponse(
            content="Done",
            model=ALPHA_MODEL,
            input_tokens=10,
            output_tokens=5,
            estimated_cost=Decimal("0.001"),
            latency_ms=100,
        )
    )
    tool = DispatchAlphaTool(event_bus=event_bus, agent_id="vera", llm_client=llm_client)

    result = await tool.execute(task="check the sheep pen", urgency="now")

    errand = errand_queue.poll("alpha")
    assert errand is not None
    assert errand.task_id == result["task_id"]
    assert errand.task == "check the sheep pen"
    assert errand.from_agent == "vera"
    assert errand.urgency == "now"

    calls = event_bus.emit.call_args_list
    assert [call.args[0] for call in calls] == [
        "alpha_dispatch",
        "task_delegated",
        "alpha_return",
        "task_completed",
    ]
    dispatch_event = calls[0].args[1]
    delegated_event = calls[1].args[1]
    assert dispatch_event["task_id"] == result["task_id"]
    assert delegated_event["task_id"] == result["task_id"]
    assert delegated_event["to_agent"] == "alpha"
    llm_client.complete.assert_called_once()


async def test_rejected_dispatch_does_not_enqueue_errand() -> None:
    tool = DispatchAlphaTool(
        event_bus=AsyncMock(),
        agent_id="alpha",
        llm_client=AsyncMock(),
    )

    result = await tool.execute(task="check the sheep pen")

    assert result["status"] == "rejected"
    assert errand_queue.poll("alpha") is None
