Here's the project context file:

## Architecture
- **Backend entry:** FastAPI app in `core/main.py` — bootstraps services (DB, Redis, TTS, agent registry), mounts `admin_routes.py` router, serves WebSocket at `/ws` for frontend real-time comms
- **Frontend entry:** Phaser.js game in `frontend/src/main.ts` — 1280x720 pixel art renderer, connects to backend via WebSocket (`VITE_WS_URL`), scene-driven (`scenes/MainScene`)
- **Website:** Next.js app in `website/` — public-facing site on Vercel, calls FastAPI REST API (`BACKEND_URL`)
- **Database:** PostgreSQL 16 + pgvector, schema in `db/init.sql` + `db/migrations/` (numbered up/down SQL files, 10+ migrations). Managed via `pnpm db:migrate/status/rollback`. Async access via asyncpg + SQLAlchemy
- **Infrastructure:** Docker Compose runs Redis (port 6381), PostgreSQL (port 5434), Langfuse (port 3100). `pnpm dev` orchestrates all four services via concurrently

## Conventions
- **Python:** 3.13, async/await everywhere, Pydantic models, ruff for lint/format. Tests in `tests/backend/` and `tests/integration/` via pytest-asyncio
- **TypeScript:** Strict mode, Vite builds, Vitest for unit tests in both `frontend/` and `website/`
- **CLI gateway:** All scripts wired through `pnpm` — `pnpm chat`, `pnpm sim`, `pnpm eval`, `pnpm coverage` all route through `scripts/chat.py`. Never invoke raw python commands
- **Git:** Conventional commits (`feat:`, `fix:`, etc.), one feature per PR
- **New features:** Backend routes go in `core/admin_routes.py` or new routers mounted in `main.py`. Agent tools go in `tools/`. Agent configs in `agents/` (YAML)

## Critical Rules
- **`db/migrations/`** — numbered and ordered; never rename or reorder existing migrations. New migrations must be sequential
- **`agents/` YAML + `core/agent_registry.py`** — agent config and registry must stay in sync; adding/removing an agent touches both
- **`core/bootstrap.py`** — service initialization order matters (DB before agent registry before memory). Changes here can break startup
- **Docker services must be healthy** before running integration tests — run `scripts/check-services.sh` first
- **"Overseer" is banned** — always use "Management" in code, configs, and issues

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
