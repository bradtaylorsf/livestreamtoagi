Here's the project context file:

## Architecture
- **Backend entry:** `core/main.py` — FastAPI app with lifespan bootstrap, mounts WebSocket, admin routes (`core/admin_routes.py`), static audio, and scheduler. Services (DB, Redis, LLM, memory) initialized in `core/bootstrap.py`
- **Frontend entry:** `frontend/src/main.ts` — Phaser.js game (1280x720, pixel art) loads `MainScene` from `frontend/src/scenes/`. Connects to backend via WebSocket (`frontend/src/network/`)
- **Website:** `website/` — Next.js app on Vercel, consumes FastAPI REST API
- **Database:** PostgreSQL 16 + pgvector. Schema in `db/init.sql`, migrations in `db/migrations/`, managed via `pnpm db:migrate` (custom `db/migrate.py`). Redis on port 6381 for shared state/kill switches
- **Key directories:** `core/` (orchestrator, conversation engine, memory, LLM client, eval, simulation), `tools/` (agent tool implementations), `agents/` (YAML personality configs), `specs/` (read-only design docs), `scripts/` (CLI entry points)

## Conventions
- **Python 3.13**, type hints everywhere, async/await for I/O, `ruff` for lint/format. Pydantic models for all schemas
- **TypeScript** strict mode, Phaser.js frontend with Vite, Next.js website. Vitest for both
- **Tests:** `tests/backend/` and `tests/integration/` (pytest + pytest-asyncio). Frontend/website use Vitest. Run all: `pnpm test`. Integration tests need Docker services running first (`docker compose up -d && bash scripts/check-services.sh`)
- **CLI via pnpm:** All scripts wired through root `package.json` — `pnpm chat`, `pnpm sim`, `pnpm eval`, `pnpm db:migrate`, etc. Never use raw python commands directly
- **Git:** Conventional commits (`feat:`, `fix:`, etc.), focused PRs, branch naming `feat/` or `fix/`

## Critical Rules
- **`specs/` is read-only** — reference docs, never modify
- **All agent output passes through Management content filter** (`core/management.py`) before TTS — bypassing this breaks the safety pipeline
- **"Overseer" is renamed to "Management"** everywhere — any new code must use "Management" not "Overseer"
- **Docker services must be healthy before integration tests** — 5 checks must pass (Redis, PostgreSQL, pgvector, pg_trgm, Langfuse). Ports: Redis=6381, Postgres=5434, Langfuse=3100
- **Cost tracking must be 100% accurate** — every LLM call tracked via Langfuse. Never approximate or skip cost recording

## Active State
- Test status: _(to be filled by loop)_
- Recent changes: Layer 8 Phaser.js frontend milestone, Overseer→Management rename, conversation continuity fixes
