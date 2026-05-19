## Architecture
- **Backend entry:** `core/main.py` — FastAPI app (`core.main:app`) run via `uvicorn` on port 8010. `lifespan()` calls `bootstrap_services()` (`core/bootstrap.py`, returns `Services`) and mounts routers: `core/admin` (auth, kill-switch), `core/auth`, `core/bridge` (Python↔Node Minecraft bridge), `core/public_routes.py`. WebSocket at `/ws` feeds the Phaser `frontend/`.
- **Database:** PostgreSQL 16 + pgvector. Schema bootstrapped from `db/init.sql`; versioned migrations in `db/migrations/` run via `python -m db up|down|status` (`db/migrate.py`). Async access through `asyncpg`/SQLAlchemy in `core/database.py` and `core/repos/`. Redis (`core/redis_client.py`) for shared state/kill switches.
- **Key dirs:** `core/` (orchestrator, memory, conversation_engine, bridge, simulation, video), `tools/` (agent tool implementations, all extend `tools/base.py`), `agents/` (YAML personalities), `config/` (conversation/event YAML), `frontend/` (Phaser+Vite), `website/` (Next.js), `scenarios/`/`evals/` (sim harnesses), `mindcraft/` (Minecraft bot fork).

## Conventions
- Python 3.13 (`>=3.12,<3.14`), full type hints, async/await for I/O, Pydantic for all schemas. Lint/format `ruff`; types `mypy` (lenient config in `pyproject.toml`).
- Tests: `pytest` under `tests/backend/` (unit) and `tests/integration/` (marked `integration`, need Docker). Run `make test-backend` (PATH-safe, mirrors CI) or `.venv/bin/pytest`. Frontend/website use Vitest. `npm run verify:*` scripts gate specific subsystems.
- New tools subclass `tools/base.py`; new routers must be imported and mounted in `core/main.py`. New agents need a YAML in `agents/` plus registration via `core/agent_registry.py`. Schema changes require a new file in `db/migrations/`.

## Critical Rules
- Never hand-edit `specs/` (read-only design reference) or `db/init.sql` without a matching migration. `uv.lock`/`pnpm-lock.yaml` are managed — don't edit by hand.
- The memory regression gate (`make test-memory-regression`) and bridge contract/protocol tests are CI-blocking; backend memory and Python↔Node bridge schemas (`core/bridge/schemas`, `contract.py`) must stay in sync across both sides.
- Use Makefile/`.venv/bin/*` targets — stale `python`/`pytest` shims on PATH cause failures. Docker services (`docker compose up -d` + `scripts/check-services.sh`) must be healthy before integration work.
- Every agent output must pass the Management content filter before TTS; cost governor tracks all LLM calls.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
