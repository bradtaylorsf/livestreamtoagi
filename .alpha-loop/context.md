## Architecture
- **Backend entry:** FastAPI app in `core/main.py` — bootstraps services (DB, Redis, TTS, agents), mounts `core/admin_routes.py`, serves WebSocket at `/ws` for frontend, static files for TTS audio
- **Frontend entry:** Phaser.js app in `frontend/src/main.ts` → `MainScene.ts` — connects via WebSocket to backend, renders pixel art world with agent sprites, speech bubbles, stream overlay
- **Website:** Next.js app in `website/` — public-facing site, calls backend REST API
- **Database:** PostgreSQL 16 + pgvector (port 5434). Schema in `db/init.sql`, migrations in `db/migrations/`, run via `pnpm db:migrate`. Repos in `core/repos/` (asyncpg + SQLAlchemy async)
- **Key directories:** `core/` (orchestrator, conversation engine, memory, eval, LLM client), `tools/` (agent tool implementations), `agents/` (YAML personality configs), `scripts/` (CLI entrypoints like `chat.py`), `evals/` + `scenarios/` (eval configs), `specs/` (read-only design docs)

## Conventions
- **Python 3.13**, strict type hints, async/await for all I/O, `ruff` for lint/format. Pydantic models for API schemas. All CLI commands wired through `pnpm` scripts in root `package.json` (e.g., `pnpm chat`, `pnpm sim`, `pnpm eval`)
- **TypeScript** strict mode, ESM, Vite builds. Frontend uses Phaser.js; website uses Next.js + Tailwind + Recharts
- **Tests:** Python in `tests/backend/` and `tests/integration/` (pytest-asyncio, `pnpm test:python`). Frontend tests co-located as `*.test.ts` (Vitest, `pnpm test:frontend`). Website tests via Vitest + Playwright (`pnpm test:website`)
- **New features:** Backend routes go in `core/admin_routes.py` or new routers imported in `core/main.py`. New agent tools in `tools/`. New CLI commands must be added to root `package.json` scripts — never require raw `python` commands

## Critical Rules
- **`specs/` is read-only** — reference docs, never modify
- **Agent configs in `agents/`** and character names must use "Management" not "Overseer" — this rename is enforced everywhere
- **Cost tracking must be 100% accurate** — any change touching `core/repos/cost_repo.py`, `core/llm_client.py`, or eval cost calculations requires verification
- **Docker services must be healthy before integration tests** — run `docker compose up -d && bash scripts/check-services.sh` (Redis:6381, Postgres:5434, Langfuse:3100)
- **`.env` is never committed** — contains all API keys, DB URLs. Python 3.14+ is unsupported (native deps won't build)

## Active State
- Test status: *(will be filled in by the loop)*
- Recent changes: *(will be filled in by the loop)*
