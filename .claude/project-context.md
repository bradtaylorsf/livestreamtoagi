## Architecture
- **Backend entry:** `core/main.py` — FastAPI app whose `lifespan` calls `core/bootstrap.py:bootstrap_services` to wire Redis, Postgres, agent registry, memory managers, LLM client, TTS, and reflection scheduler. Mounts routers from `core/admin/*_routes.py` (agent, artifact, auth, config, conversation, diagnostics, eval, kill_switch, simulation), plus `core/public_routes.py` and `core/bridge/`. Run via `uvicorn core.main:app --port 8010` (or `npm run dev:backend`).
- **Database:** PostgreSQL 16 + pgvector + pg_trgm. Raw SQL migrations in `db/migrations/NNN_name.{up,down}.sql` (48 up-files). Apply with `npm run db:migrate` (= `python -m db up`); status/rollback via `db:status` / `db:rollback`. All queries go through 19 typed repos in `core/repos/` — no direct asyncpg in routes.
- **Frontend:** `frontend/` Phaser.js + Vite (consumes `VITE_WS_URL`); `website/` Next.js admin on port 4000. Both talk to backend at 8010.
- **Key dirs:** `core/` (orchestration, memory, conversation, admin, repos, simulation, eval, characters, embodiment, bridge, video, social, events, reporting), `tools/` (15 tool modules → ToolRegistry, base in `tools/base.py`), `agents/<id>/` (YAML personality + `system_prompt.md`), `mindcraft/` + `minecraft-server*/` (Mineflayer embodiment bridge), `specs/` (read-only design canon).

## Conventions
- **Python 3.13** (pinned in `.python-version`, <3.14); type hints + async everywhere; `ruff` lint/format; Pydantic v2 for all schemas.
- **Tests** in `tests/backend/` (unit) and `tests/integration/` (Docker-required, marked `@pytest.mark.integration`). `asyncio_mode = "auto"`. Run: `make test-backend` (PATH-safe), `.venv/bin/pytest`, or `npm test` (concurrent pytest + frontend vitest + website vitest).
- **New admin route:** add to a `core/admin/*_routes.py`, include router in `core/admin/__init__.py`, mount in `core/main.py`. **New tool:** subclass `tools/base.py`, register in `ToolRegistry`. **New migration:** paired `.up.sql` + `.down.sql` in `db/migrations/`. **New LLM call:** route through `core/llm_client.py` (never call OpenRouter/OpenAI SDKs directly).
- **Agent config:** `agents/<id>/` YAML is hot-reloaded by `core/config_loader.py` — read agent identity from the registry, not hardcoded constants.

## Critical Rules
- **`management` and `alpha` are special:** management = intervention-only filter (chattiness/initiative = 0.0); alpha = non-verbal wolf (no voice, zero speaker weights). Do not "normalize" their config.
- **All agent output must pass through `core/management.py`** before broadcast/TTS — never emit dialogue events bypassing it.
- **Don't bypass repos** for business logic; don't add raw SQL outside `db/migrations/` and `core/repos/`.
- **Pre-verify Docker services** (`docker compose up -d && bash scripts/check-services.sh`) before integration tests — all 5 checks must pass.
- **`specs/` is read-only canon.** `specs/CHARACTER-SHEETS.md` + `agents/*` YAML are the source of truth for personality.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
