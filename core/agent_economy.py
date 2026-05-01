"""Agent economy — individual accounts, transfers, and budget tracking.

Each agent has a personal budget account. Tool costs are deducted from the
agent's balance. Agents can transfer funds to each other. Weekly allocations
replenish balances. A commons pool handles shared expenses.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from core.models import AgentAccount, AgentTransaction

if TYPE_CHECKING:
    import uuid

    from core.database import Database

logger = logging.getLogger(__name__)

# Default weekly budget split
DEFAULT_WEEKLY_TOTAL = Decimal("45.0")
INDIVIDUAL_SHARE = Decimal("0.6")  # 60% split equally among agents
COMMONS_SHARE = Decimal("0.4")  # 40% to commons pool


class AgentEconomyManager:
    """Manages individual agent accounts and the commons pool."""

    def __init__(self, db: Database, simulation_id: uuid.UUID | None = None) -> None:
        self._db = db
        self.simulation_id = simulation_id

    async def initialize_accounts(
        self,
        agent_ids: list[str],
        weekly_total: Decimal = DEFAULT_WEEKLY_TOTAL,
    ) -> None:
        """Create accounts for all agents if they don't exist.

        Individual allocation = (weekly_total * 0.6) / len(agent_ids).
        """
        if not agent_ids:
            return
        per_agent = (weekly_total * INDIVIDUAL_SHARE) / len(agent_ids)
        for agent_id in agent_ids:
            await self._db.execute(
                """INSERT INTO agent_accounts (agent_id, balance, weekly_allocation, simulation_id)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (agent_id, simulation_id) DO NOTHING""",
                agent_id,
                per_agent,
                per_agent,
                self.simulation_id,
            )

    async def create_account(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
        initial_balance: Decimal | None = None,
    ) -> AgentAccount:
        """Create a single agent account (used for new character onboarding).

        If account already exists, returns the existing one.
        """
        if initial_balance is not None:
            alloc = initial_balance
        else:
            # Determine per-agent share based on current account count
            count = await self._db.fetchval(
                "SELECT COUNT(*) FROM agent_accounts WHERE simulation_id = $1",
                simulation_id or self.simulation_id,
            )
            divisor = max(count or 1, 1)
            alloc = DEFAULT_WEEKLY_TOTAL * INDIVIDUAL_SHARE / divisor
        sid = simulation_id or self.simulation_id
        await self._db.execute(
            """INSERT INTO agent_accounts (agent_id, balance, weekly_allocation, simulation_id)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (agent_id, simulation_id) DO NOTHING""",
            agent_id,
            alloc,
            alloc,
            sid,
        )
        return await self.get_account(agent_id)

    async def get_account(self, agent_id: str) -> AgentAccount:
        """Get the full account for an agent."""
        row = await self._db.fetchrow(
            "SELECT * FROM agent_accounts WHERE agent_id = $1 AND simulation_id = $2",
            agent_id,
            self.simulation_id,
        )
        if row is None:
            return AgentAccount(agent_id=agent_id)
        return AgentAccount(**dict(row))

    async def get_balance(self, agent_id: str) -> Decimal:
        """Read current balance for an agent."""
        row = await self._db.fetchrow(
            "SELECT balance FROM agent_accounts WHERE agent_id = $1 AND simulation_id = $2",
            agent_id,
            self.simulation_id,
        )
        if row is None:
            return Decimal("0")
        return Decimal(str(row["balance"]))

    async def is_broke(self, agent_id: str) -> bool:
        """Check if agent's balance is <= 0."""
        return (await self.get_balance(agent_id)) <= 0

    async def deduct_cost(
        self,
        agent_id: str,
        amount: Decimal,
        description: str,
    ) -> bool:
        """Deduct a tool cost from the agent's balance.

        Returns True if the deduction succeeded, False if insufficient funds.
        """
        if amount <= 0:
            return True

        async with self._db.acquire() as conn:
            async with conn.transaction():
                # Atomic deduction — only succeeds if balance >= amount
                result = await conn.execute(
                    """UPDATE agent_accounts
                       SET balance = balance - $2,
                           total_spent = total_spent + $2,
                           updated_at = now()
                       WHERE agent_id = $1 AND balance >= $2 AND simulation_id = $3""",
                    agent_id,
                    amount,
                    self.simulation_id,
                )
                if "UPDATE 0" in result:
                    return False

                await conn.execute(
                    """INSERT INTO agent_transactions (agent_id, type, amount, description, simulation_id)
                       VALUES ($1, 'tool_cost', $2, $3, $4)""",
                    agent_id,
                    amount,
                    description,
                    self.simulation_id,
                )
        return True

    async def transfer(
        self,
        from_agent: str,
        to_agent: str,
        amount: Decimal,
        reason: str,
    ) -> bool:
        """Transfer funds between two agents atomically.

        All operations run inside a single DB transaction so a partial
        failure cannot lose money.

        Returns True on success, False if from_agent has insufficient funds.
        """
        if amount <= 0:
            return False

        async with self._db.acquire() as conn:
            async with conn.transaction():
                # Deduct from sender
                result = await conn.execute(
                    """UPDATE agent_accounts
                       SET balance = balance - $2,
                           total_transferred = total_transferred + $2,
                           updated_at = now()
                       WHERE agent_id = $1 AND balance >= $2 AND simulation_id = $3""",
                    from_agent,
                    amount,
                    self.simulation_id,
                )
                if "UPDATE 0" in result:
                    return False

                # Credit to receiver — must also succeed
                result2 = await conn.execute(
                    """UPDATE agent_accounts
                       SET balance = balance + $2,
                           total_earned = total_earned + $2,
                           updated_at = now()
                       WHERE agent_id = $1 AND simulation_id = $3""",
                    to_agent,
                    amount,
                    self.simulation_id,
                )
                if "UPDATE 0" in result2:
                    raise ValueError(f"Transfer failed: receiver {to_agent} has no account")

                # Record both sides
                await conn.execute(
                    """INSERT INTO agent_transactions (agent_id, type, amount, counterparty_agent_id, description, simulation_id)
                       VALUES ($1, 'transfer', $2, $3, $4, $5)""",
                    from_agent,
                    -amount,
                    to_agent,
                    f"Sent to {to_agent}: {reason}",
                    self.simulation_id,
                )
                await conn.execute(
                    """INSERT INTO agent_transactions (agent_id, type, amount, counterparty_agent_id, description, simulation_id)
                       VALUES ($1, 'transfer', $2, $3, $4, $5)""",
                    to_agent,
                    amount,
                    from_agent,
                    f"Received from {from_agent}: {reason}",
                    self.simulation_id,
                )
        return True

    async def weekly_allocation(
        self,
        agent_ids: list[str] | None = None,
    ) -> None:
        """Deposit weekly allocation to all active agents atomically."""
        async with self._db.acquire() as conn:
            async with conn.transaction():
                if agent_ids:
                    rows = await conn.fetch(
                        """SELECT agent_id, weekly_allocation FROM agent_accounts
                           WHERE agent_id = ANY($1) AND simulation_id = $2""",
                        agent_ids,
                        self.simulation_id,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT agent_id, weekly_allocation FROM agent_accounts WHERE simulation_id = $1",
                        self.simulation_id,
                    )

                for row in rows:
                    aid = row["agent_id"]
                    alloc = Decimal(str(row["weekly_allocation"]))
                    await conn.execute(
                        """UPDATE agent_accounts
                           SET balance = balance + $2,
                               total_earned = total_earned + $2,
                               updated_at = now()
                           WHERE agent_id = $1 AND simulation_id = $3""",
                        aid,
                        alloc,
                        self.simulation_id,
                    )
                    await conn.execute(
                        """INSERT INTO agent_transactions (agent_id, type, amount, description, simulation_id)
                           VALUES ($1, 'allocation', $2, 'Weekly allocation', $3)""",
                        aid,
                        alloc,
                        self.simulation_id,
                    )

    async def get_transactions(
        self,
        agent_id: str,
        limit: int = 20,
    ) -> list[AgentTransaction]:
        """Get recent transactions for an agent."""
        rows = await self._db.fetch(
            """SELECT * FROM agent_transactions
               WHERE agent_id = $1 AND simulation_id = $2
               ORDER BY created_at DESC
               LIMIT $3""",
            agent_id,
            self.simulation_id,
            limit,
        )
        return [AgentTransaction(**dict(r)) for r in rows]
