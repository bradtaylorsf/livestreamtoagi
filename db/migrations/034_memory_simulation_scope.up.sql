-- Migration 034: Add simulation_id to memory tables for per-simulation isolation.
-- NULL simulation_id = live/production mode (global memory).
-- Non-null = scoped to a specific simulation run.

BEGIN;

-- ── core_memory ──────────────────────────────────────────────────
-- Current PK is (agent_id). Must change to composite unique index
-- since simulation_id is nullable and PG doesn't allow nullable PKs.

ALTER TABLE core_memory DROP CONSTRAINT core_memory_pkey;

ALTER TABLE core_memory
    ADD COLUMN simulation_id UUID REFERENCES simulations(id);

-- Unique constraint using COALESCE so NULL simulation_id is treated
-- as a sentinel value for uniqueness purposes.
CREATE UNIQUE INDEX uq_core_memory_agent_sim
    ON core_memory (agent_id, COALESCE(simulation_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- Keep agent_id NOT NULL (was implicitly NOT NULL as PK)
ALTER TABLE core_memory ALTER COLUMN agent_id SET NOT NULL;

-- ── core_memory_history ──────────────────────────────────────────

ALTER TABLE core_memory_history
    ADD COLUMN simulation_id UUID REFERENCES simulations(id);

CREATE INDEX idx_cmh_simulation
    ON core_memory_history(simulation_id) WHERE simulation_id IS NOT NULL;

-- ── recall_memory ────────────────────────────────────────────────

ALTER TABLE recall_memory
    ADD COLUMN simulation_id UUID REFERENCES simulations(id);

CREATE INDEX idx_recall_simulation
    ON recall_memory(simulation_id) WHERE simulation_id IS NOT NULL;

-- ── conversation_buffer ──────────────────────────────────────────

ALTER TABLE conversation_buffer
    ADD COLUMN simulation_id UUID REFERENCES simulations(id);

CREATE INDEX idx_convbuf_simulation
    ON conversation_buffer(simulation_id) WHERE simulation_id IS NOT NULL;

-- ── journal_entries ──────────────────────────────────────────────

ALTER TABLE journal_entries
    ADD COLUMN simulation_id UUID REFERENCES simulations(id);

CREATE INDEX idx_journal_simulation
    ON journal_entries(simulation_id) WHERE simulation_id IS NOT NULL;

-- ── agent_goals ──────────────────────────────────────────────────

ALTER TABLE agent_goals
    ADD COLUMN simulation_id UUID REFERENCES simulations(id);

CREATE INDEX idx_goals_simulation
    ON agent_goals(simulation_id) WHERE simulation_id IS NOT NULL;

COMMIT;
