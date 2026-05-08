-- 042_simulation_submitter.up.sql
-- Tag simulations with the public user who submitted them and allow
-- a 'queued' status for submissions awaiting orchestrator pickup.

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS submitted_by_user_id UUID REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_simulations_submitted_by
    ON simulations (submitted_by_user_id)
    WHERE submitted_by_user_id IS NOT NULL;

-- Extend the status enum to include 'queued' (public submissions land
-- here before the orchestrator subprocess flips them to 'running').
ALTER TABLE simulations
    DROP CONSTRAINT IF EXISTS simulations_status_check;

ALTER TABLE simulations
    ADD CONSTRAINT simulations_status_check
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'));

COMMIT;
