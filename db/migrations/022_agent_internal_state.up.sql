-- Agent internal state: continuous variables for needs, moods, boredom, satisfaction.
-- Persisted from Redis snapshots during reflection cycles.

CREATE TABLE IF NOT EXISTS agent_internal_state (
    agent_id    VARCHAR(50) PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    energy      DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    satisfaction DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    boredom     DOUBLE PRECISION NOT NULL DEFAULT 0.2,
    frustration DOUBLE PRECISION NOT NULL DEFAULT 0.1,
    social_need DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    creative_need DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    recognition_need DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    mood        VARCHAR(30) NOT NULL DEFAULT 'neutral',
    version     INT NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_internal_state_updated
    ON agent_internal_state(updated_at DESC);
