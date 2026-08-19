# Blog Evidence Ledger

Status: draft support doc for approving and writing the backdated blog series

Purpose: give every approved post a source trail before it becomes an MDX file.
This is not the blog series itself. It is the evidence map to use while turning
`docs/BLOG-EDITORIAL-PLAN.md` into publishable posts.

## Date Integrity

- First repository commit: 2026-03-30, commit `45e38268`.
- No launch post should be dated before 2026-03-30 unless it is explicitly
  labeled as pre-repo context.
- Blog dates should follow the commit or issue date for the system move being
  described, not the date the post is drafted.
- If a post combines several days of work, use the date when the decisive
  design or merge landed.

## Git Timeline Anchors

| Date range | Blog arc | Representative commits |
| --- | --- | --- |
| 2026-03-30 | Origin and thesis | `45e38268` project structure, specs, configs, documentation. |
| 2026-03-31 | Reproducible substrate | `6d2d3080` FastAPI/uv, `b140c858` Docker services, `31110691` Next.js website, `05148ae9` non-conflicting ports. |
| 2026-04-01 | Centralized LLM and observability path | `7c228e14` OpenRouter client with cost tracking, `485eee52` agent loader, `72d82a14` event bus, `ca728459` security hardening. |
| 2026-04-02 | Agent cast, memory, context, conversation primitives | `f927cb20`, `9f29d511`, `a329853c`, `5f3a1584`, `95f6131a`, `c58ddcdd`, `797c978a`, `808f998b`, `57b74c78`, `94ebe480`. |
| 2026-04-03 | Tools, TTS, Management, simulation bench | `c5aa3878`, `80bfbfe0`, `6ad86fd1`, `40d52b14`, `fd9c74e6`, `5b8b433c`, `30261735`, `7de0f472`, `652860ff`. |
| 2026-04-03 to 2026-04-04 | QA and eval instrumentation | `de94945e`, `e364c03c`, `a569cb37`, `9aa92d97`, `da05c8dd`, `ef609af0`. |
| 2026-04-04 to 2026-04-05 | Negative results and evolution loop | `a6da3ea0`, `ee86e555`, `f8f5e2e4`, `ec57d908`, `8e2178db`, `c76b6c5c`, `c809620a`, `e750a29b`, `3595e6ba`. |
| 2026-04-07 to 2026-04-08 | Autonomy and internal economy | `f5499c7d`, `d68477ac`, `02648bc3`, `2b5927d9`, `285ea65f`, `9d72e942`, `486a1e06`. |
| 2026-04-08 to 2026-04-09 | Phaser office and useful failure | `326d3525`, `8bdb695c`, `263f398c`, `6ec31cd1`, `204fcd64`, `5d5c5557`, `e8b227d5`. |
| 2026-04-10 to 2026-04-12 | Public website, isolation, compaction | `be0141de`, `02d3ea65`, `4dd5338b`, `ecc0934b`, `99e5a0d4`, `b01cc321`. |
| 2026-05-07 to 2026-05-09 | Simulation-first product and replay fidelity | `cf3726fe`, `f2e46cd6`, `7286d909`, `75e895f4`, `69b94f16`, `062a4920`, `80e8ce1a`, `27752b3f`, `77bcf622`, `dde34a60`, `039d148b`. |
| 2026-05-17 to 2026-05-18 | Minecraft pivot, server, Mindcraft, bridge | `65e67b25`, `427e658f`, `1dcb3293`, `fde3340e`, `a9cedf41`, `f7bdaeed`, `dfc7b9b7`, `0daec3fe`. |
| 2026-05-18 to 2026-05-20 | Memory exposure, embodiment, Alpha, all-agent embodiment | `acc1961b`, `96f0f136`, `b2bec526`, `1d662024`, `baf13ef1`, `0daec3fe`, session summaries for E6/E7/E8. |
| 2026-05-20 to 2026-05-23 | Cost/kill, livestream, Director V2, Minecraft evals | `2dd70dc2`, `61078296`, `4a806ff9`, `c0ff268c`, `bf7a6cc7`, `fddabc29`, `59aadebf`, E17/E18 commits through `bd6932fa`. |
| 2026-05-23 to 2026-05-25 | Run modes, dreams/journals, embodied evals | `f6d37142`, `9715e971`, `70fc4195`, `3cf773e5`, `5816287f`, `c559fab7`, `ca78b3ab`, `3b670f48`. |
| 2026-05-25 to 2026-05-26 | Headless sim and Minecraft replay pipeline | `e00931d9`, `50713cb5`, `6bad5b36`, `e5836150`, `9f7ba740`, `2ba1cf13`, `2aa6a589`. |
| 2026-05-26 to 2026-05-29 | BuildScripts, RCON, civilization mechanics, emergent task board | `d107efcb`, `27462f92`, `64aa4755`, `b6ed368d`, `5cb4d57a`, `6b934cf8`, `571b1210`, `a2e31af7`, `e3cc8630`, `9e7ef3fd`, `8bc34469`. |
| 2026-06-04 | Evidence debt and observability cleanup | `92eed67b`, `c373e8b8`. |

## GitHub Issue Anchors

