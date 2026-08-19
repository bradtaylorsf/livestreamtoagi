# Blog Editorial Plan

Status: draft for approval

Purpose: replace the current placeholder blog set with a backdated research
notebook that follows the actual commit, issue, alpha-loop, doc, eval, and
simulation history of Livestream to AGI. The intended audience is AI
researchers, research engineers, and hiring managers evaluating Brad Taylor's
ability to design, instrument, debug, and communicate multi-agent AI systems.

Approval summary: `docs/BLOG-APPROVAL-SUMMARY.md`.
Machine-readable manifest: `docs/BLOG-SERIES-MANIFEST.tsv`.
Launch-batch evidence dossiers: `docs/BLOG-LAUNCH-DOSSIERS.md`.
Placeholder replacement audit: `docs/BLOG-PLACEHOLDER-REPLACEMENT-AUDIT.md`.
Companion writing rules: `docs/BLOG-WRITING-PLAYBOOK.md`.
Companion source ledger: `docs/BLOG-EVIDENCE-LEDGER.md`.

## Source Evidence

The plan below is grounded in these local sources:

- `git log --all --date=short`, especially first commit `45e38268` on
  2026-03-30 and the commit clusters from 2026-04-02 through 2026-05-29.
- GitHub issues and milestones: early layers #1-#71, simulation/eval issues
  #145-#252, simulation-first pivot #418-#435, Minecraft pivot #503-#630,
  E17/E18 evals #772/#773, E21 civilization readiness #820, and E22 headless
  replay #850.
- Alpha-loop summaries under `.alpha-loop/learnings/`, especially sessions
  epic-435, epic-504, epic-505, epic-507, epic-508, epic-509, epic-510,
  epic-513, epic-514, epic-515, epic-749, epic-772, epic-773, epic-820, and
  epic-850.
- Architecture docs in `specs/` and `docs/`, including the memory system,
  conversation engine, Minecraft pivot context, Minecraft decision records,
  run modes, cost/kill audit, Director V2 docs, command eval docs, and replay
  docs.
- Evals and simulation artifacts in `evals/results/`, `logs/`, and
  `snapshots/headless/`.

## Editorial Rules

1. Backdate each post to the date the corresponding work landed in the repo,
   not the date the replacement blog is written.
2. Write in a first-person research notebook voice: clear, technical, candid,
   and evidence-driven.
3. Prefer "what I learned" over "what I built" unless the build itself is the
   research contribution.
4. Do not overclaim. Negative results such as repetition loops, missing
   collaboration scenes, environment failures, and production wiring gaps should
   be treated as core research evidence.
5. Every post should make a hiring-manager signal visible: systems taste,
   experimental discipline, debugging maturity, safety posture, or ability to
   connect implementation to research questions.
6. Existing placeholder posts should be replaced rather than patched in place
   when their dates or claims are not grounded in the repository history.

## Current Blog Audit

| Current slug | Current date | Recommendation | Why |
| --- | --- | --- | --- |
| `first-week-lessons` | 2026-03-21 | Replace | Predates first commit by 9 days; should not ship as backdated history. |
| `conversation-engine-deep-dive` | 2026-03-28 | Replace | Predates implementation; fold into the 2026-04-03 conversation engine post. |
| `why-a-reality-show-for-ai` | 2026-04-01 | Replace/expand | Good seed angle, but should be tied to first commits and research thesis. |
| `why-agi-is-tongue-in-cheek` | 2026-04-01 | Replace/merge | Best as a section in the origin or economics posts. |
| `multi-model-matters` | 2026-04-02 | Replace/expand | Keep topic, tie to agent configs and model routing commits. |
| `designing-memory-for-agents` | 2026-04-03 | Replace | Correct topic, but date should align with 2026-04-02 memory commits. |
| `who-talks-next` | 2026-04-04 | Replace | Topic is correct; date/angle should be tied to 2026-04-02/03 engine work. |
| `the-management-problem` | 2026-04-05 | Replace | Good topic; should include Management rename and filter tuning. |
| `why-ai-agents-are-reactive` | 2026-04-06 | Replace | Strong topic; align with 2026-04-05/08 autonomy evals and implementation. |
| `eval-framework` | 2026-04-07 | Replace | Keep, but make the eval failures central rather than presenting the framework as solved. |
| `agent-dreams` | 2026-04-08 | Replace | Keep topic; include that early evals found zero dream entries before fixes. |
| `economics-of-artificial-life` | 2026-04-09 | Replace | Keep topic; anchor in cost governor, pricing, kill switch, and later E11. |
| `62-simulations-retrospective` | 2026-04-10 | Replace | Useful retrospective frame, but should not assert unverified anecdotes. |
| `what-we-got-wrong` | 2026-04-10 | Replace | Keep spirit; distribute failures into the chronological lab notebook. |

