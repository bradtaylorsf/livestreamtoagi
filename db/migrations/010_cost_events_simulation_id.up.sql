-- 010_cost_events_simulation_id.up.sql
-- Adds simulation_id to cost_events for accurate per-simulation cost attribution.
-- Previously costs were matched via time-window JOIN which was fragile with overlapping sims.

ALTER TABLE cost_events
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);

CREATE INDEX IF NOT EXISTS idx_cost_events_simulation_id
    ON cost_events (simulation_id)
    WHERE simulation_id IS NOT NULL;
