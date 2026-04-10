-- Add model_versions JSONB column to simulations and eval_runs tables
-- for tracking exact model identifiers per agent per run (reproducibility).

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS model_versions JSONB NOT NULL DEFAULT '{}';

ALTER TABLE eval_runs
    ADD COLUMN IF NOT EXISTS model_versions JSONB NOT NULL DEFAULT '{}';
