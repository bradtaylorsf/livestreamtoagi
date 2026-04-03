-- Simulation tracking table: central record tying together conversations,
-- artifacts, overseer logs, and eval results for a single simulation run.

CREATE TABLE IF NOT EXISTS simulations (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT NOT NULL,
    description           TEXT,
    config                JSONB NOT NULL,
    status                TEXT NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at          TIMESTAMPTZ,
    simulated_duration    INTERVAL,
    real_duration         INTERVAL,
    total_conversations   INT NOT NULL DEFAULT 0,
    total_turns           INT NOT NULL DEFAULT 0,
    total_tokens          INT NOT NULL DEFAULT 0,
    total_cost            DECIMAL(10,4) NOT NULL DEFAULT 0,
    total_artifacts       INT NOT NULL DEFAULT 0,
    total_overseer_flags  INT NOT NULL DEFAULT 0,
    agents_participated   TEXT[] NOT NULL DEFAULT '{}',
    error_log             JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_simulations_status ON simulations (status);
CREATE INDEX IF NOT EXISTS idx_simulations_started_at ON simulations (started_at);
CREATE INDEX IF NOT EXISTS idx_simulations_name ON simulations (name);

-- Add simulation_id FK to conversations
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);

CREATE INDEX IF NOT EXISTS idx_conversations_simulation_id
    ON conversations (simulation_id)
    WHERE simulation_id IS NOT NULL;

-- Add FK constraints to artifacts and overseer_shadow_log
-- (columns already exist from migrations 007/008, just need the FK)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_artifacts_simulation_id'
    ) THEN
        ALTER TABLE artifacts
            ADD CONSTRAINT fk_artifacts_simulation_id
            FOREIGN KEY (simulation_id) REFERENCES simulations(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_overseer_shadow_log_simulation_id'
    ) THEN
        ALTER TABLE overseer_shadow_log
            ADD CONSTRAINT fk_overseer_shadow_log_simulation_id
            FOREIGN KEY (simulation_id) REFERENCES simulations(id);
    END IF;
END $$;
