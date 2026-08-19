# Blog Launch Batch Dossiers

Status: drafting spine, pending user approval before MDX writing

Purpose: provide the evidence spine for the recommended 16-post launch batch.
This is not publishable blog copy. It is the pre-writing dossier to keep the
final posts grounded in commits, issues, docs, evals, and limitations.

## Date Corrections

During the launch-batch audit, three posts were moved from 2026-04-05 to
2026-04-04 because their decisive evidence landed on 2026-04-04:

- `repetition-problem`: eval-quality fixes and repetition issues landed in
  commit `ef609af0`, with session completion evidence in `9dfc28b2`.
- `llm-judge-social-systems`: the core eval suite and simulation analysis UI
  landed through the 2026-04-04 eval commits.
- `overseer-to-management`: the rename and filter tuning landed in
  `a6da3ea0`, followed by test and CLI fixes.

`first-evolution-loop` remains 2026-04-05 because the versioned config,
intrinsic drive, agency eval, analyzer, and orchestrator commits all landed on
that date.

## 1. `research-harness-not-demo`

- Date: 2026-03-30.
- Thesis: the project begins as a research harness, not a demo; the point is to
  make agent memory, communication, coordination, cost, and safety observable.
- Evidence anchors: commit `45e38268`; `specs/ENGINEERING-SPECS.md`;
  `specs/FINAL-IMPLEMENTATION-PLAN.md`;
  `research/RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md`.
- Limitation to include: the first commit established intent and scaffolding,
  not evidence of agent capability.
- Hiring-manager signal: turning an ambitious product idea into a testable
  research system with explicit failure surfaces.

## 2. `reproducible-agent-infrastructure`

- Date: 2026-03-31.
- Thesis: reproducible infrastructure is part of the experiment, because
  multi-agent behavior is not credible if the substrate cannot be replayed.
- Evidence anchors: issues #1, #2, #55; commits `6d2d3080`, `b140c858`,
  `31110691`, `05148ae9`; AGENTS.md default-port non-negotiables.
- Limitation to include: infrastructure does not solve agency; it makes later
  failures attributable.
- Hiring-manager signal: systems taste around local reliability, dependency
  pinning, nonstandard ports, and repeatable service startup.

## 3. `llm-call-ledger`

- Date: 2026-04-01.
- Thesis: every autonomous-agent claim needs a ledger for model choice, cost,
  observability, and kill-switch compatibility.
- Evidence anchors: issue #5; commit `7c228e14`; `core/llm_client.py`;
  `core/model_config.py`; `docs/model-configuration.md`.
- Limitation to include: early cost tracking was a foundation, later hardened
  through reconciliation and E11 kill-switch work.
- Hiring-manager signal: safety and cost governance as architectural
  invariants, not after-the-fact dashboards.

## 4. `agents-as-experimental-variables`

- Date: 2026-04-02.
- Thesis: the nine agents are not just characters; their roles, personalities,
  and model assignments are controlled variables for later behavioral analysis.
- Evidence anchors: issues #7-#15; commits #96-#106; `agents/`;
  `specs/CHARACTER-SHEETS.md`; `core/model_config.py`.
- Limitation to include: config can seed behavioral priors, but it does not
  guarantee stable identity without memory and context assembly.
- Hiring-manager signal: experimental design discipline in prompt and model
  configuration.

## 5. `three-tier-agent-memory`

- Date: 2026-04-02.
- Thesis: persistent agents need tiered memory, because context windows alone
  cannot carry identity, semantic recall, and permanent transcripts.
- Evidence anchors: issues #16-#21; commits `f927cb20`, `9f29d511`,
  `a329853c`, `5f3a1584`, `95f6131a`, `c58ddcdd`;
  `specs/MEMORY-SYSTEM.md`; `core/memory/`.
- Limitation to include: each tier can fail differently: stale core facts,
  poor retrieval, compaction loss, or transcript bloat.
- Hiring-manager signal: designing explicit storage boundaries for long-running
  agent identity.

## 6. `context-assembly-control-surface`

- Date: 2026-04-02.
- Thesis: the assembled prompt is the true runtime interface where identity,
  memory, goals, world state, tools, and safety constraints become behavior.
- Evidence anchors: issue #21; commit `c58ddcdd`; `core/context_assembly`;
  `core/system_prompt`; memory commits #108-#113.
- Limitation to include: context assembly can hide bugs if inputs are silently
  stale, missing, or over-compressed.
- Hiring-manager signal: recognizing prompt construction as a production
  control surface rather than copywriting.

## 7. `first-conversation-engine`

- Date: 2026-04-03.
- Thesis: multi-agent conversation needs a scheduler with state, not a loop
  that lets every agent talk in turn.
- Evidence anchors: issues #22-#32; commits `797c978a`, `d8e5b817`,
  `808f998b`, `7f0b4f3b`, `7ec3c89e`, `5d2b3661`, `84092bdb`,
  `9f14ad33`, `57b74c78`, `94ebe480`; `specs/CONVERSATION-ENGINE.md`;
  `core/conversation_engine.py`.
- Limitation to include: central scheduling was useful for early simulation
  but later constrained decentralized embodied behavior.
- Hiring-manager signal: building measurable social dynamics instead of
  relying on prompt vibes.

## 8. `management-before-microphones`

- Date: 2026-04-03.
- Thesis: public voice output requires a Management path before TTS, because
  safety must sit between model text and broadcast audio.
