-- 045_simulation_is_featured.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_simulations_is_featured;

ALTER TABLE simulations DROP COLUMN IF EXISTS is_featured;

COMMIT;
