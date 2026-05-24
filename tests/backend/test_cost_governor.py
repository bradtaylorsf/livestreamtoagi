"""Per-agent hourly spend cap tests for E11-3."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bridge import contract as c
from core.bridge.server import build_bridge_response_with_services
from core.cost_governor import CostGovernor
from core.exceptions import AgentCostCapExceeded
from core.llm_client import OpenRouterClient
from core.models import CostEvent, CostEventCreate
from core.repos.cost_repo import CostRepo


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class FakeRedis:
    def __init__(self, clock: MutableClock) -> None:
        self._clock = clock
        self._values: dict[str, tuple[str, datetime | None]] = {}

    async def get(self, key: str) -> str | None:
        item = self._values.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and expires_at <= self._clock():
            self._values.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        expires_at = self._clock() + timedelta(seconds=ex) if ex is not None else None
        self._values[key] = (value, expires_at)
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self._values.pop(key, None) is not None:
                deleted += 1
        return deleted


class InMemoryCostRepo:
    def __init__(self, clock: MutableClock) -> None:
        self._clock = clock
        self.events: list[CostEvent] = []
        self._next_id = 1

    def seed(
        self,
        agent_id: str,
        amount: Decimal | str,
        *,
        created_at: datetime | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> None:
        self.events.append(
            CostEvent(
                id=self._next_id,
                agent_id=agent_id,
                cost_type="llm_call",
                amount=Decimal(str(amount)),
                details={},
                simulation_id=simulation_id,
                created_at=created_at or self._clock(),
            )
        )
        self._next_id += 1

    async def add_cost(self, cost: CostEventCreate) -> CostEvent:
        event = CostEvent(
            id=self._next_id,
            agent_id=cost.agent_id,
            cost_type=cost.cost_type,
            amount=cost.amount,
            details=cost.details,
            simulation_id=cost.simulation_id,
            created_at=self._clock(),
        )
        self.events.append(event)
        self._next_id += 1
        return event

    async def get_agent_spend_since(
        self,
        agent_id: str,
        since: datetime,
        simulation_id: uuid.UUID | None = None,
    ) -> Decimal:
        return sum(
            (
                event.amount or Decimal("0")
                for event in self.events
                if event.agent_id == agent_id
                and event.created_at is not None
                and event.created_at >= since
                and (simulation_id is None or event.simulation_id == simulation_id)
            ),
            Decimal("0"),
        )


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = data or {}
        self.events.append((event_type, payload))
        return {"event_type": event_type, "data": payload}


class FakeResponse:
    def __init__(self, input_tokens: int = 10, output_tokens: int = 5) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.text = ""
        self._data = {
            "id": "gen-cost-governor",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            },
        }
        self.text = json.dumps(self._data)

    def json(self) -> dict[str, Any]:
        return self._data


class ServicesWithGovernor:
    def __init__(self, governor: CostGovernor) -> None:
        self.cost_governor = governor


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(datetime(2026, 1, 1, tzinfo=UTC))


def make_governor(
    clock: MutableClock,
    repo: InMemoryCostRepo,
    *,
    default_cap: Decimal | str | None = Decimal("0.02"),
    per_agent_caps: dict[str, Decimal | str | None] | None = None,
    window_seconds: int = 3600,
    event_bus: FakeEventBus | None = None,
    alert_threshold_pct: Decimal | str | None = None,
) -> CostGovernor:
    kwargs: dict[str, Any] = {}
    if alert_threshold_pct is not None:
        kwargs["alert_threshold_pct"] = alert_threshold_pct
    return CostGovernor(
        repo,  # type: ignore[arg-type]
        FakeRedis(clock),  # type: ignore[arg-type]
        default_hourly_cap_usd=default_cap,
        per_agent_caps_usd=per_agent_caps,
        window_seconds=window_seconds,
        clock=clock,
        event_bus=event_bus,  # type: ignore[arg-type]
        **kwargs,
    )


def make_client(
    repo: InMemoryCostRepo,
    governor: CostGovernor,
    *,
    response: FakeResponse | None = None,
) -> tuple[OpenRouterClient, AsyncMock]:
    http_client = AsyncMock()
    http_client.post = AsyncMock(return_value=response or FakeResponse())
    client = OpenRouterClient(
        "sk-test",
        repo,  # type: ignore[arg-type]
        http_client=http_client,
        cost_governor=governor,
    )
    return client, http_client.post


def bridge_cost_request(agent_id: str) -> dict[str, Any]:
    return {
        "version": c.PROTOCOL_VERSION,
        "request_id": f"req-{agent_id}",
        "agent_id": agent_id,
        "run_id": "run-cost-governor",
        "simulation_id": str(uuid.uuid4()),
        "service": "cost",
        "method": "gate",
        "payload": {
            "agent_id": agent_id,
            "action": "chat",
            "estimated_cost_usd": 0.001,
        },
        "deadline_ms": 1000,
        "cost_context": {
            "agent_tier": "conversation",
            "budget_bucket": "daily-global",
            "estimated_cost_usd": 0.001,
        },
    }


async def test_cost_repo_get_agent_spend_since_query_shape() -> None:
    db = MagicMock()
    db.fetchval = AsyncMock(return_value=Decimal("0.42"))
    since = datetime(2026, 1, 1, tzinfo=UTC)
    simulation_id = uuid.uuid4()
    repo = CostRepo(db)

    total = await repo.get_agent_spend_since("vera", since, simulation_id=simulation_id)

    assert total == Decimal("0.42")
    sql, *args = db.fetchval.call_args.args
    assert "agent_id = $1" in sql
    assert "created_at >= $2" in sql
    assert "simulation_id = $3" in sql
    assert args == ["vera", since, simulation_id]


async def test_under_cap_allows(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    governor = make_governor(clock, repo, default_cap=Decimal("1.00"))
    allowed, spend, cap = await governor.is_allowed("vera")

    assert allowed is True
    assert spend == Decimal("0")
    assert cap == Decimal("1.00")

    client, post = make_client(repo, governor)
    result = await client.complete(
        [{"role": "user", "content": "Hi"}],
        model="claude-haiku-4-5",
        agent_id="vera",
    )

    assert result.content == "ok"
    assert post.await_count == 1


async def test_synthetic_runaway_capped_within_hour(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.03")
    governor = make_governor(clock, repo, default_cap=Decimal("0.02"))

    allowed, spend, cap = await governor.is_allowed("vera")
    assert allowed is False
    assert spend == Decimal("0.03")
    assert cap == Decimal("0.02")

    client, post = make_client(repo, governor)
    with pytest.raises(AgentCostCapExceeded) as exc:
        await client.complete(
            [{"role": "user", "content": "Run away"}],
            model="claude-haiku-4-5",
            agent_id="vera",
        )

    assert exc.value.agent_id == "vera"
    post.assert_not_awaited()


async def test_other_agents_unaffected(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.03")
    governor = make_governor(clock, repo, default_cap=Decimal("0.02"))

    assert (await governor.is_allowed("vera"))[0] is False
    assert (await governor.is_allowed("rex"))[0] is True

    client, post = make_client(repo, governor)
    result = await client.complete(
        [{"role": "user", "content": "Can Rex speak?"}],
        model="claude-haiku-4-5",
        agent_id="rex",
    )

    assert result.content == "ok"
    assert post.await_count == 1


async def test_window_rolls(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.03")
    governor = make_governor(clock, repo, default_cap=Decimal("0.02"), window_seconds=3600)

    assert (await governor.is_allowed("vera"))[0] is False
    clock.advance(seconds=3601)

    allowed, spend, cap = await governor.is_allowed("vera")
    assert allowed is True
    assert spend == Decimal("0")
    assert cap == Decimal("0.02")


async def test_per_agent_override(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.015")
    repo.seed("rex", "0.015")
    governor = make_governor(
        clock,
        repo,
        default_cap=Decimal("0.02"),
        per_agent_caps={"vera": Decimal("0.01")},
    )

    assert (await governor.is_allowed("vera"))[0] is False
    assert (await governor.is_allowed("rex"))[0] is True


async def test_cap_breach_on_recorded_call_blocks_next(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    governor = make_governor(clock, repo, default_cap=Decimal("0.001"))
    client, post = make_client(
        repo, governor, response=FakeResponse(input_tokens=1000, output_tokens=0)
    )

    first = await client.complete(
        [{"role": "user", "content": "Spend exactly the cap"}],
        model="claude-haiku-4-5",
        agent_id="vera",
    )
    assert first.estimated_cost == Decimal("0.001")

    with pytest.raises(AgentCostCapExceeded):
        await client.complete(
            [{"role": "user", "content": "This should be blocked"}],
            model="claude-haiku-4-5",
            agent_id="vera",
        )
    assert post.await_count == 1


async def test_recorded_call_crossing_alert_threshold_emits_budget_update(
    clock: MutableClock,
) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.80")
    bus = FakeEventBus()
    governor = make_governor(clock, repo, default_cap=Decimal("1.00"), event_bus=bus)

    await governor.record_and_check("vera", Decimal("0.01"))

    assert bus.events == [
        (
            "budget_update",
            {
                "cap_tripped": False,
                "tripped": False,
                "agent_id": "vera",
                "window_spend_usd": Decimal("0.80"),
                "hourly_spend_usd": Decimal("0.80"),
                "cap_usd": Decimal("1.00"),
                "hourly_cap_usd": Decimal("1.00"),
                "window_seconds": 3600,
            },
        )
    ]


async def test_recorded_call_below_alert_threshold_emits_no_budget_update(
    clock: MutableClock,
) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.79")
    bus = FakeEventBus()
    governor = make_governor(clock, repo, default_cap=Decimal("1.00"), event_bus=bus)

    await governor.record_and_check("vera", Decimal("0.01"))

    assert bus.events == []


async def test_recorded_call_uses_configured_alert_threshold(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.50")
    bus = FakeEventBus()
    governor = make_governor(
        clock,
        repo,
        default_cap=Decimal("1.00"),
        event_bus=bus,
        alert_threshold_pct=Decimal("0.50"),
    )

    await governor.record_and_check("vera", Decimal("0.01"))

    assert len(bus.events) == 1
    assert bus.events[0][1]["window_spend_usd"] == Decimal("0.50")


async def test_bridge_cost_gate_returns_real_state(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "0.03")
    repo.seed("rex", "0.01")
    governor = make_governor(clock, repo, default_cap=Decimal("0.02"))
    services = ServicesWithGovernor(governor)

    blocked = await build_bridge_response_with_services(bridge_cost_request("vera"), services)
    allowed = await build_bridge_response_with_services(bridge_cost_request("rex"), services)

    assert blocked.ok is True
    assert blocked.payload == {
        "allowed": False,
        "reason": "agent_hourly_cap_exceeded",
        "remaining_budget_usd": 0.0,
    }
    assert allowed.ok is True
    assert allowed.payload is not None
    assert allowed.payload["allowed"] is True
    assert allowed.payload["remaining_budget_usd"] > 0
    c.validate_response(allowed, service="cost", method="gate")


async def test_disabled_cap_is_noop(clock: MutableClock) -> None:
    repo = InMemoryCostRepo(clock)
    repo.seed("vera", "100.00")
    governor = make_governor(clock, repo, default_cap=Decimal("0"))

    allowed, spend, cap = await governor.is_allowed("vera")

    assert allowed is True
    assert spend == Decimal("0")
    assert cap == Decimal("0")
