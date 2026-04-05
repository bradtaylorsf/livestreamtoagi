-- Revert: rename management_shadow_log back to overseer_shadow_log
ALTER TABLE management_shadow_log RENAME TO overseer_shadow_log;

-- Revert column rename
ALTER TABLE simulations RENAME COLUMN total_management_flags TO total_overseer_flags;

-- Re-insert the 'overseer' agent row
INSERT INTO agents (id, display_name, model_conversation, model_building, voice_id, status)
SELECT 'overseer', 'The Overseer', model_conversation, model_building, voice_id, status
FROM agents WHERE id = 'management'
ON CONFLICT (id) DO NOTHING;

-- Revert agent_id references in all dependent tables
UPDATE core_memory SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE core_memory_history SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE recall_memory SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE journal_entries SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE self_modification_proposals SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE overseer_shadow_log SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE artifacts SET agent_id = 'overseer' WHERE agent_id = 'management';
UPDATE cost_events SET agent_id = 'overseer' WHERE agent_id = 'management';

-- Delete the 'management' agent row
DELETE FROM agents WHERE id = 'management';
