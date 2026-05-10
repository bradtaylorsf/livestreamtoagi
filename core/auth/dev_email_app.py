"""Self-contained dev/QA app for verifying console-email magic-link capture.

The production app at ``core.main:app`` boots Postgres, Redis, agent registry,
and the rest of the world via ``bootstrap_services``. For QA who only want to
exercise the ``EMAIL_PROVIDER=console`` capture added in #466, that's massive
overkill — and impossible without a live database.

This module exposes ``app``: a tiny FastAPI app that mounts only the public
auth router (``/api/auth/*``) plus ``/healthz``, with in-process stub
services so the magic-link write path runs end-to-end without touching real
infrastructure.

Run with::

    .venv/bin/uvicorn core.auth.dev_email_app:app --port 8765

Then::

    curl -X POST http://localhost:8765/api/auth/magic-link \\
        -H 'Content-Type: application/json' \\
        -d '{"email":"qa@example.com"}'
    tail -1 "${EMAIL_CONSOLE_LOG:-/tmp/livestream-agi-emails.jsonl}"

NOT FOR PRODUCTION USE. The stub services accept every write and return
``None`` for every read — there is no auth, no persistence, no rate limiting
beyond a per-process counter.
"""

from __future__ import annotations

from fastapi import FastAPI

from core.auth import user_auth_api


class _StubDB:
    """Accepts every write, returns nothing for every read."""

    async def execute(self, *args, **kwargs) -> str:
        return "INSERT 0 1"

    async def fetchrow(self, *args, **kwargs) -> None:
        return None


class _StubRedis:
    """Per-process counter for the rate-limit key; no persistence."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, *args, **kwargs) -> None:
        return None

    async def get(self, *args, **kwargs) -> None:
        return None


class _StubServices:
    def __init__(self) -> None:
        self.db = _StubDB()
        self.redis = _StubRedis()


def _build_app() -> FastAPI:
    app = FastAPI(title="Livestream-AGI dev email capture")
    app.include_router(user_auth_api)
    app.state.services = _StubServices()

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


app = _build_app()
