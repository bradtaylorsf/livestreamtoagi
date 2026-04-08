Here's the project context file:

## Architecture
- **Entry point:** `core/main.py` — FastAPI app with WebSocket support, bootstrapped via `core/bootstrap.py` (DB, Redis, agent registry, memory, TTS, scheduler). Admin API mounted from `core/admin_routes.py`.
- **Database:** PostgreSQL 16 + pgvector (port 5434). Schema in `db/migrations/` (21 numbered up/down pairs). Managed via `pnpm db:migrate` / `pnpm db:rollback`. Uses asyncpg + SQLAlchemy async. Repos in `core/repos/`.
- **Agent system:** 9 agents defined as YAML configs in `agents/<name>/`. Conversation engine (`core/conversation_engine.py`) drives weighted speaker selection. All output filtered through `core/management.py`.
- **Three-tier memory:** Core memory (always in prompt), Recall (pgvector search in `core/memory/`), Archival (full transcripts, never deleted).
- **Frontend:** Phaser.js pixel world in `frontend/` (Vite + TypeScript). Website: Next.js in `website/`. Both connect to FastAPI backend.

## Conventions
- **Python 3.13**, type hints everywhere, async/await for I/O. Linted with `ruff` (config in `ruff.toml`). Packages: `core`, `tools`, `agents`.
- **Tests:** `tests/backend/` (pytest, asyncio_mode=auto) + `tests/integration/`. Frontend/website use Vitest. Run all: `pnpm test`. Python only: `pnpm test:python`.
- **CLI gateway:** `scripts/chat.py` is the unified CLI — all commands (`sim`, `eval`, `coverage`, `chat`) wired through `pnpm` scripts in root `package.json`. New features must be accessible via `pnpm` commands, never raw python.
- **Config:** YAML-based agent config in `config/`, loaded by `core/config_loader.py` with hot-reload via `watchfiles`.

## Critical Rules
- **Docker services must be healthy** before any integration test or backend run: `docker compose up -d && bash scripts/check-services.sh` (Redis:6381, PG:5434, Langfuse:3100).
- **Cost tracking must be 100% accurate** — every LLM call tracked via `core/llm_client.py` + Langfuse. Eval integrity depends on this.
- **`db/migrations/`** — numbered sequential migrations with up/down pairs. Never skip numbers. Schema changes require both files.
- **Agent configs (`agents/`) + `config/conversation_config.yaml`** — changing personality/weights affects all simulations and evals. The agent formerly called "Overseer" is now "Management" everywhere.
- **`.env` file** — never committed. Required keys: `OPENROUTER_API_KEY`, `DATABASE_URL`, `REDIS_URL`, and others listed in CLAUDE.md.

## Active State
- Test status: *(to be filled by loop)*
- Recent changes: *(to be filled by loop)*
