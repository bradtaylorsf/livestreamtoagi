-- 010_cost_events_simulation_id.down.sql
DROP INDEX IF EXISTS idx_cost_events_simulation_id;
ALTER TABLE cost_events DROP COLUMN IF EXISTS simulation_id;
