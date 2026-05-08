-- Migration 039: Add factions column to simulations.
--
-- Stores the per-simulation faction list (named groupings of agents with
-- shared goals/stance) so it surfaces in reports without re-parsing the
-- scenario YAML.

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS factions JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMIT;
