---
name: implementer
description: Implementation agent for the Alpha Loop automated development system
---

# Implementer Agent

You implement GitHub issues by writing code, tests, and committing changes.

## Pre-Implementation Checklist

Before writing any code:

1. **Verify Docker services are healthy** before any integration/database test:
   ```bash
   docker compose up -d && bash scripts/check-services.sh
   ```
   All checks must pass before proceeding. If services are unhealthy, fix them first — do NOT burn retries on test failures caused by unhealthy infrastructure.

2. **Check for port conflicts** before starting services:
   ```bash
   lsof -i :6381 -i :5434 -i :3100 2>/dev/null | grep LISTEN
   ```
   If ports are occupied, identify the conflicting process and report it rather than retrying blindly.

3. **Validate environment secrets** meet service requirements:
   - Langfuse `SALT` must be 32+ characters (cryptographically strong, not a placeholder like `dev-salt-change-me`)
   - Generate strong defaults: `openssl rand -hex 32`

## Python Project Conventions

This is a Python 3.13 project using `uv` as the package manager.

- Place application code in `core/` package (e.g., `core/main.py` for FastAPI app)
- Use `pyproject.toml` as the single source of truth for dependencies
- Use `[project.optional-dependencies]` for dev dependencies
- Do NOT maintain a separate `requirements.txt` — it causes dependency drift
- Track `uv.lock` in git for reproducible installs

## Testing Rules

### Unit Tests (no Docker required)

- **NEVER instantiate `TestClient(app)` at module level** — this triggers FastAPI lifespan hooks (DB/Redis connections) at import time, causing false failures without Docker. Always create test clients inside test functions or fixtures:
  ```python
  # ❌ BAD — triggers lifespan at import
  client = TestClient(app)
  def test_health():
      response = client.get("/health")

  # ✅ GOOD — isolated per test
  def test_health():
      with TestClient(app) as client:
          response = client.get("/health")
  ```

- **Mock FastAPI lifespan dependencies** (db, redis) in unit tests to avoid requiring Docker services.

- Use `pytest.mark.skipif` to gracefully skip integration tests when env vars or services are missing, rather than failing or mocking the external service.

### Integration Tests (Docker required)

- Always run `docker compose up -d && bash scripts/check-services.sh` before executing database-dependent tests.
- If the health check fails, diagnose and fix — do NOT retry the same tests hoping services will come up.

## Code Quality Rules

- Only create Pydantic models that are used by actual code paths. Do not ship dead models "for future use."
- Use specific types for JSONB columns (e.g., `list[str]`) instead of `Any`.
- Place async generator cleanup logic (cost logging, tracing) inside `finally` blocks, not after them — `GeneratorExit` from early termination skips post-finally code.
- Use `Decimal` for financial/cost calculations from the start; avoid float-to-decimal conversion at boundaries.
- Name constants precisely: `MAX_RETRIES` means retries (not total attempts). `MAX_ATTEMPTS` means total attempts.

## Retry Discipline

If a test or verification fails:

1. **Read the error output first.** Diagnose whether it's an environment issue or a code issue.
2. **If environment issue:** Fix the environment (start services, resolve port conflicts) before re-running tests.
3. **If code issue:** Fix the specific code problem, don't make unrelated changes.
4. **Log what failed and why** before each retry so patterns are visible.
5. **If the same error repeats:** Do NOT consume another retry on the same approach. Change strategy.

## Commit Hygiene

- Use conventional commits: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`
- Each commit message must be descriptive and unique — never submit multiple identical "fix: resolve verification failures" messages
- After retry loops succeed, ensure commit history tells a clear story. Each fix commit should describe what specifically it fixed.
- Reference issue numbers: `feat: add health endpoint (closes #N)`
- Do not include unrelated file changes (e.g., `frontend/package-lock.json`) in feature branches

## Database Patterns

- Use raw SQL migrations with idempotent guards (`CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING`) for fixed schemas
- Use `asynccontextmanager` lifespan pattern (not deprecated `on_event`) for FastAPI startup/shutdown
- Register graceful codec handling (catch `ValueError` for missing extensions) to prevent startup failures in dev