| Issue range | Meaning for the blog series |
| --- | --- |
| #1, #2, #5, #6, #34, #55 | Project substrate, service topology, LLM client, agent registry, event bus, website shell. |
| #7-#15 | Agent configs as controlled experimental variables. |
| #16-#21 | Three-tier memory and context assembly. |
| #22-#32 | Conversation engine mechanics and decision logging. |
| #33, #35-#43, #143 | TTS, tools, action parsing, and the transition from characters to agents. |
| #145-#158, #186-#195 | Simulation bench, artifacts, evals, dashboard, seed scenarios, and timeline reporting. |
| #168-#175 | QA pass exposing unwired tools, dummy embeddings, startup memory gaps, and compaction/reflection gaps. |
| #206-#217, #220-#221, #238-#242 | Eval UI, quality failures, Management rename, agency dimension, and evolution loop. |
| #267-#275 | Autonomy, internal economy, goals, budgets, factions, events, and dreams. |
| #258-#264, #276-#279, #326-#331 | Phaser office and public website surfaces. |
| #252 | Simulation isolation, snapshots, clones, scoped Redis, and simulation IDs. |
| #395-#416 | Admin dashboard QA walkthrough and simulation product maturity. |
| #418-#435 | Simulation-first pivot. |
| #462-#495 | Replay fidelity and MP4 export correctness. |
| #503-#532 | Minecraft pivot context and server foundation. |
| #533-#539 | Mindcraft fork evaluation. |
| #540-#548 | Python-to-Node bridge, Management/cost/kill integration. |
| #549-#555, #658 | Memory service exposure for embodied runs. |
| #556-#564 | Embodiment action layer and failure taxonomy. |
| #565-#580, #706-#721 | Alpha vertical slice and all-agent embodiment. |
| #594-#600 | Cost controls and kill switch hardening. |
| #609-#616 | Livestream pipeline as operations system. |
| #750-#758 | Director V2 and evidence-based coordination. |
| #772-#783 | E17 text-only Minecraft command eval harness. |
| #784-#791 | E18 flat-world live Minecraft command eval jobs. |
| #808-#813 | Open-source readiness gates. |
| #581-#586, #709 | Dreams, journals, and website publishing preserved through embodiment. |
| #587-#593, #714 | Embodied eval reporting. |
| #601-#608, #708-#713, #775 | Run modes and starting conditions. |
| #850-#861, #871-#876 | Headless sim, Minecraft replay, BuildIntent, compiler, screenshot feedback, build-quality scoring. |
| #820-#821, #891-#918 | Open settlement smoke, civilization ledgers, emergent task board, and claim-to-build authorization. |

## Alpha-Loop Learning Anchors

Use these session summaries as research-method evidence. They are especially
valuable for posts that need to show what failed between unit tests, review,
and real system runs.

| Epic | File(s) | Blog use |
| --- | --- | --- |
| 435 simulation-first pivot | `.alpha-loop/learnings/session-summary-session-epic-435-epic-simulation-first-pivot-make-simulations-the-primary-product.md` | Product pivot, creator form, workspace, simulation evidence surface. |
| 504 Minecraft server setup | `.alpha-loop/learnings/session-summary-session-epic-504-epic-e2-minecraft-server-setup-beginner.md` | Beginner-runbook discipline, server setup friction, local reproducibility. |
| 505 Mindcraft fork | `.alpha-loop/learnings/session-summary-session-epic-505-epic-e3-mindcraft-fork-evaluation.md` | Minimal fork divergence, profile generation, model routing. |
| 506 Python-Node bridge | `.alpha-loop/learnings/session-session-epic-506-epic-e4-python-node-bridge.json` | Contract-first bridge, Management/cost/kill integration. |
| 507 memory service exposure | `.alpha-loop/learnings/session-summary-session-epic-507-epic-e5-memory-service-exposure.md` | Thin bridge adapters delegate to canonical memory managers. |
| 508 embodiment action layer | `.alpha-loop/learnings/session-summary-session-epic-508-epic-e6-embodiment-action-layer.md` | Independent verification beats trusting runtime success labels. |
| 509 Alpha vertical slice | `.alpha-loop/learnings/session-summary-session-epic-509-epic-e7-alpha-vertical-slice.md` | Evidence freshness, errand verbs, acceptance report. |
| 510 all-agent embodiment | `.alpha-loop/learnings/session-summary-session-epic-510-epic-e8-all-agents-embodied-decentralized-conversation.md` | Decentralized conversation, all-agent profiles, soak limits. |
| 513 cost/kill | `.alpha-loop/learnings/session-summary-session-epic-513-epic-e11-cost-controls-kill-switch-hardened.md` | Environment/preflight failures vs code failures, kill path hardening. |
| 514 run modes | `.alpha-loop/learnings/session-summary-session-epic-514-epic-e12-run-mode-starting-conditions-system.md` | RunSpec, world inputs, shared blackboard, rescue loops. |
| 515 livestream | `.alpha-loop/learnings/session-summary-session-epic-515-epic-e13-livestream-pipeline.md` | Streaming reliability, capture/encoder ops, monitoring. |
| 749 Director V2 | `.alpha-loop/learnings/session-summary-session-epic-749-epic-e8-5-minecraft-director-v2-tool-parity.md` | Coordination layer backed by evidence and tool parity. |
| 772 E17 command eval | `.alpha-loop/learnings/session-summary-session-epic-772-epic-e17-text-only-minecraft-command-eval-harness.md` | Text-only command parsing before live world risk. |
| 773 E18 live eval | `.alpha-loop/learnings/session-summary-session-epic-773-epic-e18-flat-world-live-minecraft-command-eval-jobs.md` | Live flat-world evals, action telemetry, safe spawn/death loop categories. |
| 820 civilization readiness | `.alpha-loop/learnings/session-summary-session-epic-820-epic-e21-autonomous-minecraft-civilization-readiness.md` | Emergent task board, claim-to-build, collaborative settlement limits. |
| 850 headless replay | `.alpha-loop/learnings/session-summary-session-epic-850-epic-e22-headless-sim-minecraft-replay-pipeline.md` | Unit-green no-ops when per-run services are not threaded into production construction sites. |

