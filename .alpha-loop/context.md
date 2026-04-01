The project is very early stage — mostly scaffolding with empty directories and `__init__.py` stubs. Here's the context file:

---

## Architecture
- **Backend:** FastAPI (Python 3.12+) entry point at `core/main:app`, served via `uvicorn --port 8000`. WebSocket events connect to the frontend. Currently only `core/__init__.py` exists — no orchestrator/conversation/memory modules yet.
- **Frontend:** Phaser.js 3 (TypeScript) in `frontend/`, built with Vite, tested with Vitest. `src/scenes/`, `src/sprites/`, `src/ui/` directories exist but are empty.
- **Database:** PostgreSQL 16 + pgvector via Docker Compose (`docker-compose.yaml`). Redis 7 for cache. Langfuse for observability. Schema managed via Alembic (no migrations yet).
- **Agents:** 9 agent personality directories under `agents/` (vera, rex, aurora, etc.) — currently empty, expected to contain `config.yaml`, `system_prompt.md`, `behaviors.yaml` per agent.
- **Website:** Next.js app in `website/` (placeholder). Specs live in `specs/` as reference docs.

## Conventions
- **Python:** Ruff linter (line-length 100), isort with `core/tools/agents` as first-party. Pytest in `tests/backend/` with `asyncio_mode = "auto"`.
- **TypeScript:** Vite + TypeScript strict, Vitest for tests. pnpm as package manager (`frontend/pnpm-lock.yaml`).
- **Agent config:** Each agent gets `agents/{name}/config.yaml` + `system_prompt.md` + `behaviors.yaml`. Models defined in `CLAUDE.md` agent roster.
- **New backend features:** Add modules to `core/`, tools to `tools/`, wire via FastAPI. Agent tools go in `tools/*.py`.
- **Testing:** `pytest tests/backend/ -v` (Python), `cd frontend && pnpm test` (TS), integration tests via Docker Compose.

## Critical Rules
- **`docker-compose.yaml`** defines shared infra (Redis, Postgres, Langfuse) — port/credential changes break all services.
- **`CLAUDE.md`** is the agent roster source of truth (models, voices, personalities, speaker weights). Keep in sync with `agents/` configs and `specs/CHARACTER-SHEETS.md`.
- **pgvector extension** required for memory system — standard Postgres images won't work; must use `pgvector/pgvector:pg16`.
- **Cost governor** is a safety-critical system — Sentinel + kill switch must always be functional before enabling OpenRouter API calls.
- **CrewAI + OpenRouter** is the agent orchestration layer — `crewai>=0.80.0` with OpenAI-compatible API. Don't swap to direct SDK calls without updating all tool bindings.

## Active State
- **Test status:** (to be filled by loop)
- **Recent changes:** (to be filled by loop)
