## Architecture
- **Backend entry:** `core/main.py` — FastAPI app with `lifespan` hook in `core/bootstrap.py:bootstrap_services` wiring Redis, Postgres, agent registry, memory managers, LLM client, TTS, and reflection scheduler. Mounts `core/admin/*_routes.py` (58 admin endpoints under Bearer auth) and `core/public_routes.py`. Run via `uvicorn core.main:app --port 8010`.
- **Database:** PostgreSQL 16 + pgvector + pg_trgm. Raw SQL migrations in `db/migrations/NNN_name.{up,down}.sql` (37 pairs). Apply with `npm run db:migrate` (`python -m db up`). All queries go through typed repos in `core/repos/` (17 classes) — no direct asyncpg calls in route handlers.
- **Frontend:** `frontend/` Phaser.js + Vite (port via `VITE_WS_URL`); `website/` Next.js admin dashboard on port 4000. Both connect to backend on 8010.
- **Key dirs:** `core/` (orchestration, memory, conversation, admin, repos, simulation, eval, characters, social, events, reporting), `tools/` (15 tool modules → ToolRegistry), `agents/<name>/` (YAML personality + system_prompt.md), `specs/` (read-only design docs).

## Conventions
- **Python 3.13** (pinned in `.python-version`); type hints + async everywhere; `ruff` for lint/format; Pydantic v2 for all schemas.
- **Tests** in `tests/backend/` (unit) and `tests/integration/` (Docker-required, marked `@pytest.mark.integration`). `asyncio_mode = "auto"`. Run: `.venv/bin/pytest` or `npm test` (parallel pytest + frontend vitest + website vitest).
- **New admin route:** add to a `core/admin/*_routes.py`, include router in `core/admin/__init__.py`, then mount in `core/main.py`. **New tool:** add module under `tools/`, subclass `tools/base.py`, register in `ToolRegistry`. **New migration:** create paired `.up.sql`/`.down.sql` in `db/migrations/`.
- **Agent config:** YAML files in `agents/<id>/` are hot-reloaded by `core/config_loader.py` watcher — never read agent identity from hardcoded constants.

## Critical Rules
- **`management` and `alpha` agents have special rules:** management = intervention-only filter (chattiness/initiative = 0.0); alpha = non-verbal helper (no voice, zero speaker weights). Do not "normalize" their config.
- **All agent output must pass through `core/management.py`** before broadcast/TTS — never emit dialogue events bypassing it.
- **Don't bypass repos:** business logic uses `core/repos/*` not raw asyncpg. Don't add raw SQL outside `db/migrations/` and the repo layer.
- **Pre-verify Docker services** (`docker compose up -d && bash scripts/check-services.sh`) before integration tests — all 5 checks must pass.
- **`specs/` is read-only canon.** Treat `specs/CHARACTER-SHEETS.md` and `agents/*` YAML as the source of truth for personality.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
