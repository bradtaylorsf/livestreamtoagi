# Graphify Civilization Builder Review

This is the promoted review artifact from the focused Graphify run over the
civilization-builder path. The raw `graphify-out/` and `graphify-corpus/`
folders stay local; this file captures the durable cleanup map for future
agents and humans.

## Run Scope

- Corpus: `graphify-corpus/civilization-builder`
- Excluded runtime/generated folders: `logs/`, `.alpha-loop/`, `.worktrees/`,
  local Minecraft server worlds, Mindcraft working clones, generated snapshots,
  videos, build output, virtualenvs, node dependency folders, and local
  Graphify output
- Initial full graph volume: 4,006 nodes, 7,133 edges, 248 communities
- Latest code-only refresh: 3,790 nodes, 7,399 edges, 228 communities
- Latest benchmark: about 45.4x fewer tokens per query than reading the corpus
  naively
- Primary question: how agent conversation, memory, simulation, Minecraft, CLI,
  and headless mode connect, and where code drift is making review harder

The latest refresh used `graphify update graphify-corpus/civilization-builder
--force`, which does not require LLM/API calls. A semantic doc refresh was also
attempted, but this local Graphify install is configured for Bedrock extraction
without the optional `boto3` dependency. Treat `graphify-out/graph.json`,
`graphify-out/graph.html`, and `graphify-out/GRAPH_REPORT.md` as current for code
structure and partially stale for semantic doc edges until that dependency or a
different Graphify backend is configured.

## Review Hubs

Graphify makes the code quality review more useful by starting from central
hubs instead of scanning the whole repo flat.

| Area | High-signal graph evidence | Review focus |
| --- | --- | --- |
| Conversation runtime | `ConversationEngine` community is the largest hub and connects context build, speaker selection, tool return handling, archival compaction, and turn state. | Keep weighted speaker selection and Management/TTS gates intact while reducing duplicated context and logging paths. |
| Simulation runtime | `SimulationOrchestrator` has one of the highest degrees and connects world ticks, decision logs, phase runners, memory seed, embodied supervisor, and CLI/headless scripts. | Extract only narrow helpers first; avoid behavior changes until headless and CLI runs are covered. |
| Observability | `DecisionLogger`, `SelectionLogger`, Director timeline emission, Minecraft eval artifacts, and reporting live in separate islands. | Standardize append-only JSONL and artifact directories before broader report consolidation. |
| Memory/context | `ContextAssembler`, memory backend protocols, bridge memory handler, and Mindcraft `memory_context.js` form parallel prompt-context paths. | Preserve 3-tier memory boundaries; clarify what is Python prompt context versus Minecraft prompt context. |
| Bridge/director | Bridge contract, prompt gate, scene inbox, scene memory consumer, tool adapter, and build macro scheduler are dense neighboring hubs. | Keep Director V2 gating and build macro ownership visible; never silently skip bridge failures. |
| Minecraft build/eval | `BuildPlanCompiler`, refinement loop, live telemetry, action reliability, timeline exporter, and reports form multiple artifact-producing communities. | Use one evidence directory convention and keep report generation consuming the same canonical timeline. |

## Cleanup Phases

1. Repo hygiene and artifact policy
   - Track `.graphifyignore`.
   - Ignore local Graphify outputs, logs, root `artifacts/`, worktrees, and
     managed loop output.
   - Keep Graphify exclusions aligned with `.gitignore` for local Minecraft
     server worlds, Mindcraft working clones, generated snapshots, videos,
     dependency folders, and build output.
   - Promote generated files only when they become fixtures, reports, or
     decision records.

2. Observability consolidation
   - Keep `decision_log.jsonl` and `timeline-raw/director_v2.ndjson` contracts
     stable.
   - Share low-level JSONL serialization/append behavior across simulation,
     conversation export, and Director V2 timeline code.
   - Share whole-file JSONL artifact writing across Minecraft command eval and
     live eval report artifacts.
   - Share whole-file JSON and Markdown/text artifact writing across Minecraft
     eval reports, live eval reports, trace artifacts, and headless simulation
     metadata.
   - Keep remaining direct file writes limited to non-JSON/text cases, local
     fixture setup, or domain-specific generated assets where a richer helper
     would not clarify ownership.

3. Context and memory simplification
   - Treat `ContextAssembler` as the Python prompt-context source of truth.
   - Treat `core/bridge/handlers/memory.py` as the bridge adapter over existing
     managers, not a second memory implementation.
   - Keep bridge memory tier dispatch explicit: Tier 1 core reads go only
     through `CoreMemoryManager`, and Tier 2 recall reads go through the
     configured recall/memory backend adapter.
   - Treat `scripts/minecraft/fork-src/agent/skills/memory_context.js` as the
     Minecraft runtime prompt mirror, with content-free timeline evidence.
   - Keep core, recall, and archival memory separate.

