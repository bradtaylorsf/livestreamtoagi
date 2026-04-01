-- 001_initial_schema.down.sql
-- Drops all 15 tables in reverse dependency order.
-- Does NOT drop extensions (vector, pg_trgm) — they are shared and managed by db/init.sql.

DROP TABLE IF EXISTS interrupt_log;
DROP TABLE IF EXISTS conversation_selection_log;
DROP TABLE IF EXISTS expansion_proposals;
DROP TABLE IF EXISTS conversation_buffer;
DROP TABLE IF EXISTS recall_memory;
DROP TABLE IF EXISTS core_memory_history;
DROP TABLE IF EXISTS core_memory;
DROP TABLE IF EXISTS cost_events;
DROP TABLE IF EXISTS revenue_events;
DROP TABLE IF EXISTS challenges;
DROP TABLE IF EXISTS world_events;
DROP TABLE IF EXISTS world_chunks;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS transcripts;
DROP TABLE IF EXISTS agents;
