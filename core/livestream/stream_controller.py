"""Controllers for putting the public livestream into a safe state."""

from __future__ import annotations

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from core.livestream.safe_state import SafeStateConfig, StreamState

logger = logging.getLogger(__name__)

AsyncMaybeCallback = Callable[..., Awaitable[None] | None]


class StreamController(ABC):
    """Interface the kill-switch monitor uses to control stream output."""

    @property
    @abstractmethod
    def state(self) -> StreamState:
        """Return the controller's current state."""

    @abstractmethod
    async def enter_safe_state(self, reason: str) -> None:
        """Move the stream into a safe public state."""

    @abstractmethod
    async def leave_safe_state(self) -> None:
        """Release the safe state after the kill switch is deactivated."""


class BaseStreamController(StreamController):
    """Common idempotent state transition logic for stream controllers."""

    def __init__(
        self,
        config: SafeStateConfig | None = None,
        *,
        initial_state: StreamState = StreamState.ACTIVE,
    ) -> None:
        self.config = config or SafeStateConfig()
        self._state = initial_state
        self._lock = asyncio.Lock()

    @property
    def state(self) -> StreamState:
        return self._state

    async def enter_safe_state(self, reason: str) -> None:
        async with self._lock:
            if self._state is StreamState.SAFE:
                return
            previous = self._state
            await self._enter_safe_state(reason)
            self._state = StreamState.SAFE
            self._log_transition(previous, self._state, reason)

    async def leave_safe_state(self) -> None:
        async with self._lock:
            if self._state is StreamState.ACTIVE:
                return
            previous = self._state
            await self._leave_safe_state()
            self._state = StreamState.ACTIVE
            self._log_transition(previous, self._state, "kill_switch_inactive")

    @abstractmethod
    async def _enter_safe_state(self, reason: str) -> None:
        """Controller-specific enter behavior. Called under the transition lock."""

    @abstractmethod
    async def _leave_safe_state(self) -> None:
        """Controller-specific leave behavior. Called under the transition lock."""

    def _log_transition(
        self,
        from_state: StreamState,
        to_state: StreamState,
        reason: str,
    ) -> None:
        logger.info(
            "livestream.kill_switch.transition",
            extra={
                "event": "livestream.kill_switch.transition",
                "controller": type(self).__name__,
                "from_state": from_state.value,
                "to_state": to_state.value,
                "reason": reason,
                "kill_mode": self.config.kill_mode,
            },
        )


class NullStreamController(BaseStreamController):
    """Logging-only controller used until the encoder/RTMP path is registered."""

    def __init__(self, config: SafeStateConfig | None = None) -> None:
        super().__init__(config)
        self.safe_state_reasons: list[str] = []
        self.leave_count = 0

    async def _enter_safe_state(self, reason: str) -> None:
        self.safe_state_reasons.append(reason)
        logger.warning(
            "livestream.safe_state.null_controller",
            extra={
                "event": "livestream.safe_state.null_controller",
                "reason": reason,
                "kill_mode": self.config.kill_mode,
            },
        )

    async def _leave_safe_state(self) -> None:
        self.leave_count += 1
        logger.info(
            "livestream.safe_state.null_controller_released",
            extra={"event": "livestream.safe_state.null_controller_released"},
        )


class RtmpStreamController(BaseStreamController):
    """RTMP controller skeleton for the encoder service to plug into.

    The current tree does not yet own the encoder subprocess, so the concrete
    ffmpeg/OBS wiring is injected through callbacks. When ``cut_on_kill`` is
    true, this controller can terminate the provided RTMP push subprocess.
    Otherwise it invokes the holding-card callback that E13-2 should wire to
    its encoder input switch.
    """

    def __init__(
        self,
        config: SafeStateConfig,
        *,
        process: asyncio.subprocess.Process | None = None,
        holding_card_callback: AsyncMaybeCallback | None = None,
        restore_callback: AsyncMaybeCallback | None = None,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(config)
        self._process = process
        self._holding_card_callback = holding_card_callback
        self._restore_callback = restore_callback
        self._stop_timeout_seconds = stop_timeout_seconds

    async def _enter_safe_state(self, reason: str) -> None:
        if self.config.cut_on_kill:
            await self._terminate_rtmp_push(reason)
            return
        await self._activate_holding_card(reason)

    async def _leave_safe_state(self) -> None:
        if self._restore_callback is None:
            logger.info(
                "livestream.safe_state.restore_unwired",
                extra={
                    "event": "livestream.safe_state.restore_unwired",
                    "kill_mode": self.config.kill_mode,
                },
            )
            return
        await _maybe_await(self._restore_callback())

    async def _activate_holding_card(self, reason: str) -> None:
        if self._holding_card_callback is None:
            logger.warning(
                "livestream.safe_state.holding_card_unwired",
                extra={
                    "event": "livestream.safe_state.holding_card_unwired",
                    "holding_card_path": (
                        str(self.config.holding_card_path)
                        if self.config.holding_card_path is not None
                        else None
                    ),
                    "reason": reason,
                },
            )
            return
        await _maybe_await(self._holding_card_callback(self.config, reason))

    async def _terminate_rtmp_push(self, reason: str) -> None:
        if self._process is None:
            logger.warning(
                "livestream.safe_state.cut_unwired",
                extra={
                    "event": "livestream.safe_state.cut_unwired",
                    "reason": reason,
                },
            )
            return
        if self._process.returncode is not None:
            return

        self._process.terminate()
        try:
            await asyncio.wait_for(
                self._process.wait(),
                timeout=self._stop_timeout_seconds,
            )
        except TimeoutError:
            self._process.kill()
            await self._process.wait()


async def _maybe_await(result: Awaitable[None] | None) -> None:
    if inspect.isawaitable(result):
        await result
