Here's the project context file:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with WebSocket support, bootstraps services (agent registry, memory, LLM, TTS, config watcher) in `lifespan()`, mounts `admin_routes.py` for REST API
- **Database:** PostgreSQL 16 + pgvector; schema in `db/init.sql`, migrations in `db/migrations/`, managed via `pnpm db:migrate`/`db:rollback` (runs `db/migrate.py`). Redis for shared state/kill switches
- **Key directories:** `core/` (orchestrator, conversation engine, memory, eval, simulation), `tools/` (agent tool implementations), `agents/` (YAML personality configs), `frontend/` (Phaser.js pixel art renderer), `website/` (Next.js public site), `specs/` (read-only design docs)
- **Memory system:** 3-tier — `core/memory/core_memory.py` (always in prompt), `recall_memory.py` (pgvector search), `archival_memory.py` (full transcripts). Reflection system compacts/evolves memories
- **Monorepo orchestration:** Root `package.json` uses `concurrently` — `pnpm dev` starts Docker + backend (port 8010) + website (port 4000). All CLI commands wired through `pnpm` scripts calling `scripts/chat.py`

## Conventions
- **Python 3.13**, type hints everywhere, async/await for I/O, `ruff` for lint/format, Pydantic models for schemas
- **TypeScript** strict mode, ESM, Vite + Vitest (frontend), Next.js + Vitest + Playwright (website)
- **Tests:** `tests/backend/` and `tests/integration/` (pytest, asyncio_mode=auto). Frontend/website have their own Vitest suites. Run all: `pnpm test`
- **New features:** Backend routes go in `core/admin_routes.py` or new route files imported in `core/main.py`. Agent tools go in `tools/`. New CLI commands must be wired into `package.json` scripts via `scripts/chat.py` — never require raw python commands
- **Git:** Conventional commits (`feat:`, `fix:`, etc.), branch naming `feat/description`

## Critical Rules
- **`specs/` is read-only** — design reference only, never modify
- **Agent name "Management" not "Overseer"** — all code/configs must use "Management" for the content filter agent
- **Docker services must be healthy** before integration tests: run `scripts/check-services.sh` (Redis:6381, PostgreSQL:5434, Langfuse:3100)
- **Cost tracking must be 100% accurate** — eval integrity depends on it; every LLM call must be tracked through Langfuse
- **`.env` never committed** — contains all API keys (OpenRouter, Twitch, YouTube, PixelLab, Langfuse, DB, Redis, kill switch)

## Active State
- Test status: _(to be filled by loop)_
- Recent changes: _(to be filled by loop)_
