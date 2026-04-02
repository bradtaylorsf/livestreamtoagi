## Architecture
- Root dev flow is orchestrated from `package.json`: `pnpm dev` starts Docker services from `docker-compose.yaml`, runs FastAPI via `core.main:app` on port `8010`, and runs the Next.js website with `BACKEND_URL=http://localhost:8010`.
- The live backend surface is small: [`core/main.py`](/Users/bradtaylor/Github/livestreamtoagi/core/main.py) only exposes `GET /api/health` and `WS /ws`; startup connects PostgreSQL and Redis, then loads YAML agent configs through `AgentRegistry`.
- Database is PostgreSQL 16 with `pgvector`; schema changes are raw SQL files in `db/migrations/*.up.sql` and `*.down.sql`, applied by [`db/migrate.py`](/Users/bradtaylor/Github/livestreamtoagi/db/migrate.py) using `python -m db` and `DATABASE_URL`.
- `core/` holds backend runtime code, models, DB/Redis clients, event bus, and typed repos; `agents/` is the source of truth for agent config/system prompts; `frontend/` is a small Vite/Vitest TypeScript package for agent constants; `website/` is a Next.js app-router site plus an API client.
- The website proxies `/api/*` to the backend in [`website/next.config.ts`](/Users/bradtaylor/Github/livestreamtoagi/website/next.config.ts), but [`website/src/lib/api.ts`](/Users/bradtaylor/Github/livestreamtoagi/website/src/lib/api.ts) targets many future REST routes that do not exist yet.

## Conventions
- Backend is typed Python, async-first, with Pydantic models in `core/models.py`; repository/database access should follow the existing `Database` and repo patterns, not ad hoc SQL scattered through handlers.
- Frontend/website TypeScript is strict; `website/` uses the `@/*` alias via Vitest/TS config, while `frontend/` uses plain relative imports and currently exports/tests static agent metadata.
- Python tests are configured in `pyproject.toml` to run from `tests/backend` with pytest and `pytest-asyncio`; frontend tests are `frontend/src/**/*.test.ts`; website unit tests are `website/src/**/__tests__/**/*.test.ts`; website E2E is Playwright under `website/tests/e2e`.
- New backend features should be wired from `core.main.py`; new schema work needs paired numbered SQL migrations; new website API usage should assume the Next.js rewrite path `/api/*`, but only after matching backend routes are actually added.

## Critical Rules
- Treat `agents/*/config.yaml`, `system_prompt.md`, and `behaviors.yaml` as sensitive source-of-truth files; the 9-agent roster and special `overseer`/`alpha` behavior must stay consistent across backend and TS constants.
- If model names change, update both YAML agent configs and [`core/llm_client.py`](/Users/bradtaylor/Github/livestreamtoagi/core/llm_client.py); `AgentRegistry` validates configs against `MODEL_REGISTRY` and aliases.
- Keep backend port `8010` aligned across root `package.json`, root `.env.example`, `docker-compose.yaml`, and `website/next.config.ts`; mismatches break dev proxying and WS/API assumptions.
- Do not code to the aspirational README/CLAUDE architecture: the implemented backend is not the full CrewAI conversation system, and `tools/` is not a live tool runtime.
- Avoid assuming website client methods are live endpoints; today they are mostly placeholders beyond health/WebSocket support.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
