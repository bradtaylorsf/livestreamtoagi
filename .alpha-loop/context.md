Here's the project context file:

## Architecture
- **Backend entry:** `core/main.py` — FastAPI app with lifespan that connects DB, Redis, loads agents, starts reflection scheduler. Mounts REST endpoints (health, WebSocket) and wires `AgentRegistry`, `Database`, `RedisClient` singletons.
- **Frontend:** `frontend/` — Phaser.js pixel art renderer, built with Vite, no backend coupling beyond WebSocket at runtime.
- **Website:** `website/` — Next.js on Vercel, consumes FastAPI REST API via `BACKEND_URL`.
- **Database:** PostgreSQL 16 + pgvector. Schema in `db/init.sql`, migrations in `db/migrations/`, managed via `db/migrate.py` (`pnpm db:migrate`). Repos in `core/repos/` (CostRepo, MemoryRepo).
- **Key directories:** `core/memory/` (3-tier memory: core, recall, archival), `agents/` (YAML personality configs), `tools/` (agent tool implementations), `specs/` (read-only design docs), `scripts/` (chat CLI, test_agent harness, check-services).

## Conventions
- Python 3.13, type hints everywhere, async/await for I/O, Pydantic models for schemas. Lint with `ruff`. Tests via `pytest` in `tests/backend/` (asyncio_mode=auto).
- Frontend/website: TypeScript strict, ESM, Vitest. Root `pnpm test` runs all three test suites concurrently.
- New features: Python modules go in `core/` or `tools/`, register in `core/main.py` lifespan if they need startup. New agents defined as YAML in `agents/`, loaded by `AgentRegistry.load_all()`. DB changes need a migration in `db/migrations/`.
- Git: conventional commits (`feat:`, `fix:`, etc.), branch naming `feat/description`.

## Critical Rules
- **`specs/` is read-only** — reference only, never modify.
- **Docker services must be healthy** before integration tests: run `scripts/check-services.sh` (Redis:6381, PostgreSQL:5434, Langfuse:3100). Tests marked `@pytest.mark.integration` require them.
- **`core/main.py` lifespan** wires everything — adding/removing services here breaks the entire app. `AgentRegistry`, `Database`, and `RedisClient` are singletons; don't instantiate duplicates.
- **Memory system** (core/recall/archival in `core/memory/`) and **Overseer content filter** are coupled to every agent output — changes cascade to all 9 agents.
- **`.env` never committed.** Python 3.14+ unsupported (native deps won't build).

## Active State
- Test status: *(to be filled in by the loop)*
- Recent changes: *(to be filled in by the loop)*
