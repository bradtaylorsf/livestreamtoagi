-- Rollback migration 036: Restore nullable simulation_id on remaining tables.

-- Drop full indexes and restore partial indexes
DROP INDEX IF EXISTS idx_phase_assertions_simulation;
CREATE INDEX idx_phase_assertions_simulation ON phase_assertions(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_evolution_cycles_simulation;
CREATE INDEX idx_evolution_cycles_simulation ON evolution_cycles(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_char_applications_simulation;
CREATE INDEX idx_char_applications_simulation ON character_applications(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_char_departures_simulation;
CREATE INDEX idx_char_departures_simulation ON character_departures(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_alliances_simulation;
CREATE INDEX idx_alliances_simulation ON alliances(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_alliance_members_simulation;
CREATE INDEX idx_alliance_members_simulation ON alliance_members(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_alliance_proposals_simulation;
CREATE INDEX idx_alliance_proposals_simulation ON alliance_proposals(simulation_id) WHERE simulation_id IS NOT NULL;

-- Restore nullable
ALTER TABLE phase_assertions ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE evolution_cycles ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE character_applications ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE character_departures ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE alliances ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE alliance_members ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE alliance_proposals ALTER COLUMN simulation_id DROP NOT NULL;

-- Drop simulation_id from alliance_members (added in 036)
ALTER TABLE alliance_members DROP COLUMN IF EXISTS simulation_id;
