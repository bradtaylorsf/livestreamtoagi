## Architecture
- **Backend entry:** `core/main:app` (FastAPI + WebSocket) launched via `uvicorn` on port 8010; orchestrates CrewAI agents, routes LLM calls through OpenRouter, and emits world state over WebSocket to the Phaser frontend.
- **Frontend:** `frontend/` Phaser.js 3 + Vite renderer (pixel-art world) consumes WS from backend; `website/` is a separate Next.js public site on Vercel calling the FastAPI REST API.
- **Data layer:** PostgreSQL 16 + pgvector (3-tier memory: Core/Recall/Archival, transcripts, world state) on port 5434; Redis 7 (shared state, kill switches) on port 6381; Langfuse on 3100 for LLM cost/token observability.
- **Key dirs:** `agents/` (YAML personality configs for 9 agents), `core/` (orchestrator, memory, conversation engine, video render pipeline), `tools/` (agent tool impls), `tests/` (organized by layer), `specs/` (read-only design), `scripts/` (deploy/utility incl. Minecraft smoke/soak wrappers).
- **Minecraft embodiment:** propose_build BuildScripts stream to live MC via RCON (recent commits show active Director V2 + Mindcraft integration on this branch).

## Conventions
- **Python 3.13 only** (pinned via `.python-version`; 3.14+ breaks pydantic-core builds). Type hints everywhere, async/await for I/O, `ruff` for lint+format, Pydantic for all API schemas, snake_case funcs / PascalCase classes.
- **TypeScript:** strict mode, ESM, named exports, `const` by default.
- **Tests:** pytest + pytest-asyncio + pytest-cov for backend (`make test-backend` pins `.venv/bin/pytest` for non-activated shells); Vitest for frontend/website; Playwright E2E for website.
- **Git:** conventional commits (`feat:`, `fix:`, `refactor:`, etc.), one feature/fix per PR.
- **New features:** wire agent personalities via `agents/*.yaml`; route new tools through `tools/` and register with CrewAI orchestrator in `core/`; every agent output must pass through Management content filter before TTS.

## Critical Rules
- **Never commit `.env`** — contains OpenRouter, Twitch, YouTube, PixelLab, Langfuse, kill-switch keys.
- **`specs/` is read-only reference** — do not modify design docs from code tasks.
- **Pre-verify services** before integration tests: `docker compose up -d && bash scripts/check-services.sh` (all 5 checks: Redis, Postgres, pgvector, pg_trgm, Langfuse must pass).
- **Management filter + cost governor** are non-negotiable integration points — every agent output passes through Management; every LLM call hits the cost governor / kill switch.
- **Local Gemma:** use `gemma-4-e4b`, NOT reasoning variants like `gemma-4-26b-a4b` (emits empty content).
- **Headless sim snapshots:** always pass `--output-dir snapshots/headless` so dashboard can serve artifacts.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
