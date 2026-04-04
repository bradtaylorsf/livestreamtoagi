-- Migration 014: Add agent_relationships table for structured social dynamics.

CREATE TABLE IF NOT EXISTS agent_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id),
    agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    sentiment_score DECIMAL(3,2),
    trust_score DECIMAL(3,2),
    interaction_count INT DEFAULT 0,
    last_interaction_at TIMESTAMPTZ,
    relationship_summary TEXT,
    evolution_log JSONB DEFAULT '[]',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(simulation_id, agent_id, target_agent_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_relationships_simulation
    ON agent_relationships(simulation_id);
CREATE INDEX IF NOT EXISTS idx_agent_relationships_agents
    ON agent_relationships(agent_id, target_agent_id);
