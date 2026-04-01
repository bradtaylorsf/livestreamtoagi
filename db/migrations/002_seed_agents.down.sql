-- 002_seed_agents.down.sql
-- Removes only the seeded agent rows.

DELETE FROM agents
WHERE id IN ('vera', 'rex', 'aurora', 'pixel', 'fork', 'sentinel', 'grok', 'overseer', 'alpha');