## Docs And Specs Anchors

| Theme | Primary files |
| --- | --- |
| Project thesis and implementation plan | `specs/ENGINEERING-SPECS.md`, `specs/FINAL-IMPLEMENTATION-PLAN.md`, `research/RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md`. |
| Agent identities and model assignment | `agents/`, `specs/CHARACTER-SHEETS.md`, `docs/model-configuration.md`, `core/model_config.py`. |
| Memory and context | `specs/MEMORY-SYSTEM.md`, `core/memory/`, `core/context_assembly`, `core/system_prompt`. |
| Conversation engine | `specs/CONVERSATION-ENGINE.md`, `core/conversation_engine.py`, `core/conversation/`. |
| Management and TTS safety | `core/management.py`, `core/tts`, `docs/cost-kill-audit.md`. |
| Simulation-first system | `core/simulation/`, `evals/prompts/`, `website/src/app/simulations`, `docs/SCENARIO-AUTHORING.md`. |
| Minecraft pivot and decisions | `specs/MINECRAFT-PIVOT-CONTEXT.md`, `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md`, `docs/decisions/0000-summary.md`, `docs/decisions/0010-bridge-protocol.md`, `docs/decisions/0011-director-v2-architecture.md`. |
| Minecraft bridge and action reliability | `docs/minecraft/bridge-contract.md`, `docs/minecraft/failure-taxonomy.md`, `docs/minecraft/action-command-reliability.md`, `core/embodiment/`, `core/minecraft/`, `mindcraft/`. |
| Minecraft command evals | `docs/minecraft/command-eval.md`, `docs/minecraft/open-settlement-smoke.md`, `docs/minecraft/emergent-mode.md`. |
| Run modes and embodied evals | `docs/run-modes.md`, `docs/run-modes/blank-slate-embodied.md`, `docs/eval-embodied.md`. |
| Replay and artifacts | `docs/MINECRAFT-REPLAY.md`, `core/minecraft/replay/`, `snapshots/headless/`. |
| Livestream operations | `docs/livestream/`, `core/streaming/`, `core/livestream/`. |

## Eval, Log, And Snapshot Anchors

| Artifact type | Paths to inspect before drafting |
| --- | --- |
| Early eval results | `evals/results/eval-e24db48d-1e96-4630-9456-72cc8f22f221.json` and neighboring `evals/results/*.json`. |
| Eval prompts | `evals/prompts/*.yaml`, especially agency, social dynamics, safety, productivity, errors, world evolution, and build verification. |
| Soak run summaries | `logs/soak-safe/20260520T165606Z/summary.txt`, `logs/overnight-e12-minecraft/20260524T154739Z/`, `logs/env-driven-large-meadow-shakeout/20260525T064541Z/`. |
| Open settlement evidence | `logs/open-settlement-90m/`, `logs/open-settlement-shakeout/`, `logs/trial-2026-05-27/20260528T060953Z/acceptance-report.md`. |
| Headless snapshots | `snapshots/headless/`, especially `_open_settlement_smoke_preflight.json`. |
| Cost evidence | `logs/openrouter-activity-reconciliation-20260525-015501.csv`, cost-ledger TSVs under Minecraft soak logs. |
| Decision-log and replay schema evidence | `core/simulation/decision_log_schema.py`, `docs/minecraft/timeline-schema.md`, `docs/MINECRAFT-REPLAY.md`. |

## Drafting Checks Per Post

Before drafting any approved post:

1. Confirm the date against `git log --all --date=short`.
2. Confirm the issue range with `gh issue view` or the commit message.
3. Read at least one local doc/spec tied to the topic.
4. Inspect at least one alpha-loop, eval, log, or snapshot artifact when the
   post makes a claim about behavior.
5. Include a limitation or negative result unless the post is purely an ADR.
6. Avoid changing dates to make the narrative cleaner.

## Approval Boundary

This ledger is preparatory. It does not approve writing or replacing
`website/content/blog/*.mdx`. The next step after approval is to draft the
approved launch batch using this ledger and `docs/BLOG-WRITING-PLAYBOOK.md`.
