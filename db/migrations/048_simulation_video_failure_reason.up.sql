-- 048_simulation_video_failure_reason.up.sql
-- Persist render failure/skipped detail so the public workspace can explain
-- why a local MP4 is not available.

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS video_render_failure_reason TEXT;

COMMIT;
