-- Individual agent economy accounts and transaction ledger
CREATE TABLE IF NOT EXISTS agent_accounts (
    agent_id VARCHAR(50) PRIMARY KEY REFERENCES agents(id),
    balance NUMERIC(10,4) NOT NULL DEFAULT 0,
    weekly_allocation NUMERIC(10,4) NOT NULL DEFAULT 3.0,
    total_earned NUMERIC(10,4) NOT NULL DEFAULT 0,
    total_spent NUMERIC(10,4) NOT NULL DEFAULT 0,
    total_transferred NUMERIC(10,4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_transactions (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL REFERENCES agents(id),
    type VARCHAR(20) NOT NULL
        CHECK (type IN ('allocation', 'tool_cost', 'transfer', 'bonus', 'investment', 'penalty')),
    amount NUMERIC(10,4) NOT NULL,
    counterparty_agent_id VARCHAR(50) REFERENCES agents(id),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_transactions_agent_time
    ON agent_transactions(agent_id, created_at DESC);
