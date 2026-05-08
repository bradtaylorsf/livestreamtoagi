-- Migration 038: Add hypothesis / outcomes / learnings to simulations.
--
-- Turns each simulation into a research artifact: hypothesis (expectation),
-- outcomes (structured baseline + evals + surprises + failures), and
-- learnings (post-run reflections by agents or the user).

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS hypothesis TEXT,
    ADD COLUMN IF NOT EXISTS outcomes JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS learnings JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMIT;
