# Session Summary: session/epic-435-epic-simulation-first-pivot-make-simulations-the-primary-product

## Overview
This session pivoted the product to simulation-first across 17 issues spanning backend (schema, auth, energy timeseries, video pipeline, YouTube publish), frontend scoped routes, and website redesign. 15 issues succeeded with zero test-fix retries — first-run pass rate was exceptional thanks to comprehensive scoped test coverage. Recurring weaknesses clustered around scope discipline, cross-endpoint completeness, and integration gaps between backend wiring and the UI surfaces meant to invoke them.

## Recurring Patterns
- **Token-consumption ordering for auth/single-use resources:** validate signing secrets and config prerequisites *before* consuming magic-link tokens (#422, #423, #424, #428, #432, #433) — fails closed without burning user state.
- **DB-backed state-machine claim for idempotent background jobs:** `UPDATE ... WHERE status IS NULL RETURNING` for video render (#425) and YouTube publish (#434); avoids duplicate work under concurrent triggers.
- **Pure-helper extraction for testable UI logic:** `buildPickerLabel`, `filterSimulations`, scoped-context selectors (#427, #428, #429) — fast deterministic tests without DOM setup.
- **Layered fallback for optional metadata:** explicit YAML `meta:` block → leading comment → derived value (#429); flag column on existing entity instead of a separate table (#433).
- **Pair-set / frozenset pattern for relational scoring:** alliance/faction pair expansion at config-load for O(1) hot-path membership checks (#419).
- **Reviewer-as-second-pass catches semantic bugs tests cannot:** `<video poster=mp4>` rendering blank (#426, #427), broken scoped breadcrumb (#427), config-check ordering (#422, #423).

## Recurring Anti-Patterns
- **Scope creep in PRs:** unrelated infrastructure (auth + submit API) bundled into UI redesign issues (#418, #426); #418 PR included #419 factions changes. Inflates review surface and muddies history.
- **Public-endpoint drift from admin models:** `GET /api/simulations/{id}` builds its own response dict and silently misses new fields added to the admin Pydantic model (#418, #419).
- **Migration changes without updating `test_migrations.py` ALL_TABLES / DROP list:** silent rollback-coverage regression (#422, #423).
- **Backend wiring shipped without UI surface:** share-as-challenge endpoint (#432, #433), magic-link login flow (#424), `/simulations/live` not linked from nav (#432). Technically complete but user-inaccessible.
- **Optional heavy deps imported lazily without `pyproject.toml` declaration:** Playwright (#424, #425) — tests pass, production fails at import.
- **Fire-and-forget render + immediate completion email:** the email's video link branch is effectively dead because render hasn't finished (#424, #425).
- **Application-level count-then-insert for uniqueness/concurrency caps:** TOCTOU race; only a partial unique index is race-free (#422, #423).
- **Two creation paths with research fields handled in only one:** `--hypothesis` silently dropped on `--sim-id` existing-row branch (#418, #419).
- **Trusting verification counts in issue text:** issue said "19 scenarios" while repo had 18 (#428, #429).
- **Hardcoded top-level paths inside scoped-route components:** breadcrumbs and tab links break sim scope (#426, #427).
- **Unbounded append-only log tables added without retention policy:** `agent_energy_log` (#420, #421).

## Recommendations
- **Update `implement` prompt:** when acceptance criteria name an endpoint, grep for ALL route prefixes (public AND admin) and verify each surfaces new fields before declaring done. Specifically check `core/public_routes.py` whenever an admin Pydantic model is extended.
- **Update `implement` prompt:** when adding a migration with new tables, also update `tests/backend/test_migrations.py` ALL_TABLES and DROP list in the same change — add to the implementation checklist.
- **Update `code-review` skill:** add explicit check "diff scope matches issue number — flag any files unrelated to the stated issue's acceptance criteria, even if tests pass."
- **Update `implement` prompt:** when shipping a backend endpoint, require either a UI surface invoking it OR a tracked follow-up issue + TODO marker in the relevant component file. Pure backend-only PRs need explicit justification.
- **Update `security-analysis` skill:** add check item "single-use token consumed before all preconditions verified (auth secrets, signing keys, downstream service health)."
- **Update `implement` prompt:** when importing a third-party library at module load, verify it is declared in `pyproject.toml` / `requirements.txt`. Lazy imports of heavy runtime deps (Playwright, ffmpeg wrappers) require explicit dependency declarations.
- **Update `implement` prompt:** when adding a parameter to a "create" path, search for parallel branches (e.g., `--sim-id` existing-row path) and apply the parameter consistently to all branches, or fail loudly when the parameter is incompatible.
- **Update `implementation-planning` skill:** treat verification counts and concrete numbers in issue text as suspect — verify against repo state during planning, not as authoritative truth.
- **Update `implement` prompt:** new append-only log tables must explicitly opt in or out of the retention sweep with a code comment justifying the choice.
- **Update `code-review` skill:** flag uniqueness/cap enforcement done via app-level count-then-insert without an accompanying partial unique index.

## Metrics
| Metric | Value |
|--------|-------|
| Issues processed | 17 |
| Success rate | 88% |
| Avg duration | 1329s |
| Total duration | 377 min |
