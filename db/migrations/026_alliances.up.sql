-- Alliance system — factions, alliances, and political dynamics
CREATE TABLE IF NOT EXISTS alliances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id),
    name VARCHAR(100) NOT NULL,
    founded_by TEXT NOT NULL,
    purpose TEXT,
    shared_treasury DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    dissolved_at TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS alliance_members (
    alliance_id UUID REFERENCES alliances(id),
    agent_id TEXT NOT NULL,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    left_at TIMESTAMPTZ DEFAULT NULL,
    PRIMARY KEY (alliance_id, agent_id)
);

CREATE TABLE IF NOT EXISTS alliance_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id),
    proposer TEXT NOT NULL,
    alliance_name TEXT NOT NULL,
    purpose TEXT,
    invitees TEXT[] NOT NULL,
    votes JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
