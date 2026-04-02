## Architecture
- Root `pnpm dev` starts Docker services, `uvicorn core.main:app` on `:8010`, and the Next website on `:4000`; `core/main.py` owns app startup/shutdown, loads `Database`, `RedisClient`, and `AgentRegistry`, and currently exposes only `/api/health` plus `/ws`.
- PostgreSQL 16 is the primary store, with `pgvector` and `pg_trgm` enabled by [`db/init.sql`](/Users/bradtaylor/Github/livestreamtoagi/db/init.sql); schema lives in raw SQL under [`db/migrations`](/Users/bradtaylor/Github/livestreamtoagi/db/migrations), applied by `python -m db`, and queried through `asyncpg` via [`core/database.py`](/Users/bradtaylor/Github/livestreamtoagi/core/database.py) and `core/repos/*.py`.
- [`agents`](/Users/bradtaylor/Github/livestreamtoagi/agents) contains one folder per agent with `config.yaml`, `system_prompt.md`, and `behaviors.yaml`; [`core/agent_registry.py`](/Users/bradtaylor/Github/livestreamtoagi/core/agent_registry.py) loads those files and validates model names against [`core/llm_client.py`](/Users/bradtaylor/Github/livestreamtoagi/core/llm_client.py).
- [`website/src/app`](/Users/bradtaylor/Github/livestreamtoagi/website/src/app) is a Next App Router site; [`website/src/lib/api.ts`](/Users/bradtaylor/Github/livestreamtoagi/website/src/lib/api.ts) calls `/api/*`, which [`website/next.config.ts`](/Users/bradtaylor/Github/livestreamtoagi/website/next.config.ts) rewrites to `BACKEND_URL`. [`frontend/src`](/Users/bradtaylor/Github/livestreamtoagi/frontend/src) currently holds agent metadata/tests, not a wired Phaser bootstrap.

## Conventions
- Backend is Python with FastAPI, Pydantic models in [`core/models.py`](/Users/bradtaylor/Github/livestreamtoagi/core/models.py), async/await for I/O, and a thin repository pattern (`core/repos/*`). Frontend/website are strict TypeScript with ESM.
- Tests are split by layer: `tests/backend` for `pytest`, `frontend/src/**/*.test.ts` for Vitest, `website/src/**/__tests__` for website Vitest, and `website/tests/e2e` for Playwright.
- Root `pnpm test` runs Python, frontend, and website unit tests concurrently after installing JS deps; integration tests are `pytest -m integration` and expect Docker services to be up first.
- New backend features should be wired through schema migration if needed, a Pydantic/repo update, then explicit route registration in [`core/main.py`](/Users/bradtaylor/Github/livestreamtoagi/core/main.py); there are no separate router modules yet.

## Critical Rules
- Do not casually change or delete migration files or [`db/init.sql`](/Users/bradtaylor/Github/livestreamtoagi/db/init.sql); tests and recall-memory vector search depend on that history and on `vector(1536)`.
- Keep `agents/<id>` files, seeded rows in `002_seed_agents.up.sql`, and `MODEL_REGISTRY` in sync; mismatched IDs or model names break agent loading.
- Update backend and website contracts together: the website already assumes `/api/agents`, `/api/world/chunks`, `/api/challenges`, `/api/stats`, and `/api/lore`, but FastAPI does not implement them yet.
- Common mistake here is trusting README/CLAUDE as current implementation; the shipped code is much narrower than the planned architecture.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
- Current implementation scope: health check, WebSocket event bus, DB/repos/migrations, agent config loading, and a mostly static Next site scaffold.
