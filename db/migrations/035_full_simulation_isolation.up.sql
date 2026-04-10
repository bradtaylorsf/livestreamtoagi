-- Migration 035: Complete simulation isolation.
--
-- 1. Add is_live flag to simulations table with partial unique index
-- 2. Seed the dedicated live simulation row
-- 3. Add simulation_id to all remaining tables
-- 4. Backfill existing NULL simulation_id rows to the live simulation
-- 5. Add NOT NULL constraints and clean up COALESCE indexes from migration 034

-- Well-known UUID for the live simulation
-- Referenced in code as core.constants.LIVE_SIMULATION_ID
DO $$ BEGIN RAISE NOTICE 'Live simulation UUID: 00000000-0000-0000-0000-000000000001'; END $$;

-- ── 1. Add is_live to simulations ──────────────────────────────

ALTER TABLE simulations ADD COLUMN IF NOT EXISTS is_live BOOLEAN NOT NULL DEFAULT FALSE;

-- Only one simulation can be live at a time
CREATE UNIQUE INDEX IF NOT EXISTS uq_simulations_live
    ON simulations (is_live) WHERE is_live = TRUE;

-- ── 2. Seed the live simulation row ────────────────────────────

INSERT INTO simulations (id, name, description, config, status, is_live, agents_participated)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Live Livestream',
    'Persistent live simulation for the 24/7 livestream',
    '{"mode": "live"}'::jsonb,
    'running',
    TRUE,
    '{}'
) ON CONFLICT (id) DO NOTHING;

-- ── 3. Add simulation_id to unscoped tables ────────────────────

-- world_chunks
ALTER TABLE world_chunks
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_world_chunks_simulation
    ON world_chunks(simulation_id) WHERE simulation_id IS NOT NULL;

-- world_events
ALTER TABLE world_events
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_world_events_simulation
    ON world_events(simulation_id) WHERE simulation_id IS NOT NULL;

-- expansion_proposals
ALTER TABLE expansion_proposals
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_expansion_proposals_simulation
    ON expansion_proposals(simulation_id) WHERE simulation_id IS NOT NULL;

-- agent_internal_state: has PRIMARY KEY (agent_id), need composite unique
ALTER TABLE agent_internal_state DROP CONSTRAINT IF EXISTS agent_internal_state_pkey;
ALTER TABLE agent_internal_state
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_state_agent_sim
    ON agent_internal_state (agent_id, COALESCE(simulation_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- agent_accounts: has PRIMARY KEY (agent_id), need composite unique
ALTER TABLE agent_accounts DROP CONSTRAINT IF EXISTS agent_accounts_pkey;
ALTER TABLE agent_accounts
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_accounts_agent_sim
    ON agent_accounts (agent_id, COALESCE(simulation_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- agent_transactions
ALTER TABLE agent_transactions
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_agent_transactions_simulation
    ON agent_transactions(simulation_id) WHERE simulation_id IS NOT NULL;

-- self_modification_proposals
ALTER TABLE self_modification_proposals
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_self_mod_proposals_simulation
    ON self_modification_proposals(simulation_id) WHERE simulation_id IS NOT NULL;

-- challenges
ALTER TABLE challenges
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_challenges_simulation
    ON challenges(simulation_id) WHERE simulation_id IS NOT NULL;

-- revenue_events
ALTER TABLE revenue_events
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_revenue_events_simulation
    ON revenue_events(simulation_id) WHERE simulation_id IS NOT NULL;

-- conversation_selection_log (has conversation_id FK but no simulation_id)
ALTER TABLE conversation_selection_log
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_conv_selection_simulation
    ON conversation_selection_log(simulation_id) WHERE simulation_id IS NOT NULL;

-- interrupt_log
ALTER TABLE interrupt_log
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_interrupt_log_simulation
    ON interrupt_log(simulation_id) WHERE simulation_id IS NOT NULL;

-- energy_change_log
ALTER TABLE energy_change_log
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);
CREATE INDEX IF NOT EXISTS idx_energy_change_simulation
    ON energy_change_log(simulation_id) WHERE simulation_id IS NOT NULL;

-- ── 4. Backfill all NULL simulation_id → live simulation ───────

UPDATE simulations SET is_live = FALSE WHERE id != '00000000-0000-0000-0000-000000000001' AND is_live = TRUE;

-- Tables from migration 034
UPDATE core_memory SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE core_memory_history SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE recall_memory SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE conversation_buffer SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE journal_entries SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE agent_goals SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;

-- Tables from migration 009/010
UPDATE conversations SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE cost_events SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE artifacts SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE management_shadow_log SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;

-- Tables from this migration
UPDATE world_chunks SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE world_events SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE expansion_proposals SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE agent_internal_state SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE agent_accounts SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE agent_transactions SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE self_modification_proposals SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE challenges SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE revenue_events SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE conversation_selection_log SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE interrupt_log SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE energy_change_log SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;

-- agent_relationships (from migration 014)
UPDATE agent_relationships SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;

-- ── 5. Add NOT NULL constraints ────────────────────────────────

-- Tables from migration 034
ALTER TABLE core_memory ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE core_memory_history ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE recall_memory ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE conversation_buffer ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE journal_entries ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE agent_goals ALTER COLUMN simulation_id SET NOT NULL;

-- Tables from migrations 009/010
ALTER TABLE conversations ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE cost_events ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE artifacts ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE management_shadow_log ALTER COLUMN simulation_id SET NOT NULL;

-- Tables from this migration
ALTER TABLE world_chunks ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE world_events ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE expansion_proposals ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE agent_internal_state ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE agent_accounts ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE agent_transactions ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE self_modification_proposals ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE challenges ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE revenue_events ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE conversation_selection_log ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE interrupt_log ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE energy_change_log ALTER COLUMN simulation_id SET NOT NULL;

-- agent_relationships
ALTER TABLE agent_relationships ALTER COLUMN simulation_id SET NOT NULL;

-- ── 6. Clean up COALESCE unique index from migration 034 ──────
-- Now that simulation_id is NOT NULL, replace COALESCE index with proper unique

DROP INDEX IF EXISTS uq_core_memory_agent_sim;
CREATE UNIQUE INDEX uq_core_memory_agent_sim
    ON core_memory (agent_id, simulation_id);

-- Also fix the new tables from this migration
DROP INDEX IF EXISTS uq_agent_state_agent_sim;
CREATE UNIQUE INDEX uq_agent_state_agent_sim
    ON agent_internal_state (agent_id, simulation_id);

DROP INDEX IF EXISTS uq_agent_accounts_agent_sim;
CREATE UNIQUE INDEX uq_agent_accounts_agent_sim
    ON agent_accounts (agent_id, simulation_id);

-- Drop the partial indexes (WHERE simulation_id IS NOT NULL) since column is now NOT NULL
-- These partial indexes are still valid but less efficient than full indexes
DROP INDEX IF EXISTS idx_cmh_simulation;
CREATE INDEX idx_cmh_simulation ON core_memory_history(simulation_id);

DROP INDEX IF EXISTS idx_recall_simulation;
CREATE INDEX idx_recall_simulation ON recall_memory(simulation_id);

DROP INDEX IF EXISTS idx_convbuf_simulation;
CREATE INDEX idx_convbuf_simulation ON conversation_buffer(simulation_id);

DROP INDEX IF EXISTS idx_journal_simulation;
CREATE INDEX idx_journal_simulation ON journal_entries(simulation_id);

DROP INDEX IF EXISTS idx_goals_simulation;
CREATE INDEX idx_goals_simulation ON agent_goals(simulation_id);
