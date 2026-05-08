## Architecture
- **Backend entry:** `core/main.py` — FastAPI app with `lifespan()` that calls `bootstrap_services()` (db, redis, agent_registry, memory, LLM, TTS, scheduler), mounts `admin_router`, `auth_api`, `kill_switch_api`, `public_router`. WebSocket via `core/event_bus.py`.
- **Frontend entry:** Phaser.js in `frontend/` (Vite, port via `VITE_WS_URL`). **Website entry:** Next.js in `website/src/app/` (App Router; admin UI + public pages, port 4000).
- **Database:** PostgreSQL 16 + pgvector + pg_trgm. Raw SQL migrations in `db/migrations/NNN_*.{up,down}.sql` (37+ pairs). Run with `pnpm db:migrate`. Repo classes in `core/repos/`.
- **Key dirs:** `core/` (orchestrator, memory, conversation, simulation, eval, admin, social, events), `tools/` (15 tool modules → ToolRegistry), `agents/<name>/` (YAML personality + system_prompt.md), `tests/{backend,integration}/`, `specs/` (read-only design docs), `research/` (papers).

## Conventions
- **Python 3.13** pinned in `.python-version` (3.14+ unsupported). Async/await everywhere; type hints required; `ruff` for lint/format; Pydantic v2 for schemas; snake_case funcs / PascalCase classes.
- **TypeScript** strict mode, ESM, named exports, `const` default.
- **Tests:** `pytest` with `asyncio_mode = "auto"` for backend; Vitest for frontend/website; Playwright E2E for website. `tests/integration/` requires Docker services. Run all via `pnpm test` or `pnpm test:python`.
- **New backend routes:** add router and include in `core/main.py` (or attach under `core/admin/` / `core/public_routes.py`). New tools: register in `tools/__init__.py` ToolRegistry. New agents: create `agents/<name>/{config,behaviors}.yaml` + `system_prompt.md`.
- **Commits:** Conventional commits (`feat:`, `fix:`, etc.); one feature per PR.

## Critical Rules
- **Don't modify** `specs/` (canonical design reference) or `agents/management/` and `agents/alpha/` special-rule configs (Management = `chattiness:0`, Alpha = non-verbal, zero speaker weights).
- **Migrations are paired** — every `NNN_*.up.sql` needs a matching `.down.sql`. Never edit a migration after merge; add a new numbered pair.
- **All agent output** must flow through `core/management.py` content filter before TTS broadcast. Don't bypass.
- **Bootstrap order matters:** `TTSPipeline` is constructed before `bootstrap_services()`, and `agent_registry` is injected after — preserve this in `lifespan()`.
- **Service preflight:** run `docker compose up -d && bash scripts/check-services.sh` before integration tests; ports default to Redis 6381, Postgres 5434, Langfuse 3100 (configurable via env).

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
