# Session Summary: session/epic-417-epic-admin-dashboard-bug-fixes-22-issues-from-qa-walkthrough-may-2026

## Overview
All 22 issues from the QA walkthrough epic completed successfully on first pass with zero test-fix retries across the entire batch (1971 backend + 335 frontend + 206 website tests passing). The session demonstrated strong technical execution — clean path-traversal validation, helper extraction patterns, and DB-level filter design — but suffered from systemic PR-scope discipline failures, with most issues bundling unrelated refactors into single-issue diffs.

## Recurring Patterns
- **Path-traversal validation**: Consistent use of `Path.resolve().relative_to(allowed_dir)` in try/except for user-supplied filenames (seed_file, snapshot files) — clean, idiomatic, reusable.
- **`_build_agent_profile` / `_project_root` helper extraction**: Consolidating shared assembly logic across list/detail endpoints kept routes thin and made tests monkey-patchable without `__file__` gymnastics.
- **Optional `simulation_id` query param defaulting to `None` (unscoped)**: Replaced hardcoded `LIVE_SIMULATION_ID` defaults across `/api/agents/*`, `/api/conversations`, `/api/evals/*` — repo layer handles aggregation.
- **Persist-on-write + compute-on-read fallback**: For value-derivation bugs (durations, snapshot timestamps), persist correctly going forward AND compute from source columns at read time — avoids forcing backfill as a prerequisite.
- **Pair scope tests for both presence and absence**: Asserting `"simulation_id" not in query` alongside scoped assertions locks in both code paths.
- **Skeleton-loader minimum-delay gating**: `useDelayedFlag` prevents sub-100ms flash, paired with `SkeletonBlock`/`SkeletonGrid` primitives.

## Recurring Anti-Patterns
- **Massive PR-scope creep** (appeared in 11+ issues): Issues #402, #404, #408, #411, #413, #414, #415, #416 all bundled the simulation launcher, scenario listing, agent profile refactor, and `_build_agent_profile` extraction into unrelated diffs. Made review harder and bisection painful.
- **Hardcoded `LIVE_SIMULATION_ID` as default scope**: Silently breaks non-live access, hides historical data; appeared as the root cause across #395, #396, #397, #406.
- **`.gitignore` churn**: Repeatedly adding `.venv` / `venv` without trailing slashes alongside existing slashed entries; one issue committed a `.venv` symlink with developer-specific absolute path.
- **TS `as` casts hiding contract mismatches**: `PublicEvalRunDetail.status` field missing on backend but cast on frontend nearly shipped silent 10-min polling timeouts.
- **JSX unicode-escape rendering bug**: `\u2014` written directly in JSX children renders literally — recurring across #403, #404 — needs `{"\u2014"}` or actual em-dash.
- **SSR hydration mismatches from sessionStorage in `useState`**: `useCurrentSimulationId` and `AgentDetailClient` both initialized state from `window`/sessionStorage on first render.
- **AC drift on "all endpoints" clauses**: #407 marked done despite `/evals/summary`, `/evals/history`, `/evals/categories` not accepting `simulation_id`.
- **Linking to routes that don't exist yet**: `SeedFileLink` → `/scenarios/<name>` ships a guaranteed 404.

## Recommendations
- **Add a PR-scope guardrail to the implement prompt**: Before committing, the agent should diff the changes against the issue's stated AC and flag any files touched that aren't justified by the AC. Force a "scope justification" line per non-AC file or split into separate PRs. This is the dominant failure mode across the session.
- **Update the `code-review` skill** to add automated checks for: (1) `\uXXXX` literals in JSX children, (2) `useState` initialized from `window`/`sessionStorage` (SSR hydration risk), (3) `as` casts on API response shapes where the field doesn't exist on the Pydantic model, (4) sessionStorage-hydrated filter state not threaded into the initial fetch.
- **Add a `LIVE_SIMULATION_ID` lint rule**: Grep the codebase to flag any new occurrences as default scopes in route handlers — this single anti-pattern produced 4+ separate bugs in the session.
- **Update `implementation-planning` skill**: When ACs use plural/glob phrasing ("all X endpoints", "every Y page"), require the plan to enumerate the full target list explicitly so partial coverage is caught at planning time, not review time.
- **Pre-commit symlink check**: `.gitignore` directory entries don't cover symlinks of the same name. Add a pre-commit hook (or implement-prompt step) to reject committed symlinks pointing outside the repo or to absolute paths.
- **Reinforce `git-workflow` skill** with a "one issue, one diff" rule and a worktree-hygiene reminder: stale changes in an open worktree will leak into the next issue's PR if not stashed.
- **Add a frontend-contract verification step**: When the agent adds a polled field, run a quick check that (a) the field exists on the Pydantic response model, (b) the route handler actually populates it, and (c) the TS interface declares it without `as` casts.
- **Flag stub/placeholder routes during implement**: If a link points to a route that doesn't exist (`/scenarios/<name>`), either gate behind a feature flag or link to an external source — a TODO is not acceptable.

## Metrics
| Metric | Value |
|--------|-------|
| Issues processed | 22 |
| Success rate | 100% |
| Avg duration | 682s |
| Total duration | 250 min |
