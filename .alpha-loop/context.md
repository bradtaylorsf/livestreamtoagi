## Architecture
- **Backend entry:** `core/main:app` (FastAPI + WebSocket) launched via `uvicorn core.main:app --port 8010`; bootstrap wiring in `core/bootstrap.py`, orchestrator in `core/simulation/orchestrator.py` driving `core/simulation/phases.py`.
- **LLM + tools:** `core/llm_client.py` routes through OpenRouter using `core/model_config.py`; agents invoke tools through `core/tool_executor.py`. Minecraft pipeline lives in `core/minecraft/` (blueprint generator, cloud providers, `scripts/build_in_minecraft.py`).
- **Frontend:** Phaser.js 3 renderer in `frontend/` (Vite + Vitest). **Website:** Next.js in `website/` (Vercel, Vitest + Playwright E2E).
- **Database:** PostgreSQL 16 + pgvector on port 5434, Redis 7 on 6381, Langfuse on 3100 — all via `docker compose up -d` then `bash scripts/check-services.sh`.
- **Key dirs:** `agents/` (YAML personality configs), `core/` (orchestrator/memory/conversation), `tools/` (agent tool impls), `tests/` (organized by layer), `specs/` (read-only design), `snapshots/headless/` (sim artifacts for dashboard).

## Conventions
- Python 3.13 only (3.14+ breaks pydantic-core); type hints everywhere, async/await for I/O, Pydantic for API schemas, `ruff check`/`ruff format` for `core/` and `tools/`.
- TypeScript strict mode, ESM, named exports, `const` by default.
- Tests: `pytest tests/backend/ -v` or `make test-backend` (PATH-safe, pins `.venv/bin/pytest`). Frontend/website use Vitest; website E2E uses Playwright.
- Commits: Conventional (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`); branches `feat/...` or `fix/...`; one feature per PR.
- New agents: add YAML in `agents/` + register in `core/model_config.py`. New tools: implement in `tools/` and wire through `core/tool_executor.py`.

## Critical Rules
- **Never commit `.env`** — contains OpenRouter, Twitch/YouTube, Langfuse, DB, kill-switch secrets.
- **`specs/` is read-only reference** — do not modify design docs as part of feature work.
- **Management content filter is mandatory** — every agent output must pass through it before TTS (3s intervention delay).
- **Cost governor + kill switch** (`AGENT_HOURLY_CAP_USD`, `KILL_SWITCH_API_KEY`) must remain wired; do not bypass in new code paths.
- **Render pipeline targets pin `.venv/bin/python` / `.venv/bin/playwright`** — keep that pinning to defeat stale PATH shims.
- **Gemma reasoning models emit empty content** (e.g., `gemma-4-26b-a4b`) — use `gemma-4-e4b` for local sims.
- **Headless sims must use `--output-dir snapshots/headless`** so the dashboard can serve artifacts.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)
