## Architecture
- **Backend entry:** `core/main.py` — FastAPI app with `lifespan()` that calls `bootstrap_services()` (Postgres/Redis/agent registry). Mounts `core/admin` (admin/auth/kill-switch), `core/auth` (magic-link), `core/public_routes`, plus a `/ws` WebSocket fed by `core/event_bus.py`. Run: `.venv/bin/uvicorn core.main:app --reload --port 8010`.
- **Database:** PostgreSQL 16 + pgvector. Schema bootstrap in `db/init.sql`; versioned migrations in `db/migrations/` run via `python -m db up|status|down` (`pnpm db:migrate`). Async access through `core/database.py` (asyncpg/SQLAlchemy). Redis (`core/redis_client.py`) for shared state/kill switch.
- **Core directories:** `core/` (orchestrator, conversation_engine, memory/, management, cost governor, simulation, video), `tools/` (agent tool impls), `agents/<name>/` (YAML personality configs), `frontend/` (Phaser+Vite), `website/` (Next.js), `mindcraft/` (pinned Minecraft bot fork), `scripts/minecraft/` (dev server, setup).
- **Three apps, one repo:** `pnpm dev` orchestrates Docker, Minecraft dev server, backend (8010), frontend (5173), website (4000) via `concurrently`.

## Conventions
- **Python 3.12–3.13** (not 3.14). Type hints + async everywhere; Pydantic for API schemas; `ruff` lint/format (config `ruff.toml`); imports stdlib→third-party→local.
- **Tests:** pytest in `tests/backend/` (`asyncio_mode=auto`, 136 files), Vitest in `frontend`/`website`, Playwright E2E + integration tests gated by `@pytest.mark.integration`. Use `.venv/bin/pytest` or `make test-backend` (PATH-safe). Per-feature scripts: `pnpm verify:minecraft-*`.
- **New features wire-in:** new FastAPI routers must be imported and included in `core/main.py`; new DB changes require a numbered migration in `db/migrations/`; new agents need a full `agents/<name>/` config set; WebSocket-visible state goes through `core/event_bus.py`.
- Conventional commits; branch `feat/`–`fix/`; one feature per PR.

## Critical Rules
- `specs/` is **read-only reference**; `research/PAPER-INDEX.md` is the prior-art lookup. Don't edit specs to "fix" behavior.
- Never commit `.env`. `.venv/`, `mindcraft/node_modules/`, `node_modules/` are vendored — don't modify or delete.
- Schema (`db/init.sql`) and `db/migrations/` must move together — adding columns without a migration breaks `auto_migrate=True` at startup.
- `core/main.py` lifespan ordering matters: `TTSPipeline` is created before bootstrap, then the agent registry is injected — don't reorder.
- Memory is 3-tier and archival is **never deleted**; cost governor + Management content filter sit in the agent output path — bypassing them is a correctness bug.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: Epic E3 Mindcraft fork evaluation; reproducible Mindcraft install + Minecraft server setup (E2); new `scripts/minecraft/dev-server.sh`.
