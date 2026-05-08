-- 044_simulation_video.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_simulations_video_render_status;

ALTER TABLE simulations
    DROP CONSTRAINT IF EXISTS simulations_video_render_status_check;

ALTER TABLE simulations DROP COLUMN IF EXISTS video_rendered_at;
ALTER TABLE simulations DROP COLUMN IF EXISTS video_render_status;
ALTER TABLE simulations DROP COLUMN IF EXISTS video_url;

COMMIT;
