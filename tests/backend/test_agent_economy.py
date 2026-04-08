"""Tests for individual agent economy system (#270)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_economy import AgentEconomyManager
from tools.economy_tools import TransferBudgetTool, ViewAccountTool


# ── Fake DB for unit testing (no real PostgreSQL needed) ──


class _FakeConnection:
    """Wraps FakeDB to emulate an asyncpg connection with transaction support."""

    def __init__(self, db) -> None:
        self._db = db

    async def execute(self, query: str, *args) -> str:
        return await self._db.execute(query, *args)

    @asynccontextmanager
    async def transaction(self):
        yield  # no-op for in-memory fake


class FakeDB:
    """In-memory fake database for testing AgentEconomyManager."""

    def __init__(self) -> None:
        self.accounts: dict[str, dict] = {}
        self.transactions: list[dict] = []
        self._tx_id = 0

    async def execute(self, query: str, *args) -> str:
        q = query.strip().upper()
        if "INSERT INTO AGENT_ACCOUNTS" in q:
            agent_id = args[0]
            if agent_id not in self.accounts:
                self.accounts[agent_id] = {
                    "agent_id": agent_id,
                    "balance": args[1],
                    "weekly_allocation": args[2],
                    "total_earned": Decimal("0"),
                    "total_spent": Decimal("0"),
                    "total_transferred": Decimal("0"),
                    "updated_at": None,
                }
            return "INSERT 1"
        elif "UPDATE AGENT_ACCOUNTS" in q and "BALANCE >= $2" in q:
            agent_id = args[0]
            amount = Decimal(str(args[1]))
            acc = self.accounts.get(agent_id)
            if acc is None or acc["balance"] < amount:
                return "UPDATE 0"
            if "TOTAL_SPENT" in q:
                acc["balance"] -= amount
                acc["total_spent"] += amount
            elif "TOTAL_TRANSFERRED" in q:
                acc["balance"] -= amount
                acc["total_transferred"] += amount
            return "UPDATE 1"
        elif "UPDATE AGENT_ACCOUNTS" in q and "BALANCE + $2" in q:
            agent_id = args[0]
            amount = Decimal(str(args[1]))
            acc = self.accounts.get(agent_id)
            if acc:
                acc["balance"] += amount
                acc["total_earned"] += amount
            return "UPDATE 1"
        elif "INSERT INTO AGENT_TRANSACTIONS" in q:
            self._tx_id += 1
            # Type may be a hardcoded SQL literal — detect and shift args
            if "'TOOL_COST'" in q:
                tx = {"id": self._tx_id, "agent_id": args[0], "type": "tool_cost",
                      "amount": args[1], "counterparty_agent_id": None,
                      "description": args[2] if len(args) > 2 else None, "created_at": None}
            elif "'TRANSFER'" in q:
                tx = {"id": self._tx_id, "agent_id": args[0], "type": "transfer",
                      "amount": args[1], "counterparty_agent_id": args[2] if len(args) > 2 else None,
                      "description": args[3] if len(args) > 3 else None, "created_at": None}
            elif "'ALLOCATION'" in q:
                tx = {"id": self._tx_id, "agent_id": args[0], "type": "allocation",
                      "amount": args[1], "counterparty_agent_id": None,
                      "description": "Weekly allocation", "created_at": None}
            else:
                tx = {"id": self._tx_id, "agent_id": args[0],
                      "type": args[1] if len(args) > 1 else "unknown",
                      "amount": args[2] if len(args) > 2 else Decimal("0"),
                      "counterparty_agent_id": args[3] if len(args) > 3 else None,
                      "description": args[4] if len(args) > 4 else None, "created_at": None}
            self.transactions.append(tx)
            return "INSERT 1"
        return "OK"

    @asynccontextmanager
    async def acquire(self, *, timeout: float = 10.0):
        """Yield a fake connection that delegates to self and supports transaction()."""
        yield _FakeConnection(self)

    async def fetchrow(self, query: str, *args):
        agent_id = args[0]
        acc = self.accounts.get(agent_id)
        if acc is None:
            return None
        return acc

    async def fetch(self, query: str, *args):
        if "AGENT_TRANSACTIONS" in query.upper():
            agent_id = args[0]
            limit = args[1] if len(args) > 1 else 20
            txs = [t for t in reversed(self.transactions) if t["agent_id"] == agent_id]
            return txs[:limit]
        elif "AGENT_ACCOUNTS" in query.upper():
            if args:
                # Filter by agent IDs
                agent_ids = args[0]
                return [self.accounts[a] for a in agent_ids if a in self.accounts]
            return list(self.accounts.values())
        return []


# ── Tests ──


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def economy(db):
    return AgentEconomyManager(db)


@pytest.mark.asyncio
async def test_initialize_accounts(economy, db):
    """Initialize creates accounts with correct allocation."""
    await economy.initialize_accounts(["vera", "rex", "fork"], weekly_total=Decimal("45"))
    assert len(db.accounts) == 3
    # 45 * 0.6 / 3 = $9 per agent
    assert db.accounts["vera"]["balance"] == Decimal("9")
    assert db.accounts["rex"]["weekly_allocation"] == Decimal("9")


@pytest.mark.asyncio
async def test_deduct_cost_success(economy, db):
    """Deduct cost when agent has sufficient funds."""
    await economy.initialize_accounts(["vera"], weekly_total=Decimal("45"))
    success = await economy.deduct_cost("vera", Decimal("1.50"), "LLM call")
    assert success is True
    balance = await economy.get_balance("vera")
    assert balance == Decimal("27") - Decimal("1.50")  # 45*0.6/1 = 27


@pytest.mark.asyncio
async def test_deduct_cost_insufficient_funds(economy, db):
    """Deduct fails when agent has insufficient funds."""
    await economy.initialize_accounts(["rex"], weekly_total=Decimal("10"))
    # Balance = 10 * 0.6 / 1 = 6.0
    success = await economy.deduct_cost("rex", Decimal("100"), "Expensive call")
    assert success is False


@pytest.mark.asyncio
async def test_transfer_atomic(economy, db):
    """Transfer moves funds between two agents."""
    await economy.initialize_accounts(["vera", "rex"], weekly_total=Decimal("30"))
    # Each gets 30*0.6/2 = $9
    success = await economy.transfer("vera", "rex", Decimal("3.00"), "Payment for build")
    assert success is True
    vera_balance = await economy.get_balance("vera")
    rex_balance = await economy.get_balance("rex")
    assert vera_balance == Decimal("6")
    assert rex_balance == Decimal("12")


@pytest.mark.asyncio
async def test_transfer_insufficient_funds(economy, db):
    """Transfer fails when sender has insufficient funds."""
    await economy.initialize_accounts(["vera", "rex"], weekly_total=Decimal("10"))
    # Each gets $3
    success = await economy.transfer("vera", "rex", Decimal("50"), "Too much")
    assert success is False


@pytest.mark.asyncio
async def test_broke_mode(economy, db):
    """Agent is broke when balance hits 0."""
    await economy.initialize_accounts(["vera"], weekly_total=Decimal("10"))
    # Balance = 6.0
    balance = await economy.get_balance("vera")
    await economy.deduct_cost("vera", balance, "Spend everything")
    assert await economy.is_broke("vera") is True


@pytest.mark.asyncio
async def test_weekly_allocation_distribution(economy, db):
    """Weekly allocation adds funds to all agent accounts."""
    await economy.initialize_accounts(["vera", "rex"], weekly_total=Decimal("30"))
    # Drain vera's balance first
    initial = await economy.get_balance("vera")
    await economy.deduct_cost("vera", initial, "spend all")
    assert await economy.get_balance("vera") == Decimal("0")

    # Weekly allocation restores
    await economy.weekly_allocation()
    balance = await economy.get_balance("vera")
    assert balance == Decimal("9")  # 30*0.6/2 = 9


@pytest.mark.asyncio
async def test_get_transactions(economy, db):
    """Transaction history is recorded and retrievable."""
    await economy.initialize_accounts(["vera"], weekly_total=Decimal("30"))
    await economy.deduct_cost("vera", Decimal("2.50"), "Test deduction")
    txs = await economy.get_transactions("vera")
    assert len(txs) == 1
    assert txs[0].type == "tool_cost"


# ── Tool tests ──


@pytest.mark.asyncio
async def test_transfer_budget_tool():
    """TransferBudgetTool executes a transfer."""
    economy = AsyncMock()
    economy.transfer = AsyncMock(return_value=True)
    economy.get_balance = AsyncMock(return_value=Decimal("5.00"))

    tool = TransferBudgetTool(economy_manager=economy, agent_id="vera")
    result = await tool.execute(to_agent_id="rex", amount=2.0, reason="For the build")
    assert result["status"] == "ok"
    assert result["transferred"] == "2.0"
    economy.transfer.assert_called_once()


@pytest.mark.asyncio
async def test_transfer_budget_tool_insufficient_funds():
    """TransferBudgetTool rejects when insufficient funds."""
    economy = AsyncMock()
    economy.transfer = AsyncMock(return_value=False)
    economy.get_balance = AsyncMock(return_value=Decimal("1.00"))

    tool = TransferBudgetTool(economy_manager=economy, agent_id="vera")
    result = await tool.execute(to_agent_id="rex", amount=50.0, reason="Too much")
    assert result["status"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_view_account_tool():
    """ViewAccountTool returns balance and history."""
    from core.models import AgentAccount, AgentTransaction

    economy = AsyncMock()
    economy.get_account = AsyncMock(return_value=AgentAccount(
        agent_id="vera", balance=Decimal("10.50"),
        weekly_allocation=Decimal("3.00"),
    ))
    economy.get_transactions = AsyncMock(return_value=[
        AgentTransaction(id=1, agent_id="vera", type="allocation",
                        amount=Decimal("3.00"), description="Weekly allocation"),
    ])

    tool = ViewAccountTool(economy_manager=economy, agent_id="vera")
    result = await tool.execute()
    assert result["status"] == "ok"
    assert result["balance"] == "10.50"
    assert len(result["recent_transactions"]) == 1
