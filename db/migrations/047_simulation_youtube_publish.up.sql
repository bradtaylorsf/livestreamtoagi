-- 047_simulation_youtube_publish.up.sql
-- Track YouTube auto-publish state for completed simulation videos.
-- Opt-in per simulation via publish_to_youtube; the worker stamps
-- youtube_publish_status as it claims, uploads, and finalizes.

BEGIN;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS publish_to_youtube BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS youtube_url TEXT;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS youtube_publish_status TEXT;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS youtube_published_at TIMESTAMPTZ;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS youtube_publish_attempts INT NOT NULL DEFAULT 0;

ALTER TABLE simulations
    ADD COLUMN IF NOT EXISTS youtube_failure_reason TEXT;

ALTER TABLE simulations
    DROP CONSTRAINT IF EXISTS simulations_youtube_publish_status_check;

ALTER TABLE simulations
    ADD CONSTRAINT simulations_youtube_publish_status_check
    CHECK (
        youtube_publish_status IS NULL
        OR youtube_publish_status IN ('pending', 'publishing', 'done', 'failed')
    );

CREATE INDEX IF NOT EXISTS idx_simulations_youtube_publish_status
    ON simulations (youtube_publish_status)
    WHERE youtube_publish_status IS NOT NULL;

COMMIT;
