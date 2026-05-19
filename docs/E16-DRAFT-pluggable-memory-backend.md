# DRAFT — E16 Pluggable Memory Backend + E5-8 seam

Status: **draft, nothing filed.** This file contains issue bodies ready for
`gh issue create`, plus the patches to `MINECRAFT-PIVOT-ISSUE-PLAN.md` and the
`#507` epic checklist that make the `**Plan:**` links resolve. Review, then file.

Decisions baked in:

- New epic number is **E16** (E1–E15 are taken; E13 = Livestream Pipeline).
- **E5's existing children (#549–#555) are not modified.** E5-8 is an *additive*
  child of E5 and its acceptance criteria re-run the full memory regression
  suite itself, so coverage is achieved without editing E5-6's dependency list.
- The backend swap, Answer Engine adapter, graph layer, and eval harness are
  **E16, off the critical path** (`E1→E2→E3→E4→(E5∥E6)→E7→E8→E12/E13→E15→E14`),
  parallelizable like E9. They do **not** go inside E5.
- **Embedding decision (Brad, confirmed):** Answer Engine owns its own embedding
  provider; livestreamtoagi does not need to supply precomputed vectors. E16-3
  is therefore a normal integration/boundary issue, **not** a feasibility gate.
  The only consequence: the `answer_engine` backend path is validated against a
  live Answer Engine instance, not the `EMBEDDING_PROVIDER=deterministic` local
  path — accepted, because E16 is off the critical path and E7/E8 ship on
  `default`, which keeps the deterministic-local bar.

---

## 1. Issue body — `E5-8` (child of Epic E5 / #507)

`gh issue create --repo bradtaylorsf/livestreamtoagi --label backend --label preserve-no-regress --title "E5-8 — MemoryBackend protocol seam" --body-file -` (body below)

````markdown
E5-8 — MemoryBackend protocol seam
**Epic:** #507 (E5 — Memory Service Exposure)
**Plan:** [docs/MINECRAFT-PIVOT-ISSUE-PLAN.md](docs/MINECRAFT-PIVOT-ISSUE-PLAN.md) → §5 E5-8

