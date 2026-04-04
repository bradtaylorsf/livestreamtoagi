Here's the project context:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with lifespan that bootstraps services (DB, Redis, LLM, TTS, memory), mounts `admin_routes.py` REST router, and opens WebSocket for frontend
- **Database:** PostgreSQL 16 + pgvector. Schema managed by custom migrator in `db/` (12 up/down migration pairs in `db/migrations/`). Repos in `core/repos/` (agent, artifact, conversation, cost, memory, simulation, transcript, world)
- **Core engine:** `core/conversation_engine.py` drives agent dialogue; speaker selection in `core/conversation/speaker_selector.py` with energy, pacing, proximity, and topic subsystems
- **Memory system:** 3-tier in `core/memory/` — core (always-in-prompt), recall (pgvector semantic search), archival (full transcripts). Reflection/compaction run periodically
- **Frontend:** Phaser.js pixel art renderer in `frontend/` (Vite + TypeScript). Website: Next.js in `website/`. Both connect to backend via REST/WebSocket

## Conventions
- Python 3.13 (pinned in `.python-version`), strict type hints, async/await everywhere. Ruff for lint/format
- TypeScript strict mode, ESM, Vite builds for both frontend and website
- Tests: `tests/backend/` (pytest, unit) and `tests/integration/` (needs Docker services). Frontend/website use Vitest. Run all via `pnpm test` at root
- New tools go in `tools/`, new repos in `core/repos/`, new conversation subsystems in `core/conversation/`. Agent configs are YAML in `agents/`
- DB changes: add numbered migration pair in `db/migrations/`, run `pnpm db:migrate`

## Critical Rules
- Docker services (Redis:6381, PostgreSQL:5434, Langfuse:3100) must be healthy before integration tests — run `scripts/check-services.sh` first
- `core/bootstrap.py` wires all services together; adding a new service requires updating both bootstrap and shutdown
- Cost tracking must be 100% accurate (eval integrity depends on it) — every LLM call must log to `cost_repo`
- Agent configs in `agents/` and seed migration `002_seed_agents` must stay in sync
- Overseer content filter (`core/overseer.py`) sits between agent output and TTS — bypassing it breaks safety guarantees

## Active State
- Test status: _(to be filled by loop)_
- Recent changes: _(to be filled by loop)_
