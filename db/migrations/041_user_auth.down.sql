-- 041_user_auth.down.sql

DROP INDEX IF EXISTS idx_magic_link_tokens_expires;
DROP TABLE IF EXISTS magic_link_tokens;
DROP INDEX IF EXISTS idx_users_email_lower;
DROP TABLE IF EXISTS users;