### Context (why)
E5-3 (#551) funnels the bridge memory verbs and `tools/memory_tools.py` through
one code path ("single source of truth"). This issue formalizes that path as a
`MemoryBackend` Protocol so the recall/archival implementation is swappable
without touching any caller. It is a **pure refactor with zero behavior change**:
the existing managers become the `default` implementation behind the protocol.
This is the seam that lets E16 introduce an Answer Engine backend later without
ever putting a backend change on the E5→E7 critical path.

### Scope
- **In:** Define a `MemoryBackend` Protocol in `core/memory/` covering the
  recall read/write and archival read/write surface that E5-3 unified. Make the
  existing `RecallMemoryManager` / `ArchivalMemoryManager` the `default`
  implementation behind it. The E5-3 single-source path returns/consumes the
  protocol type. Backend selection is config-driven with `default` as the only
  registered provider in this issue.
- **Out:** Any new backend implementation, Answer Engine, graph/edges, Core
  memory changes, eval harness — all E16. No change to what is stored or
  retrieved.

### Acceptance criteria
- Zero behavior change: the full memory regression suite (same set as E5-6:
  `test_core_memory*.py`, `test_recall_memory.py`, `test_archival_memory.py`,
  `test_cross_conversation_memory.py`, `test_memory_seed.py`,
  `test_memory_snapshot.py`, `test_memory_tools.py`) is green, run inside this
  issue against the protocol path.
- A test asserts the `default` backend satisfies the `MemoryBackend` protocol
  and is the selected backend when no override is set.
- A bridge↔tool parity check (as in E5-3) still passes through the protocol.
- The `EMBEDDING_PROVIDER=deterministic` local path is unaffected.

### Files / modules likely touched
`core/memory/backend.py` (new Protocol), `core/memory/*`; cross-ref
`tools/memory_tools.py`, `core/bridge/handlers/memory.py`

### Dependencies
#551 (E5-3). Recommended checklist position: immediately before #554 (E5-6) so
the refactor runs against a known-good baseline. This issue re-runs the E5-6
suite itself as acceptance, so #554's dependency list is intentionally left
unchanged.

### Track
Sequential (small, pure refactor)

## Local LM Studio validation

This pivot must be validated with local models through LM Studio before the issue is considered complete. Do not require OpenRouter spend for acceptance.

Required evidence in the issue/PR:
- Confirm LM Studio is reachable with `pnpm llm:local --list-only` or `python scripts/check_local_llm.py`.
- Run applicable smoke tests or simulations with local env vars, for example:

```bash
LLM_PROVIDER=lmstudio LOCAL_LLM_BASE_URL=http://localhost:1234/v1 LOCAL_LLM_MODEL=<model-id-from-LM-Studio> EMBEDDING_PROVIDER=deterministic python scripts/run_simulation.py --seed-file scenarios/local_llm_validation.yaml --max-cost 0.01
```

- For building-tier or reflection/dream work, set `LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>` when available.
- For Minecraft/Mindcraft bot validation, use generated local-dev profiles whose `model` and `code_model` target LM Studio/OpenAI-compatible local model IDs instead of `openrouter/...`.
- Record the LM Studio model ID(s), the command(s) run, and whether validation ran against the local Mac server. If an issue has no LLM runtime path, state that explicitly and verify the nearest local smoke path instead.
````

---

## 2. Issue body — Epic `E16` (new epic)

`gh issue create --repo bradtaylorsf/livestreamtoagi --label epic --title "Epic E16 — Pluggable Memory Backend + Memory Eval Harness" --body-file -` (body below). File the children from the §5 plan block (section 4) the same way #549–#555 were generated, then paste the live issue numbers into the checklist.

````markdown
## Goal
Behind the E5-8 seam, make the recall/archival memory implementation swappable;
add an Answer Engine backend so the project dogfoods our own data platform; add
a substrate-agnostic write-time / retrieval-time **memory eval harness** that can
score the toy store *and* real simulation traffic. Preserve existing behavior on
the `default` backend — no regression.

## Ordered Work

Alpha Loop processes these task-list lines strictly from top to bottom. This is the only checklist that should contain child issue refs. (Numbers assigned when children are generated from the plan, as #549–#555 were.)

- [ ] #TBD E16-1 — Recall/Archival backend provider abstraction (sequential) — deps: E5-8
- [ ] #TBD E16-2 — Answer Engine adapter: recall + archival (sequential) — deps: E16-1
- [ ] #TBD E16-3 — Embedding-provider reconciliation / local-validation path (sequential) — deps: E16-2
- [ ] #TBD E16-4 — Typed memory-edge / graph layer (parallel-ready) — deps: E16-1
- [ ] #TBD E16-5 — Write-time decision capture on the compaction path (parallel-ready) — deps: E16-1
- [ ] #TBD E16-6 — Standalone eval harness + MemoryBackend protocol (parallel-ready) — deps: —
- [ ] #TBD E16-7 — livestreamtoagi adapter for the eval harness (dogfood) (sequential) — deps: E16-1, E16-5, E16-6
- [ ] #TBD E16-8 — Eval-harness reporting + CI smoke integration (sequential) — deps: E16-6, E16-7
- [ ] #TBD E16-9 — Backend parity + latency gate, ADR, docs (sequential) — deps: E16-2, E16-3, E16-4

## Dependencies

- Depends on epics: #507 (E5 — specifically the E5-8 seam and E5-3 single source of truth).
- Real-traffic dogfooding value lands after E7/E8 (embodied agents producing memory).
- Plan: [docs/MINECRAFT-PIVOT-ISSUE-PLAN.md](docs/MINECRAFT-PIVOT-ISSUE-PLAN.md) → §5 EPIC 16

## Sequencing Notes

- **Off the critical path.** The spine is `E1→E2→E3→E4→(E5∥E6)→E7→E8→E12/E13→E15→E14`. E16 runs parallel after E5, like E9. A vertical slice (E7) and full embodiment (E8) ship on the `default` (in-process Postgres/pgvector) backend with no E16 dependency.
- **Embedding ownership.** Answer Engine owns embedding for the `answer_engine` backend (Brad's decision). E16-3 wires and documents that boundary: the `answer_engine` path is validated against a live Answer Engine instance; the `EMBEDDING_PROVIDER=deterministic` / LM Studio bar continues to apply to the `default` backend, which is what E7/E8 ship on. No precomputed-vector passthrough required; not a feasibility gate.
- **Core memory stays local.** Answer Engine has no concept of an always-in-prompt versioned per-agent block; E16 does not move `core_memory` / `core_memory_history`.
- Parallel-ready children (E16-4, E16-5, E16-6) can be split for separate planning after their listed deps; the epic checklist still runs serially.
- The standalone eval harness (E16-6) lives in its own public repo (`github.com/bradtaylorsf/alpha-recall`) and is the portfolio artifact; only the adapter (E16-7) lives in this repo. Cross-ref E10-4 for scorecard integration.

## Acceptance Criteria

- [ ] Recall/archival backend is selectable by config; `default` is byte-for-byte the pre-E16 behavior and the full memory regression suite is green on it.
- [ ] An `answer_engine` backend round-trips recall + archival against a live Answer Engine instance (Answer Engine owns embedding).
- [ ] A parity test asserts `default` and `answer_engine` return equivalent results for the memory regression suite; a latency report compares both against the E5-7 baseline within a documented budget or files a follow-up.
- [ ] The eval harness produces real write-time (storage P/R, granularity accuracy, entity F1, edge P/R) and retrieval-time (recall@k, precision@k, LLM utility, counterfactual delta) numbers against at least one real simulation run.
- [ ] An ADR records the pluggable-backend decision and the Answer Engine integration boundary.
- [ ] Every ordered child issue is closed, intentionally skipped, or explicitly called out in the verification comment.
- [ ] Local LM Studio / deterministic-embedding validation evidence is recorded for every child, or the issue explains why no LLM runtime path exists.

## Verification Expectations

- After the loop finishes, run `alpha-loop run --verify-only <epic-number>` or validate the session PR manually.
- Validate with the most realistic local path available: the memory regression suite on both backends, the eval harness against a deterministic-embedding local run, and an Answer Engine instance brought up via its `docker-compose.yml`.
- Record any manual validation gaps before closing the epic.

## Local LM Studio validation

This pivot must be validated with local models through LM Studio before the epic is considered complete. Do not require OpenRouter spend for acceptance.

Required evidence in the issue/PR:
- Confirm LM Studio is reachable with `pnpm llm:local --list-only` or `python scripts/check_local_llm.py`.
- Run applicable smoke tests or simulations with local env vars, for example:

```bash
LLM_PROVIDER=lmstudio LOCAL_LLM_BASE_URL=http://localhost:1234/v1 LOCAL_LLM_MODEL=<model-id-from-LM-Studio> EMBEDDING_PROVIDER=deterministic python scripts/run_simulation.py --seed-file scenarios/local_llm_validation.yaml --max-cost 0.01
```

- For building-tier or reflection/dream work, set `LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>` when available.
- For Minecraft/Mindcraft bot validation, use generated local-dev profiles whose `model` and `code_model` target LM Studio/OpenAI-compatible local model IDs instead of `openrouter/...`.
- Record the LM Studio model ID(s), the command(s) run, and whether validation ran against the local Mac server. If an issue has no LLM runtime path, state that explicitly and verify the nearest local smoke path instead.
````

---

## 3. Patch — `MINECRAFT-PIVOT-ISSUE-PLAN.md`

### 3a. Epic list table (§1, after the E15 row, line ~84)

```
| **E16** | Pluggable Memory Backend + Memory Eval Harness | Behind the E5-8 seam, make recall/archival storage swappable; add an Answer Engine backend to dogfood our own data platform; add a substrate-agnostic write-time / retrieval-time memory eval harness that scores the toy store and real traffic. Preserve `default`-backend behavior — no regression. | E5 (E5-8); real value after E7/E8 | 9 |
```

Update the total line (~86): `**Total: ~119 micro-issues across 16 epics.**`

### 3b. Dependency graph note (§2, "Parallelizable epics", ~line 151)

> **After E5 completes:** `E16` (pluggable backend + eval harness) can run in
> parallel with `E9`. It is off the critical-path spine; E7/E8 ship on the
> `default` backend. `E16-3` (embedding-provider reconciliation) is a feasibility
> gate for the Answer Engine path — if it fails, E16 narrows to the eval harness.

### 3c. Add `E5-8` bullet under `### EPIC 5` (after the E5-7 bullet, ~line 600)

```
- **E5-8 — MemoryBackend protocol seam**
  - Context: E5-3 funnels bridge + `tools/memory_tools.py` through one path;
    formalize it as a `MemoryBackend` Protocol so recall/archival is swappable
    without touching callers. Pure refactor; existing managers = `default` impl.
    Enables E16 without putting any backend change on the E5→E7 critical path.
  - Scope (in): `MemoryBackend` Protocol in `core/memory/`; managers become the
    `default` backend behind it; config-driven selection (`default` only here).
    (out): any new backend / Answer Engine / graph / Core memory (E16).
  - Acceptance: zero behavior change — full memory regression suite green via
    the protocol path; test asserts `default` satisfies the protocol and is
    selected by default; deterministic-embedding local path unaffected.
  - Files: `core/memory/backend.py` (new), `core/memory/*`; cross-ref
    `tools/memory_tools.py`, `core/bridge/handlers/memory.py`
  - Deps: E5-3. Recommended position: before E5-6 (this issue re-runs the E5-6
    suite as its own acceptance; E5-6's dep list is left unchanged).
  - Track: sequential. Labels: `backend`,`preserve-no-regress`
```

### 3d. New `### EPIC 16` block (§5, after EPIC 15)

```
### EPIC 16 — Pluggable Memory Backend + Memory Eval Harness

Goal: swap recall/archival storage behind the E5-8 seam; dogfood Answer Engine;
add a substrate-agnostic memory eval harness. `default`-backend behavior is
preserve-no-regress. Off the critical path. E16-1..E16-3 sequential; E16-4..E16-6
parallel; E16-7..E16-9 sequential.

- **E16-1 — Recall/Archival backend provider abstraction**
  - Context: E5-8 defines the protocol; E16-1 turns it into a provider registry
    with a `default` (in-process Postgres/pgvector) provider that is byte-for-byte
    current behavior, selected by config.
  - Scope (in): provider registry + `default` provider + config switch.
    (out): non-default providers, Core memory.
  - Acceptance: memory regression suite green on `default`; switching providers
    is a config change touching zero callers.
  - Deps: E5-8. Track: sequential. Labels: `backend`,`preserve-no-regress`
- **E16-2 — Answer Engine adapter: recall + archival**
  - Context: dogfood `../answer-engine` as durable recall/archival store.
  - Scope (in): `core/memory/backends/answer_engine.py` mapping recall
    store/retrieve and archival store/retrieve onto Answer Engine REST/MCP
    (`/api/v1/content`, `/search/semantic|hybrid`, `get_content`); namespace by
    `simulation_id`+`agent_id`; 1536-dim parity check. (out): graph/edges
    (E16-4), Core memory, eval (E16-6).
  - Acceptance: a recall write then search, and a transcript store then fetch,
    via the `answer_engine` backend return results equivalent to `default`.
  - Deps: E16-1. Track: sequential. Labels: `backend`,`area:bridge`
- **E16-3 — Embedding ownership boundary + Answer Engine validation path**
  - Context: Answer Engine owns embedding for the `answer_engine` backend
    (Brad's decision). This issue makes the boundary explicit and documents how
    the path is validated, since it sits outside the deterministic-local bar.
  - Scope (in): let Answer Engine embed on ingest/search; document that the
    `answer_engine` backend is validated against a live Answer Engine instance
    and that the `EMBEDDING_PROVIDER=deterministic`/LM Studio bar continues to
    apply to the `default` backend (E7/E8 path). (out): precomputed-vector
    passthrough, changing Answer Engine internals.
  - Acceptance: a recall write→search round-trip via the `answer_engine`
    backend against a live Answer Engine instance; the embedding-ownership
    boundary and validation posture are documented (feeds the E16-9 ADR).
  - Deps: E16-2. Track: sequential. Labels: `backend`,`documentation`
- **E16-4 — Typed memory-edge / graph layer**
  - Context: net-new (neither repo has typed edges/traversal); enables graph
    recall and the harness's edge metrics.
  - Scope (in): memory edges (ENTITY_LINK, TEMPORAL_NEXT, SUPERSEDES,
    DERIVED_FROM, CONTRADICTS) + 1-hop traversal boost in recall scoring; decide
    home (livestreamtoagi sidecar table vs Answer Engine feature) in the ADR.
    (out): multi-hop beyond depth 1 (follow-up).
  - Acceptance: a SUPERSEDES edge created at write time measurably reorders a
    recall result; behind a flag, default off (no regression).
  - Deps: E16-1. Track: parallelizable. Labels: `backend`,`eval-finding`
- **E16-5 — Write-time decision capture on the compaction path**
  - Context: `core/memory/compaction.py` already decides what to store; capture
    the decision as a trace so the harness can score it.
  - Scope (in): record `{should_store, granularity, entities, proposed_edges,
    reason}` per store decision (Alpha-Recall `StoreDecision` shape); no change
    to what is stored unless a flag flips. (out): the judges (E16-6).
  - Acceptance: a run emits a decision trace per compaction; existing compaction
    tests green.
  - Deps: E16-1. Track: parallelizable. Labels: `backend`,`eval-finding`
- **E16-6 — Standalone eval harness + MemoryBackend protocol**
  - Context: the Alpha-Recall IP — substrate-agnostic write/retrieval eval.
    Own public repo `github.com/bradtaylorsf/alpha-recall`; ships a SQLite toy
    backend for the portfolio demo.
  - Scope (in): write-time judge (storage P/R, granularity acc, entity F1, edge
    P/R), retrieval-time judge (recall@k, precision@k, LLM utility,
    counterfactual delta), benchmark runner, fixtures, report, `MemoryBackend`
    protocol. (out): livestreamtoagi wiring (E16-7).
  - Acceptance: `alpha-recall benchmark --suite all` runs clean with non-zero
    metrics and a real failures section; judge mockable without an API key.
  - Deps: —. Track: parallelizable. Labels: `eval-finding`
- **E16-7 — livestreamtoagi adapter for the eval harness (dogfood)**
  - Context: run the *same* loops on real simulation traffic.
  - Scope (in): adapter implementing the harness `MemoryBackend` protocol
    against the memory facade (`default` or `answer_engine`) + the E16-5
    decision traces. (out): new memory semantics.
  - Acceptance: the harness scores write-time and retrieval-time metrics on a
    real local run's memory.
  - Deps: E16-1, E16-5, E16-6. Track: sequential. Labels: `backend`,`eval-finding`
- **E16-8 — Eval-harness reporting + CI smoke integration**
  - Context: make memory eval part of normal run reporting (cross-ref E10-4).
  - Scope (in): surface harness output in `core/reporting/` scorecard; CI smoke
    with deterministic embeddings + mocked judge. (out): production tracing.
  - Acceptance: a scorecard includes write/retrieval eval fields; CI smoke green
    without network or API keys.
  - Deps: E16-6, E16-7. Track: sequential. Labels: `qa`,`eval-finding`
- **E16-9 — Backend parity + latency gate, ADR, docs**
  - Context: lock in equivalence and cost-of-indirection.
  - Scope (in): parity test (`default` vs `answer_engine` over the memory
    regression suite); latency comparison vs the E5-7 baseline with a documented
    budget; ADR `docs/decisions/00NN-pluggable-memory-backend.md`; companion
    doc. (out): perf tuning beyond the budget (follow-up).
  - Acceptance: parity test required + green (or documented divergences);
    latency report committed within budget or follow-up filed; ADR merged.
  - Deps: E16-2, E16-3, E16-4. Track: sequential. Labels: `qa`,`documentation`
```

---

## 4. Epic `#507` checklist edit (intentional epic-body change — needs your OK)

To make E5-8 run under `alpha-loop`, one line is added to `#507`'s `## Ordered
Work`. This adds a line; it does **not** edit #549–#555. Insert after the
`#553 E5-5` line and before `#554 E5-6`:

```
- [ ] #<E5-8-number> E5-8 — MemoryBackend protocol seam (sequential) — deps: #551
```

Also add to #507's "Sequencing Notes → Sequential children": `- #<E5-8-number> E5-8: #551`.

This is the only change to an existing issue body. Flagged separately because it
changes what `alpha-loop run --epic 507` executes.

---

## 5. Why this shape (one-paragraph rationale for the file/PR)

E5's contract is "expose existing memory, no regression," and its acceptance is
deterministic-embedding local validation — Answer Engine (OpenAI-only embeddings,
separate Node service, added latency, no graph, no eval) cannot satisfy that and
must not sit on the E5→E7 critical path. E5-8 is the minimal, defensible
hardening that converts E5-3's "single source of truth" into a typed swappable
seam at zero behavior cost. Everything ambitious — Answer Engine dogfooding, the
typed-edge graph layer, and the write/retrieval eval harness (the Alpha-Recall
IP, which stays its own public repo and gains a real-traffic adapter) — lands in
E16, parallel to E9, after a vertical slice already works. One eval harness, one
memory facade, one storage substrate.
