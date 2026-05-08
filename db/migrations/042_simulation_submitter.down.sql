-- 042_simulation_submitter.down.sql

BEGIN;

ALTER TABLE simulations
    DROP CONSTRAINT IF EXISTS simulations_status_check;

ALTER TABLE simulations
    ADD CONSTRAINT simulations_status_check
    CHECK (status IN ('running', 'completed', 'failed', 'cancelled'));

DROP INDEX IF EXISTS idx_simulations_submitted_by;
ALTER TABLE simulations DROP COLUMN IF EXISTS submitted_by_user_id;

COMMIT;
