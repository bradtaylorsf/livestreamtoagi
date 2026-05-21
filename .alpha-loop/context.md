## Architecture
- **Backend entry:** FastAPI app at `core/main.py` (`uvicorn core.main:app --port 8010`). Lifespan bootstraps services via `core/bootstrap.py`, mounts `core/admin`, `core/auth`, `core/bridge`, `core/public_routes.py`, scheduler, WebSocket, event bus, TTS, idle behavior.
- **Frontend:** Phaser.js + Vite in `frontend/` (WS to `ws://localhost:8010/ws`). **Website:** Next.js in `website/` (REST to backend).
- **Database:** PostgreSQL 16 + pgvector. Schema lives in `db/migrations/` (numbered `NNN_*.up.sql` / `.down.sql`). Apply via `npm run db:migrate` (`python -m db up`). Redis at port 6381 for shared state.
- **Core subsystems** (each a subdir under `core/`): `memory/` (3-tier: core/recall/archival), `bridge/` (Minecraft/mindcraft RPC), `embodiment/`, `conversation/`, `simulation/`, `video/`, `world/`, `youtube/`, `social/`. Agent tool implementations in `tools/`.
- **Minecraft embodiment:** `minecraft-server/`, `minecraft-server-easy/`, `mindcraft/` (forked Node bot framework). Bridge protocol connects Python ↔ Node via `core/bridge/`.

## Conventions
- **Python 3.13** pinned (`.python-version`); 3.14+ unsupported. Use `.venv/bin/...` directly — Makefile/package.json pin venv paths to dodge stale shims.
- **Async-first:** all I/O uses `async/await`. Type hints mandatory; Pydantic for API schemas. Ruff for lint+format. Imports: stdlib → third-party → local.
- **Tests:** `tests/backend/` (unit, fast) and `tests/integration/` (needs Docker services + `-m integration` marker). `pyproject.toml` sets `asyncio_mode = "auto"`. Run with `make test-backend` (mirrors CI exactly with coverage).
- **Commits:** Conventional (`feat:`, `fix:`, `refactor:`, etc.). Branches `feat/...` or `fix/...`. One feature per PR.
- **New routes:** import into `core/main.py` lifespan or include via routers in `core/admin/`, `core/public_routes.py`, `core/bridge/`. New agent tools go in `tools/` and register through `core/tool_executor.py`.

## Critical Rules
- **Never commit** `.env`, `.coverage`, `uv.lock` conflicts, or anything under `livestream_agi.egg-info/`. `specs/` is read-only reference.
- **Docker services must be up** before integration tests or verification — run `docker compose up -d && bash scripts/check-services.sh` (all 5 checks must pass).
- **Management content filter** (`core/management.py`) gates every agent output before TTS — do not bypass.
- **Memory regression gate:** any change touching memory/bridge must pass `make test-memory-regression` (the 13-file list in the Makefile mirrors CI).
- **Bridge contract** (`tests/backend/test_bridge_contract.py`) and Node-side `mindcraft/` must move together — JSON schemas are the source of truth.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
