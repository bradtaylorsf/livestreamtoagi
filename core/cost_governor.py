"""Hard per-agent cost governor for LLM and bridge spend gates."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.event_bus import EventType

if TYPE_CHECKING:
    import uuid

    from core.event_bus import EventBus
    from core.redis_client import RedisClient
    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

AGENT_CAP_BLOCK_PREFIX = "agent_cap_block:"
DEFAULT_SPEND_ALERT_THRESHOLD_PCT = Decimal("0.8")


def _to_decimal(value: Decimal | int | str | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class CostGovernor:
    """Enforce a rolling per-agent spend cap backed by ``cost_events``.

    Redis stores only the short-lived block flag. The authoritative spend
    calculation stays in Postgres so every provider path that logs cost events
    contributes to the same hourly window.
    """

    def __init__(
        self,
        cost_repo: CostRepo,
        redis: RedisClient,
        *,
        default_hourly_cap_usd: Decimal | int | str | None,
        per_agent_caps_usd: dict[str, Decimal | int | str | None] | None = None,
        window_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
        event_bus: EventBus | None = None,
        alert_threshold_pct: Decimal | int | str | None = DEFAULT_SPEND_ALERT_THRESHOLD_PCT,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._cost_repo = cost_repo
        self._redis = redis
        self._default_hourly_cap_usd = _to_decimal(default_hourly_cap_usd)
        self._per_agent_caps_usd = {
            agent_id: _to_decimal(cap) for agent_id, cap in (per_agent_caps_usd or {}).items()
        }
        self._window_seconds = window_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_bus = event_bus
        self._alert_threshold_pct = _to_decimal(alert_threshold_pct)

    @property
    def window_seconds(self) -> int:
        return self._window_seconds

    def cap_for(self, agent_id: str) -> Decimal | None:
        """Return the configured hourly cap for ``agent_id``.

        ``None`` and values less than or equal to zero intentionally disable
        the cap, matching the issue contract for local/noop validation.
        """
        cap = self._per_agent_caps_usd.get(agent_id, self._default_hourly_cap_usd)
        if cap is None or cap <= Decimal("0"):
            return None
        return cap

    async def is_allowed(
        self,
        agent_id: str,
        *,
        simulation_id: uuid.UUID | None = None,
    ) -> tuple[bool, Decimal, Decimal]:
        """Return ``(allowed, spend_in_window, cap)`` for this agent."""
        cap = self.cap_for(agent_id)
        if cap is None:
            return True, Decimal("0"), Decimal("0")

        block_key = self._block_key(agent_id)
        if await self._redis.get(block_key) is not None:
            return False, cap, cap

        since = self._clock() - timedelta(seconds=self._window_seconds)
        spend = await self._cost_repo.get_agent_spend_since(
            agent_id,
            since,
            simulation_id=simulation_id,
        )
        if spend >= cap:
            await self._trip(agent_id, spend, cap)
            return False, spend, cap

        return True, spend, cap

    async def record_and_check(self, agent_id: str, amount: Decimal | int | str) -> None:
        """Re-evaluate the agent after a persisted cost event.

        ``amount`` is accepted for structured logging and future alerting, while
        the enforcement decision intentionally re-queries ``cost_events`` so it
        cannot drift from the durable accounting source.
        """
        _ = _to_decimal(amount)
        cap = self.cap_for(agent_id)
        if cap is None:
            return

        block_key = self._block_key(agent_id)
        if await self._redis.get(block_key) is not None:
            return

        since = self._clock() - timedelta(seconds=self._window_seconds)
        spend = await self._cost_repo.get_agent_spend_since(agent_id, since)
        if spend >= cap:
            await self._trip(agent_id, spend, cap)
            return

        if (
            self._alert_threshold_pct is not None
            and self._alert_threshold_pct > Decimal("0")
            and spend / cap >= self._alert_threshold_pct
        ):
            await self._emit_budget_update(agent_id, spend, cap, cap_tripped=False)

    async def reset(self, agent_id: str) -> None:
        """Clear a temporary block for admin actions or tests."""
        await self._redis.delete(self._block_key(agent_id))

    def _block_key(self, agent_id: str) -> str:
        return f"{AGENT_CAP_BLOCK_PREFIX}{agent_id}"

    async def _trip(self, agent_id: str, spend: Decimal, cap: Decimal) -> None:
        await self._redis.set(
            self._block_key(agent_id),
            "tripped",
            ex=self._window_seconds,
        )
        logger.warning(
            "Agent hourly spend cap tripped",
            extra={
                "cost_cap": {
                    "cap_tripped": True,
                    "agent_id": agent_id,
                    "hourly_spend_usd": spend,
                    "hourly_cap_usd": cap,
                    "window_seconds": self._window_seconds,
                }
            },
        )
        await self._emit_budget_update(agent_id, spend, cap, cap_tripped=True)

    async def _emit_budget_update(
        self,
        agent_id: str,
        spend: Decimal,
        cap: Decimal,
        *,
        cap_tripped: bool,
    ) -> None:
        if self._event_bus is None:
            return
        event: dict[str, Any] = {
            "cap_tripped": cap_tripped,
            "tripped": cap_tripped,
            "agent_id": agent_id,
            "window_spend_usd": spend,
            "hourly_spend_usd": spend,
            "cap_usd": cap,
            "hourly_cap_usd": cap,
            "window_seconds": self._window_seconds,
        }
        try:
            await self._event_bus.emit(EventType.BUDGET_UPDATE.value, event)
        except Exception:
            logger.warning("Failed to emit cost budget update event", exc_info=True)
