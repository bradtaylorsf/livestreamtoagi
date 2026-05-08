-- 047_simulation_youtube_publish.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_simulations_youtube_publish_status;

ALTER TABLE simulations
    DROP CONSTRAINT IF EXISTS simulations_youtube_publish_status_check;

ALTER TABLE simulations DROP COLUMN IF EXISTS youtube_failure_reason;
ALTER TABLE simulations DROP COLUMN IF EXISTS youtube_publish_attempts;
ALTER TABLE simulations DROP COLUMN IF EXISTS youtube_published_at;
ALTER TABLE simulations DROP COLUMN IF EXISTS youtube_publish_status;
ALTER TABLE simulations DROP COLUMN IF EXISTS youtube_url;
ALTER TABLE simulations DROP COLUMN IF EXISTS publish_to_youtube;

COMMIT;
