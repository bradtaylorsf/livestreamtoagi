from __future__ import annotations

import asyncio

import pytest

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.livestream.kill_switch_monitor import KillSwitchMonitor
from core.livestream.safe_state import StreamState


class _FakeRedis:
    def __init__(self, initial: str | None = None) -> None:
        self.value = initial
        self.get_calls: list[str] = []
        self.get_event = asyncio.Event()

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        self.get_event.set()
        return self.value


class _RecordingController:
    def __init__(self) -> None:
        self.state = StreamState.ACTIVE
        self.enter_reasons: list[str] = []
        self.leave_count = 0
        self.enter_event = asyncio.Event()

    async def enter_safe_state(self, reason: str) -> None:
        self.enter_reasons.append(reason)
        self.state = StreamState.SAFE
        self.enter_event.set()

    async def leave_safe_state(self) -> None:
        self.leave_count += 1
        self.state = StreamState.ACTIVE


class _FlakyEnterController(_RecordingController):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_enter = True

    async def enter_safe_state(self, reason: str) -> None:
        if self.fail_next_enter:
            self.fail_next_enter = False
            raise RuntimeError("encoder refused transition")
        await super().enter_safe_state(reason)


async def test_absent_key_leaves_stream_active() -> None:
    redis = _FakeRedis()
    controller = _RecordingController()
    monitor = KillSwitchMonitor(redis, controller)

    await monitor.poll_once()

    assert controller.state is StreamState.ACTIVE
    assert controller.enter_reasons == []
    assert controller.leave_count == 0
    assert redis.get_calls == [KILL_SWITCH_KEY]


async def test_active_key_enters_safe_state_within_one_poll() -> None:
    redis = _FakeRedis(KILL_SWITCH_ACTIVE_VALUE)
    controller = _RecordingController()
    monitor = KillSwitchMonitor(redis, controller, poll_interval=60.0)
    task = asyncio.create_task(monitor.run())

    try:
        await asyncio.wait_for(controller.enter_event.wait(), timeout=1.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert controller.state is StreamState.SAFE
    assert controller.enter_reasons == ["kill_switch_active"]


async def test_deleting_key_leaves_safe_state() -> None:
    redis = _FakeRedis(KILL_SWITCH_ACTIVE_VALUE)
    controller = _RecordingController()
    monitor = KillSwitchMonitor(redis, controller)

    await monitor.poll_once()
    redis.value = None
    await monitor.poll_once()

    assert controller.state is StreamState.ACTIVE
    assert controller.enter_reasons == ["kill_switch_active"]
    assert controller.leave_count == 1


async def test_repeated_active_polls_do_not_reenter() -> None:
    redis = _FakeRedis(KILL_SWITCH_ACTIVE_VALUE)
    controller = _RecordingController()
    monitor = KillSwitchMonitor(redis, controller)

    await monitor.poll_once()
    await monitor.poll_once()
    await monitor.poll_once()

    assert controller.state is StreamState.SAFE
    assert controller.enter_reasons == ["kill_switch_active"]
    assert controller.leave_count == 0


async def test_failed_transition_does_not_advance_last_known_state() -> None:
    redis = _FakeRedis(KILL_SWITCH_ACTIVE_VALUE)
    controller = _FlakyEnterController()
    monitor = KillSwitchMonitor(redis, controller)

    with pytest.raises(RuntimeError, match="encoder refused transition"):
        await monitor.poll_once()

    assert monitor.last_active is None

    await monitor.poll_once()

    assert monitor.last_active is True
    assert controller.enter_reasons == ["kill_switch_active"]


async def test_monitor_cancels_cleanly() -> None:
    redis = _FakeRedis()
    controller = _RecordingController()
    monitor = KillSwitchMonitor(redis, controller, poll_interval=60.0)
    task = asyncio.create_task(monitor.run())

    await asyncio.wait_for(redis.get_event.wait(), timeout=1.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("poll_interval", [0.0, -1.0])
def test_poll_interval_must_be_positive(poll_interval: float) -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        KillSwitchMonitor(_FakeRedis(), _RecordingController(), poll_interval=poll_interval)