- Evidence anchors: issues #31, #33, #143; commits `40a4ac0b`,
  `c5aa3878`, `5b8b433c`; `core/management.py`; `core/tts`.
- Limitation to include: early filtering had to be relaxed later because too
  much authority suppresses social dynamics.
- Hiring-manager signal: public-output safety gates and human-intervention
  design.

## 9. `tools-turn-characters-into-agents`

- Date: 2026-04-03.
- Thesis: agents become meaningfully testable only when they can use tools that
  change memory, world state, code, audience state, and project artifacts.
- Evidence anchors: issues #35-#43; commits #134-#142; `tools/`;
  security fixes around self-modification and sandboxed execution.
- Limitation to include: tool registration and execution wiring later produced
  QA failures; tool existence did not mean tool availability.
- Hiring-manager signal: action surfaces, sandboxing, and security-minded tool
  design.

## 10. `simulations-as-lab-bench`

- Date: 2026-04-04.
- Thesis: the project became research-grade when simulations, artifacts,
  dashboards, eval runners, and seed scenarios turned behavior into evidence.
- Evidence anchors: issues #145-#158 and #186-#195; commits `30261735`,
  `2668dd45`, `6c9b6ae0`, `7de0f472`, `68e2feaf`, `652860ff`,
  `e364c03c`, `a569cb37`, `9aa92d97`; `core/simulation/`;
  `evals/prompts/`.
- Limitation to include: simulation evidence still depended on correct state
  isolation and faithful replay, both of which required later work.
- Hiring-manager signal: moving from demo operation to experimental
  instrumentation.

## 11. `qa-as-research-method`

- Date: 2026-04-04.
- Thesis: QA became a research method because each failure identified a place
  where the architecture claimed capability it had not actually wired.
- Evidence anchors: issues #168-#175; commit `de94945e`; fixes for tool
  registration, core memory startup, dummy embeddings, compaction use, and
  reflection scheduler startup.
- Limitation to include: many problems were not model failures; they were
  construction-site failures where production paths used different instances
  than tests.
- Hiring-manager signal: debugging maturity and willingness to treat QA
  findings as scientific data.

## 12. `repetition-problem`

- Date: 2026-04-04.
- Thesis: the first major negative result was repetition: agents could talk
  without producing durable, differentiated, useful progress.
- Evidence anchors: eval `e24db48d`; issues #213-#217 and #229-#236; commits
  `ef609af0` and `9dfc28b2`; early `evals/results/*.json`.
- Limitation to include: the eval showed symptoms before the system had enough
  embodied action to distinguish social failure from environment poverty.
- Hiring-manager signal: publishing uncomfortable measurements instead of
  hiding them behind launch polish.

## 13. `llm-judge-social-systems`

- Date: 2026-04-04.
- Thesis: LLM-as-judge was a practical measurement layer for social systems,
  useful when treated as a noisy instrument rather than ground truth.
- Evidence anchors: issues #155-#158, #206-#212, #240-#242; commits
  `e364c03c`, `da05c8dd`, `c76b6c5c`, `c809620a`; `evals/prompts/*.yaml`;
  early eval JSONs.
- Limitation to include: judges can miss causal mechanisms and reward surface
  fluency; findings still need implementation follow-up.
- Hiring-manager signal: pragmatic evaluation design for subjective multi-agent
  behavior.

## 14. `overseer-to-management`

- Date: 2026-04-04.
- Thesis: renaming Overseer to Management was not cosmetic; it clarified that
  safety authority is a system role, not another character in the fiction.
- Evidence anchors: issues #220-#221; commits `a6da3ea0`, `ee86e555`,
  `f8f5e2e4`; `core/management.py`; TTS/content-filter pipeline.
- Limitation to include: filter tuning is a tradeoff between public safety and
  suppressing emergent social dynamics.
- Hiring-manager signal: product judgment around authority, naming, and
  operational safety.

## 15. `first-evolution-loop`

- Date: 2026-04-05.
- Thesis: the first evolution loop was research operations: simulate,
  evaluate, classify, improve, and keep versioned records.
- Evidence anchors: issues #238-#242; commits `ec57d908`, `8e2178db`,
  `c76b6c5c`, `c809620a`, `e750a29b`, `3595e6ba`; eval analyzer and
  versioned config code.
- Limitation to include: an improvement loop can optimize prompts around weak
  measurements unless eval categories are treated skeptically.
- Hiring-manager signal: automation with traceability rather than vague
  self-improvement claims.

## 16. `reactive-to-proactive-agents`

- Date: 2026-04-08.
- Thesis: the autonomy diagnosis showed that agents needed internal state,
  initiative, goals, budgets, factions, events, and dreams to escape reactive
  dialogue loops.
- Evidence anchors: issues #267-#275; commits `f5499c7d`, `d68477ac`,
  `02648bc3`, `2b5927d9`, `285ea65f`; `specs/AGENT-AUTONOMY-EVAL-STRATEGY.md`;
  autonomy/internal economy code paths.
- Limitation to include: proactive state can create activity without meaningful
  collaboration, which later Minecraft evals made more visible.
- Hiring-manager signal: diagnosing behavioral failure as a system-state
  problem, then adding measurable mechanisms.

## Approval Boundary

These dossiers are preparatory. They do not approve writing or replacing
`website/content/blog/*.mdx`. After approval, use this file alongside
`docs/BLOG-WRITING-PLAYBOOK.md` to draft the launch batch.
