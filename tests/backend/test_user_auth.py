"""Tests for the public user auth flow (magic links, /me, logout)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.auth import user_auth_api
from core.auth.auth_routes import _hash_token, _safe_relative_redirect
from core.auth.dependencies import (
    USER_SESSION_COOKIE,
    _check_email_rate_limit,
    _validate_user_jwt,
    is_valid_email,
)
from core.models import User

# ── Helpers ───────────────────────────────────────────────────


def _make_user(**overrides) -> User:
    defaults: dict = {
        "id": uuid.uuid4(),
        "email": "alice@example.com",
        "created_at": datetime.now(UTC),
        "last_login_at": datetime.now(UTC),
        "simulations_submitted": 0,
        "total_cost_spent": Decimal("0"),
    }
    defaults.update(overrides)
    return User(**defaults)


@pytest.fixture
def auth_app():
    """Build a minimal FastAPI app exposing only /api/auth with mocked services."""
    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(return_value=None)
    mock_db.execute = AsyncMock(return_value="INSERT 0 1")

    mock_redis = MagicMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis

    app = FastAPI()
    app.include_router(user_auth_api)
    app.state.services = mock_services

    env = {
        "AUTH_JWT_SECRET": "test-user-jwt-secret",
        "EMAIL_PROVIDER": "console",
        "EMAIL_FROM": "no-reply@test.dev",
        "PUBLIC_BASE_URL": "http://localhost:8000",
    }
    with patch.dict(os.environ, env):
        with TestClient(app) as client:
            yield client, mock_db, mock_redis


# ── Email validation & JWT helpers ────────────────────────────


class TestEmailValidation:
    @pytest.mark.parametrize(
        "email,expected",
        [
            ("alice@example.com", True),
            ("a@b.co", True),
            ("not-an-email", False),
            ("foo@", False),
            ("@bar.com", False),
            ("foo@bar", False),
            ("", False),
            ("foo bar@baz.com", False),
        ],
    )
    def test_is_valid_email(self, email: str, expected: bool) -> None:
        assert is_valid_email(email) is expected


class TestUserJWT:
    def test_valid(self) -> None:
        secret = "test-secret"
        uid = str(uuid.uuid4())
        token = jwt.encode(
            {"sub": uid, "exp": datetime.now(UTC) + timedelta(hours=1)},
            secret,
            algorithm="HS256",
        )
        with patch.dict(os.environ, {"AUTH_JWT_SECRET": secret}):
            assert _validate_user_jwt(token) == uid

    def test_expired(self) -> None:
        secret = "test-secret"
        token = jwt.encode(
            {"sub": "u", "exp": datetime.now(UTC) - timedelta(hours=1)},
            secret,
            algorithm="HS256",
        )
        with patch.dict(os.environ, {"AUTH_JWT_SECRET": secret}):
            assert _validate_user_jwt(token) is None

    def test_no_secret(self) -> None:
        with patch.dict(os.environ, {"AUTH_JWT_SECRET": ""}):
            assert _validate_user_jwt("anything") is None


# ── Rate limit ────────────────────────────────────────────────


class TestEmailRateLimit:
    async def test_allows_within_limit(self) -> None:
        mock_redis = MagicMock()
        mock_redis.incr = AsyncMock(return_value=3)
        mock_redis.expire = AsyncMock()

        mock_request = MagicMock()
        mock_request.app.state.services.redis = mock_redis

        await _check_email_rate_limit(mock_request, "x@example.com")

    async def test_blocks_over_limit(self) -> None:
        mock_redis = MagicMock()
        mock_redis.incr = AsyncMock(return_value=6)
        mock_redis.expire = AsyncMock()

        mock_request = MagicMock()
        mock_request.app.state.services.redis = mock_redis

        with pytest.raises(HTTPException) as exc_info:
            await _check_email_rate_limit(mock_request, "x@example.com")
        assert exc_info.value.status_code == 429

    async def test_graceful_without_redis(self) -> None:
        mock_request = MagicMock()
        mock_request.app.state.services.redis = None
        await _check_email_rate_limit(mock_request, "x@example.com")


# ── /api/auth/magic-link ──────────────────────────────────────


class TestMagicLinkRequest:
    def test_happy_path_creates_token(self, auth_app) -> None:
        client, mock_db, mock_redis = auth_app
        # console provider is the default — no actual email sent
        resp = client.post(
            "/api/auth/magic-link", json={"email": "alice@example.com"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        # Token row inserted
        assert mock_db.execute.called
        sql, *args = mock_db.execute.call_args.args
        assert "INSERT INTO magic_link_tokens" in sql
        # email arg is normalized to lowercase
        assert args[1] == "alice@example.com"

    def test_invalid_email_returns_400(self, auth_app) -> None:
        client, *_ = auth_app
        resp = client.post("/api/auth/magic-link", json={"email": "not-an-email"})
        assert resp.status_code == 400

    def test_rate_limit_blocks_after_5(self, auth_app) -> None:
        client, _, mock_redis = auth_app
        # Simulate 6th request in window
        mock_redis.incr = AsyncMock(return_value=6)
        resp = client.post(
            "/api/auth/magic-link", json={"email": "alice@example.com"}
        )
        assert resp.status_code == 429

    def test_console_provider_writes_jsonl(self, auth_app, tmp_path) -> None:
        """EMAIL_PROVIDER=console should append a JSONL record with the magic link.

        Repros the QA pain point from issue #466 where uvicorn's log config
        swallowed the application logger and the plaintext token had no
        capturable side-channel.
        """
        client, *_ = auth_app
        log_path = tmp_path / "emails.jsonl"
        # Don't set EMAIL_CONSOLE_REDIS_STREAM -- we don't want this test
        # to depend on a running Redis.
        with patch.dict(os.environ, {"EMAIL_CONSOLE_LOG": str(log_path)}):
            resp = client.post(
                "/api/auth/magic-link", json={"email": "alice@example.com"}
            )
        assert resp.status_code == 200
        assert log_path.exists(), "console log file was not created"
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert lines, "console log file is empty"
        record = json.loads(lines[-1])
        assert record["to"] == "alice@example.com"
        assert "sign-in" in record["subject"].lower()
        assert isinstance(record["links"], list) and record["links"], (
            "expected at least one extracted magic link in 'links'"
        )
        link = record["links"][0]
        assert link.startswith("http")
        assert "/api/auth/verify?token=" in link

    def test_console_log_empty_env_falls_back_to_default(
        self, auth_app, tmp_path, monkeypatch
    ) -> None:
        """Blank EMAIL_CONSOLE_LOG (the .env.example default) must still capture.

        Regression: `os.environ.get("EMAIL_CONSOLE_LOG", default)` returns "" --
        not the default -- when the var is set-but-empty. `Path("")` then
        resolves to "." and the OSError is swallowed, killing capture.
        """
        client, *_ = auth_app
        # Redirect the module-level default into tmp_path so we don't pollute
        # /tmp/livestream-agi-emails.jsonl on the dev machine.
        from core.auth import email as email_mod

        fake_default = tmp_path / "fallback.jsonl"
        monkeypatch.setattr(email_mod, "DEFAULT_CONSOLE_LOG_PATH", str(fake_default))
        with patch.dict(os.environ, {"EMAIL_CONSOLE_LOG": ""}):
            resp = client.post(
                "/api/auth/magic-link", json={"email": "alice@example.com"}
            )
        assert resp.status_code == 200
        assert fake_default.exists(), (
            "blank EMAIL_CONSOLE_LOG should fall back to DEFAULT_CONSOLE_LOG_PATH"
        )
        assert fake_default.read_text(encoding="utf-8").strip(), (
            "fallback log file is empty"
        )

    def test_safe_next_path_is_included_in_email_link(self, auth_app) -> None:
        client, *_ = auth_app
        send_mock = AsyncMock()
        with patch("core.auth.auth_routes.send_email", send_mock):
            resp = client.post(
                "/api/auth/magic-link",
                json={
                    "email": "alice@example.com",
                    "next": "/simulations/new?scenario=lab_rivals.yaml",
                },
            )

        assert resp.status_code == 200
        body_text = send_mock.await_args.kwargs["body_text"]
        assert "next=%2Fsimulations%2Fnew%3Fscenario%3Dlab_rivals.yaml" in body_text

    def test_unsafe_next_path_is_not_included_in_email_link(self, auth_app) -> None:
        client, *_ = auth_app
        send_mock = AsyncMock()
        with patch("core.auth.auth_routes.send_email", send_mock):
            resp = client.post(
                "/api/auth/magic-link",
                json={
                    "email": "alice@example.com",
                    "next": "https://evil.test/phish",
                },
            )

        assert resp.status_code == 200
        body_text = send_mock.await_args.kwargs["body_text"]
        assert "next=" not in body_text


class TestSafeRelativeRedirect:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/simulations/new?scenario=lab_rivals.yaml", "/simulations/new?scenario=lab_rivals.yaml"),
            ("/simulations#draft", "/simulations#draft"),
            ("https://evil.test/phish", None),
            ("//evil.test/phish", None),
            ("simulations/new", None),
            ("/\\evil.test", None),
        ],
    )
    def test_allows_only_same_site_relative_paths(
        self,
        raw: str,
        expected: str | None,
    ) -> None:
        assert _safe_relative_redirect(raw) == expected


# ── /api/auth/verify ──────────────────────────────────────────


class TestVerifyMagicLink:
    def test_happy_path_sets_cookie_and_redirects(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        new_user_id = uuid.uuid4()

        # First fetchrow: token consume → returns email
        # Second fetchrow: upsert_on_login → returns user row
        mock_db.fetchrow = AsyncMock(
            side_effect=[
                {"email": "alice@example.com"},
                {
                    "id": new_user_id,
                    "email": "alice@example.com",
                    "created_at": datetime.now(UTC),
                    "last_login_at": datetime.now(UTC),
                    "simulations_submitted": 0,
                    "total_cost_spent": Decimal("0"),
                },
            ]
        )

        resp = client.get(
            "/api/auth/verify",
            params={"token": "rawtoken"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/simulations"
        assert USER_SESSION_COOKIE in resp.cookies

    def test_safe_next_redirect_is_honored(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        new_user_id = uuid.uuid4()

        mock_db.fetchrow = AsyncMock(
            side_effect=[
                {"email": "alice@example.com"},
                {
                    "id": new_user_id,
                    "email": "alice@example.com",
                    "created_at": datetime.now(UTC),
                    "last_login_at": datetime.now(UTC),
                    "simulations_submitted": 0,
                    "total_cost_spent": Decimal("0"),
                },
            ]
        )

        resp = client.get(
            "/api/auth/verify",
            params={
                "token": "rawtoken",
                "next": "/simulations/new?scenario=lab_rivals.yaml",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/simulations/new?scenario=lab_rivals.yaml"
        assert USER_SESSION_COOKIE in resp.cookies

    def test_unsafe_next_redirect_falls_back(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        new_user_id = uuid.uuid4()

        mock_db.fetchrow = AsyncMock(
            side_effect=[
                {"email": "alice@example.com"},
                {
                    "id": new_user_id,
                    "email": "alice@example.com",
                    "created_at": datetime.now(UTC),
                    "last_login_at": datetime.now(UTC),
                    "simulations_submitted": 0,
                    "total_cost_spent": Decimal("0"),
                },
            ]
        )

        resp = client.get(
            "/api/auth/verify",
            params={"token": "rawtoken", "next": "//evil.test/phish"},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/simulations"
        assert USER_SESSION_COOKIE in resp.cookies

    def test_invalid_token_returns_400(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        resp = client.get(
            "/api/auth/verify",
            params={"token": "bogus"},
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_consume_uses_hashed_token(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        client.get(
            "/api/auth/verify",
            params={"token": "rawtoken"},
            follow_redirects=False,
        )
        # First fetchrow call is the token consume
        sql, *args = mock_db.fetchrow.call_args_list[0].args
        assert "UPDATE magic_link_tokens" in sql
        assert args[0] == _hash_token("rawtoken")

    def test_no_jwt_secret_returns_503(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        mock_db.fetchrow = AsyncMock(
            side_effect=[
                {"email": "alice@example.com"},
                {
                    "id": uuid.uuid4(),
                    "email": "alice@example.com",
                    "created_at": datetime.now(UTC),
                    "last_login_at": datetime.now(UTC),
                    "simulations_submitted": 0,
                    "total_cost_spent": Decimal("0"),
                },
            ]
        )
        with patch.dict(os.environ, {"AUTH_JWT_SECRET": ""}):
            resp = client.get(
                "/api/auth/verify",
                params={"token": "rawtoken"},
                follow_redirects=False,
            )
        assert resp.status_code == 503


# ── /api/auth/logout & /api/auth/me ──────────────────────────


class TestLogoutAndMe:
    def test_logout_clears_cookie(self, auth_app) -> None:
        client, *_ = auth_app
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        # The set-cookie header should clear the user_session cookie.
        cookie_headers = resp.headers.get_list("set-cookie")
        assert any(USER_SESSION_COOKIE in h for h in cookie_headers)

    def test_me_without_cookie_returns_401(self, auth_app) -> None:
        client, *_ = auth_app
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_cookie_returns_user(self, auth_app) -> None:
        client, mock_db, _ = auth_app
        user = _make_user()
        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at,
                "last_login_at": user.last_login_at,
                "simulations_submitted": user.simulations_submitted,
                "total_cost_spent": user.total_cost_spent,
            }
        )
        token = jwt.encode(
            {"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(days=30)},
            "test-user-jwt-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/auth/me",
            cookies={USER_SESSION_COOKIE: token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(user.id)
        assert data["email"] == user.email

    def test_me_with_expired_cookie_returns_401(self, auth_app) -> None:
        client, *_ = auth_app
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(hours=1)},
            "test-user-jwt-secret",
            algorithm="HS256",
        )
        resp = client.get(
            "/api/auth/me",
            cookies={USER_SESSION_COOKIE: token},
        )
        assert resp.status_code == 401
