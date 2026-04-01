-- Extensions required by livestream-to-agi
-- Runs on first PostgreSQL boot via /docker-entrypoint-initdb.d/
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Langfuse requires its own database
CREATE DATABASE langfuse OWNER agi;
