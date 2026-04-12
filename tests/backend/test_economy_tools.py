"""Tests for tools/economy_tools.py — TransferBudgetTool, ViewAccountTool edge cases.

Core happy-path tests are in test_agent_economy.py; this file covers
self-transfer rejection, zero/negative amount, and ViewAccountTool formatting.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.economy_tools import TransferBudgetTool, ViewAccountTool


def _make_economy_manager() -> AsyncMock:
    mgr = AsyncMock()
    mgr.transfer = AsyncMock(return_value=True)
    mgr.get_balance = AsyncMock(return_value=Decimal("100.00"))
    return mgr


class TestTransferBudgetTool:
    async def test_self_transfer_rejected(self) -> None:
        mgr = _make_economy_manager()
        tool = TransferBudgetTool(economy_manager=mgr, agent_id="rex")

        result = await tool.execute(
            to_agent_id="rex", amount=10.0, reason="self",
        )
        assert result["status"] == "rejected"
        assert "yourself" in result["reason"].lower()
        mgr.transfer.assert_not_called()

    async def test_zero_amount_rejected(self) -> None:
        mgr = _make_economy_manager()
        tool = TransferBudgetTool(economy_manager=mgr, agent_id="rex")

        result = await tool.execute(
            to_agent_id="aurora", amount=0, reason="zero test",
        )
        assert result["status"] == "rejected"
        assert "positive" in result["reason"].lower()

    async def test_negative_amount_rejected(self) -> None:
        mgr = _make_economy_manager()
        tool = TransferBudgetTool(economy_manager=mgr, agent_id="rex")

        result = await tool.execute(
            to_agent_id="aurora", amount=-5.0, reason="negative test",
        )
        assert result["status"] == "rejected"

    async def test_successful_transfer(self) -> None:
        mgr = _make_economy_manager()
        mgr.get_balance = AsyncMock(return_value=Decimal("90.00"))

        tool = TransferBudgetTool(economy_manager=mgr, agent_id="rex")
        result = await tool.execute(
            to_agent_id="aurora", amount=10.0, reason="payment",
        )

        assert result["status"] == "ok"
        assert result["transferred"] == "10.0"
        assert result["to"] == "aurora"
        assert result["new_balance"] == "90.00"

    async def test_insufficient_funds(self) -> None:
        mgr = _make_economy_manager()
        mgr.transfer.return_value = False
        mgr.get_balance.return_value = Decimal("5.00")

        tool = TransferBudgetTool(economy_manager=mgr, agent_id="rex")
        result = await tool.execute(
            to_agent_id="aurora", amount=100.0, reason="big payment",
        )

        assert result["status"] == "insufficient_funds"
        assert result["balance"] == "5.00"


class TestViewAccountTool:
    async def test_empty_account(self) -> None:
        mgr = AsyncMock()
        account = MagicMock()
        account.balance = Decimal("0.00")
        account.weekly_allocation = Decimal("50.00")
        account.total_earned = Decimal("0.00")
        account.total_spent = Decimal("0.00")
        mgr.get_account.return_value = account
        mgr.get_transactions.return_value = []

        tool = ViewAccountTool(economy_manager=mgr, agent_id="rex")
        result = await tool.execute()

        assert result["status"] == "ok"
        assert result["balance"] == "0.00"
        assert result["recent_transactions"] == []

    async def test_account_with_transactions(self) -> None:
        mgr = AsyncMock()
        account = MagicMock()
        account.balance = Decimal("75.50")
        account.weekly_allocation = Decimal("50.00")
        account.total_earned = Decimal("100.00")
        account.total_spent = Decimal("24.50")
        mgr.get_account.return_value = account

        tx1 = MagicMock(type="transfer_out", amount=Decimal("10.00"),
                        description="Payment", counterparty_agent_id="aurora")
        tx2 = MagicMock(type="allocation", amount=Decimal("50.00"),
                        description=None, counterparty_agent_id=None)
        mgr.get_transactions.return_value = [tx1, tx2]

        tool = ViewAccountTool(economy_manager=mgr, agent_id="rex")
        result = await tool.execute()

        assert result["status"] == "ok"
        assert result["balance"] == "75.50"
        assert len(result["recent_transactions"]) == 2

        first = result["recent_transactions"][0]
        assert first["type"] == "transfer_out"
        assert first["amount"] == "10.00"
        assert first["description"] == "Payment"
        assert first["with"] == "aurora"

        second = result["recent_transactions"][1]
        assert "description" not in second
        assert "with" not in second
        mgr.get_transactions.assert_called_once_with("rex", limit=5)