## Replacement Mechanics

Recommended default: replace the current MDX files with the new
research-notebook slugs. The current URLs are not yet valuable enough to justify
keeping inaccurate dates, and the new slugs make the site read as a deliberate
research corpus instead of a small set of launch essays.

If SEO/backlink preservation matters later, add redirects after the new posts
exist:

| Current slug | Redirect or replacement target |
| --- | --- |
| `first-week-lessons` | Delete or redirect to `repetition-problem` after launch. |
| `conversation-engine-deep-dive` | Redirect to `first-conversation-engine`. |
| `why-a-reality-show-for-ai` | Redirect to `research-harness-not-demo`. |
| `why-agi-is-tongue-in-cheek` | Fold into `research-harness-not-demo` and `llm-call-ledger`; delete standalone. |
| `multi-model-matters` | Redirect to `agents-as-experimental-variables`. |
| `designing-memory-for-agents` | Redirect to `three-tier-agent-memory`. |
| `who-talks-next` | Redirect to `first-conversation-engine`. |
| `the-management-problem` | Redirect to `management-before-microphones` or `overseer-to-management`. |
| `why-ai-agents-are-reactive` | Redirect to `reactive-to-proactive-agents`. |
| `eval-framework` | Redirect to `llm-judge-social-systems`. |
| `agent-dreams` | Redirect to `dreams-as-control-mechanism`. |
| `economics-of-artificial-life` | Redirect to `llm-call-ledger` at first, then `autonomy-needs-kill-switch` after the Minecraft arc is written. |
| `62-simulations-retrospective` | Redirect to `simulation-first-pivot` or `negative-result-activity-not-collaboration`. |
| `what-we-got-wrong` | Redirect to `repetition-problem`. |

## Proposed Replacement Series

