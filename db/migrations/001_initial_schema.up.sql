-- 001_initial_schema.up.sql
-- Creates all 15 tables for the livestream-to-agi project.
-- Extensions (vector, pg_trgm) are created by db/init.sql on first boot;
-- repeated here with IF NOT EXISTS for standalone migration safety.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- Tables with no foreign-key dependencies
-- ============================================================

CREATE TABLE IF NOT EXISTS agents (
    id VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    model_conversation VARCHAR(100) NOT NULL,
    model_building VARCHAR(100) NOT NULL,
    voice_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transcripts (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    participants TEXT[] NOT NULL,
    content TEXT NOT NULL,
    token_count INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    trigger_type VARCHAR(32) NOT NULL,
    trigger_details JSONB,
    initial_energy FLOAT NOT NULL,
    final_energy FLOAT,
    turn_count INTEGER DEFAULT 0,
    participating_agents JSONB NOT NULL,
    topics_discussed JSONB,
    closed_by VARCHAR(32),
    location VARCHAR(64),
    audience_events_during INTEGER DEFAULT 0,
    config_hash VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS world_chunks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    x_offset INT NOT NULL,
    y_offset INT NOT NULL,
    width INT NOT NULL,
    height INT NOT NULL,
    tile_data JSONB NOT NULL,
    objects JSONB DEFAULT '[]',
    built_by TEXT[],
    built_date TIMESTAMP DEFAULT NOW(),
    description TEXT,
    proposal_votes JSONB,
    tileset_url VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS world_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50),
    description TEXT,
    agents_involved TEXT[],
    audience_participation BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS challenges (
    id SERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    submitted_by VARCHAR(100),
    source VARCHAR(20),
    status VARCHAR(20) DEFAULT 'pending',
    assigned_agents TEXT[],
    result TEXT,
    cost_estimate FLOAT,
    actual_cost FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS revenue_events (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50),
    amount DECIMAL(10,2),
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Note: cost_events.agent_id intentionally has no FK constraint per spec
CREATE TABLE IF NOT EXISTS cost_events (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50),
    cost_type VARCHAR(50),
    amount DECIMAL(10,4),
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- Tables with foreign-key dependencies
-- ============================================================

CREATE TABLE IF NOT EXISTS core_memory (
    agent_id VARCHAR(50) PRIMARY KEY REFERENCES agents(id),
    content TEXT NOT NULL,
    token_count INT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW(),
    version INT DEFAULT 1
);

CREATE TABLE IF NOT EXISTS core_memory_history (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES agents(id),
    content TEXT NOT NULL,
    version INT NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    change_reason TEXT
);

CREATE TABLE IF NOT EXISTS recall_memory (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES agents(id),
    summary TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    event_type VARCHAR(50),
    participants TEXT[],
    transcript_id INT REFERENCES transcripts(id),
    importance_score FLOAT DEFAULT 0.5,
    timestamp TIMESTAMP DEFAULT NOW(),
    recalled_count INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversation_buffer (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES agents(id),
    role VARCHAR(20) NOT NULL,
    speaker VARCHAR(50),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS expansion_proposals (
    id SERIAL PRIMARY KEY,
    proposed_by VARCHAR(50) REFERENCES agents(id),
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'proposed',
    votes_for INT DEFAULT 0,
    votes_against INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Note: conversation_selection_log.conversation_id has no FK per spec
CREATE TABLE IF NOT EXISTS conversation_selection_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL,
    turn_number INTEGER NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    selected_agent_id VARCHAR(32) NOT NULL,
    was_interrupt BOOLEAN DEFAULT FALSE,
    agent_scores JSONB NOT NULL,
    detected_topic VARCHAR(64),
    previous_speaker_id VARCHAR(32),
    conversation_energy FLOAT,
    active_agents JSONB,
    trigger_type VARCHAR(32),
    config_hash VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS interrupt_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    attempting_agent_id VARCHAR(32) NOT NULL,
    would_have_spoken_id VARCHAR(32) NOT NULL,
    interrupt_score FLOAT NOT NULL,
    threshold_at_time FLOAT NOT NULL,
    succeeded BOOLEAN NOT NULL,
    reason TEXT
);

-- ============================================================
-- Indexes
-- ============================================================

-- pgvector IVF FLAT index for cosine similarity search on recall_memory.
-- Note: IVF FLAT indexes are most effective with data in the table;
-- lists=100 is suitable for initial setup and moderate row counts.
CREATE INDEX IF NOT EXISTS idx_recall_embedding
    ON recall_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_recall_agent
    ON recall_memory (agent_id);

CREATE INDEX IF NOT EXISTS idx_recall_timestamp
    ON recall_memory (timestamp);

-- GIN index for array containment queries on transcripts.participants
CREATE INDEX IF NOT EXISTS idx_transcripts_participants
    ON transcripts USING gin (participants);

CREATE INDEX IF NOT EXISTS idx_transcripts_event
    ON transcripts (event_type);

CREATE INDEX IF NOT EXISTS idx_convbuf_agent
    ON conversation_buffer (agent_id, created_at);

CREATE INDEX IF NOT EXISTS idx_selection_log_conversation
    ON conversation_selection_log (conversation_id);

CREATE INDEX IF NOT EXISTS idx_selection_log_agent
    ON conversation_selection_log (selected_agent_id);

CREATE INDEX IF NOT EXISTS idx_selection_log_time
    ON conversation_selection_log (timestamp);