4. Simulation API refactor
   - Separate orchestration policy from CLI/headless argument parsing.
   - Keep API launch routes using a shared command/spawn helper instead of
     rebuilding `run_simulation.py` / `run_headless_sim.py` argv in each route.
   - Keep default run modes stable: Python director, embodied, and Director V2.
   - Verify `scripts/run_simulation.py`, `scripts/run_headless_sim.py`, and
     snapshot outputs under `snapshots/headless/`.

5. Minecraft bridge and director cleanup
   - Review `prompt_gate.py`, `scene_inbox.py`, `scene_memory.py`,
     `tool_adapter.py`, and build macro scheduling as one subsystem.
   - Keep tool parity explicit and testable.
   - Keep `director.gate` handler responses validated through the bridge
     contract model so direct tests, WebSocket dispatch, and Node schema
     expectations cannot drift apart.
   - Preserve RCON/BuildPlanCompiler failure visibility.

6. Dead-code and duplicate-code sweep
   - Remove or document exact tracked duplicates only after ownership is clear.
   - Leave generated server copies and local run folders ignored.
   - Keep one tracked agent-instruction surface: `AGENTS.md` plus
     `.agents/skills/`. Retire duplicate `.claude/` and `.codex/` context/agent
     output from git so stale local memory does not compete with current
     instructions.
   - Prefer focused deletions with tests over broad rewrites.

## Verification Matrix

| Phase | Minimum checks |
| --- | --- |
| Hygiene | `git check-ignore` for runtime folders; `git diff --check` |
| Observability | `ruff check core/observability ...`; decision logger, selection logger, and Director timeline tests |
| Context/memory | `tests/backend/test_context_assembly.py`, memory bridge tests, memory backend tests |
| Simulation | Headless smoke with output under `snapshots/headless/`; CLI sim smoke when services are available |
| Minecraft | Director gate/tool adapter/timeline tests; local LM Studio Minecraft smoke before deleting bridge code |

## Latest Validation Evidence

- LM Studio preflight: `scripts/check_local_llm.py --list-only` reached
  `http://localhost:1234/v1`; `google/gemma-4-e4b` returned
  `local llm ready`. The `.env`-selected `qwen/qwen3.5-9b` returned empty
  content in this run, so the smoke pinned Gemma explicitly.
- Headless smoke: `LLM_PROVIDER=lmstudio LOCAL_LLM_MODEL=google/gemma-4-e4b
  LOCAL_LLM_MODEL_BUILDING=google/gemma-4-e4b EMBEDDING_PROVIDER=deterministic
  scripts/run_headless_sim.py --scenario scenarios/experimental_short_run.yaml
  --name graphify-refactor-smoke --max-cost 0.01 --seed 42 --skip-eval
  --verbose`.
- Headless result: simulation `d949844b-850c-4ece-8937-3dd8382d3104`, artifacts
  under `snapshots/headless/20260605T012704Z_graphify-refactor-smoke/`,
  3 conversations, 18 turns, 10 artifacts, runtime model
  `lmstudio:google/gemma-4-e4b`, and `$0.0000` paid cost.
- Observability result: the smoke wrote `metadata.json`, `decision_log.jsonl`
  with 29 rows, `build_intents.jsonl` with 1 row, and one compiled BuildScript
  under `build_scripts/`.
- Follow-up consolidation: `write_jsonl()` now covers Minecraft command-eval
  and live-eval NDJSON artifacts, while `append_jsonl()` covers the ownership,
  trade, theft, diplomacy, and conflict ledgers used by the civilization
  builder path.
- Director soak consolidation: settlement objective seeding and Director
  acceptance NDJSON evidence now use the same `write_jsonl()` helper, preserving
  the raw evidence files consumed by `build_timeline.py` and acceptance reports.
- Artifact-file consolidation: `write_json_file()` and `write_text_file()` now
  cover Minecraft command-eval scores/reports, live-eval summaries/scores/traces
  and Markdown reports, and headless simulation `metadata.json`.
- Artifact-file checks: focused `ruff check` passed for the touched
  observability/eval/simulation files, and focused `pytest` passed 20 artifact
  tests covering JSONL, JSON/text files, Minecraft eval reports, live eval
  artifacts, and simulation artifact paths.
- Report-script consolidation: Director acceptance, emergent acceptance,
  settlement smoke, and action-reliability scripts now use the same shared
  JSON/text artifact writers for their report files instead of open-coded
  `Path.write_text(json.dumps(...))` blocks.
- Report-script checks: focused `ruff check` passed for those report scripts,
  and focused `pytest` passed 57 tests covering emergent mode, Director
  acceptance soak reporting, settlement smoke signals, and action reliability.
- Headless/build-planning consolidation: `headless_scorer`, `build_plan_decomposer`,
  and `build_refinement_loop` now use the shared JSON/text artifact writers for
  eval scores, judge cache entries, decomposer cache entries, per-iteration
  BuildPlan/script/feedback files, image prompts, and final summaries.
- Headless/build-planning checks: focused `ruff check` passed for the touched
  headless/build-planning files, and focused `pytest` passed 38 tests covering
  headless scoring, BuildPlan decomposition cache behavior, and refinement-loop
  artifact persistence.
