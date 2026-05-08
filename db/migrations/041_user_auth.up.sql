-- 041_user_auth.up.sql
-- Public user accounts authenticated via emailed magic links.
-- Separate from admin auth (which uses ADMIN_PASSWORD/ADMIN_JWT_SECRET).

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    simulations_submitted INT NOT NULL DEFAULT 0,
    total_cost_spent NUMERIC(10,4) NOT NULL DEFAULT 0
);

-- Case-insensitive uniqueness without depending on the citext extension.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
    ON users (lower(email));

-- One-time magic-link tokens. We store sha256(token) so a DB compromise
-- does not yield usable links. Single-use is enforced by the consume()
-- repo method (atomic UPDATE ... WHERE used_at IS NULL).
CREATE TABLE IF NOT EXISTS magic_link_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_magic_link_tokens_expires
    ON magic_link_tokens (expires_at);
