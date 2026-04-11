BEGIN;

ALTER TABLE agent_prompt_versions DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE conversation_param_versions DROP COLUMN IF EXISTS simulation_id;
ALTER TABLE active_config DROP COLUMN IF EXISTS simulation_id;

COMMIT;
