-- 043_user_notify_on_complete.up.sql
-- Add per-user opt-out for completion emails plus a stable unsubscribe
-- token used in email footer links. Token is a random URL-safe string
-- (generated app-side) — never the user id, so revealing one doesn't
-- leak account identifiers.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS notify_on_complete BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS unsubscribe_token TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_unsubscribe_token
    ON users (unsubscribe_token)
    WHERE unsubscribe_token IS NOT NULL;

COMMIT;
