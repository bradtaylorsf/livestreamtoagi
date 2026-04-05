-- Rename overseer_shadow_log table to management_shadow_log (idempotent)
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='overseer_shadow_log') THEN
        ALTER TABLE overseer_shadow_log RENAME TO management_shadow_log;
    END IF;
END $$;

-- Rename the column in simulations table (idempotent)
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='simulations' AND column_name='total_overseer_flags'
    ) THEN
        ALTER TABLE simulations RENAME COLUMN total_overseer_flags TO total_management_flags;
    END IF;
END $$;

-- Insert the new 'management' agent row (copy from 'overseer')
INSERT INTO agents (id, display_name, model_conversation, model_building, voice_id, status)
SELECT 'management', 'Management', model_conversation, model_building, voice_id, status
FROM agents WHERE id = 'overseer'
ON CONFLICT (id) DO NOTHING;

-- Update agent_id references in all dependent tables
UPDATE core_memory SET agent_id = 'management' WHERE agent_id = 'overseer';
UPDATE core_memory_history SET agent_id = 'management' WHERE agent_id = 'overseer';
UPDATE recall_memory SET agent_id = 'management' WHERE agent_id = 'overseer';
UPDATE journal_entries SET agent_id = 'management' WHERE agent_id = 'overseer';
UPDATE self_modification_proposals SET agent_id = 'management' WHERE agent_id = 'overseer';
UPDATE artifacts SET agent_id = 'management' WHERE agent_id = 'overseer';
UPDATE cost_events SET agent_id = 'management' WHERE agent_id = 'overseer';

-- Update shadow log if it exists (table may have been renamed above)
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='management_shadow_log') THEN
        EXECUTE 'UPDATE management_shadow_log SET agent_id = ''management'' WHERE agent_id = ''overseer''';
    END IF;
END $$;

-- Delete the old 'overseer' agent row (all FKs now point to 'management')
DELETE FROM agents WHERE id = 'overseer';
