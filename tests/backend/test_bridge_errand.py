"""Tests for Alpha errand delivery and completion over the bridge (E7-2/E7-4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.bridge import contract as c
from core.bridge.errand_queue import ErrandQueue, errand_queue
from core.bridge.server import build_bridge_response_with_services
from tests.backend.test_bridge_memory import FakeCompactor


class RecallFromCompactor:
    def __init__(self, compactor: FakeCompactor) -> None:
        self.compactor = compactor
        self.calls: list[tuple[str, str, int, object | None]] = []

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: object | None = None,
    ) -> str:
        self.calls.append((agent_id, query_text, limit, simulation_id))
        matches = [
            memory
            for memory in self.compactor.recall_memories
            if memory.agent_id == agent_id
        ][:limit]
        if not matches:
            return "## Relevant memories\n\nNo relevant memories found."
        lines = ["## Relevant memories"]
        lines.extend(f"- [{memory.event_type}] {memory.summary}" for memory in matches)
        return "\n".join(lines)


@dataclass
class ErrandMemoryServices:
    compactor: FakeCompactor | None
    recall_memory: RecallFromCompactor | None = None
    core_memory: object | None = None
    memory_backend: object | None = None


def _request(
    agent_id: str = "alpha",
    *,
    method: str = "poll",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": c.PROTOCOL_VERSION,
        "request_id": f"req-errand-{method}-test",
        "agent_id": agent_id,
        "run_id": "run-test",
        "simulation_id": "sim-test",
        "service": "errand",
        "method": method,
        "payload": payload if payload is not None else {"agent_id": agent_id},
        "deadline_ms": 5000,
        "cost_context": {
            "agent_tier": "errand",
            "budget_bucket": "bridge",
            "estimated_cost_usd": 0.0,
        },
    }


def _memory_recall_request(
    query: str,
    *,
    agent_id: str = "alpha",
    simulation_id: str = "sim-test",
) -> dict[str, Any]:
    return {
        "version": c.PROTOCOL_VERSION,
        "request_id": "req-errand-memory-recall-test",
        "agent_id": agent_id,
        "run_id": "run-test",
        "simulation_id": simulation_id,
        "service": "memory",
        "method": "recall",
        "payload": {"query": query, "tier": "recall", "limit": 5},
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


def test_errand_queue_records_completion_by_task_id() -> None:
    queue = ErrandQueue()

    result = queue.record_completion(
        "task-complete-1",
        "success",
        "✓",
        "1/1 steps finished",
        [{"action_id": "place-1", "status": "success", "detail": "placed"}],
    )

    assert result.completed_at_ms > 0
    assert queue.get_completion("task-complete-1") == result
    assert result.status == "success"
    assert result.symbol == "✓"
    assert result.step_results == (
        {"action_id": "place-1", "status": "success", "detail": "placed"},
    )


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


async def test_bridge_errand_complete_records_result() -> None:
    errand_queue.clear()
    try:
        response = await build_bridge_response_with_services(
            _request(
                method="complete",
                payload={
                    "task_id": "task-bridge-complete-1",
                    "status": "success",
                    "symbol": "✓",
                    "detail": "1/1 steps finished",
                    "step_results": [
                        {
                            "action_id": "place-1",
                            "status": "success",
                            "detail": "placed: position=0,64,0",
                        }
                    ],
                },
            ),
            services=object(),
        )

        assert response.ok is True
        assert response.payload == {"accepted": True}
        c.validate_response(response, service="errand", method="complete")
        completion = errand_queue.get_completion("task-bridge-complete-1")
        assert completion is not None
        assert completion.status == "success"
        assert completion.symbol == "✓"
        assert completion.detail == "1/1 steps finished"
        assert completion.step_results[0]["action_id"] == "place-1"
    finally:
        errand_queue.clear()


async def test_bridge_errand_complete_writes_retrievable_memory() -> None:
    errand_queue.clear()
    compactor = FakeCompactor()
    recall = RecallFromCompactor(compactor)
    services = ErrandMemoryServices(compactor=compactor, recall_memory=recall)
    try:
        payload = {
            "task_id": "task-bridge-memory-1",
            "status": "success",
            "symbol": "✓",
            "detail": "1/1 steps finished near the sheep pen",
            "step_results": [
                {
                    "action_id": "place-1",
                    "status": "success",
                    "detail": "placed: torch at position=0,64,0",
                }
            ],
        }

        response = await build_bridge_response_with_services(
            _request(method="complete", payload=payload),
            services=services,
        )

        assert response.ok is True
        assert response.payload == {"accepted": True}
        c.validate_response(response, service="errand", method="complete")
        assert len(compactor.calls) == 1
        call = compactor.calls[0]
        assert call["agent_id"] == "alpha"
        assert call["event_type"] == "errand_outcome"
        assert call["participants"] == ["alpha"]
        assert "task_id: task-bridge-memory-1" in call["interaction"]
        assert "outcome: ✓ success" in call["interaction"]
        assert "1/1 steps finished near the sheep pen" in call["interaction"]
        assert "place-1" in call["interaction"]
        assert "placed: torch at position=0,64,0" in call["interaction"]
        assert len(compactor.transcripts) == 1
        assert len(compactor.recall_memories) == 1
        assert compactor.recall_memories[0].transcript_id == compactor.transcripts[0].id

        recall_response = await build_bridge_response_with_services(
            _memory_recall_request("task-bridge-memory-1 sheep pen torch"),
            services=services,
        )

        assert recall_response.ok is True
        recalled = c.validate_response(recall_response, service="memory", method="recall")
        assert isinstance(recalled, c.MemoryRecallResponse)
        assert recalled.formatted is not None
        assert "task-bridge-memory-1" in recalled.formatted
        assert "✓ success" in recalled.formatted
        assert "placed: torch at position=0,64,0" in recalled.formatted
    finally:
        errand_queue.clear()


async def test_bridge_errand_complete_is_memory_idempotent_by_task_id() -> None:
    errand_queue.clear()
    compactor = FakeCompactor()
    services = ErrandMemoryServices(
        compactor=compactor,
        recall_memory=RecallFromCompactor(compactor),
    )
    try:
        request = _request(
            method="complete",
            payload={
                "task_id": "task-bridge-memory-duplicate",
                "status": "success",
                "symbol": "✓",
                "detail": "1/1 steps finished",
                "step_results": [
                    {
                        "action_id": "place-1",
                        "status": "success",
                        "detail": "placed: dirt at position=1,64,1",
                    }
                ],
            },
        )

        first = await build_bridge_response_with_services(request, services=services)
        second = await build_bridge_response_with_services(request, services=services)

        assert first.ok is True
        assert second.ok is True
        assert first.payload == second.payload == {"accepted": True}
        assert len(compactor.calls) == 1
        assert len(compactor.recall_memories) == 1
    finally:
        errand_queue.clear()


async def test_bridge_errand_complete_acks_when_memory_compactor_unavailable() -> None:
    errand_queue.clear()
    try:
        response = await build_bridge_response_with_services(
            _request(
                method="complete",
                payload={
                    "task_id": "task-bridge-memory-no-compactor",
                    "status": "failure",
                    "symbol": "✗",
                    "detail": "path blocked",
                    "step_results": [],
                },
            ),
            services=ErrandMemoryServices(compactor=None),
        )

        assert response.ok is True
        assert response.payload == {"accepted": True}
        c.validate_response(response, service="errand", method="complete")
        completion = errand_queue.get_completion("task-bridge-memory-no-compactor")
        assert completion is not None
        assert completion.status == "failure"
        assert completion.symbol == "✗"
    finally:
        errand_queue.clear()


async def test_bridge_errand_complete_rejects_unknown_status() -> None:
    errand_queue.clear()
    try:
        response = await build_bridge_response_with_services(
            _request(
                method="complete",
                payload={
                    "task_id": "task-bridge-complete-bad",
                    "status": "done",
                    "symbol": "✓",
                    "detail": "bad status",
                    "step_results": [],
                },
            ),
            services=object(),
        )

        assert response.ok is False
        assert response.error is not None
        assert response.error.code == c.ERR_INVALID_PAYLOAD
        assert errand_queue.get_completion("task-bridge-complete-bad") is None
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
