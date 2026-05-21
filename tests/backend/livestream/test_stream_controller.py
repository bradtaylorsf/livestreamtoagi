from __future__ import annotations

import asyncio
import logging

import pytest

from core.livestream.safe_state import SafeStateConfig, StreamState, load_safe_state_config
from core.livestream.stream_controller import (
    BaseStreamController,
    NullStreamController,
    RtmpStreamController,
)


async def test_null_controller_enter_leave_are_idempotent_and_record_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    controller = NullStreamController()

    with caplog.at_level(logging.INFO):
        await controller.enter_safe_state("kill_switch_active")
        await controller.enter_safe_state("kill_switch_active")
        await controller.leave_safe_state()
        await controller.leave_safe_state()

    assert controller.state is StreamState.ACTIVE
    assert controller.safe_state_reasons == ["kill_switch_active"]
    assert controller.leave_count == 1

    transition_records = [
        record for record in caplog.records if record.message == "livestream.kill_switch.transition"
    ]
    assert [(r.from_state, r.to_state, r.reason) for r in transition_records] == [
        ("active", "safe", "kill_switch_active"),
        ("safe", "active", "kill_switch_inactive"),
    ]


class _BlockingController(BaseStreamController):
    def __init__(self) -> None:
        super().__init__()
        self.enter_count = 0
        self.enter_started = asyncio.Event()
        self.release_enter = asyncio.Event()

    async def _enter_safe_state(self, reason: str) -> None:
        self.enter_count += 1
        self.enter_started.set()
        await self.release_enter.wait()

    async def _leave_safe_state(self) -> None:
        return None


async def test_controller_lock_serializes_concurrent_safe_state_transitions() -> None:
    controller = _BlockingController()
    tasks = [
        asyncio.create_task(controller.enter_safe_state("kill_switch_active")) for _ in range(3)
    ]

    await asyncio.wait_for(controller.enter_started.wait(), timeout=1.0)
    controller.release_enter.set()
    await asyncio.gather(*tasks)

    assert controller.state is StreamState.SAFE
    assert controller.enter_count == 1


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def terminate(self) -> None:
        self.terminate_called = True

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9

    async def wait(self) -> int:
        self.returncode = 0
        return self.returncode


async def test_rtmp_cut_mode_terminates_push_process_once() -> None:
    process = _FakeProcess()
    controller = RtmpStreamController(
        SafeStateConfig(cut_on_kill=True),
        process=process,  # type: ignore[arg-type]
    )

    await controller.enter_safe_state("kill_switch_active")
    await controller.enter_safe_state("kill_switch_active")

    assert controller.state is StreamState.SAFE
    assert process.terminate_called is True
    assert process.kill_called is False


def test_safe_state_config_loads_holding_card_defaults() -> None:
    config = load_safe_state_config(
        {
            "LIVESTREAM_HOLDING_CARD": "~/hold.png",
            "LIVESTREAM_SAFE_TRANSITION_SECONDS": "0.25",
        }
    )

    assert config.kill_mode == "holding_card"
    assert config.cut_on_kill is False
    assert str(config.holding_card_path).endswith("hold.png")
    assert config.transition_seconds == 0.25


def test_safe_state_config_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="LIVESTREAM_KILL_MODE"):
        load_safe_state_config({"LIVESTREAM_KILL_MODE": "panic"})