| Date | Slug | Title | Summary | Main evidence |
| --- | --- | --- | --- | --- |
| 2026-03-30 | `research-harness-not-demo` | The Research Harness: Why a Livestreamed Agent World | Introduce the project as a longitudinal multi-agent research instrument: persistent agents, shared world, budget pressure, audience feedback, and public evidence. The point is not AGI branding; it is creating conditions where memory, coordination, and action can fail visibly. | Commit `45e38268`; `specs/ENGINEERING-SPECS.md`; `research/RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md`. |
| 2026-03-31 | `reproducible-agent-infrastructure` | Reproducible Infrastructure for Agent Experiments | Explain why the first real research work was boring infrastructure: FastAPI, Docker, Postgres, Redis, pgvector, Next.js, nonstandard ports, and repeatable local services. Emphasize that multi-agent claims need a reproducible substrate. | Issues #1, #2, #55; commits `6d2d3080`, `b140c858`, `31110691`; AGENTS.md non-negotiables. |
| 2026-04-01 | `llm-call-ledger` | Every LLM Call Needs a Ledger | Argue that agent autonomy without cost visibility is theatre. Introduce OpenRouter routing, model config, Langfuse/cost-governor intent, and the early design decision that all model calls must route through one client. | Issue #5; commit `7c228e14`; `core/llm_client.py`; `core/model_config.py`; `docs/model-configuration.md`. |
| 2026-04-02 | `agents-as-experimental-variables` | Casting Agents as Experimental Variables | Cover the nine-agent config layer and how personality, role, and model assignment became experimental variables. Hiring angle: designing a system where behavior can be attributed to explicit configuration rather than prompt sprawl. | Issues #7-#15; commits #96-#106; `agents/`; `specs/CHARACTER-SHEETS.md`. |
| 2026-04-02 | `three-tier-agent-memory` | A Three-Tier Memory System for Persistent Agents | Describe core, recall, and archival memory as the answer to identity drift and context exhaustion. Focus on the boundary between always-in-prompt identity, semantic retrieval, and never-deleted transcripts. | Issues #16-#21; commits `f927cb20`, `9f29d511`, `a329853c`, `5f3a1584`, `95f6131a`, `c58ddcdd`; `specs/MEMORY-SYSTEM.md`. |
| 2026-04-02 | `context-assembly-control-surface` | Context Assembly Is Where the Agent Actually Lives | Show that the assembled prompt is the real runtime interface for memory, personality, current situation, tools, and safety. This can be a technical bridge from memory to conversation. | Issue #21; `core/context_assembly`; `core/system_prompt`; memory commits. |
| 2026-04-03 | `first-conversation-engine` | Who Talks Next? Building the First Conversation Engine | Deep dive into weighted speaker selection, hot-reload config, topic detection, interrupts, pacing, proximity, energy, triggers, and decision logging. End by noting that central direction worked for simulation, but later became a limitation. | Issues #22-#32; commits `797c978a` through `94ebe480`; `specs/CONVERSATION-ENGINE.md`; `core/conversation_engine.py`. |
| 2026-04-03 | `management-before-microphones` | Management Before Microphones | Explain why the content filter and TTS path had to exist before public output. Cover Management as out-of-band safety, not a world character, and the 3-second intervention model. | Issues #31, #33, #143; `core/management.py`; commits `40a4ac0b`, `c5aa3878`, `5b8b433c`. |
| 2026-04-03 | `tools-turn-characters-into-agents` | Tools Turn Characters Into Agents | Move from dialogue to action surface: memory tools, code sandbox, audience, social/revenue, web search, tilemap, self-modification, and Alpha dispatch. The angle is that tools reveal whether an agent can act, not just talk. | Issues #35-#43; commits #134-#142; `tools/`; tool security fixes. |
| 2026-04-04 | `simulations-as-lab-bench` | Simulations Became the Lab Bench | Explain the first major internal pivot: building full-day simulations, artifact persistence, admin dashboards, seed scenarios, eval runners, and timeline reporters so claims could be measured across runs. | Issues #145-#158, #186-#195; commits #160-#204; alpha-loop layer 7.5 summaries. |
| 2026-04-04 | `qa-as-research-method` | QA as a Research Method | Use the memory/conversation QA pass to show how bugs became scientific findings: tools not wired, dummy embeddings, compaction bypasses, startup state gaps, reflection scheduler gaps. | Issues #168-#175; commit `de94945e`; alpha-loop reviewer learnings. |
| 2026-04-04 | `repetition-problem` | The Repetition Problem | Publish the uncomfortable eval result: agents repeated conversations, bled identities, skipped speakers, and talked without acting. Frame repetition as the first decisive measurement failure. | Eval `e24db48d`; issues #213-#217 and #229-#236; commits `ef609af0`, `9dfc28b2`. |
| 2026-04-04 | `llm-judge-social-systems` | LLM-as-Judge Evals for Artificial Social Systems | Introduce the 12-category eval suite as a pragmatic measurement layer for dialogue, entertainment, safety, agency, productivity, errors, social dynamics, and world evolution. Include limits and failure modes. | Issues #155-#158, #206-#212, #240-#242; `evals/prompts/`; eval JSONs. |
| 2026-04-04 | `overseer-to-management` | From Overseer to Management | Explain the rename and filter relaxation as a product/research correction: safety needs authority, but too much filtering suppresses social dynamics. | Issues #220-#221; commits `a6da3ea0`, `ee86e555`, `f8f5e2e4`. |
| 2026-04-05 | `first-evolution-loop` | The First Evolution Loop | Cover DB-backed versioned configs, intrinsic drives, agency evals, eval analyzer, and simulate -> eval -> improve. Position it as early automated research operations, not self-improvement hype. | Issues #238-#242; commit `3595e6ba`; alpha-loop usage. |
| 2026-04-08 | `reactive-to-proactive-agents` | Making Reactive Agents Proactive | Explain the diagnosis from `AGENT-AUTONOMY-EVAL-STRATEGY.md`: statelessness, dead initiative, reactive goals, stale external data, and shared budget flattening tension. Then cover internal state, initiative, goals, budgets, factions, events, dreams. | Issues #267-#275; commit `285ea65f`; `specs/AGENT-AUTONOMY-EVAL-STRATEGY.md`. |
| 2026-04-08 | `dreams-as-control-mechanism` | Dreams as a Control Mechanism | Make this candid: early evals found zero dream entries, then dream bugs were fixed. Explain dreams as high-temperature reflection to break loops and generate goals, not as mysticism. | Commits `9d72e942`, `486a1e06`; evals showing missing dreams; dream/journal code. |
| 2026-04-09 | `pixel-office-useful-failure` | The Pixel Office Was a Useful Failure | Cover Phaser, sprites, office layout, speech bubbles, ambient movement, activity indicators, and why a rendered office still did not create verifiable physical action. This sets up the Minecraft pivot. | Layer 8 commits; issues #44-#51, #258-#264, #276-#279; `frontend/`; office commits. |
| 2026-04-10 | `public-website-research-surface` | Public Website as Research Surface | Explain the website as more than marketing: public agent profiles, world pages, evals, challenges, conversations, API routes, and making the project inspectable by outside researchers. | Layer 10 issues #56-#68, #326-#331; commits `be0141de`, #348-#350; `website/`. |
| 2026-04-10 | `simulation-isolation-counterfactuals` | Simulation Isolation and Counterfactual Runs | Describe simulation-scoped Redis/memory, snapshots, clones, and `simulation_id` propagation. Research angle: credible counterfactuals require isolated state. | Issue #252; commits `02d3ea65`, `4dd5338b`, `ecc0934b`, `99e5a0d4`; `research/RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md`. |
| 2026-04-12 | `token-bloat-memory-compaction` | Token Bloat, Compaction, and Long-Running Agents | Explain long-run token bloat and why compaction is not an optimization but a survival requirement for persistent agents. | Commit `b01cc321`; memory/eval logs; `core/memory/`. |
| 2026-05-07 | `dashboard-walkthrough-product-shift` | The Dashboard Walkthrough That Changed the Product | Use the admin/dashboard QA burst to show the product maturing around simulations: route scoping, pickers, eval buttons, snapshot views, structured config, relationship data, and page clarity. | Epic 417 issues #395-#416; alpha-loop summary; commits #437-#447. |
| 2026-05-08 | `simulation-first-pivot` | The Simulation-First Pivot | Major post. Reposition simulations as the primary product: public submissions, hypothesis/outcomes/learnings, memory seed, energy timeline, creator form, workspace tabs, MP4 export, and YouTube publishing. | Epic 435 issues #418-#435; commits #451-#461; alpha-loop summary. |
| 2026-05-09 | `replay-fidelity-research-fidelity` | Replay Fidelity Is Research Fidelity | Argue that if replay is wrong, the evidence is wrong. Cover turn-level cues, real office render, roster correctness, current ports, fail-closed cue loading, MP4 status, and visual regression. | Epic 468/475 issues #462-#495; alpha-loop summaries; render/replay commits. |
| 2026-05-17 | `minecraft-pivot` | The Minecraft Pivot | Explain why the project moved from Phaser to Minecraft: tilemap JSON was not enough; agents needed a concrete action space with independent verification. | Commit `65e67b25`; `specs/MINECRAFT-PIVOT-CONTEXT.md`; `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md`. |
| 2026-05-17 | `choosing-embodiment-stack` | Choosing the Embodiment Stack | Decision-record post: Paper 1.21.6, Mindcraft pin, Mineflayer, Node 20, Java 21, offline dev auth, OBS capture path, and launch gates. | Commit `427e658f`; `docs/decisions/0000-summary.md` through `0007`; issues #518-#524. |
| 2026-05-18 | `forking-mindcraft` | Forking Mindcraft Without Losing the Thesis | Cover reproducible Mindcraft install, model routing, profile schema, minimal reversible fork divergence, and config-bound generation of profiles. | E3 issues #533-#539; alpha-loop epic-505 summary; docs/minecraft/mindcraft-fork.md. |
| 2026-05-18 | `python-node-bridge` | The Python-to-Node Bridge | Explain the authenticated bridge between Minecraft bodies and the Python brain: memory, Management, cost gates, kill switch, observability, and why WebSocket won over HTTP. | E4 issues #540-#548; commit `0daec3fe`; `docs/decisions/0010-bridge-protocol.md`; `docs/minecraft/bridge-contract.md`. |
| 2026-05-19 | `memory-leaves-office` | Memory Leaves the Office | Show how the three-tier memory architecture moved into embodied runs through bridge services while preserving canonical managers. Emphasize avoiding duplicated memory semantics in bridge handlers. | E5 issues #549-#555, #658; alpha-loop epic-507 summary; memory bridge docs. |
| 2026-05-19 | `verification-over-vibes` | Verification Over Vibes | Core embodied-agent research post. Movement, block placement, perception, action failure taxonomy, build-from-plan, and Python-side verification of Node/Minecraft outcomes. | E6 issues #556-#564; alpha-loop epic-508 summary; `docs/minecraft/failure-taxonomy.md`. |
| 2026-05-20 | `alpha-vertical-slice` | Alpha as the Vertical Slice | Tell the end-to-end story of Alpha: profile, errand poll/complete verbs, verified in-world errand, memory write, Management review, cost gate, kill switch, acceptance report. | E7 issues #565-#571; alpha-loop epic-509 summary; `docs/minecraft/alpha-slice-report.md`. |
| 2026-05-20 | `retiring-central-director` | Retiring the Central Director | Explain all-agent embodiment, generated profiles, personality mapping, Management out-of-band, stability soaks, and the difference between decentralized conversation and Director V2. | E8 issues #572-#580, #706-#721; `docs/decisions/0004-decentralized-conversation.md`; soak logs. |
| 2026-05-21 | `autonomy-needs-kill-switch` | Autonomy Needs a Kill Switch | Expand the economics theme with hardened per-simulation caps, per-agent hourly caps, phone-accessible kill switch, bot/world halting, spend alerting, and test preflight learnings. | E11 issues #594-#600; alpha-loop epic-513 summary; `docs/cost-kill-audit.md`; `docs/kill-switch-operator.md`. |
| 2026-05-21 | `livestream-pipeline-ops-system` | A Livestream Pipeline Is an Ops System | Cover capture, RTMP, overlays, TTS in stream, resilience, stream kill path, monitoring, and why production streaming is reliability engineering. Include environment-failure lessons. | E13 issues #609-#616; alpha-loop epic-515 summary; `docs/livestream/`. |
| 2026-05-22 | `director-v2-evidence-coordination` | Director V2: Back to Coordination, But With Evidence | Explain why pure decentralized behavior needed a coordination layer: scene inbox, spatial hearing, turn scheduler, prompt gates, memory digests, tool parity, macro scheduling, scale gates. | E8.5 issues #750-#758; alpha-loop epic-749 summary; `docs/decisions/0011-director-v2-architecture.md`. |
| 2026-05-23 | `minecraft-commands-without-minecraft` | Testing Minecraft Commands Without Minecraft | E17 post: text-only command eval harness, schema extraction, skill cards, fixture format, provider runner, parser and semantic evaluator, report writer, deterministic dry-run paths. | E17 issues #777-#783; alpha-loop epic-772 summary; `docs/minecraft/command-eval.md`. |
| 2026-05-23 | `flat-world-live-evals` | From Text Commands to Live Flat-World Evals | E18 post: flat-world profile, individual command smoke, replaying E17 artifacts, pathfinding/collision, inventory/block mutation, death-loop/safe-spawn, multi-agent timing, live reports. | E18 issues #784-#791; alpha-loop epic-773 summary; live eval artifacts. |
| 2026-05-23 | `open-source-readiness-safety-gate` | Open Source Readiness as a Safety Gate | Explain public launch gates: disable unsafe public paths, prevent Management-disabled broadcasts, route builder spend through cost visibility, align docs with Minecraft-first reality. | Issues #808-#813; commits `17446920`, `bd029665`; `docs/OPEN_SOURCE_READINESS.md`; `docs/OPEN_SOURCE_AUDIT_REPORT.md`. |
| 2026-05-24 | `preserving-dreams-journals-embodiment` | Preserving Dreams and Journals Through Embodiment | E9 post: preserving reflection, dreams, journal image generation, website publishing, and regression tests after the world layer changed. | E9 issues #581-#586, #709; alpha-loop epic-511; journal commits. |
| 2026-05-25 | `embodied-eval-reporting` | Adapting Evals to Embodied Worlds | E10 post: embodied event loaders, build-verification category, existing suite preservation, run-mode scorecards, regression gates, and build-quality feedback. | E10 issues #587-#593, #714; alpha-loop epic-512; `docs/eval-embodied.md`. |
| 2026-05-25 | `run-modes-starting-conditions` | Run Modes and Starting Conditions | E12 post: unified RunSpec, personas, factions/goals, seeded vs blank memory, world inputs, persistent/experimental modes, shared blackboard, distress/rescue loops. | E12 issues #601-#608, #708-#713, #775; alpha-loop epic-514; `docs/run-modes.md`. |
| 2026-05-25 | `negative-result-activity-not-collaboration` | Negative Result: Activity Is Not Collaboration | Use soak and acceptance reports to show a key failure: many actions/build events and bounded queues still did not prove rich multi-turn collaboration. This is a strong research credibility post. | `logs/andy42-*/*/acceptance-report.md`; `logs/two-team-civilization/*/summary.txt`; Director V2 reports. |
| 2026-05-26 | `headless-sim-minecraft-replay` | Headless Sims Meet Minecraft Replay | E22 overview: headless RunMode, EmbodimentExecutor, decision logs, scenario eval targets, world events/needs, replay CLI, website integration, and artifact tabs. | E22 issues #851-#861; alpha-loop epic-850; `docs/MINECRAFT-REPLAY.md`. |
| 2026-05-26 | `build-intent-to-build-script` | From Build Intent to Build Script | Technical compiler post: `BuildIntent`, reference images, BuildPlan decomposer, skill-card macro compiler, build-quality scoring, RCON execution, and screenshot feedback. | E22 issues #855-#858, #871-#876; `core/minecraft/`; `scripts/replay_in_minecraft.py`. |
| 2026-05-27 | `streaming-buildscripts-live-world` | Streaming BuildScripts Into a Live World | Cover `propose_build` streaming to live Minecraft through RCON, MCRcon async issues, throttling, compiler wall fixes, and surfacing bridge failures rather than silently skipping. | Commits `b6ed368d`, `2ad9d974`, `1dae306f`, `c2425af2`, `5cb4d57a`; RCON/replay docs. |
| 2026-05-28 | `civilization-mechanics-social-infrastructure` | Civilization Mechanics Are Social Infrastructure | Ownership, trade, theft, diplomacy, conflict, and why civilization requires ledgers, permissions, incentives, and consequences rather than just more agents. | E21 issues #891-#895; civilization mechanics commits; `docs/minecraft/two-team-civilization-plan.md`. |
| 2026-05-28 | `emergent-task-board` | Emergent Task Boards Beat Phase Machines | Explain the shift from scripted settlement phases to first-claim-wins task boards, shared objectives, Director tool adapter wiring, and prompt teaching for emergent builds. | Issues #902-#909; `docs/minecraft/emergent-mode.md`; alpha-loop E21 learnings. |
| 2026-05-29 | `claim-task-earn-build-right` | Claim a Task, Earn the Right to Build | Final E21 readiness post: claim-a-task -> may `planAndBuild` as an authorization primitive that couples social commitment to world action. | Issue #918; commit `8bc34469`; alpha-loop epic-820 summary. |
| 2026-06-04 | `research-debt-observability-debt` | Research Debt and Observability Debt | Recent cleanup post: observability consolidation, artifact route lookup, decision-log fields, repo hygiene, and why research systems accumulate evidence debt. | Commits `92eed67b`, `c373e8b8`; `graphify-out/GRAPH_REPORT.md`; `core/simulation/decision_log_schema.py`. |

