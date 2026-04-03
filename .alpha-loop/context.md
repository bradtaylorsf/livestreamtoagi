Here's the project context:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with WebSocket support, mounts static files, initializes DB/Redis/AgentRegistry/Scheduler in lifespan handler
- **Database:** PostgreSQL 16 + pgvector (port 5434), schema in `db/init.sql`, migrations in `db/migrations/`, run via `pnpm db:migrate` (`python -m db`)
- **Key directories:** `core/` (orchestrator, memory, conversation engine, LLM client, TTS), `tools/` (agent tool implementations — code execution, web, messaging, world state), `agents/` (YAML personality configs), `frontend/` (Phaser.js pixel art renderer), `website/` (Next.js public site)
- **Infrastructure:** Docker Compose runs Redis (6381), PostgreSQL (5434), Langfuse (3100); `scripts/check-services.sh` validates all 5 health checks before dev
- **Dev startup:** `pnpm dev` launches Docker, backend (uvicorn :8010), and website (:4000) concurrently

## Conventions
- **Python 3.13** (pinned in `.python-version`), type hints everywhere, async/await for I/O, Pydantic models for schemas, `ruff` for lint/format
- **TypeScript:** strict mode, ESM, Vite + Vitest (frontend), Next.js + Vitest + Playwright (website)
- **Tests:** all Python tests in `tests/backend/`, run via `pytest` (asyncio_mode=auto); integration tests marked `@pytest.mark.integration`; `pnpm test` runs all three suites in parallel
- **Git:** conventional commits (`feat:`, `fix:`, etc.), branch naming `feat/`, `fix/`; one feature per PR
- **New features:** Python tools go in `tools/`, core logic in `core/`, agent configs in `agents/` YAML; register tools in `tools/__init__.py`, wire endpoints in `core/main.py`

## Critical Rules
- **`db/init.sql` + `db/migrations/`** — schema changes require migrations; init.sql seeds Docker fresh installs, migrations handle incremental updates — keep both in sync
- **Docker services must be healthy** before running integration tests or backend — always run `scripts/check-services.sh` first
- **Overseer filter** (`core/overseer.py`) gates all agent output before TTS — bypassing it breaks content safety
- **Non-default ports:** Redis=6381, Postgres=5434, Langfuse=3100 — don't assume standard ports
- **`.env` secrets** never committed; `OPENROUTER_API_KEY` required for any LLM calls; cost governor in `core/repos/cost_repo.py` tracks spend

## Active State
- Test status: *(to be filled)*
- Recent changes: structured dialogue/action parsing for TTS (#143), security fixes in tools milestone, session review fixes
