-- Prompt logs: record assembled context sent to LLM for debugging
CREATE TABLE IF NOT EXISTS prompt_logs (
    id          SERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    simulation_id   UUID REFERENCES simulations(id) ON DELETE CASCADE,
    agent_id        VARCHAR(50) NOT NULL,
    turn_number     INT NOT NULL DEFAULT 0,
    full_prompt     TEXT NOT NULL,
    sections_included JSONB NOT NULL DEFAULT '{}',
    total_tokens    INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompt_logs_conversation ON prompt_logs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_prompt_logs_simulation ON prompt_logs(simulation_id);