- Long-tail artifact consolidation: generated world/sprite/tilemap metadata,
  replay manifests, public/admin snapshot exports, public run config files,
  memory snapshots, build CLI artifacts, profile generation, monitor HTML, and
  issue-state cache writes now use the same shared JSON/text file helpers.
  Canonical Minecraft timeline exports and local console-email JSONL capture
  also use the shared JSONL/JSON helpers.
- Long-tail checks: the broad raw JSON artifact-write search over `core/` and
  `scripts/` is clean for the targeted `Path.write_text(json.dumps(...))` /
  `model_dump_json` patterns; focused `ruff check` passed for the touched
  helper users; focused `ruff --select F401,F821` passed for `scripts/chat.py`;
  focused `pytest` passed 274 tests covering replay manifests, monitor output,
  profile generation, generated assets, public/admin simulation exports, and
  the build-in-Minecraft CLI.
- Timeline/auth checks: focused `ruff check` passed for canonical Minecraft
  timeline export, console email capture, and adjacent tests; focused `pytest`
  passed 61 tests covering timeline export, magic-link auth, dev email capture,
  and livestream alert email behavior. The remaining targeted raw JSONL writer
  search hits are test fixture setup only.
- Graphify ignore expansion: local over-limit runtime directories were confirmed
  to be ignored by git and added to `.graphifyignore` as well. Current local
  size examples were `logs/` 3.8G, `.worktrees/` 1.2G, `.alpha-loop/` 872M, and
  many `minecraft-server-easy-*` shakeout worlds at roughly 247-270M each.
- Tracked duplicate sweep: `.claude/` context/skill output and stale
  `.codex/agents` instructions were removed from git in favor of `AGENTS.md`
  and `.agents/skills/`; the website's duplicate `SummaryCard` implementation
  was reduced to a single component plus a compatibility re-export.
- Duplicate-scan remainder: exact tracked duplicates left in place are managed
  `.alpha-loop/templates/` mirrors, empty `__init__.py`/`.gitkeep` markers, and
  intentional asset pairs such as on/off office object sprites and reference
  blueprint images.
- Context/memory bridge simplification: `core/bridge/handlers/memory.py` now
  uses explicit tier-specific read helpers over the existing managers. Core
  reads return only Tier 1 core memory and do not touch recall; recall reads
  prefer the configured memory backend adapter and then fall back to
  `recall_memory`.
- Context/memory checks: focused `ruff check` passed for the bridge memory
  handler and runtime-memory tests; focused `pytest` passed 51 tests covering
  runtime Python memory injection, no-content bridge logging, memory tier
  dispatch, bridge auth/error handling, and closed handler registry wiring.
- Simulation launch consolidation: `core/simulation/launch.py` now owns
  canonical `run_simulation.py` and `run_headless_sim.py` command construction
  plus detached subprocess defaults. Admin seeded runs, admin headless runs,
  public submitted runs, and the legacy admin watch-conversation branch call
  this helper instead of each open-coding launch behavior.
- Simulation launch checks: focused `ruff check` passed for the launch helper
  and touched route files; focused `pytest` passed 67 tests covering launch
  helper command shapes, admin simulation routes, and public submission routes.
  Adjacent CLI/config checks passed 26 tests covering run-simulation defaults,
  public run config translation, and headless executor CLI flags.
- Bridge/director cleanup: `handle_director_gate()` now constructs typed
  `DirectorGateResponse` payloads for both Director V2 decisions and legacy
  mode bypass, closing the direct-handler/schema validation gap while preserving
  build macro grants.
- Bridge/director checks: focused `ruff check` passed for the Director handler
  and tests; focused `pytest` passed 189 tests covering Director gate behavior,
  bridge server dispatch, and bridge contract fixtures.
- Bridge result: the headless `propose_build` path compiled a cabin BuildScript
  and attempted live RCON. RCON was down, and the failure surfaced in logs
  instead of being silently skipped.
- Minecraft launch result: `PATH=/opt/homebrew/opt/openjdk@21/bin:$PATH
  SMOKE_TIMEOUT=180 scripts/minecraft/start-server.sh --smoke` reached the
  Paper `Done (` ready line and stopped cleanly.
- Final checks: focused `ruff check`, focused `pytest` suite (114 tests),
  `bash scripts/check-services.sh`, and `git diff --check` passed.
- Follow-up checks: Minecraft eval artifact tests (15 tests) and civilization
  ledger/Director adapter tests (117 tests) passed after the shared JSONL
  consolidation.
- Director soak checks: settlement seed, Director acceptance, and emergent-mode
  report tests (24 tests) passed after moving raw NDJSON evidence writes to the
  shared helper.

## Invariants

- All LLM calls stay routed through `core/llm_client.py`.
- Management content review remains before TTS and public output.
- Cost governor and kill switch stay on every runtime path.
- `decision_log.jsonl` keeps runtime model and tool-intent details.
- Memory remains 3-tier: core, recall, archival.
- Minecraft `propose_build` remains connected to BuildPlanCompiler and RCON
  execution; failures must surface.
- Headless snapshots stay under `snapshots/headless/`.
