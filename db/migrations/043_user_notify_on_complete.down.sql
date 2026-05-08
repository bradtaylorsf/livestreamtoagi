-- 043_user_notify_on_complete.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_users_unsubscribe_token;
ALTER TABLE users DROP COLUMN IF EXISTS unsubscribe_token;
ALTER TABLE users DROP COLUMN IF EXISTS notify_on_complete;

COMMIT;
