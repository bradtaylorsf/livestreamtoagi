-- 003_schema_hardening.up.sql
-- Standardize timestamps to TIMESTAMPTZ, add NOT NULL and CHECK constraints.

-- ============================================================
-- 1. Standardize TIMESTAMP → TIMESTAMPTZ
-- ============================================================

ALTER TABLE agents ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE transcripts ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE world_chunks ALTER COLUMN built_date TYPE TIMESTAMPTZ;
ALTER TABLE world_events ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE challenges ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE challenges ALTER COLUMN completed_at TYPE TIMESTAMPTZ;
ALTER TABLE revenue_events ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE cost_events ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE core_memory ALTER COLUMN last_updated TYPE TIMESTAMPTZ;
ALTER TABLE core_memory_history ALTER COLUMN changed_at TYPE TIMESTAMPTZ;
ALTER TABLE recall_memory ALTER COLUMN timestamp TYPE TIMESTAMPTZ;
ALTER TABLE conversation_buffer ALTER COLUMN created_at TYPE TIMESTAMPTZ;
ALTER TABLE expansion_proposals ALTER COLUMN created_at TYPE TIMESTAMPTZ;

-- ============================================================
-- 2. Add NOT NULL constraints on required columns
-- ============================================================

ALTER TABLE cost_events ALTER COLUMN amount SET NOT NULL;
ALTER TABLE cost_events ALTER COLUMN cost_type SET NOT NULL;
ALTER TABLE revenue_events ALTER COLUMN amount SET NOT NULL;
ALTER TABLE revenue_events ALTER COLUMN source SET NOT NULL;
ALTER TABLE world_events ALTER COLUMN event_type SET NOT NULL;
ALTER TABLE world_events ALTER COLUMN description SET NOT NULL;

-- ============================================================
-- 3. Add CHECK constraints on status columns
-- ============================================================

ALTER TABLE agents ADD CONSTRAINT chk_agents_status
    CHECK (status IN ('active', 'sleeping', 'paused', 'muted'));

ALTER TABLE challenges ADD CONSTRAINT chk_challenges_status
    CHECK (status IN ('pending', 'active', 'completed', 'failed'));

ALTER TABLE expansion_proposals ADD CONSTRAINT chk_proposals_status
    CHECK (status IN ('proposed', 'approved', 'rejected', 'built'));
