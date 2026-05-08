-- 046_challenges_simulation_link.up.sql
-- Repurpose /challenges as user-submitted simulation scenarios shared with
-- the community. A "challenge" is now backed by a user-submitted simulation
-- plus a description and tags; the existing FK challenges.simulation_id is
-- preserved for legacy rows (which remain hidden because their target
-- simulation has shared_as_challenge = FALSE).

BEGIN;

-- New per-challenge tagging surface (free-form, e.g. "creative", "social").
ALTER TABLE challenges
    ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

-- When the simulation was first shared as a challenge. Distinct from
-- challenges.created_at so we can render "shared 3h ago" without conflating
-- it with the row's creation timestamp for legacy data.
ALTER TABLE challenges
    ADD COLUMN IF NOT EXISTS shared_at TIMESTAMPTZ;

-- Flip on a simulation when its submitter shares it. Filtering on this flag
-- keeps the new /challenges feed clean of legacy chat-only rows that point
-- at the live simulation.
ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS shared_as_challenge BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_simulations_shared_challenge
    ON simulations (shared_as_challenge)
    WHERE shared_as_challenge = TRUE;

COMMIT;
