"""Poll the global kill switch and drive the livestream safe state."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY
from core.livestream.stream_controller import StreamController

logger = logging.getLogger(__name__)


class KillSwitchRedis(Protocol):
    async def get(self, key: str) -> str | None:
        """Return the raw global Redis value for ``key``."""


class KillSwitchMonitor:
    """Bridge Redis ``kill_switch`` state to a stream controller.

    Recovery window: the stream enters or leaves safe state on the next poll.
    The default production window is therefore at most one second plus the
    controller transition time.
    """

    def __init__(
        self,
        redis: KillSwitchRedis,
        controller: StreamController,
        *,
        poll_interval: float = 1.0,
        key: str = KILL_SWITCH_KEY,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")
        self._redis = redis
        self._controller = controller
        self._poll_interval = poll_interval
        self._key = key
        self._last_active: bool | None = None

    @property
    def last_active(self) -> bool | None:
        return self._last_active

    async def run(self) -> None:
        """Run until cancelled."""

        try:
            while True:
                try:
                    await self.poll_once()
                except Exception:
                    logger.exception(
                        "livestream.kill_switch.monitor_poll_failed",
                        extra={"event": "livestream.kill_switch.monitor_poll_failed"},
                    )
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.info(
                "livestream.kill_switch.monitor_cancelled",
                extra={"event": "livestream.kill_switch.monitor_cancelled"},
            )
            raise

    async def poll_once(self) -> None:
        """Read the key once and apply any active/inactive transition."""

        active = await self._read_active()
        previous = self._last_active
        if previous == active:
            return

        if active:
            await self._enter_safe_state(previous)
        elif previous is True:
            await self._leave_safe_state(previous)
        self._last_active = active

    async def _read_active(self) -> bool:
        try:
            return await self._redis.get(self._key) == KILL_SWITCH_ACTIVE_VALUE
        except Exception:
            logger.warning(
                "livestream.kill_switch.lookup_failed",
                extra={"event": "livestream.kill_switch.lookup_failed"},
                exc_info=True,
            )
            return True

    async def _enter_safe_state(self, previous: bool | None) -> None:
        logger.info(
            "livestream.kill_switch.observed",
            extra={
                "event": "livestream.kill_switch.observed",
                "kill_switch_active": True,
                "previous_active": previous,
                "action": "enter_safe_state",
            },
        )
        await self._controller.enter_safe_state("kill_switch_active")

    async def _leave_safe_state(self, previous: bool | None) -> None:
        logger.info(
            "livestream.kill_switch.observed",
            extra={
                "event": "livestream.kill_switch.observed",
                "kill_switch_active": False,
                "previous_active": previous,
                "action": "leave_safe_state",
            },
        )
        await self._controller.leave_safe_state()
