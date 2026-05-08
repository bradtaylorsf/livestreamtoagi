-- 044_simulation_video.up.sql
-- Track render-to-MP4 state for each simulation. The render is triggered
-- by the orchestrator on completion and is intentionally idempotent: the
-- worker uses video_render_status as a lock-style state field.

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS video_url TEXT;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS video_render_status TEXT;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS video_rendered_at TIMESTAMPTZ;

ALTER TABLE simulations
    DROP CONSTRAINT IF EXISTS simulations_video_render_status_check;

ALTER TABLE simulations
    ADD CONSTRAINT simulations_video_render_status_check
    CHECK (
        video_render_status IS NULL
        OR video_render_status IN ('pending', 'rendering', 'done', 'failed', 'skipped')
    );

CREATE INDEX IF NOT EXISTS idx_simulations_video_render_status
    ON simulations (video_render_status)
    WHERE video_render_status IS NOT NULL;

COMMIT;
