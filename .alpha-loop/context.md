Here's the project context:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with lifespan manager that bootstraps services (DB, Redis, TTS, scheduler), mounts `admin_routes.py` and `public_routes.py`, serves WebSocket at `/ws` for frontend
- **Database:** PostgreSQL 16 + pgvector; schema in `db/migrations/` (numbered up/down SQL files), managed via `pnpm db:migrate`; connection through `core/database.py` using asyncpg/SQLAlchemy async
- **Frontend:** `frontend/` — Phaser.js pixel art renderer connecting to backend via WebSocket; built with Vite
- **Website:** `website/` — Next.js public site consuming FastAPI REST API; deployed on Vercel
- **Agent system:** 9 agents defined in `agents/` (YAML configs); orchestrated by `core/conversation_engine.py` with weighted speaker selection; all output filtered through `core/management.py` before TTS

## Conventions
- **Python:** 3.13, type hints everywhere, async/await for I/O, Pydantic models for schemas, `ruff` for lint/format
- **TypeScript:** strict mode, ESM, Vite builds, Vitest for tests
- **Tests:** `tests/backend/` and `tests/integration/` for Python (pytest, asyncio_mode=auto); `frontend/` and `website/` have colocated Vitest suites; run all via `pnpm test`
- **CLI:** All scripts wired through `pnpm` in root `package.json` — `pnpm sim`, `pnpm eval`, `pnpm chat`, `pnpm db:migrate`; never call raw python directly
- **Git:** Conventional commits (`feat:`, `fix:`, etc.), focused single-purpose PRs

## Critical Rules
- **`specs/` is read-only** — design reference documents, never modify
- **Agent outputs must pass through Management filter** (`core/management.py`) before TTS — bypassing breaks content safety
- **DB migrations are ordered** — `db/migrations/` numbered files must stay sequential; adding out-of-order breaks `pnpm db:migrate`
- **Docker services must be healthy before integration tests** — run `scripts/check-services.sh` first (Redis:6381, PostgreSQL:5434, Langfuse:3100)
- **Cost tracking must be 100% accurate** — every LLM call goes through `core/llm_client.py` with Langfuse tracing; never bypass for eval integrity

## Active State
- Test status: _(to be filled by loop)_
- Recent changes: simulation isolation fixes, error logging for evals, DB-backed eval analysis (commits around #252)
