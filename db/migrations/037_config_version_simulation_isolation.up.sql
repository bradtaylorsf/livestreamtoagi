-- Migration 037: Add simulation_id to config versioning tables.
--
-- Tables missed in migrations 035/036: agent_prompt_versions,
-- conversation_param_versions, active_config.

BEGIN;

-- 1. Add simulation_id columns

ALTER TABLE agent_prompt_versions
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);

ALTER TABLE conversation_param_versions
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);

ALTER TABLE active_config
    ADD COLUMN IF NOT EXISTS simulation_id UUID REFERENCES simulations(id);

-- 2. Backfill existing rows to live simulation

UPDATE agent_prompt_versions SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE conversation_param_versions SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;
UPDATE active_config SET simulation_id = '00000000-0000-0000-0000-000000000001' WHERE simulation_id IS NULL;

-- 3. Enforce NOT NULL

ALTER TABLE agent_prompt_versions ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE conversation_param_versions ALTER COLUMN simulation_id SET NOT NULL;
ALTER TABLE active_config ALTER COLUMN simulation_id SET NOT NULL;

-- 4. Update unique constraints

-- agent_prompt_versions: version is unique per agent PER simulation
ALTER TABLE agent_prompt_versions DROP CONSTRAINT IF EXISTS agent_prompt_versions_agent_id_version_key;
DROP INDEX IF EXISTS uq_apv_agent_version_sim;
CREATE UNIQUE INDEX uq_apv_agent_version_sim
    ON agent_prompt_versions(agent_id, version, simulation_id);

-- conversation_param_versions: version is unique PER simulation
ALTER TABLE conversation_param_versions DROP CONSTRAINT IF EXISTS conversation_param_versions_version_key;
DROP INDEX IF EXISTS uq_cpv_version_sim;
CREATE UNIQUE INDEX uq_cpv_version_sim
    ON conversation_param_versions(version, simulation_id);

-- active_config: one active config per agent PER simulation
ALTER TABLE active_config DROP CONSTRAINT IF EXISTS active_config_pkey;
DROP INDEX IF EXISTS uq_active_config_agent_sim;
CREATE UNIQUE INDEX uq_active_config_agent_sim
    ON active_config(agent_id, simulation_id);

-- 5. Add simulation_id indexes

CREATE INDEX IF NOT EXISTS idx_apv_simulation ON agent_prompt_versions(simulation_id);
CREATE INDEX IF NOT EXISTS idx_cpv_simulation ON conversation_param_versions(simulation_id);
CREATE INDEX IF NOT EXISTS idx_active_config_simulation ON active_config(simulation_id);

COMMIT;
