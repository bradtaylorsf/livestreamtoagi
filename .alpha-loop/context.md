## Architecture
- **Backend entry:** `core/main.py` — FastAPI app with lifespan that calls `bootstrap_services()` (in `core/bootstrap.py`); mounts `admin_router`, `bridge_router`, `public_router`, `auth_api`, `kill_switch_api`, plus `/ws` WebSocket for the Phaser frontend.
- **Database:** PostgreSQL 16 + pgvector via `asyncpg` (wired in `core/database.py`); raw SQL migrations live in `db/migrations/NNN_*.up.sql` / `*.down.sql` (047+ files); auto-applied on startup when `bootstrap_services(auto_migrate=True)`.
- **State:** Redis 7 (`core/redis_client.py`, keys in `core/redis_keys.py`) for shared/scoped state and kill switches; event flow goes through `core/event_bus.py`.
- **Layout:** `core/` orchestrator + memory + LLM routing; `tools/` agent tool implementations (e.g., `journal_image_tool`); `agents/<name>/system_prompt.md` YAML+markdown personalities; `frontend/` Phaser+Vite; `website/` Next.js; `specs/` read-only design docs; `.alpha-loop/` epic queue + skill templates.

## Conventions
- Python 3.13 strict (pinned in `.python-version`, 3.14 unsupported); type hints everywhere; async I/O; `ruff` for lint+format; Pydantic models on API boundaries; mypy is aspirational (many `Any` flows disabled in `pyproject.toml`).
- Tests live in `tests/backend/` (unit, `pytest-asyncio` auto-mode) and `tests/integration/` (marker `integration:`; needs Docker services). Run via `pytest tests/backend/` or `make test-backend` (PATH-safe for shell runners without `.venv/bin`).
- New FastAPI routes: define a router module in `core/`, import + `app.include_router(...)` in `core/main.py`. New migration: add paired `NNN_*.up.sql`/`*.down.sql` under `db/migrations/`. New agent: add `agents/<name>/system_prompt.md` and register via `core/agent_registry.py`.

## Critical Rules
- **Never commit** `.env` (contains OpenRouter/Twitch/YouTube/Langfuse/KillSwitch keys); honor cost caps (`AGENT_HOURLY_CAP_USD*`) — `core/cost_governor.py` and `core/kill_switch.py` are load-bearing safety.
- `specs/` is read-only reference — don't edit during implementation.
- Migrations are **forward-only in numbering** — always add the next sequential `NNN`; always provide a working `.down.sql`.
- Before integration tests or verifying issues, run `docker compose up -d && bash scripts/check-services.sh` (all 5 checks must pass: Redis 6381, Postgres 5434, pgvector, pg_trgm, Langfuse 3100).
- Every agent output must pass through `core/management.py` content filter before TTS — don't bypass it when adding new speech paths.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
