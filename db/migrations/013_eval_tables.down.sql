-- Reverse migration 013: Drop eval tables (order respects FK constraints).

DROP TABLE IF EXISTS eval_results;
DROP TABLE IF EXISTS eval_runs;
