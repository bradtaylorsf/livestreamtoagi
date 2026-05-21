## Architecture
- Backend entrypoint: `core/main.py` (FastAPI app via `uvicorn core.main:app --port 8010`); lifespan boots `core/bootstrap.py` services, mounts `admin_router`, `bridge_router`, `public_router`, and a WebSocket
- Frontend `frontend/` (Phaser.js + Vite) renders the pixel world over a WebSocket; `website/` is a separate Next.js public site; Minecraft embodiment lives in `mindcraft/` + `minecraft-server*/`
- DB: PostgreSQL 16 + pgvector on port **5434**; schema bootstrapped from `db/init.sql` plus 48 numbered up/down migrations in `db/migrations/` run by `db/migrate.py` (auto-migrate on startup). Redis 7 on port **6381**
- Key dirs: `core/` (orchestrator, conversation_engine, memory, bridge, embodiment, video, eval, admin, auth), `tools/` (agent tools), `agents/<name>/` (YAML personality configs per agent), `specs/` (read-only), `research/PAPER-INDEX.md` (prior art)

## Conventions
- Python 3.13 (pinned `.python-version`, `<3.14`), `uv` for envs, type hints + `async`/`await` everywhere, Pydantic for all API schemas, `ruff` for lint/format (config in `ruff.toml`)
- Tests in `tests/backend/` (173 files, pytest with `asyncio_mode = "auto"`) and `tests/integration/` (Docker-backed, marked `integration`); run via `make test-backend` which pins `.venv/bin/pytest` so it works without venv activation
- TypeScript: strict mode, ESM, named exports, `const` by default (`frontend/`, `website/`)
- New LLM calls must go through `core/llm_client.py` (OpenRouter routing → Langfuse + cost governor); never call provider SDKs directly
- New routes: mount on existing routers (`admin_router`, `bridge_router`, `public_router`) which are already wired in `core/main.py`; new DB changes need paired `.up.sql` / `.down.sql` in `db/migrations/`

## Critical Rules
- Every agent utterance MUST pass `core/management.py` content filter before TTS (3-second intervention window) — never bypass
- Memory is 3-tier (Core / Recall / Archival) — respect tier boundaries; memory regression gate `make test-memory-regression` covers 13 specific tests
- `specs/` is read-only — update code, not specs, to match. Don't reassign agent models ad-hoc (personality is tied to model choice in `agents/<name>/`)
- Default ports are non-standard (Redis 6381, Postgres 5434, Langfuse 3100); don't hardcode standard ports. Run `docker compose up -d && bash scripts/check-services.sh` before integration work
- External comms (social, email, agent PRs) require human approval gate — don't remove it. `.env` never commits; secrets via env vars listed in `AGENTS.md`

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
