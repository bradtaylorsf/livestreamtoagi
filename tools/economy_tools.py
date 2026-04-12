"""Agent economy tools — transfer funds and view account balance."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .base import BaseTool

if TYPE_CHECKING:
    from core.agent_economy import AgentEconomyManager


class TransferBudgetTool(BaseTool):
    """Transfer funds from your account to another agent."""

    name = "transfer_budget"
    description = "Send funds to another agent with a reason"
    parameters: dict[str, Any] = {
        "to_agent_id": {
            "type": "string",
            "description": "The agent to send funds to",
        },
        "amount": {
            "type": "number",
            "description": "Amount to transfer (positive number)",
        },
        "reason": {
            "type": "string",
            "description": "Why you are sending this payment",
        },
    }

    def __init__(self, economy_manager: AgentEconomyManager, agent_id: str) -> None:
        self._economy = economy_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        to_agent = kwargs["to_agent_id"].lower().strip()
        amount = Decimal(str(kwargs["amount"]))
        reason = kwargs["reason"]

        if amount <= 0:
            return {"status": "rejected", "reason": "Amount must be positive"}

        if to_agent == self._agent_id:
            return {"status": "rejected", "reason": "Cannot transfer to yourself"}

        success = await self._economy.transfer(
            self._agent_id, to_agent, amount, reason,
        )
        if not success:
            balance = await self._economy.get_balance(self._agent_id)
            return {
                "status": "insufficient_funds",
                "balance": str(balance),
                "reason": f"Cannot transfer ${amount} — your balance is ${balance}",
            }

        new_balance = await self._economy.get_balance(self._agent_id)
        return {
            "status": "ok",
            "transferred": str(amount),
            "to": to_agent,
            "reason": reason,
            "new_balance": str(new_balance),
        }


class ViewAccountTool(BaseTool):
    """View your current account balance and recent transactions."""

    name = "view_account"
    description = "Check your balance and recent transaction history"
    parameters: dict[str, Any] = {}

    def __init__(self, economy_manager: AgentEconomyManager, agent_id: str) -> None:
        self._economy = economy_manager
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        account = await self._economy.get_account(self._agent_id)
        transactions = await self._economy.get_transactions(self._agent_id, limit=5)

        recent = []
        for tx in transactions:
            entry: dict[str, Any] = {
                "type": tx.type,
                "amount": str(tx.amount),
            }
            if tx.description:
                entry["description"] = tx.description
            if tx.counterparty_agent_id:
                entry["with"] = tx.counterparty_agent_id
            recent.append(entry)

        return {
            "status": "ok",
            "balance": str(account.balance),
            "weekly_allocation": str(account.weekly_allocation),
            "total_earned": str(account.total_earned),
            "total_spent": str(account.total_spent),
            "recent_transactions": recent,
        }
