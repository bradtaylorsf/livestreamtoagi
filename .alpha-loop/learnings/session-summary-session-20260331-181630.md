# Session Summary: session/20260331-181630

## Overview
- Processed 3 issues over 81 minutes with a 67% success rate (2 succeeded, 1 failed). Both successful issues required 3 retries each, indicating systematic friction in the verify-and-fix loop rather than one-off problems. Key blockers were weak default secrets, port conflicts, and retry cycles that inflated duration on otherwise small tasks.

## Recurring Patterns
- **Smoke/integration tests as verification gates** — both issues used lightweight tests (directory existence, Redis PING, Postgres extensions) to confirm work, catching real problems early
- **Pin versions and use environment variable defaults** — pinning Docker images to major tags and using `${VAR:-default}` patterns appeared as best practice across infra work
- **Match project conventions for file placement** — placing FastAPI in `core/main.py` and extracting Ruff config to `ruff.toml` aligned with existing structure rather than fighting it

## Recurring Anti-Patterns
- **3 retries on both successful issues** — retry loops are masking root causes rather than preventing them; agents are brute-forcing through failures instead of diagnosing first
- **Identical/vague commit messages across retries** — three "fix: resolve verification failures" commits make history unreadable and hide what each attempt actually changed
- **Weak placeholder secrets accepted at config time, rejected at runtime** — Langfuse SALT failure is a class of bug where defaults pass syntax checks but fail service-level validation
- **Dual dependency tracking** — `requirements.txt` alongside `pyproject.toml` and untracked `uv.lock` risks drift and breaks reproducibility

## Recommendations
- **Add a pre-verification environment check** to the implement prompt: scan for port conflicts (`lsof -i :<port>`), validate secret strength against known service minimums, and confirm no stale containers before starting services
- **Enforce commit hygiene after retries** — after a retry loop succeeds, squash fix commits into a single descriptive commit before marking the issue complete
- **Require root-cause annotation on retries** — when a retry is triggered, the agent should log *why* the previous attempt failed before re-running, so patterns become visible without post-hoc analysis
- **Standardize on a single dependency source** — generate `requirements.txt` from `pyproject.toml` (or drop it entirely if using `uv`) and track `uv.lock` in git
- **Add HTTP 200 checks to service verification** — container health checks confirm the process is running, but don't catch app-level failures like Langfuse's 500; add an explicit HTTP status assertion for all web-accessible services

## Metrics
| Metric | Value |
|--------|-------|
| Issues processed | 3 |
| Success rate | 67% |
| Avg duration | 1614s |
| Total duration | 81 min |
