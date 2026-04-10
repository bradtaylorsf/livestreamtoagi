-- Rollback migration 034: Remove simulation_id from memory tables.

BEGIN;

-- ── agent_goals ──────────────────────────────────────────────────
DROP INDEX IF EXISTS idx_goals_simulation;
ALTER TABLE agent_goals DROP COLUMN IF EXISTS simulation_id;

-- ── journal_entries ──────────────────────────────────────────────
DROP INDEX IF EXISTS idx_journal_simulation;
ALTER TABLE journal_entries DROP COLUMN IF EXISTS simulation_id;

-- ── conversation_buffer ──────────────────────────────────────────
DROP INDEX IF EXISTS idx_convbuf_simulation;
ALTER TABLE conversation_buffer DROP COLUMN IF EXISTS simulation_id;

-- ── recall_memory ────────────────────────────────────────────────
DROP INDEX IF EXISTS idx_recall_simulation;
ALTER TABLE recall_memory DROP COLUMN IF EXISTS simulation_id;

-- ── core_memory_history ──────────────────────────────────────────
DROP INDEX IF EXISTS idx_cmh_simulation;
ALTER TABLE core_memory_history DROP COLUMN IF EXISTS simulation_id;

-- ── core_memory ──────────────────────────────────────────────────
DROP INDEX IF EXISTS uq_core_memory_agent_sim;
ALTER TABLE core_memory DROP COLUMN IF EXISTS simulation_id;

-- Restore original PK (only safe if no duplicate agent_ids exist,
-- which is guaranteed since simulation_id was always NULL for live data).
ALTER TABLE core_memory ADD PRIMARY KEY (agent_id);

COMMIT;
