"""End-to-end bridge proof for Alpha errand outcomes entering memory (E7-4)."""

from __future__ import annotations

from core.bridge import contract as c
from core.bridge.errand_queue import errand_queue
from core.bridge.server import build_bridge_response_with_services
from tests.backend.test_bridge_errand import (
    ErrandMemoryServices,
    RecallFromCompactor,
    _memory_recall_request,
    _request,
)
from tests.backend.test_bridge_memory import FakeCompactor


async def test_alpha_errand_dispatch_complete_and_recall_memory_round_trip() -> None:
    errand_queue.clear()
    compactor = FakeCompactor()
    services = ErrandMemoryServices(
        compactor=compactor,
        recall_memory=RecallFromCompactor(compactor),
    )
    try:
        assert errand_queue.enqueue(
            "alpha",
            "alpha-e7-memory-task",
            "place a torch at the sheep pen marker",
            from_agent="vera",
            urgency="now",
        )

        poll = await build_bridge_response_with_services(
            _request("alpha", method="poll"),
            services=services,
        )
        assert poll.ok is True
        assert poll.payload is not None
        assert poll.payload["task_id"] == "alpha-e7-memory-task"
        assert poll.payload["from_agent"] == "vera"

        complete = await build_bridge_response_with_services(
            _request(
                "alpha",
                method="complete",
                payload={
                    "task_id": poll.payload["task_id"],
                    "status": "success",
                    "symbol": "✓",
                    "detail": "2/2 steps finished at the sheep pen marker",
                    "step_results": [
                        {
                            "action_id": "nav-1",
                            "status": "success",
                            "detail": "reached: position=2,64,0",
                        },
                        {
                            "action_id": "place-1",
                            "status": "success",
                            "detail": "placed: torch at position=2,64,0",
                        },
                    ],
                },
            ),
            services=services,
        )
        assert complete.ok is True
        assert complete.payload == {"accepted": True}
        assert len(compactor.calls) == 1
        assert compactor.calls[0]["event_type"] == "errand_outcome"
        assert compactor.calls[0]["participants"] == ["alpha", "vera"]
        assert len(compactor.transcripts) == 1
        assert len(compactor.recall_memories) == 1
        assert compactor.recall_memories[0].transcript_id == compactor.transcripts[0].id

        recall = await build_bridge_response_with_services(
            _memory_recall_request("alpha-e7-memory-task sheep pen torch"),
            services=services,
        )

        assert recall.ok is True
        recalled = c.validate_response(recall, service="memory", method="recall")
        assert isinstance(recalled, c.MemoryRecallResponse)
        assert recalled.formatted is not None
        assert "alpha-e7-memory-task" in recalled.formatted
        assert "✓ success" in recalled.formatted
        assert "placed: torch at position=2,64,0" in recalled.formatted
    finally:
        errand_queue.clear()