## Launch Batch Recommendation

Recommended launch batch: the first 16 posts, ending with the first autonomy
architecture post. This gives the public site a complete initial research arc:

1. Start with the thesis and reproducible substrate.
2. Build agents, memory, context, conversation, safety, and tools.
3. Turn simulations into the measurement surface.
4. Publish the first negative results.
5. Show the first automated eval/improvement loop.

That batch is strong enough for a hiring manager to evaluate the work before the
Minecraft arc is published, and it avoids launching with a huge list of thin
posts.

| Batch | Posts | Purpose |
| --- | --- | --- |
| Launch batch | Posts 1-16, through `reactive-to-proactive-agents` | Establish research thesis, early architecture, eval discipline, self-improvement loop, and autonomy diagnosis. |
| Batch 2 | Posts 17-24, through `replay-fidelity-research-fidelity` | Explain autonomy fixes, website/simulation product pivot, and replay evidence. |
| Batch 3 | Posts 25-32, through `retiring-central-director` | Publish the Minecraft pivot, bridge, memory exposure, verification, Alpha, and all-agent embodiment. |
| Batch 4 | Posts 33-38, through `open-source-readiness-safety-gate` | Publish cost/kill, livestream ops, Director V2, and command/live eval harnesses. |
| Batch 5 | Posts 39-49 | Publish preservation, embodied evals, run modes, negative collaboration result, headless replay, compiler, civilization mechanics, and observability debt. |

