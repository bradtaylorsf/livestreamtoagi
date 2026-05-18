## Architecture
- **Backend entry:** `core/main.py` — FastAPI `app` with `lifespan()` that calls `bootstrap_services()`; mounts `core/admin` (admin/auth/kill-switch), `core/auth` (user auth), and `core/public_routes.py`. WebSocket + REST. Run via `uvicorn core.main:app --port 8010`.
- **Database:** PostgreSQL 16 + pgvector. Schema in `db/migrations/NNN_*.{up,down}.sql` (paired up/down), bootstrap in `db/init.sql`, applied by `db/migrate.py` (auto-migrates on startup). Redis 7 for shared state/kill switches.
- **Key dirs:** `core/` (orchestrator, conversation engine, memory, video render, simulation), `tools/` (agent tool implementations, all extend `tools/base.py`), `agents/` (YAML personality configs), `frontend/` (Phaser.js + Vite world renderer), `website/` (Next.js 16 + React 19), `specs/` & `research/` (read-only reference).
- **Streaming path:** Phaser frontend → headless Chrome/Xvfb → OBS/ffmpeg → Restream → Twitch/YouTube.

## Conventions
- **Python 3.13** (pinned `.python-version`; `<3.14` hard limit). Type hints everywhere, async/await for all I/O, Pydantic for API schemas, `ruff` lint/format, stdlib→third-party→local imports.
- **TypeScript** strict, ESM, named exports, `const` by default.
- **Tests:** pytest in `tests/backend/` (122 files, unit) and `tests/integration/`. Run `make test-backend` (PATH-safe, mirrors CI, `-m "not integration"` + coverage). Frontend/website use Vitest; website E2E uses Playwright.
- **New features:** new FastAPI routes wired through `core/public_routes.py` / `core/admin` routers imported in `core/main.py`; new agent tools subclass `tools/base.py`; new DB changes need paired `.up.sql`/`.down.sql` migration files.

## Critical Rules
- Never edit `specs/` or `research/` — read-only design reference. Never commit `.env`.
- DB migrations are paired: every `NNN_*.up.sql` needs a matching `.down.sql`; numbering is sequential — don't reuse/skip numbers.
- `make`/Makefile targets pin `.venv/bin/*` to dodge stale PATH shims — use them rather than bare `python`/`pytest`/`playwright`.
- Verify Docker services first: `docker compose up -d && bash scripts/check-services.sh` (all 5 must pass) before integration tests.
- Edits to `core/video/cue_parser.py` or the replay-cues route require `make test-replay-cues`.
- Non-default ports: Redis 6381, Postgres 5434, Langfuse 3100.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop) — on branch `codex/minecraft-pivot-decisions`; active Minecraft pivot work in `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` and `scripts/minecraft/`.
