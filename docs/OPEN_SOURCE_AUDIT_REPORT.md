# Open Source Audit Report

Date: 2026-05-23
Repository: `/Users/bradtaylor/Documents/GitHub/livestreamtoagi`
GitHub repo: `bradtaylorsf/livestreamtoagi`

## Critical Public-Service Blockers

These block unattended public API/livestream operation. They do not block making
the repository public as clearly marked pre-alpha work-in-progress code.

1. Public agent chat is both broken and outside Management review. `core/public_routes.py:896` exposes `POST /agents/{agent_id}/chat`; `core/public_routes.py:923` calls `svc.llm_client.chat(...)`, but `OpenRouterClient` only exposes `complete()` and `stream()` (`core/llm_client.py:560`, `core/llm_client.py:669`). If repaired naively, it would return model text directly at `core/public_routes.py:936` without `core/management.py` review, violating the invariant in `AGENTS.md:77`.
2. The bridge `cost.gate` verb currently always allows. `core/bridge/server.py:136` returns a stub payload with `allowed: True`, and the pivot docs still identify the hard per-agent hourly cap as missing (`docs/MINECRAFT-PIVOT-ISSUE-PLAN.md:45`, `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md:80`, `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md:941`). This is tracked by E11 (#513/#596/#598/#600) and should block public 24/7 autonomy.
3. Development emit can bypass Management and TTS-gate expectations if exposed. Dev endpoints default to enabled when `ENV` is absent (`core/main.py:231`, `.env.example:112`), and `/api/dev/emit` can synthesize TTS and emit `agent_speak` at `core/main.py:537`, `core/main.py:562`, and `core/main.py:573` without Management review. This is tolerable only as local tooling with production ENV and routing locked down.

## High Findings

1. Minecraft builder-plan OpenRouter routing is a bounded exception, but not through the Python cost/Langfuse path. The eval CLI uses `core.llm_client.OpenRouterClient` (`core/minecraft/eval/provider.py:9`, `core/minecraft/eval/provider.py:59`), but `scripts/minecraft/fork-src/agent/skills/builder_provider.js:371` calls OpenRouter directly with `fetch()`. It has purpose validation and local call/USD caps (`scripts/minecraft/fork-src/agent/skills/builder_provider.js:117`, `scripts/minecraft/fork-src/agent/skills/builder_provider.js:148`, `scripts/minecraft/fork-src/agent/skills/builder_provider.js:319`), but it bypasses `core/llm_client.py:394` cost logging and Langfuse tracing. Tracked by #811: document this exception in an issue/ADR or route it through the bridge before public paid use.
2. Local Minecraft sims disable Management by default. `.env.example:135` documents `MC_SIM_DISABLE_MANAGEMENT default: 1`, and `scripts/minecraft/run-local-sim.sh:280` turns that into `MINECRAFT_MANAGEMENT_REVIEW_MODE=disabled`. The committed chat gate fails closed when enabled (`scripts/minecraft/fork-src/agent/bridge/management_review.js:35`, `scripts/minecraft/fork-src/agent/bridge/management_review.js:79`), and the cohort connector patches `openChat` before chat/TTS/broadcast (`scripts/minecraft/connect-cohort-bot.sh:587`, `scripts/minecraft/connect-cohort-bot.sh:605`, `scripts/minecraft/connect-cohort-bot.sh:621`). Tracked by #810: keep the disabled default strictly local and impossible in any public run mode.
3. The public auth/JWT setup bug is still open as priority-critical (#501). The code has good primitives (`core/auth/jwt_secrets.py:7`, secure cookies at `core/auth/auth_routes.py:176`, admin cookies at `core/admin/auth_routes.py:53`), but public readiness should require a normal dev/public flow that cannot silently fail when `AUTH_JWT_SECRET` is missing.
4. Kill switch exists, but full embodied coverage is not complete. Admin kill uses `X-Kill-Switch-Key` and Redis TTL (`core/admin/kill_switch_routes.py:26`, `core/admin/kill_switch_routes.py:46`); the Python orchestrator checks Redis (`core/simulation/orchestrator.py:1088`), and bridge errand paths gate Alpha (`core/bridge/server.py:483`). E11 still needs Node-bot/world-loop halt coverage (#598) and stream kill path coverage (#614).

## Medium Findings

1. Legacy Phaser/replay/video/tilemap code is not obsolete by itself. README and pivot docs correctly say it remains until Minecraft capture plus website adaptation replace it (`README.md:9`, `README.md:49`, `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md:83`, `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md:1117`, `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md:1166`). Treat `frontend/`, `core/video/`, replay routes, `tools/world_state.py`, tilemap/sprite/PixelLab pieces as legacy but required until E14/E15 gates.
2. Root agent docs still read Phaser-first. `AGENTS.md:7`, `AGENTS.md:22`, and `AGENTS.md:36` describe the Phaser/pixel-art renderer as primary even though README has current Minecraft-pivot context (`README.md:7`, `README.md:29`). `CLAUDE.md:5`, `CLAUDE.md:12`, and `CLAUDE.md:88` are also old-renderer-first. Update these in `docs/` or managed instruction sources; do not edit `specs/` to backfill reality.
3. `docs/OPEN_SOURCE_READINESS.md` now records the repo-public vs. public-service split and links the follow-up epic #808.
4. CI mostly matches runtime versions, but not the Makefile automation convention. CI uses Python 3.13 (`.github/workflows/ci.yml:17`) and has backend/memory/frontend/website/render/integration jobs, but it invokes bare `pytest`, `ruff`, `mypy`, and `python -m playwright` after system installs (`.github/workflows/ci.yml:21`, `:48`, `:71`, `:148`) while `AGENTS.md:83` and the Makefile prefer `.venv/bin/...` targets (`Makefile:1`, `Makefile:26`, `Makefile:31`). Decide whether CI is an explicit exception.
5. Contributor package-manager story is mixed. README says run `pnpm install` then `npm --prefix frontend/website install` (`README.md:131`), CI uses `npm ci` for frontend/website (`.github/workflows/ci.yml:100`, `:115`), and tracked locks include root `pnpm-lock.yaml` plus both `package-lock.json` and `pnpm-lock.yaml` under frontend/website. Add a short policy so contributors know which lockfiles are authoritative.
6. Tracked managed-agent artifacts may confuse public contributors. `.alpha-loop` has 248 tracked files (1.6M tracked; 712M local ignored), and `.agents`, `.claude`, `skills`, and `.codex` all contain tracked local agent instructions/skills. `.alpha-loop/vision.md:15` still says greenfield/pixel-art Phase 2-3. Either document these as project history/automation inputs or trim/archive before a clean public launch.

## Low Findings

1. `sandbox/Dockerfile:2` and `sandbox/Dockerfile:5` still use Python 3.12 while the app requires Python 3.13 (`pyproject.toml:5`, `README.md:108`). Because the sandbox runs standard-library snippets in isolation this is not the app interpreter, but it should be documented or updated.
2. `pyproject.toml:4` still describes a pixel-art world. Not harmful, but stale package metadata.
3. Docker Compose dev defaults are intentionally local but should stay clearly non-production: Redis/Postgres/Langfuse fallbacks at `docker-compose.yaml:6`, `docker-compose.yaml:23`, `docker-compose.yaml:39`, `docker-compose.yaml:40`, and `docker-compose.yaml:42`; matching examples at `.env.example:108`.
4. Test suite passes but emits warnings: deprecated `websockets.legacy`, unawaited async mocks/loop tasks in backend tests, and one expected bad-audio URL warning in frontend tests. These are not release blockers but are contributor-noise cleanup.

## Safe To Make Public?

Yes for public repository visibility as clearly marked pre-alpha work-in-progress
after this report, README disclaimer, readiness checklist, and fake-key cleanup
are committed. No for broad public autonomous operation or unattended 24/7
public broadcast until the service gates are complete.

Remaining public-service gates: #809 for public chat, #501 for public auth/JWT,
E11 (#513/#596/#598/#600) for cost/kill hardening, E13 (#515/#614) for stream
kill coverage, #810 for Management-enabled public run modes, #811 for builder
OpenRouter cost visibility, and #812 for legacy replay/Phaser triage through
E14/E15.

## Architecture Map

- Backend: FastAPI app in `core/main.py`, public routes in `core/public_routes.py`, admin subrouters in `core/admin/`, bootstrap/service wiring in `core/bootstrap.py`, LLM routing/cost logging in `core/llm_client.py`, Management filter in `core/management.py`, orchestration in `core/simulation/` and legacy `core/conversation_engine.py`.
- Memory: three-tier model lives across `core/memory/`, `core/repos/memory_repo.py`, pgvector/archival tables, and bridge handlers. E16 (#659) is the current pluggable-backend/eval expansion.
- Minecraft embodiment: committed source-of-truth patches under `scripts/minecraft/fork-src/agent/`, connector/run scripts under `scripts/minecraft/`, Python bridge contract/server under `core/bridge/`, and current eval harnesses under `core/minecraft/eval/` plus `tests/backend/test_mc_*`.
- Legacy renderer/replay: `frontend/` Phaser renderer, `website/src/components/replay/*`, replay routes, `core/video/`, render Makefile targets, tilemap/world-state tools. Required until E14/E15 gates, not automatically dead.
- Website: Next.js app in `website/`, simulation/replay/public auth routes and components, still depending on replay asset sync (`website/package.json:7`, `website/package.json:17`). E15 owns adaptation.
- Eval/reporting: Python eval code in `core/eval/`, Minecraft command/live evals in `core/minecraft/eval/`, scenario fixtures under `evals/`, `scenarios/`, and `tests/backend/fixtures/`.

## Security Review

- Secrets: tracked risky extension scan was clean for `.env`, `.pem`, `.key`, `.p12`, `.log`, `.mp4`. A redacted gitleaks history scan covered 695 commits and reported no leaks. Fake `sk-...` unit-test placeholders were replaced with non-secret-looking test strings.
- Auth/authz: admin supports bcrypt hash or deprecated plaintext fallback (`core/admin/dependencies.py:72`); rate limits fail open if Redis is unavailable (`core/admin/dependencies.py:43`, `core/auth/dependencies.py:41`). Public magic-link tokens are hashed (`core/auth/auth_routes.py:61`) and redirects are relative-only (`core/auth/auth_routes.py:65`).
- CORS: localhost defaults plus env extra origins are in `core/main.py:144`; `allow_credentials=True` is acceptable only with strict production `CORS_ORIGINS`.
- SSRF: `tools/web_tools.py:214` validates public HTTP(S), blocks localhost/private/reserved hosts (`tools/web_tools.py:293`), resolves DNS before fetch (`tools/web_tools.py:217`), and revalidates redirects (`tools/web_tools.py:232`).
- SQL injection: sampled dynamic SQL builds clauses internally and binds user values (`core/public_routes.py:1649`, `core/public_routes.py:1676`); artifact sorting uses a fixed whitelist (`core/repos/artifact_repo.py:183`). No concrete SQL injection finding from this pass.
- Subprocess/command injection: public/admin simulation launchers validate scenario paths and call `subprocess.Popen` with list args (`core/public_routes.py:2670`, `core/public_routes.py:2838`, `core/admin/simulation_routes.py:144`, `core/admin/simulation_routes.py:191`). ffmpeg paths use list args (`core/video/render_pipeline.py:210`, `core/video/audio_timeline.py:127`). No shell-injection finding from this pass.
- Sandbox: code execution is agent allowlisted (`tools/code_execution.py:47`), language allowlisted (`tools/code_execution.py:25`, `tools/code_execution.py:74`), and Docker/gVisor/network-none/read-only/tmpfs constrained (`tools/code_execution.py:92`). The Minecraft `!executeCode` action routes through the bridge and never runs locally on bridge failure (`scripts/minecraft/fork-src/agent/commands/execute_code_action.js:1`, `scripts/minecraft/fork-src/agent/commands/execute_code_action.js:79`, `scripts/minecraft/fork-src/agent/commands/execute_code_action.js:101`).
- Bridge auth: Node client requires `MINECRAFT_BRIDGE_TOKEN` (`scripts/minecraft/fork-src/agent/bridge/python_bridge.js:450`); server rejects missing/wrong tokens before accept (`core/bridge/server.py:535`); query-token fallback is opt-in only (`core/bridge/server.py:500`).
- XSS: the only direct `dangerouslySetInnerHTML` match is JSON-LD serialization (`website/src/components/JsonLd.tsx:5`). Keep data source review in mind, but no exploitable XSS was identified in this pass.
- Unsafe deserialization: `yaml.safe_load` is used for scenarios (`core/public_routes.py:2430`). No `pickle.loads` or `yaml.load` finding in inspected app paths.

## Documentation And Contributor Readiness

README, CONTRIBUTING, SECURITY, and docs/README are directionally good and explicitly warn about pre-alpha/Minecraft pivot status (`README.md:7`, `CONTRIBUTING.md:3`, `SECURITY.md:3`, `docs/README.md:3`). Setup commands match Python 3.13 and service ports (`README.md:108`, `README.md:128`, `README.md:201`; `CONTRIBUTING.md:18`). The remaining readiness gaps are stale `AGENTS.md`/`CLAUDE.md` overview text, mixed lockfile/package-manager policy, and root issue-template coverage: `.github/ISSUE_TEMPLATE/agent-ready.yml:1` is the only issue template and lacks security/private-reporting or stale-pivot triage prompts.

## Test And CI Health

| Check | Result | Notes |
| --- | --- | --- |
| `git status --short` | pass | Clean before report creation. |
| tracked risky file scan | pass | No tracked `.env`, `.pem`, `.key`, `.p12`, `.log`, or `.mp4`. |
| `make test-backend` | pass | 3307 passed, 2 skipped, 47 deselected, 19 warnings in 45.86s. |
| `make test-memory-regression` | pass | 154 passed, 3 deselected in 2.01s. |
| `npm --prefix frontend test` | pass | 337 tests passed; one expected bad-audio URL stderr. |
| `npm --prefix website test` | pass | 420 tests passed. |

## Issue Inventory Summary

Open issues at audit start: 156. Follow-up issues created from this audit:
#808, #809, #810, #811, #812, and #813.

Audit-start label counts: architecture: 8, area:bridge: 3, area:embodiment: 27, area:livestream: 10, area:run-modes: 32, area:server: 8, backend: 65, bug: 19, documentation: 6, enhancement: 10, epic: 13, eval-finding: 10, frontend: 27, in-review: 61, minecraft: 40, needs-human-input: 9, needs-research: 1, parallelizable: 27, preserve-no-regress: 26, priority-critical: 12, priority-high: 11, priority-medium: 3, qa: 33, ready: 41.

| Epic/status bucket | Open count | Issue numbers |
| --- | ---: | --- |
| E8 | 15 | #572, #573, #574, #575, #576, #577, #578, #579, #580, #706, #707, #718, #719, #720, #721 |
| E9 | 8 | #511, #581, #582, #583, #584, #585, #586, #709 |
| E10 | 9 | #512, #587, #588, #589, #590, #591, #592, #593, #714 |
| E11 | 8 | #513, #594, #595, #596, #597, #598, #599, #600 |
| E12 | 15 | #514, #601, #602, #603, #604, #605, #606, #607, #608, #708, #710, #711, #712, #713, #775 |
| E13 | 9 | #515, #609, #610, #611, #612, #613, #614, #615, #616 |
| E14 | 8 | #516, #617, #618, #619, #620, #621, #622, #623 |
| E15 | 8 | #517, #624, #625, #626, #627, #628, #629, #630 |
| E16 | 11 | #659, #660, #661, #662, #663, #664, #665, #666, #667, #668, #715 |
| E17 | 7 | #777, #778, #779, #780, #781, #782, #783 |
| E18 | 8 | #784, #785, #786, #787, #788, #789, #790, #791 |
| E19 | 1 | #774 |
| unepic/legacy | 49 | #50, #52, #53, #54, #57, #62, #64, #65, #66, #67, #69, #70, #71, #223, #254, #299, #300, #301, #302, #303, #372, #373, #417, #435, #449, #450, #462, #464, #465, #466, #467, #468, #475, #476, #477, #478, #479, #480, #481, #484, #486, #492, #493, #500, #501, #502, #769, #770, #771 |

Specific requested range notes:

- #503 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #504 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #505 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #506 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #507 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #508 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #509 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #510 is already closed; no open-issue action except preserving completed context in docs/decisions.
- #482, #483, and #485 in the requested #475-#486 range are PRs, not open issues; #483/#485 are merged and should drive closure checks for #477/#476.

## Issue Recommendations

| Issue | Title | Current labels | Recommendation | Rationale |
| --- | --- | --- | --- | --- |
| #50 | Implement streaming pipeline — Xvfb + headless Chrome + ffmpeg/OBS + Restream | ready | close as duplicate | Superseded by E13 livestream pipeline (#515/#609-#616); retain only unique acceptance criteria before closing. |
| #52 | Implement TwitchIO chat bot with all commands | ready | rewrite for Minecraft/current architecture | Twitch chat work should target the Minecraft stream/control surface, not the original Phaser stream assumptions. |
| #53 | Implement CostGovernor budget enforcement system | ready | close as duplicate | Covered by E11 cost/kill hardening (#513/#594-#600). |
| #54 | Implement monitoring and health check system | ready | rewrite for Minecraft/current architecture | Monitoring should be reframed around Minecraft capture, bridge, Node bots, and public site health. |
| #57 | Implement scheduled content blocks (daily schedule system) | ready | needs human decision | Scheduled content may still matter, but product priority changed to embodied persistent/short-run modes. |
| #62 | Implement world expansion pipeline — proposal to reveal | ready | rewrite for Minecraft/current architecture | World expansion should become Minecraft build/progression work, not pixel-office reveal. |
| #64 | Implement agent journal generation and storage | ready | close as duplicate | Covered by E9 preserve dreams/journals (#511/#581-#586/#709). |
| #65 | Implement Daily Brief generation system (Pixel's daily recap) | ready | needs human decision | Daily brief/recap is product-facing and should be re-prioritized against Minecraft run modes. |
| #66 | Implement trending news injection for morning standup | ready | needs security review | Trending-news injection creates external-content and prompt-injection risk before public broadcast. |
| #67 | Implement auto-clipping system for content highlights | ready | rewrite for Minecraft/current architecture | Auto-clipping should depend on E13 Minecraft capture artifacts, not the legacy renderer. |
| #69 | Create seed data — initial world expansion proposals and challenges | ready | close as obsolete/not planned | Seed data is tied to old world-expansion proposals; replace with Minecraft scenario/run-mode fixtures if needed. |
| #70 | Create end-to-end integration test — full conversation loop | ready | rewrite for Minecraft/current architecture | Conversation-loop E2E should target embodied/Director V2 paths and Management gates. |
| #71 | Create Playwright E2E test — visual stream verification | ready | rewrite for Minecraft/current architecture | Visual stream verification belongs with E13/E15 Minecraft stream and website adaptation. |
| #223 | Implement agent appearance evolution — reflection generates new skins and animations | ready | needs human decision | Appearance evolution can be rewritten for Minecraft skins/cosmetics or closed as Phaser sprite-era scope. |
| #254 | bug: cost tracking missing for ~75% of LLM calls — simulation_id never passed to llm.complete() | bug, in-review, priority-critical | needs security review | Cost-accounting discrepancy touches spend controls; verify current cost_events coverage before closing. |
| #299 | feat: office layout redesign — reception entrance, common area, shared offices | enhancement, architecture | close as obsolete/not planned | Office layout redesign is Phaser office scope and conflicts with Minecraft pivot/E14 retirement. |
| #300 | feat: Alpha as office dog — bed in Vera's office, idle roaming throughout office | enhancement | close as obsolete/not planned | Office Alpha-as-dog behavior is old Phaser-office flavor; rewrite only if desired as Minecraft behavior. |
| #301 | feat: common area entertainment — DJ tables, disco ball, ping pong, beanbag chairs, 8-bit arcade | enhancement | close as obsolete/not planned | Common-area entertainment props are pixel-office scope, not current Minecraft architecture. |
| #302 | feat: zoom and camera controls — office detail view to world overview | enhancement, architecture | close as obsolete/not planned | Office zoom/camera controls are Phaser world scope and should not block current work. |
| #303 | feat: outdoor environment and building exterior — grass, roads, expansion plots | enhancement | close as obsolete/not planned | Outdoor office environment work is superseded by Minecraft world work. |
| #372 | perf: token bloat in long-running simulations — context window grows 5x | (none) | rewrite for Minecraft/current architecture | Token bloat remains relevant, but acceptance should reference Director V2/embodied prompt gates. |
| #373 | feat: focused tool coverage simulation for 11 missing tools | (none) | rewrite for Minecraft/current architecture | Tool coverage simulation should be aligned with E17/E18 command eval harnesses. |
| #417 | [Epic] Admin/Dashboard Bug Fixes — 22 issues from QA walkthrough (May 2026) | priority-high, epic, needs-human-input | needs human decision | Old admin QA epic has checked subissues; decide whether remaining acceptance still matters after pivot. |
| #435 | [Epic] Simulation-First Pivot — make simulations the primary product | priority-high, epic, needs-human-input | needs human decision | Simulation-first strategic epic is superseded by Minecraft/run-mode pivot; preserve useful public submission pieces only. |
| #449 | fix(api): /api/stats counters inconsistently scoped — total_simulations is global, conversations/cost are live-only | bug | keep as-is | Stats scoping is still a current API correctness bug. |
| #450 | fix(data): trust_score never populated — agent_relationships.trust_score is NULL for all rows | bug | good first issue after cleanup | Trust-score population is bounded data plumbing once current social graph expectations are confirmed. |
| #462 | fix(video): playwright not declared as dependency — render fails on every fresh env | bug, in-review | close as duplicate | Playwright is now declared in render/website deps; verify fresh-env render then close as completed/stale. |
| #464 | fix(ui): /simulations/[id]?tab=X doesn't auto-select tab on initial cold load | bug, in-review, frontend | good first issue after cleanup | Single website deep-link bug with low architectural risk. |
| #465 | fix(ui): SimulationContext picker stale on direct URL navigation between sims | bug, in-review, frontend | good first issue after cleanup | Single website stale-state navigation bug with low architectural risk. |
| #466 | chore(dev): EMAIL_PROVIDER=console — write magic links to a file/stream so QA can capture them | enhancement, in-review | good first issue after cleanup | Console email capture is local-dev contributor ergonomics and bounded. |
| #467 | polish(ui): Evals tab conditional visibility on running sims is surprising | enhancement, in-review, frontend | good first issue after cleanup | UI visibility polish is bounded after current IA is confirmed. |
| #468 | [Epic] Complete simulation→MP4 render + Epic #435 QA polish (6 issues) | priority-critical, epic, frontend | needs human decision | Old simulation-to-MP4 epic is legacy but may remain required until E14/E15 gates; decide whether to keep, rewrite, or close. |
| #475 | [Epic] Post-#468 QA — simulation exports must look like the live office | priority-critical, epic, frontend, needs-human-input | needs human decision | Office-export QA epic is legacy; close/rewrite child issues only after deciding E14/E15 replacement status. |
| #476 | fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles | bug, in-review, priority-critical, frontend | close as duplicate | Merged PR #485 says it closes this; verify acceptance and close as completed/duplicate. |
| #477 | fix(video): generate turn-level replay cues instead of conversation-sized blobs | bug, in-review, priority-critical, backend | close as duplicate | Merged PR #483 says it closes this; verify acceptance and close as completed/duplicate. |
| #478 | fix(video): serve local MP4 exports and expose render status to the website | bug, in-review, priority-critical, frontend, backend | keep as-is | Legacy MP4 serving remains useful until E14/E15 retire replacement path. |
| #479 | fix(auth): simulation creator magic-link overlay must not nest forms or reset draft | bug, in-review, priority-high, frontend | keep as-is | Magic-link UX is current public submission/auth surface, not Phaser-specific. |
| #480 | fix(simulations): public submissions must honor selected scenario agents and exclusions | bug, in-review, priority-high, frontend, backend | rewrite for Minecraft/current architecture | Public submissions should be reconciled with E12 run modes and embodied rosters. |
| #481 | feat(journals): show generated journal illustrations in agent journals | enhancement, in-review, priority-medium, frontend, backend | keep as-is | Journal publishing is explicitly preserved by E9. |
| #484 | fix(video): render worker must target the website replay route with current ports | bug, in-review, priority-critical, backend | keep as-is | Render-worker port/route correctness still matters while legacy replay exists. |
| #486 | fix(frontend): default WebSocket URLs should use backend port 8010 | bug, in-review, priority-high, frontend | good first issue after cleanup | Default URL/port bug is bounded and testable. |
| #492 | fix(video): replay render must honor simulation roster and fail closed on cue load errors | bug, in-review, priority-high, frontend, backend | keep as-is | Replay fail-closed behavior is required while legacy video remains enabled. |
| #493 | test(replay): visually assert office tilemap and multiple sprites in replay e2e | in-review, qa, priority-high, frontend | keep as-is | Replay visual test remains a guard until E14/E15 retirement gates pass. |
| #500 | QA(PR #499): MP4 export acceptance can still pass metadata while serving stale/dirty replay video | bug, ready, priority-critical, frontend, backend | keep as-is | Acceptance false-positive is a live risk for the legacy MP4 path until retirement. |
| #501 | QA(PR #499): magic-link creator flow cannot complete on normal dev stack without AUTH_JWT_SECRET | bug, ready, priority-critical, frontend, backend | needs security review | Auth flow failure around AUTH_JWT_SECRET touches public login and should block public launch. |
| #502 | QA(PR #499): documented simulation tab deep links `?tab=hypothesis` and `?tab=cost` still fall back to Overview | bug, ready, frontend | good first issue after cleanup | Simulation tab deep-link bug is bounded website polish. |
| #511 | Epic E9 — Dreams / Journals / Website Publishing Preserved | epic | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #512 | Epic E10 — Eval & Reporting Adapted | epic | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #513 | Epic E11 — Cost Controls & Kill Switch Hardened | epic, needs-human-input | needs security review | Cost controls and kill switch are public-autonomy blockers. |
| #514 | Epic E12 — Run-Mode / Starting-Conditions System | epic | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #515 | Epic E13 — Livestream Pipeline | epic, needs-human-input | needs human decision | Label already marks human input as required; keep out of automated cleanup until decided. |
| #516 | Epic E14 — Retire the Phaser Layer | epic | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #517 | Epic E15 — Website Adaptation | epic | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #572 | E8-1 — Generate all agent profiles from config (single source of truth) | in-review, backend, minecraft, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #573 | E8-2 — Embody cohort 1: Vera + Rex | in-review, minecraft, parallelizable, preserve-no-regress, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #574 | E8-3 — Embody cohort 2: Aurora + Pixel + Fork | in-review, minecraft, parallelizable, preserve-no-regress, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #575 | E8-4 — Embody cohort 3: Sentinel + Grok | in-review, minecraft, parallelizable, preserve-no-regress, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #576 | E8-5 — Map personality knobs -> Mindcraft conversation behavior | in-review, minecraft, needs-research, parallelizable | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #577 | E8-6 — Retire the Python conversation director for embodied runs | in-review, architecture, backend, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #578 | E8-7 — Management out-of-band on all bot chat | in-review, backend, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #579 | E8-8 — Multi-agent stability soak (hours) | in-review, qa, minecraft | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #580 | E8-9 — Cohort acceptance report | in-review, needs-human-input, minecraft | needs human decision | Label already marks human input as required; keep out of automated cleanup until decided. |
| #581 | E9-1 — Reflection runs on embodied activity | backend, parallelizable, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #582 | E9-2 — Dreams unchanged in embodied runs | backend, parallelizable, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #583 | E9-3 — Journal image generation still works | parallelizable, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #584 | E9-4 — Website publishing of journals/dreams intact | frontend, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #585 | E9-5 — Dreams/journals regression gate | qa, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #586 | E9-6 — Scenario fixtures updated (dream/reflection) | preserve-no-regress, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #587 | E10-1 — Eval data loader handles embodied events | backend, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #588 | E10-2 — Add a build-verification eval category | eval-finding, backend, parallelizable | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #589 | E10-3 — Preserve existing eval categories/suites | backend, parallelizable, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #590 | E10-4 — Reporting/scorecard reflects embodied metrics | backend, parallelizable | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #591 | E10-5 — Eval suite for the two run modes | backend, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #592 | E10-6 — Eval regression gate | qa, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #593 | E10-7 — Eval docs updated | documentation | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #594 | E11-1 — Audit & document current cost/kill mechanisms | in-review, architecture, backend, parallelizable | needs security review | Current cost/kill audit should include findings from this report. |
| #595 | E11-2 — Carry over per-simulation cost cap to persistent runs | in-review, backend, parallelizable, preserve-no-regress | needs security review | Rolling/persistent cost caps are required before 24/7 public autonomy. |
| #596 | E11-3 — Build hard per-agent hourly spend cap (NET-NEW) | in-review, priority-critical, backend, preserve-no-regress | needs security review | Hard per-agent hourly spend cap is explicitly missing and priority-critical. |
| #597 | E11-4 — Phone-accessible kill switch verified end-to-end | in-review, backend, preserve-no-regress | needs security review | Phone-accessible kill switch is emergency control and must be verified. |
| #598 | E11-5 — Kill switch halts the Node bots & world loop | in-review, priority-critical, minecraft, area:bridge | needs security review | Node bot/world-loop kill behavior is priority-critical. |
| #599 | E11-6 — Spend/kill alerting | in-review, backend | needs security review | Spend/kill alerting is part of public safety posture. |
| #600 | E11-7 — Cost/kill hardening regression gate | in-review, qa, preserve-no-regress | needs security review | Regression gate should become public launch gate. |
| #601 | E12-1 — Unified run-spec schema | backend, preserve-no-regress, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #602 | E12-2 — Backstory/persona -> Mindcraft profile injection | minecraft, parallelizable, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #603 | E12-3 — Factions/goals as inputs in embodied runs | backend, parallelizable, preserve-no-regress, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #604 | E12-4 — Seeded vs blank-slate memory for embodied runs | parallelizable, preserve-no-regress, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #605 | E12-5 — World as an input wired to E2 | minecraft, parallelizable, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #606 | E12-6 — Persistent 24/7 mode | backend, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #607 | E12-7 — Experimental short-run mode | backend, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #608 | E12-8 — Run-mode docs + examples | documentation, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #609 | E13-1 — Capture prototype (the E1-R6 method) | in-review, minecraft, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #610 | E13-2 — Encoder + RTMP push to Twitch/YouTube | in-review, parallelizable, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #611 | E13-3 — Stream overlays (agent labels, status) | in-review, parallelizable, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #612 | E13-4 — Audio/TTS in the stream | in-review, parallelizable, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #613 | E13-5 — 24/7 resilience (auto-recover capture/encoder/stream) | in-review, qa, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #614 | E13-6 — Stream kill path tied to the kill switch | in-review, priority-critical, area:livestream | needs security review | Stream kill path tied to kill switch is priority-critical public-broadcast control. |
| #615 | E13-7 — Stream health monitoring/alerting | in-review, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #616 | E13-8 — Livestream ops runbook | documentation, in-review, area:livestream | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #617 | E14-1 — Retirement readiness gate | architecture, needs-human-input | needs human decision | E14 retirement readiness is the formal deletion gate. |
| #618 | E14-2 — Remove the Phaser frontend | architecture, frontend, parallelizable | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #619 | E14-3 — Remove tilemap/office/sprite/PixelLab pipeline | architecture, backend, parallelizable | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #620 | E14-4 — Remove Phaser-canvas replay + its video render | frontend, backend, parallelizable | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #621 | E14-5 — Remove tools/world_state.py Redis-snapshot world API | backend, parallelizable | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #622 | E14-6 — Purge retired-system references in docs/CLAUDE.md | documentation | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #623 | E14-7 — Post-retirement full regression | qa | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #624 | E15-1 — Inventory website coupling to the Phaser world | architecture, frontend | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #625 | E15-2 — World page -> Minecraft world view | frontend, parallelizable, area:livestream | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #626 | E15-3 — Live page embeds the Minecraft stream | frontend, parallelizable, area:livestream | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #627 | E15-4 — Simulation/replay pages -> Minecraft recordings | frontend, parallelizable | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #628 | E15-5 — Simulation creator/list support new run modes | frontend, parallelizable, area:run-modes | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #629 | E15-6 — Website regression + visual check | qa, frontend | keep as-is | Formal legacy retirement/adaptation gate; do not close until E14/E15 acceptance passes. |
| #630 | E15-7 — Website adaptation acceptance | frontend, needs-human-input | needs human decision | E15 website acceptance decides when legacy replay/site coupling can retire. |
| #659 | Epic E16 — Pluggable Memory Backend + Memory Eval Harness | epic | keep as-is | Current memory-backend/eval epic aligns with docs and architecture. |
| #660 | E16-1 — Recall/Archival backend provider abstraction | backend, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #661 | E16-6 — Standalone eval harness + MemoryBackend protocol | eval-finding | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #662 | E16-2 — Answer Engine adapter: recall + archival | backend, area:bridge | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #663 | E16-4 — Typed memory-edge / graph layer | eval-finding, backend | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #664 | E16-5 — Write-time decision capture on the compaction path | eval-finding, backend | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #665 | E16-3 — Embedding ownership boundary + Answer Engine validation path | documentation, backend | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #666 | E16-7 — livestreamtoagi adapter for the eval harness (dogfood) | eval-finding, backend | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #667 | E16-8 — Eval-harness reporting + CI smoke integration | qa, eval-finding | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #668 | E16-9 — Backend parity + latency gate, ADR, docs | documentation, qa | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #706 | E8-10 — Action-command reliability gate for local LLM Minecraft sims | in-review, qa, minecraft, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #707 | E8-11 — Behavioral acceptance gate for collaborative embodied runs | in-review, qa, needs-human-input, minecraft, area:embodiment | needs human decision | Behavioral acceptance gate must be human-reviewed before fan-out. |
| #708 | E12-9 — Runtime Python-memory context injection for Mindcraft decisions | ready, backend, minecraft, preserve-no-regress, area:bridge, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #709 | E9-7 — Reflection/dream outputs influence later embodied behavior | ready, backend, minecraft, preserve-no-regress | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #710 | E12-10 — Embodied simulation supervisor lifecycle | ready, backend, minecraft, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #711 | E12-11 — Simulation Management policy modes | ready, backend, preserve-no-regress, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #712 | E12-12 — Shared task/world-state blackboard for embodied collaboration | ready, backend, minecraft, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #713 | E12-13 — Distress/rescue interrupt loop for stuck or endangered agents | ready, priority-high, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #714 | E10-8 — Build-quality feedback loop for embodied runs | ready, eval-finding, backend, minecraft | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #715 | E16-10 — Embodied memory-use eval for continuity | ready, qa, eval-finding, backend | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #718 | E8-12 — Structured timeline and LLM/token telemetry for embodied Minecraft runs | enhancement, in-review, qa, priority-high, backend, minecraft, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #719 | E8-13 — Live cohort monitor UI for embodied Minecraft soak evidence | enhancement, in-review, qa, priority-medium, frontend, backend, minecraft, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #720 | E8-14 — Harden Mindcraft action interruption and PathStopped crash recovery | bug, in-review, qa, priority-high, backend, minecraft, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #721 | E8-15 — Add autonomous heartbeat and idle-stall recovery for embodied agents | bug, in-review, qa, priority-high, backend, minecraft, area:embodiment | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #769 | Director V2: word-boundary agent name match in prompt gate | (none) | good first issue after cleanup | Prompt-gate word-boundary matching is narrow and testable once labels/context are added. |
| #770 | Director V2: centralize default agent→role map (remove hardcoded list in prompt_gate) | (none) | good first issue after cleanup | Centralizing the role map is bounded refactor with clear tests. |
| #771 | Director V2: move timeline NDJSON writes outside the prompt gate lock | (none) | keep as-is | Timeline write-lock performance issue is current Director V2 architecture work; add labels. |
| #774 | Epic E19 — Synthetic Command Data + Small Model Tuning | qa, eval-finding, epic, backend, minecraft, area:embodiment | keep as-is | Current E19 tuning epic is valid but depends on E17/E18 evaluator quality. |
| #775 | E12-14 — Multi-phase plan-build settlement scenario | ready, priority-medium, eval-finding, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #777 | E17-1 — Command schema extractor from Mindcraft + fork command definitions | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #778 | E17-2 — Action skill-card registry for move, observe, build, craft, gather, conversation, and safety | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #779 | E17-3 — Text scenario fixture generator/loadable dataset format | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #780 | E17-4 — Provider runner CLI with .env, local model, and OpenRouter support | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #781 | E17-5 — Parser and semantic evaluator using real command contracts | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #782 | E17-6 — Report/artifact writer and model comparison summaries | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #783 | E17-7 — Package scripts, docs, and regression tests | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #784 | E18-1 — Flat/starter world eval profile and deterministic launch config | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #785 | E18-2 — Individual command smoke CLI with verbose action telemetry | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #786 | E18-3 — Dataset replay runner consuming E17 passing artifacts | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #787 | E18-4 — Pathfinding/collision eval category | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #788 | E18-5 — Inventory and block mutation eval categories | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #789 | E18-6 — Death-loop, stuck/unstuck, and safe-spawn eval categories | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #790 | E18-7 — Multi-agent timing/action-queue eval category | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |
| #791 | E18-8 — Live report artifacts and package scripts | ready, in-review, qa, backend, minecraft, area:embodiment, area:run-modes, area:server | keep as-is | Current Minecraft/pivot-era epic or child issue; labels and status match active architecture. |

## Recommended Next Steps

1. Disable or fix `POST /agents/{agent_id}/chat` so it uses `complete()` and Management review before any public response.
2. Treat E11 (#513/#596/#598/#600) and E13 kill-path issue #614 as public-launch blockers.
3. Update `AGENTS.md`, `CLAUDE.md`, package metadata, and create `docs/OPEN_SOURCE_READINESS.md` with a gate checklist linking to this report.
4. Triage old office/Phaser issues in one explicit pass: close #299-#303, decide #468/#475/#435/#417, and keep replay/video bugs only where they guard E14/E15.
5. Document the builder-provider OpenRouter exception or route it through the Python bridge/LLM client so cost/Langfuse/governor visibility is centralized.
