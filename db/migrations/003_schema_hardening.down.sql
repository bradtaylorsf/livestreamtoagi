-- 003_schema_hardening.down.sql
-- Revert schema hardening changes.

-- Remove CHECK constraints
ALTER TABLE agents DROP CONSTRAINT IF EXISTS chk_agents_status;
ALTER TABLE challenges DROP CONSTRAINT IF EXISTS chk_challenges_status;
ALTER TABLE expansion_proposals DROP CONSTRAINT IF EXISTS chk_proposals_status;

-- Remove NOT NULL constraints
ALTER TABLE cost_events ALTER COLUMN amount DROP NOT NULL;
ALTER TABLE cost_events ALTER COLUMN cost_type DROP NOT NULL;
ALTER TABLE revenue_events ALTER COLUMN amount DROP NOT NULL;
ALTER TABLE revenue_events ALTER COLUMN source DROP NOT NULL;
ALTER TABLE world_events ALTER COLUMN event_type DROP NOT NULL;
ALTER TABLE world_events ALTER COLUMN description DROP NOT NULL;

-- Revert TIMESTAMPTZ → TIMESTAMP
ALTER TABLE agents ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE transcripts ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE world_chunks ALTER COLUMN built_date TYPE TIMESTAMP;
ALTER TABLE world_events ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE challenges ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE challenges ALTER COLUMN completed_at TYPE TIMESTAMP;
ALTER TABLE revenue_events ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE cost_events ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE core_memory ALTER COLUMN last_updated TYPE TIMESTAMP;
ALTER TABLE core_memory_history ALTER COLUMN changed_at TYPE TIMESTAMP;
ALTER TABLE recall_memory ALTER COLUMN timestamp TYPE TIMESTAMP;
ALTER TABLE conversation_buffer ALTER COLUMN created_at TYPE TIMESTAMP;
ALTER TABLE expansion_proposals ALTER COLUMN created_at TYPE TIMESTAMP;
