## Architecture
- FastAPI app in `core/main.py` (lifespan-bootstrapped via `core.bootstrap.bootstrap_services`); mounts `core/admin`, `core/auth`, `core/public_routes.py`, plus a `/ws` WebSocket. Frontend (Phaser, `frontend/`) connects to `ws://…/ws`; Next.js website (`website/src/app/*`) calls REST via `BACKEND_URL`.
- DB: PostgreSQL 16 + pgvector on port 5434. Schema lives in `db/migrations/NNN_*.{up,down}.sql` (94 files through `015_phase_assertions`). Run via `pnpm db:migrate` (`python -m db up`); auto-applied at startup when `auto_migrate=True`. Repos in `core/repos/`.
- Domain modules under `core/`: `conversation/`, `memory/`, `simulation/`, `world/`, `eval/`, `social/`, `youtube/`, `video/`, `events/`. Agent personalities in `agents/*.yaml`; tool implementations in `tools/`; sandboxed code execution in `sandbox/` (Docker + gVisor).
- Redis 7 on 6381 (`core/redis_client.py`, keys in `core/redis_keys.py`) for shared state and kill switches. Langfuse on 3100 for LLM telemetry.
- Dev orchestration via `pnpm dev` → concurrently runs docker, backend (uvicorn 8010), frontend (Vite), website (Next 4000).

## Conventions
- Python 3.12–3.13 only (3.14+ unsupported). Type hints + async/await everywhere; Pydantic for schemas; `ruff` (config in `ruff.toml`) lints/formats `core/ tools/`. mypy is intentionally lenient — see `pyproject.toml` `disable_error_code` list.
- TypeScript strict mode, ESM, named exports. `const` by default.
- Tests: pytest with `asyncio_mode = "auto"`; testpaths `tests/backend` and `tests/integration` (integration tests require Docker — mark with `@pytest.mark.integration`). Frontend/website use Vitest; website E2E uses Playwright.
- New backend route → add a router module under `core/` and include it in `core/main.py` (alongside `admin_router`, `public_router`). New migration → next sequential number with both `.up.sql` and `.down.sql`.
- Conventional commits (`feat:`, `fix:`, etc.); branch `feat/…` or `fix/…`; one feature per PR.

## Critical Rules
- Never edit `specs/` — read-only design reference. `research/PAPER-INDEX.md` is the entry point for prior art.
- Migrations are append-only and paired: editing an applied `.up.sql` (or shipping without a `.down.sql`) breaks `db:rollback` and prod state.
- Every agent output must pass through `core/management.py` content filter before `core/tts.py` — bypassing it skips the 3-second intervention window.
- `core/bootstrap.py` wires the dependency graph (registry → memory → LLM client → TTS); adding a service means updating both `Services` and `shutdown_services`.
- Don't commit `.env`. External comms (social/email) require human approval — see `core/social/` and `specs/HUMAN-CHECKLIST.md`.
- Pre-flight: `docker compose up -d && bash scripts/check-services.sh` (5 checks must pass) before any integration work.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
