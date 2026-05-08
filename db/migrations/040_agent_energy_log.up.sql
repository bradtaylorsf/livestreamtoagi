-- 040_agent_energy_log.up.sql
-- Persists per-agent, per-turn energy values so the workspace can render an
-- energy timeline visualization. The conversation engine writes one row per
-- active participant on each turn.

CREATE TABLE IF NOT EXISTS agent_energy_log (
    id BIGSERIAL PRIMARY KEY,
    simulation_id UUID NOT NULL,
    agent_id VARCHAR(50) NOT NULL,
    conversation_id UUID NOT NULL,
    turn_number INTEGER NOT NULL,
    energy DOUBLE PRECISION NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (simulation_id, agent_id, conversation_id, turn_number)
);

-- Composite index supports the timeline query path
-- (filter by simulation_id, group by agent_id, ordered by timestamp).
CREATE INDEX IF NOT EXISTS idx_agent_energy_log_sim_agent_ts
    ON agent_energy_log (simulation_id, agent_id, timestamp);