## Launch Batch Briefs

These are outline-level briefs for the first writing pass. They are not the
final posts; they are meant to make approval and drafting faster.

| # | Slug | Tags | Sections to draft |
| --- | --- | --- | --- |
| 1 | `research-harness-not-demo` | `research`, `multi-agent`, `vision` | The problem with demos; why persistent agents; why public evidence; what would count as failure; what the first commit committed me to. |
| 2 | `reproducible-agent-infrastructure` | `infrastructure`, `systems`, `research-methods` | Why infra came first; service topology; pgvector and Redis roles; nonstandard ports as local reliability; reproducibility as research ethics. |
| 3 | `llm-call-ledger` | `cost-governance`, `llm-routing`, `autonomy` | Autonomy has a bill; one LLM client; model routing; early cost events; why direct provider calls are banned; research signal for hiring managers. |
| 4 | `agents-as-experimental-variables` | `agents`, `multi-model`, `experimental-design` | Nine roles; model diversity; personality configs as controlled variables; what was intentionally seeded; what I wanted to measure later. |
| 5 | `three-tier-agent-memory` | `memory`, `pgvector`, `agent-identity` | Context windows are not memory; core/recall/archival tiers; compaction/reflection; expected failure modes; why this design was testable. |
| 6 | `context-assembly-control-surface` | `prompts`, `context`, `architecture` | The assembled prompt as runtime state; how memories/tools/goals enter; why context assembly is a product boundary; risks of prompt sprawl. |
| 7 | `first-conversation-engine` | `conversation-engine`, `social-dynamics`, `architecture` | Weighted speaker selection; topic relevance; energy and pacing; interrupts; logging decisions; why centralized control was useful but temporary. |
| 8 | `management-before-microphones` | `safety`, `tts`, `content-filtering` | Why safety came before voice; Management as out-of-band; 3-second TTS window; public-output constraints; what must never bypass it. |
| 9 | `tools-turn-characters-into-agents` | `tools`, `agency`, `sandboxing` | Tool inventory; action vs dialogue; sandbox/security hardening; Alpha dispatch; what tool usage revealed about real agency. |
| 10 | `simulations-as-lab-bench` | `simulation`, `evals`, `instrumentation` | Why full-day sims; artifacts; admin dashboards; seed scenarios; simulation tracking; how this changed the project from show to lab. |
| 11 | `qa-as-research-method` | `qa`, `debugging`, `research-methods` | QA findings as scientific evidence; unwired tools; dummy embeddings; compaction path bugs; production construction sites vs unit instances. |
| 12 | `repetition-problem` | `negative-results`, `evals`, `agents` | The uncomfortable eval; repeated transcripts; identity bleed; absent agents; talk without action; what changed after seeing the failure. |
| 13 | `llm-judge-social-systems` | `evals`, `methodology`, `llm-as-judge` | Why LLM-as-judge; 12 categories; examples of useful findings; what judges miss; how eval findings became implementation issues. |
| 14 | `overseer-to-management` | `safety`, `product-design`, `agent-systems` | Why the name changed; filter tuning; safety as system role, not character role; balancing creativity against public risk. |
| 15 | `first-evolution-loop` | `self-improvement`, `evals`, `automation` | Versioned configs; agency dimension; analyzer classifying prompt vs technical issues; simulate/eval/improve; why this is ops, not magic. |
| 16 | `reactive-to-proactive-agents` | `autonomy`, `agency`, `agent-state` | Diagnosis of reactivity; dead initiative; internal state; autonomous goals; individual budgets; factions/events/dreams; measurable targets. |

## Suggested Publication Order

Publish in chronological order. The blog index will sort newest first, but the
series should include navigation copy like "Previous in the lab notebook" and
"Next in the lab notebook" after posts exist.

For launch, I recommend writing the first 12-16 posts immediately, through the
first evolution/autonomy loop, then continuing the Minecraft arc in batches. A
public site with the full list but only a partially written series may look
unfinished; a site with 16 strong posts and a clear "Minecraft pivot series
coming next" note will read as deliberate.

## Strongest Research Through-Line

The series should make this claim visible without overclaiming:

> I started with simulated multi-agent conversation, instrumented the system
> until the failures became measurable, discovered that persistent agency
> collapses without memory, evals, action verification, and cost controls, then
> pivoted into Minecraft so collaboration could be tested as embodied,
> inspectable world change.

## Approval Questions

Please approve or edit these before drafting:

1. Should the launch batch include all 49 posts, or should I draft the first
   12-16 now and keep the Minecraft posts queued?
2. Should current placeholder slugs be preserved where possible for SEO, or can
   I replace them with the new research-notebook slugs?
3. Should the tone use "I" throughout, or "we" when describing system behavior
   and alpha-loop runs?
