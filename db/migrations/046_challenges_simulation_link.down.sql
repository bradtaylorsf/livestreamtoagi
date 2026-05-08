-- 046_challenges_simulation_link.down.sql
-- Reverse the schema additions from the up migration.

BEGIN;

DROP INDEX IF EXISTS idx_simulations_shared_challenge;

ALTER TABLE simulations
    DROP COLUMN IF EXISTS shared_as_challenge;

ALTER TABLE challenges
    DROP COLUMN IF EXISTS shared_at;

ALTER TABLE challenges
    DROP COLUMN IF EXISTS tags;

COMMIT;
