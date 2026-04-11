Here's the project context file:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with lifespan handler, mounts `admin_routes.py` and `public_routes.py`, opens WebSocket at `/ws`. Bootstrap in `core/bootstrap.py` initializes DB, Redis, and agent services.
- **Database:** PostgreSQL 16 + pgvector. Schema managed via custom migration runner in `db/` (36 migrations, up/down SQL pairs). Run `pnpm db:migrate` / `pnpm db:status`. Init schema in `db/init.sql`.
- **Key directories:** `core/` = orchestrator, conversation engine, memory, eval, simulation, LLM client. `tools/` = agent tool implementations (code exec, economy, social, world state). `agents/` = YAML personality configs. `config/` = conversation/event config, office layout. `evals/` + `scenarios/` = simulation eval system.
- **Frontend/Website:** `frontend/` = Phaser.js pixel art renderer (Vite + Vitest). `website/` = Next.js public site (Vitest + Playwright). Both connect to backend via WebSocket/REST.
- **Dev orchestration:** Root `package.json` uses `concurrently` — `pnpm dev` starts Docker, backend (:8010), frontend, and website together. `pnpm chat` / `pnpm sim` for CLI interaction.

## Conventions
- **Python 3.13** (pinned in `.python-version`), type hints everywhere, async/await for I/O, `ruff` for lint/format, Pydantic models for schemas.
- **Tests:** `tests/backend/` and `tests/integration/` (pytest + pytest-asyncio). Frontend/website use Vitest. Run all: `pnpm test`. Integration tests need `docker compose up -d` first.
- **New features:** Backend routes go in `core/admin_routes.py` or `core/public_routes.py`. New agent tools go in `tools/` and must be registered in `core/tool_executor.py`. New CLI commands must be wired through `scripts/chat.py` into `pnpm` scripts — never require raw `python` invocation.

## Critical Rules
- **`specs/` is read-only reference** — never modify spec files during implementation.
- **All agent output passes through Management filter** (`core/management.py`) before TTS — bypassing this breaks content safety.
- **Simulation isolation:** simulation_id must propagate through all tools/memory/DB writes. Migrations 034-036 enforce this — schema changes must preserve isolation.
- **Cost tracking must be 100% accurate** — every LLM call must record cost events. This is load-bearing for eval integrity.
- **"Overseer" is renamed to "Management"** everywhere — migration 016 did the DB rename; use "Management" in all new code and configs.

## Active State
- Test status: _(to be filled by loop)_
- Recent changes: simulation isolation fixes, error logging for evals, DB-backed eval analysis (commits around #252)
