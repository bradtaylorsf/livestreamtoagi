"""Repositories for public user accounts and magic-link tokens."""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import TYPE_CHECKING

from core.models import User

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from core.database import Database


def _new_unsubscribe_token() -> str:
    return secrets.token_urlsafe(24)


def _row_to_user(row: dict) -> User:
    return User(**dict(row))


class UserRepo:
    """CRUD for the ``users`` table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        row = await self.db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return _row_to_user(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        row = await self.db.fetchrow(
            "SELECT * FROM users WHERE lower(email) = lower($1)", email
        )
        return _row_to_user(row) if row else None

    async def upsert_on_login(self, email: str, *, login_at: datetime) -> User:
        """Insert a new user (or update last_login_at on an existing one).

        Generates an unsubscribe token on first login and back-fills it for
        legacy rows that pre-date migration 043.
        """
        row = await self.db.fetchrow(
            """INSERT INTO users (email, last_login_at, unsubscribe_token)
               VALUES ($1, $2, $3)
               ON CONFLICT (lower(email)) DO UPDATE
                 SET last_login_at = EXCLUDED.last_login_at,
                     unsubscribe_token = COALESCE(
                         users.unsubscribe_token,
                         EXCLUDED.unsubscribe_token
                     )
               RETURNING *""",
            email,
            login_at,
            _new_unsubscribe_token(),
        )
        return _row_to_user(row)

    async def get_by_unsubscribe_token(self, token: str) -> User | None:
        row = await self.db.fetchrow(
            "SELECT * FROM users WHERE unsubscribe_token = $1",
            token,
        )
        return _row_to_user(row) if row else None

    async def set_notify_on_complete(
        self,
        user_id: uuid.UUID,
        *,
        enabled: bool,
    ) -> User | None:
        row = await self.db.fetchrow(
            """UPDATE users SET notify_on_complete = $1
               WHERE id = $2
               RETURNING *""",
            enabled,
            user_id,
        )
        return _row_to_user(row) if row else None

    async def ensure_unsubscribe_token(self, user_id: uuid.UUID) -> str | None:
        """Back-fill the unsubscribe token for users predating migration 043."""
        row = await self.db.fetchrow(
            """UPDATE users
               SET unsubscribe_token = COALESCE(unsubscribe_token, $1)
               WHERE id = $2
               RETURNING unsubscribe_token""",
            _new_unsubscribe_token(),
            user_id,
        )
        return row["unsubscribe_token"] if row else None

    async def increment_sims_and_cost(
        self,
        user_id: uuid.UUID,
        *,
        cost_delta: Decimal,
    ) -> User | None:
        row = await self.db.fetchrow(
            """UPDATE users
               SET simulations_submitted = simulations_submitted + 1,
                   total_cost_spent = total_cost_spent + $1
               WHERE id = $2
               RETURNING *""",
            cost_delta,
            user_id,
        )
        return _row_to_user(row) if row else None


class MagicLinkTokenRepo:
    """Single-use magic-link tokens; we store sha256(token) as the PK."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        token_hash: str,
        email: str,
        *,
        expires_at: datetime,
    ) -> None:
        await self.db.execute(
            """INSERT INTO magic_link_tokens (token_hash, email, expires_at)
               VALUES ($1, $2, $3)""",
            token_hash,
            email,
            expires_at,
        )

    async def consume(self, token_hash: str) -> str | None:
        """Atomically mark a token as used and return its email if valid.

        Returns None if the token is unknown, already used, or expired.
        """
        row = await self.db.fetchrow(
            """UPDATE magic_link_tokens
               SET used_at = now()
               WHERE token_hash = $1
                 AND used_at IS NULL
                 AND expires_at > now()
               RETURNING email""",
            token_hash,
        )
        return row["email"] if row else None
