-- Down: drop the research fields added in 038.

BEGIN;

ALTER TABLE simulations
    DROP COLUMN IF EXISTS hypothesis,
    DROP COLUMN IF EXISTS outcomes,
    DROP COLUMN IF EXISTS learnings;

COMMIT;
