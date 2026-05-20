"""Tests for Alpha errand delivery over the bridge (E7-2, #566)."""

from __future__ import annotations

from typing import Any

from core.bridge import contract as c
from core.bridge.errand_queue import ErrandQueue, errand_queue
from core.bridge.server import build_bridge_response_with_services


def _request(agent_id: str = "alpha") -> dict[str, Any]:
    return {
        "version": c.PROTOCOL_VERSION,
        "request_id": "req-errand-poll-test",
        "agent_id": agent_id,
        "run_id": "run-test",
        "simulation_id": "sim-test",
        "service": "errand",
        "method": "poll",
        "payload": {"agent_id": agent_id},
        "deadline_ms": 5000,
        "cost_context": {
            "agent_tier": "errand",
            "budget_bucket": "bridge",
            "estimated_cost_usd": 0.0,
        },
    }


def test_errand_queue_is_fifo_per_agent() -> None:
    queue = ErrandQueue()

    assert queue.enqueue("alpha", "task-1", "first", "vera", "when_free") is True
    assert queue.enqueue("alpha", "task-2", "second", "rex", "now") is True

    first = queue.poll("alpha")
    second = queue.poll("alpha")

    assert first is not None
    assert first.task_id == "task-1"
    assert first.task == "first"
    assert second is not None
    assert second.task_id == "task-2"
    assert second.urgency == "now"
    assert queue.poll("alpha") is None


def test_errand_queue_isolates_agents_and_empty_poll_returns_none() -> None:
    queue = ErrandQueue()

    assert queue.poll("alpha") is None
    assert queue.enqueue("alpha", "task-alpha", "alpha task", "vera") is True
    assert queue.enqueue("rex", "task-rex", "rex task", "vera") is True

    rex = queue.poll("rex")
    alpha = queue.poll("alpha")

    assert rex is not None
    assert rex.task_id == "task-rex"
    assert alpha is not None
    assert alpha.task_id == "task-alpha"


def test_errand_queue_drops_duplicate_task_ids_within_ttl() -> None:
    queue = ErrandQueue(duplicate_ttl_seconds=60)

    assert queue.enqueue("alpha", "same-task", "first", "vera") is True
    assert queue.enqueue("alpha", "same-task", "duplicate", "rex") is False

    errand = queue.poll("alpha")
    assert errand is not None
    assert errand.task == "first"
    assert queue.poll("alpha") is None


async def test_bridge_errand_poll_returns_next_queued_errand() -> None:
    errand_queue.clear()
    try:
        assert errand_queue.enqueue(
            "alpha",
            "task-bridge-1",
            "check the sheep pen",
            "vera",
            "now",
        )

        response = await build_bridge_response_with_services(_request("alpha"), services=object())

        assert response.ok is True
        payload = response.payload
        assert payload is not None
        assert response.payload == {
            "task_id": "task-bridge-1",
            "task": "check the sheep pen",
            "from_agent": "vera",
            "dispatched_at_ms": payload["dispatched_at_ms"],
            "urgency": "now",
        }
        assert payload["dispatched_at_ms"] > 0
        c.validate_response(response, service="errand", method="poll")
        assert errand_queue.poll("alpha") is None
    finally:
        errand_queue.clear()


async def test_bridge_errand_poll_returns_empty_response_when_none_pending() -> None:
    errand_queue.clear()
    try:
        response = await build_bridge_response_with_services(_request("alpha"), services=None)

        assert response.ok is True
        assert response.payload == {
            "task_id": None,
            "task": None,
            "from_agent": None,
            "dispatched_at_ms": None,
            "urgency": None,
        }
        c.validate_response(response, service="errand", method="poll")
    finally:
        errand_queue.clear()
