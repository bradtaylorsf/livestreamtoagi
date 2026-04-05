-- Versioned agent prompt configurations (evolution loop prerequisite)
CREATE TABLE IF NOT EXISTS agent_prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(50) NOT NULL REFERENCES agents(id),
    version INT NOT NULL,
    system_prompt TEXT NOT NULL,
    behaviors JSONB NOT NULL DEFAULT '{}',
    config_params JSONB NOT NULL DEFAULT '{}',
    change_reason TEXT,
    source VARCHAR(20) NOT NULL CHECK (source IN ('seed', 'manual', 'eval_loop')),
    eval_run_id UUID REFERENCES eval_runs(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(agent_id, version)
);

-- Versioned conversation parameters
CREATE TABLE IF NOT EXISTS conversation_param_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version INT NOT NULL UNIQUE,
    params JSONB NOT NULL,
    change_reason TEXT,
    source VARCHAR(20) NOT NULL CHECK (source IN ('seed', 'manual', 'eval_loop')),
    eval_run_id UUID REFERENCES eval_runs(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Active version pointers
CREATE TABLE IF NOT EXISTS active_config (
    agent_id VARCHAR(50) PRIMARY KEY REFERENCES agents(id),
    prompt_version INT NOT NULL,
    conversation_param_version INT NOT NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_prompt_versions_agent
    ON agent_prompt_versions(agent_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_param_versions_version
    ON conversation_param_versions(version DESC);
