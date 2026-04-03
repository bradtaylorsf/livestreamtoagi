-- Artifact persistence for all tool outputs
-- Stores every tool invocation and its result for simulation validation

CREATE TABLE IF NOT EXISTS artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id   UUID,
    conversation_id UUID REFERENCES conversations(id),
    agent_id        TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_input      JSONB,
    tool_output     JSONB,
    artifact_type   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'executed',
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_artifacts_simulation_id
    ON artifacts (simulation_id);

CREATE INDEX IF NOT EXISTS idx_artifacts_agent_id
    ON artifacts (agent_id);

CREATE INDEX IF NOT EXISTS idx_artifacts_artifact_type
    ON artifacts (artifact_type);

CREATE INDEX IF NOT EXISTS idx_artifacts_created_at
    ON artifacts (created_at);

CREATE INDEX IF NOT EXISTS idx_artifacts_simulation_agent
    ON artifacts (simulation_id, agent_id);
