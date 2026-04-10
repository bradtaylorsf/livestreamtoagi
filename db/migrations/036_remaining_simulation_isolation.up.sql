-- Migration 036: Complete simulation isolation for remaining tables.
--
-- Tables missed in migration 035 that still have nullable simulation_id:
-- phase_assertions, evolution_cycles, character_applications,
-- character_departures, alliances, alliance_members, alliance_proposals

-- ── 0. Add simulation_id column to alliance_members (missing from 026) ──

ALTER TABLE alliance_members
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);

-- ── 1. Backfill NULL simulation_id → live simulation ─────────

UPDATE phase_assertions SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE evolution_cycles SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE character_applications SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE character_departures SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE alliances SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE alliance_members SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE alliance_proposals SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;

-- ── 2. Enforce NOT NULL ──────────────────────────────────────

ALTER TABLE phase_assertions ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE evolution_cycles ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE character_applications ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE character_departures ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE alliances ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE alliance_members ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE alliance_proposals ALTER COLUMN simulation_id SET NOT NULL;

-- ── 3. Replace partial indexes with full indexes ─────────────

DROP INDEX IF EXISTS idx_phase_assertions_simulation;
CREATE INDEX idx_phase_assertions_simulation ON phase_assertions(simulation_id);

DROP INDEX IF EXISTS idx_evolution_cycles_simulation;
CREATE INDEX idx_evolution_cycles_simulation ON evolution_cycles(simulation_id);

DROP INDEX IF EXISTS idx_char_applications_simulation;
CREATE INDEX idx_char_applications_simulation ON character_applications(simulation_id);

DROP INDEX IF EXISTS idx_char_departures_simulation;
CREATE INDEX idx_char_departures_simulation ON character_departures(simulation_id);

DROP INDEX IF EXISTS idx_alliances_simulation;
CREATE INDEX idx_alliances_simulation ON alliances(simulation_id);

DROP INDEX IF EXISTS idx_alliance_members_simulation;
CREATE INDEX idx_alliance_members_simulation ON alliance_members(simulation_id);

DROP INDEX IF EXISTS idx_alliance_proposals_simulation;
CREATE INDEX idx_alliance_proposals_simulation ON alliance_proposals(simulation_id);
