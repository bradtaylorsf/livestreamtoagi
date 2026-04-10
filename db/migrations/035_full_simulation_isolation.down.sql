-- Rollback migration 035: Undo full simulation isolation.
-- Restores nullable simulation_id, removes is_live, drops new columns.

-- ── 1. Restore partial indexes from migration 034 ─────────────

DROP INDEX IF EXISTS idx_cmh_simulation;
CREATE INDEX idx_cmh_simulation ON core_memory_history(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_recall_simulation;
CREATE INDEX idx_recall_simulation ON recall_memory(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_convbuf_simulation;
CREATE INDEX idx_convbuf_simulation ON conversation_buffer(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_journal_simulation;
CREATE INDEX idx_journal_simulation ON journal_entries(simulation_id) WHERE simulation_id IS NOT NULL;

DROP INDEX IF EXISTS idx_goals_simulation;
CREATE INDEX idx_goals_simulation ON agent_goals(simulation_id) WHERE simulation_id IS NOT NULL;

-- Restore COALESCE unique index on core_memory
DROP INDEX IF EXISTS uq_core_memory_agent_sim;
CREATE UNIQUE INDEX uq_core_memory_agent_sim
    ON core_memory (agent_id, COALESCE(simulation_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- ── 2. Drop NOT NULL constraints ──────────────────────────────

ALTER TABLE core_memory ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE core_memory_history ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE recall_memory ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE conversation_buffer ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE journal_entries ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE agent_goals ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE conversations ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE cost_events ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE artifacts ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE management_shadow_log ALTER COLUMN simulation_id DROP NOT NULL;
ALTER TABLE agent_relationships ALTER COLUMN simulation_id DROP NOT NULL;

-- ── 3. Drop columns from newly scoped tables ──────────────────

ALTER TABLE world_chunks DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE world_events DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE expansion_proposals DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE self_modification_proposals DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE challenges DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE revenue_events DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE conversation_selection_log DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE interrupt_log DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE energy_change_log DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE agent_transactions DROP COLUMN IF EXISTS simulation_id;

-- agent_internal_state: drop column and restore PK
DROP INDEX IF EXISTS uq_agent_state_agent_sim;
ALTER TABLE agent_internal_state DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE agent_internal_state ADD PRIMARY KEY (agent_id);

-- agent_accounts: drop column and restore PK
DROP INDEX IF EXISTS uq_agent_accounts_agent_sim;
ALTER TABLE agent_accounts DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE agent_accounts ADD PRIMARY KEY (agent_id);

-- ── 4. Drop indexes from new tables ───────────────────────────

DROP INDEX IF EXISTS idx_world_chunks_simulation;
DROP INDEX IF EXISTS idx_world_events_simulation;
DROP INDEX IF EXISTS idx_expansion_proposals_simulation;
DROP INDEX IF EXISTS idx_agent_transactions_simulation;
DROP INDEX IF EXISTS idx_self_mod_proposals_simulation;
DROP INDEX IF EXISTS idx_challenges_simulation;
DROP INDEX IF EXISTS idx_revenue_events_simulation;
DROP INDEX IF EXISTS idx_conv_selection_simulation;
DROP INDEX IF EXISTS idx_interrupt_log_simulation;
DROP INDEX IF EXISTS idx_energy_change_simulation;

-- ── 5. Remove live simulation row and is_live column ──────────

DELETE FROM simulations WHERE id = '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_simulations_live;
ALTER TABLE simulations DROP COLUMN IF EXISTS is_live;
