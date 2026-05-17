## Architecture
- Root `package.json` orchestrates Docker, FastAPI, Phaser, and Next: `pnpm dev` starts services, `core.main:app` on `8010`, Vite frontend on `5173`, and website on `4000`.
- FastAPI entrypoint is `core/main.py`: lifespan calls `bootstrap_services()`, mounts `/ws`, `/api/health`, `/api/dev/*`, `/api/admin/*`, `/api/*` public routes, `/videos/*`, and `/audio/*`.
- Database is PostgreSQL 16 + pgvector via `asyncpg` in `core/database.py`; schema lives in paired raw SQL migrations under `db/migrations/`, applied with `python -m db up` or `pnpm db:migrate`.
- Key directories: `core/` backend subsystems and repos, `tools/` agent tools, `agents/` YAML identities, `frontend/` Phaser world renderer, `website/` Next app router site, `tests/` pytest/vitest/e2e coverage.

## Conventions
- Python is async-first FastAPI/Pydantic v2 with typed repository classes in `core/repos/`; avoid direct DB access outside repos/managers unless matching existing patterns.
- TypeScript is strict ESM: `frontend/` uses Vite + Phaser, `website/` uses Next app router with `@/*` alias and API helpers in `website/src/lib/api.ts`.
- Tests run from root with `pnpm test`; focused commands are `.venv/bin/pytest`, `npm --prefix frontend test`, `npm --prefix website test`, and `npm --prefix website run test:e2e`.
- New backend routes wire into `core/public_routes.py` for public API or a domain module in `core/admin/` plus `core/admin/__init__.py`; frontend realtime changes must match `core/event_bus.py` event types and `frontend/src/types/events.ts`.

## Critical Rules
- Do not casually alter the 9-agent canon in `agents/`, `specs/CHARACTER-SHEETS.md`, DB seed migrations, or UI constants; `management` and `alpha` have special nonstandard behavior.
- Model names must stay synchronized across `core/llm_client.py` `MODEL_REGISTRY`, `agents/*/config.yaml`, and `db/migrations/002_seed_agents.up.sql`.
- Port/env changes must be updated together in `.env.example`, `website/.env.example`, `package.json`, `docker-compose.yaml`, `frontend/vite.config.ts`, and `website/next.config.ts`.
- Schema changes need numbered `.up.sql` and `.down.sql` migrations; preserve existing migrations and query through typed repos/managers rather than ad hoc SQL.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
