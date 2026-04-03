-- Reverse migration 009: drop simulation tracking

ALTER TABLE overseer_shadow_log
    DROP CONSTRAINT IF EXISTS fk_overseer_shadow_log_simulation_id;

ALTER TABLE artifacts
    DROP CONSTRAINT IF EXISTS fk_artifacts_simulation_id;

DROP INDEX IF EXISTS idx_conversations_simulation_id;
ALTER TABLE conversations
    DROP COLUMN IF EXISTS simulation_id;

DROP TABLE IF EXISTS simulations;
