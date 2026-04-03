-- Shadow/log-only mode for Overseer content filter
-- Records what the Overseer *would* flag/block without actually intervening
CREATE TABLE IF NOT EXISTS overseer_shadow_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID,
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    agent_id TEXT NOT NULL,
    original_content TEXT NOT NULL,
    filter_layer INT NOT NULL,
    severity INT NOT NULL CHECK (severity >= 1 AND severity <= 5),
    action_would_take TEXT NOT NULL,
    reason TEXT NOT NULL,
    flagged_keywords TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_overseer_shadow_log_conv_created
    ON overseer_shadow_log (conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_overseer_shadow_log_simulation
    ON overseer_shadow_log (simulation_id)
    WHERE simulation_id IS NOT NULL;
