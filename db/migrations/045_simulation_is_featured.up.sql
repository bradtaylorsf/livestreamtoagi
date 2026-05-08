-- 045_simulation_is_featured.up.sql
-- Adds an `is_featured` flag to simulations so the home page can surface a
-- curated set of runs. The partial index keeps featured-only queries cheap
-- as the simulations table grows.

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_simulations_is_featured
    ON simulations (is_featured)
    WHERE is_featured = TRUE;

COMMIT;
