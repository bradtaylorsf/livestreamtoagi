Here's the project context file:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with lifespan that bootstraps services (Redis, Postgres, agent registry, memory, TTS), mounts `admin_routes.py`, starts scheduler, and opens WebSocket for frontend
- **Database:** PostgreSQL 16 + pgvector, schema in `db/init.sql`, migrations in `db/migrations/`, repos in `core/repos/` (cost_repo, memory_repo, conversation_repo, etc.). Redis on port 6381 for shared state
- **Key directories:** `core/` (orchestrator, conversation engine, memory system, LLM client, eval engine), `tools/` (agent tool implementations — code exec, web, messaging, audience), `agents/` (YAML personality configs), `frontend/` (Phaser.js pixel world), `website/` (Next.js public site), `specs/` (read-only design docs)
- **Simulation loop:** `core/simulation/orchestrator.py` drives phases via `core/conversation/speaker_selector.py`; all agent output passes through `core/overseer.py` content filter
- **Services:** Docker Compose runs Redis (6381), Postgres (5434), Langfuse (3100); `scripts/check-services.sh` validates health

## Conventions
- Python 3.13, type hints everywhere, async/await for I/O, Pydantic models for schemas, `ruff` for lint/format
- Tests in `tests/backend/` and `tests/integration/`; run all with `pnpm test`, Python only with `pnpm test:python` (pytest with asyncio_mode=auto)
- Conventional commits (`feat:`, `fix:`, `refactor:`), branch naming `feat/`, `fix/`
- New tools go in `tools/`, new repos in `core/repos/`, new conversation features in `core/conversation/`
- Root `package.json` orchestrates everything via `concurrently`; `pnpm dev` starts Docker + backend + website together

## Critical Rules
- **`specs/` is read-only** — design reference only, never modify
- **Costs must be 100% accurate** — cost tracking in `core/repos/cost_repo.py` and eval engine are critical for eval integrity; no approximations
- **Memory system is 3-tier** (core/recall/archival in `core/memory/`) — changes to one tier can break the others; update together
- **Docker services must be healthy before integration tests** — run `scripts/check-services.sh` first (5 checks must pass)
- **Agent YAML configs in `agents/`** are loaded by `core/config_loader.py` with hot-reload; schema changes require updating both

## Active State
- Test status: _(to be filled by loop)_
- Recent changes: _(to be filled by loop)_
