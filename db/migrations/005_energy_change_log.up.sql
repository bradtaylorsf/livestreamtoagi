-- 005_energy_change_log.up.sql
-- Adds energy_change_log table for tracking conversation energy changes per turn.

CREATE TABLE IF NOT EXISTS energy_change_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL,
    turn_number INTEGER NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    changes JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_energy_change_log_conversation_id
    ON energy_change_log (conversation_id);
