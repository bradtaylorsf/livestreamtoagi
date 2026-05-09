-- 048_simulation_video_failure_reason.down.sql

BEGIN;

ALTER TABLE simulations DROP COLUMN IF EXISTS video_render_failure_reason;

COMMIT;
