-- Character application pipeline and departures
CREATE TABLE IF NOT EXISTS character_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id),
    name VARCHAR(50) NOT NULL,
    role VARCHAR(100),
    personality_sketch TEXT,
    proposed_by TEXT NOT NULL,
    source VARCHAR(20) NOT NULL CHECK (source IN ('system', 'agent', 'audience')),
    model_conversation VARCHAR(100),
    model_building VARCHAR(100),
    agent_votes JSONB DEFAULT '{}',
    audience_votes_for INT DEFAULT 0,
    audience_votes_against INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'proposed' CHECK (status IN ('proposed', 'deliberating', 'voting', 'approved', 'rejected', 'onboarded')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS character_departures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id),
    agent_id TEXT NOT NULL,
    reason VARCHAR(20) CHECK (reason IN ('low_satisfaction', 'exile_vote', 'voluntary')),
    departure_narrative TEXT,
    departed_at TIMESTAMPTZ DEFAULT NOW()
);
