#!/usr/bin/env python3
"""Generate the approved backdated research-notebook blog series."""

from __future__ import annotations

import csv
import json
import shutil
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "BLOG-SERIES-MANIFEST.tsv"
BLOG_DIR = ROOT / "website" / "content" / "blog"


DETAILS: dict[str, dict[str, object]] = {
    "research-harness-not-demo": {
        "tags": ["research", "multi-agent", "vision"],
        "excerpt": "The first commit framed Livestream to AGI as a research harness for persistent multi-agent behavior, not a polished demo.",
        "question": "What kind of environment would make multi-agent failure visible enough to study instead of easy to hide?",
        "system": "I started with a public, persistent world: named agents, a shared budget, a visible stream, and an architecture that could eventually connect conversation, memory, tools, and world state. The important move was not the branding. It was deciding that the system should expose its own failures.",
        "evidence": [
            "Commit `45e38268` initialized the project structure, specs, configs, and documentation.",
            "`specs/ENGINEERING-SPECS.md` defined the backend, frontend, memory, TTS, cost, and safety shape.",
            "`research/RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md` framed the project as a longitudinal research program.",
        ],
        "broke": "The first commit proved almost nothing about agent capability. It only created a place where capability claims could later be tested.",
        "signal": "The professional signal here is research framing: I wanted an instrument where memory, coordination, cost, and safety could be measured over time.",
        "next": "The next problem was less glamorous and more important: make the substrate reproducible enough that later behavior would not depend on my laptop being in a lucky state.",
    },
    "reproducible-agent-infrastructure": {
        "tags": ["infrastructure", "systems", "research-methods"],
        "excerpt": "Before the agents could be interesting, the experiment needed a repeatable service substrate.",
        "question": "How do I make a multi-agent experiment reproducible enough that failures can be attributed to the system rather than the environment?",
        "system": "The early stack became FastAPI, Docker Compose, PostgreSQL, Redis, pgvector, and a Next.js website shell. I also moved the project onto Python 3.13 and nonstandard local ports so common developer services would not collide with the experiment.",
        "evidence": [
            "Issues #1, #2, and #55 covered the backend, Docker services, and website foundation.",
            "Commits `6d2d3080`, `b140c858`, `31110691`, and `05148ae9` landed the core infrastructure and port corrections.",
            "`AGENTS.md` now treats the nonstandard Redis, PostgreSQL, and Langfuse ports as non-negotiable.",
        ],
        "broke": "Infrastructure did not make the agents more capable. It made their future failures less ambiguous.",
        "signal": "The signal is systems taste: boring reproducibility decisions are part of research method, not scaffolding to skip.",
        "next": "Once services could run, the next invariant was that model calls had to be observable and governed from one path.",
    },
    "llm-call-ledger": {
        "tags": ["cost-governance", "llm-routing", "autonomy"],
        "excerpt": "Autonomy without a ledger is theater; every model call needed routing, cost visibility, and safety compatibility.",
        "question": "What has to be true before I can let agents spend tokens continuously?",
        "system": "I centralized LLM calls through the OpenRouter client and model config rather than letting call sites speak directly to providers. That gave the system one place to attach cost tracking, routing, observability, and later kill-switch behavior.",
        "evidence": [
            "Issue #5 tracked the OpenRouter LLM client work.",
            "Commit `7c228e14` added the OpenRouter client with cost tracking.",
            "`core/llm_client.py`, `core/model_config.py`, and `docs/model-configuration.md` define the central routing surface.",
        ],
        "broke": "This first ledger was only the foundation. Later work had to fix double-counting, reconciliation, and hard caps.",
        "signal": "The signal is safety judgment: cost and observability belong in the architecture before autonomy is scaled.",
        "next": "With model calls centralized, the next step was to make each agent an explicit experimental variable rather than a pile of prompts.",
    },
    "agents-as-experimental-variables": {
        "tags": ["agents", "multi-model", "experimental-design"],
        "excerpt": "The nine-agent cast became an experimental design surface: role, personality, and model assignment were all explicit variables.",
        "question": "How can I make agent behavior attributable to configuration choices rather than prompt sprawl?",
        "system": "I added complete configs for the agent roster and treated their role, model assignment, voice, and behavioral priors as data. That made Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Management, and Alpha easier to compare and later migrate into Minecraft profiles.",
        "evidence": [
            "Issues #7-#15 created the complete agent configuration files.",
            "Commits #96-#106 landed the early agent configs across the roster.",
            "`agents/`, `specs/CHARACTER-SHEETS.md`, and `core/model_config.py` hold the configuration surface.",
        ],
        "broke": "A character sheet does not preserve identity by itself. Without memory and context assembly, even clear roles can wash out during long runs.",
        "signal": "The signal is experimental design: agent differences are encoded where they can be inspected, changed, and evaluated.",
        "next": "The next architectural question was memory: how can an agent remain itself after the prompt window moves on?",
    },
    "three-tier-agent-memory": {
        "tags": ["memory", "pgvector", "agent-identity"],
        "excerpt": "Persistent agents needed separate memory tiers for identity, semantic recall, and permanent transcripts.",
        "question": "What should count as memory when agents are expected to persist beyond a single conversation?",
        "system": "I split memory into core, recall, and archival tiers. Core memory stays in prompt as identity. Recall memory uses vector search for relevant retrieval. Archival memory preserves transcripts rather than pretending summaries are enough.",
        "evidence": [
            "Issues #16-#21 covered core, recall, archival, compaction, reflection, and context assembly.",
            "Commits `f927cb20`, `9f29d511`, `a329853c`, `5f3a1584`, `95f6131a`, and `c58ddcdd` landed the memory stack.",
            "`specs/MEMORY-SYSTEM.md` and `core/memory/` define the tier boundaries.",
        ],
        "broke": "Each tier introduced a different failure mode: stale core facts, bad retrieval, lossy compaction, or transcript bloat.",
        "signal": "The signal is boundary design: long-running identity needs storage contracts, not just longer prompts.",
        "next": "Memory only matters when it enters the model at the right moment, so the next control surface was context assembly.",
    },
    "context-assembly-control-surface": {
        "tags": ["context", "prompts", "architecture"],
        "excerpt": "The assembled prompt became the runtime interface where identity, memory, world state, tools, and safety met.",
        "question": "Where does an agent actually live at inference time?",
        "system": "The context assembly layer joined personality, current state, memories, recent transcripts, tools, and constraints into the prompt seen by the model. This made prompt construction a production boundary rather than an ad hoc string-building step.",
        "evidence": [
            "Issue #21 tracked context window assembly for agent turns.",
            "Commit `c58ddcdd` landed the initial context assembly implementation.",
            "`core/context_assembly`, `core/system_prompt`, and `specs/MEMORY-SYSTEM.md` describe the prompt inputs.",
        ],
        "broke": "A clean assembly layer can still hide stale or missing inputs if the upstream managers are not wired into the real runtime path.",
        "signal": "The signal is architecture judgment: prompts are not copy; they are the interface where state becomes behavior.",
        "next": "Once single-agent turns could be assembled, the next problem was social: who should speak next?",
    },
    "first-conversation-engine": {
        "tags": ["conversation-engine", "social-dynamics", "architecture"],
        "excerpt": "The first conversation engine turned multi-agent dialogue into a scheduled, logged social process.",
        "question": "How do nine agents share conversational space without becoming round-robin puppets?",
        "system": "I built a conversation engine with hot-loaded config, topic detection, speaker selection, interrupts, energy, pacing, proximity, triggers, and selection logging. The goal was to make social flow tunable and inspectable.",
        "evidence": [
            "Issues #22-#32 covered the conversation engine primitives and orchestrator.",
            "Commits `797c978a`, `808f998b`, `7f0b4f3b`, `57b74c78`, and `94ebe480` landed the major pieces.",
            "`specs/CONVERSATION-ENGINE.md` and `core/conversation_engine.py` define the scheduling model.",
        ],
        "broke": "Central scheduling made early simulations possible, but it later became a constraint once agents needed embodied local perception and decentralized conversation.",
        "signal": "The signal is measurement-minded social design: conversational dynamics were logged and tunable from the beginning.",
        "next": "Before those conversations could be spoken publicly, every utterance needed a safety path.",
    },
    "management-before-microphones": {
        "tags": ["safety", "tts", "content-filtering"],
        "excerpt": "The Management filter and TTS path had to exist before any agent voice reached a public stream.",
        "question": "What should sit between an LLM utterance and broadcast audio?",
        "system": "The system introduced a Management content filter and Edge TTS voice path before public output. I wanted a producer-like safety role with a delay window rather than raw model text flowing straight to speech.",
        "evidence": [
            "Issues #31, #33, and #143 covered Management, TTS, and structured dialogue/action parsing.",
            "Commits `40a4ac0b`, `c5aa3878`, and `5b8b433c` landed the filter, voices, and parsing path.",
            "`core/management.py`, `core/tts`, and `tools/` show where output becomes action or speech.",
        ],
        "broke": "The first filter posture was too blunt for a social system. Safety needs authority, but excessive filtering can flatten the behavior being studied.",
        "signal": "The signal is operational safety: live output gets a gate before it gets a microphone.",
        "next": "Once agents could speak safely, the next question was whether they could act.",
    },
    "tools-turn-characters-into-agents": {
        "tags": ["tools", "agency", "sandboxing"],
        "excerpt": "Tools exposed the difference between characters that talk and agents that can change state.",
        "question": "What makes an agent more than a conversational persona?",
        "system": "I added tool surfaces for messages, world state, audience communication, memory, code execution, self-modification proposals, tilemaps, revenue, web access, and Alpha dispatch. The point was to give agents state-changing affordances that could later be audited.",
        "evidence": [
            "Issues #35-#43 covered the first tool layer.",
            "Commits #134-#142 landed core, memory, audience, sandbox, self-modification, tilemap, revenue, web, and Alpha tools.",
            "`tools/` contains the action surface and the security fixes around sandboxing and self-modification.",
        ],
        "broke": "A tool existing in the repo did not mean it was available in the production conversation path; QA later caught that exact gap.",
        "signal": "The signal is action-surface design with security boundaries, not just giving models bigger prompts.",
        "next": "The next step was to run long enough simulations that tool availability and agent behavior could be measured.",
    },
    "simulations-as-lab-bench": {
        "tags": ["simulation", "evals", "instrumentation"],
        "excerpt": "Full-day simulations, artifacts, dashboards, and evals turned the show concept into a lab bench.",
        "question": "How do I turn freeform multi-agent behavior into evidence?",
        "system": "I added simulation tracking, artifact persistence, seed scenarios, admin endpoints, dashboards, eval runners, and reporting. The system started to treat each run as a record that could be inspected, compared, and improved.",
        "evidence": [
            "Issues #145-#158 and #186-#195 covered simulation tracking, artifacts, dashboards, evals, and reporting.",
            "Commits `30261735`, `2668dd45`, `7de0f472`, `652860ff`, `e364c03c`, and `9aa92d97` landed the bench.",
            "`core/simulation/`, `evals/prompts/`, and the admin dashboard paths show the measurement surface.",
        ],
        "broke": "A simulation bench can still lie if state leaks between runs or if replay does not match what happened.",
        "signal": "The signal is research operations: I converted a live system into something that could produce inspectable artifacts.",
        "next": "The first serious test of that bench was QA, which found architectural gaps rather than just model mistakes.",
    },
    "qa-as-research-method": {
        "tags": ["qa", "debugging", "research-methods"],
        "excerpt": "The first QA pass turned wiring bugs into research findings about where the architecture was only theoretical.",
        "question": "What does QA reveal when the claim is that agents can remember, talk, and use tools?",
        "system": "The QA pass checked memory and conversation paths end to end. It moved recall and journal creation into the engine, wired tools into conversations, initialized memory at app startup, replaced dummy embeddings, and put compaction and reflection on real paths.",
        "evidence": [
            "Issues #168-#175 tracked the memory and conversation QA findings.",
            "Commit `de94945e` consolidated the QA fixes.",
            "`core/conversation_engine.py`, `core/memory/`, and `tools/` reflect the production-path wiring changes.",
        ],
        "broke": "Many failures were construction-site failures: the right object existed, but production used a different path than the test harness.",
        "signal": "The signal is debugging maturity: I treated QA as a way to falsify architecture claims.",
        "next": "With instrumentation in place, the evals started surfacing an uncomfortable behavioral failure: repetition.",
    },
    "repetition-problem": {
        "tags": ["negative-results", "evals", "agents"],
        "excerpt": "The first decisive negative result was repetition: the agents could talk without making durable progress.",
        "question": "What happens when persistent agents have social machinery but not enough internal pressure to change?",
        "system": "The eval quality work made repetition visible. The transcripts showed repeated topics, weak differentiation, identity bleed, missing speakers, and talk that did not reliably turn into action.",
        "evidence": [
            "Eval `eval-e24db48d-1e96-4630-9456-72cc8f22f221.json` is the anchor artifact for early repetition concerns.",
            "Issues #213-#217 and #229-#236 tracked eval quality and repetition fixes.",
            "Commits `ef609af0` and `9dfc28b2` landed the first eval-quality fix session and completion.",
        ],
        "broke": "The system could produce conversation that looked active while remaining behaviorally stuck.",
        "signal": "The signal is candor: the research notebook should publish negative results when they are the actual finding.",
        "next": "Once repetition was measurable, the next question was how to judge social systems without pretending the judge is perfect.",
    },
    "llm-judge-social-systems": {
        "tags": ["evals", "methodology", "llm-as-judge"],
        "excerpt": "The 12-category eval suite became a practical, imperfect instrument for judging social agent behavior.",
        "question": "How do I evaluate open-ended agent behavior without reducing it to a single fake score?",
        "system": "I built a set of eval categories for creativity, agency, productivity, social dynamics, economic behavior, internal state, entertainment, safety, errors, dialogue quality, narrative, and world evolution. The point was to organize findings and turn them into implementation work.",
        "evidence": [
            "Issues #155-#158, #206-#212, and #240-#242 cover eval prompts, analysis UI, and the agency dimension.",
            "Commits `e364c03c`, `da05c8dd`, `c76b6c5c`, and `c809620a` landed eval categories and analysis work.",
            "`evals/prompts/*.yaml` and `evals/results/*.json` are the evaluation artifacts.",
        ],
        "broke": "An LLM judge can reward fluent summaries and miss causal mechanisms. Every finding still needs implementation evidence.",
        "signal": "The signal is pragmatic methodology: noisy evaluators can still be useful when their limits are explicit.",
        "next": "The same eval work also exposed that the safety role needed clearer framing.",
    },
    "overseer-to-management": {
        "tags": ["safety", "product-design", "agent-systems"],
        "excerpt": "Renaming Overseer to Management clarified that safety authority is a system role, not another fictional character.",
        "question": "What should the safety role be called and how much should it intervene?",
        "system": "I renamed Overseer to Management, relaxed filtering, and fixed continuity issues. The rename mattered because it moved the role out of the fiction and into operational authority.",
        "evidence": [
            "Issues #220-#221 tracked the rename and filter tuning.",
            "Commits `a6da3ea0`, `ee86e555`, and `f8f5e2e4` updated code, tests, and CLI scripts.",
            "`core/management.py` is the safety role that must remain in the output path.",
        ],
        "broke": "If Management is too aggressive, it suppresses the social dynamics the experiment is trying to observe.",
        "signal": "The signal is product judgment: naming, authority, and filter posture shape both safety and research validity.",
        "next": "After the filter was clearer, I tried the first version of an automated improvement loop.",
    },
    "first-evolution-loop": {
        "tags": ["self-improvement", "evals", "automation"],
        "excerpt": "The first evolution loop was research operations, not magic self-improvement.",
        "question": "Can the system close a loop from simulation results to targeted changes without losing traceability?",
        "system": "I added versioned agent configs, intrinsic drives, an agency eval dimension, an eval analyzer, and a simulate -> evaluate -> improve orchestrator. The aim was to classify findings and make improvement proposals auditable.",
        "evidence": [
            "Issues #238-#242 covered versioned configs, drives, agency evals, analyzer, and loop orchestration.",
            "Commits `ec57d908`, `8e2178db`, `c76b6c5c`, `c809620a`, `e750a29b`, and `3595e6ba` landed the loop.",
            "`core/simulation/` and the eval analyzer paths connect runs to improvement suggestions.",
        ],
        "broke": "A loop can optimize toward weak measurements if the evaluator is treated as truth rather than an instrument.",
        "signal": "The signal is disciplined automation: improvement proposals need versioning and evidence, not hype.",
        "next": "The next failure was deeper than prompts: agents were reactive by default.",
    },
    "reactive-to-proactive-agents": {
        "tags": ["autonomy", "agency", "agent-state"],
        "excerpt": "The autonomy diagnosis reframed agency as a state problem, not a smarter-model problem.",
        "question": "Why do capable models still sit still until prompted?",
        "system": "I added internal state, initiative, autonomous goals, individual budgets, factions, events, and dream mechanics. The architecture started to give agents changing pressures that could surface without a direct human prompt.",
        "evidence": [
            "Issues #267-#275 tracked the autonomy and internal economy work.",
            "Commits `f5499c7d`, `d68477ac`, `02648bc3`, `2b5927d9`, and `285ea65f` landed the system.",
            "`specs/AGENT-AUTONOMY-EVAL-STRATEGY.md` diagnoses reactivity, statelessness, and budget flattening.",
        ],
        "broke": "Proactivity can create activity without collaboration. Later embodied evals had to separate motion from coordinated progress.",
        "signal": "The signal is diagnosis: I traced a behavioral failure to missing state machinery and added measurable mechanisms.",
        "next": "The first mechanism to revisit was dreams, which had to become concrete rather than decorative.",
    },
    "dreams-as-control-mechanism": {
        "tags": ["dreams", "memory", "creativity"],
        "excerpt": "Dreams became a control mechanism for breaking loops, not a mystical flourish.",
        "question": "Can high-temperature reflection create new goals and associations when agents are stuck?",
        "system": "Dreams pulled from recent conversation, personality, and loose recall memories to produce rest-period reflections. I wanted them to introduce novelty and give agents material for later initiative.",
        "evidence": [
            "Commits `9d72e942` and `486a1e06` fixed dream bugs and added longer simulation coverage.",
            "`core/memory/` and journal/dream code paths connect reflection to persistent state.",
            "`evals/results/*.json` includes early evidence that dream entries were missing before fixes.",
        ],
        "broke": "The early system could report a dream feature while producing zero dream entries. That is a production-path failure, not a creative insight.",
        "signal": "The signal is restraint: I treated an evocative feature as a testable control mechanism.",
        "next": "The next visibility layer was the pixel office, which made agents easier to watch but not yet embodied.",
    },
    "pixel-office-useful-failure": {
        "tags": ["frontend", "simulation", "negative-results"],
        "excerpt": "The Phaser office made the system visible, but it also exposed the limits of a symbolic world.",
        "question": "Does a rendered office make agent collaboration more real or just easier to watch?",
        "system": "I wired the Phaser frontend to backend events, added pathfinding, ambient movement, speech bubbles, TTS timing, desks, furniture, and world visuals. It created a more legible show surface.",
        "evidence": [
            "Issues #44-#51, #258-#264, and #276-#279 covered the Phaser office and event wiring.",
            "Commits `326d3525`, `8bdb695c`, `263f398c`, `6ec31cd1`, `204fcd64`, `5d5c5557`, and `e8b227d5` landed the office work.",
            "`frontend/` contains the Phaser renderer and office world implementation.",
        ],
        "broke": "The office could show movement and speech without proving physical task completion or collaboration.",
        "signal": "The signal is product/research taste: useful visualization still has to be interrogated as evidence.",
        "next": "The public website then became the place to expose what the system was actually doing.",
    },
    "public-website-research-surface": {
        "tags": ["website", "research", "transparency"],
        "excerpt": "The website became a research surface: agent profiles, world state, evals, conversations, and public contribution paths.",
        "question": "How do I make the project inspectable to people who are not inside the dev environment?",
        "system": "I added public pages for agents, world state, evals, conversations, challenges, contributions, lore, safety, and simulations. The website started to turn internal artifacts into an external research record.",
        "evidence": [
            "Layer 10 issues #56-#68 and continuation issues #326-#331 covered the public site work.",
            "Commits `be0141de`, `6fb512b7`, `14c4579b`, `61446f47`, `077e104a`, and `489fd1c1` wired real pages and APIs.",
            "`website/` and `website/src/lib/blog.ts` define the publishing surface.",
        ],
        "broke": "A public site can make weak evidence look polished if the underlying artifacts are not honest.",
        "signal": "The signal is communication: I wanted outside readers to inspect runs, not just read claims.",
        "next": "To make comparisons credible, simulation state had to be isolated.",
    },
    "simulation-isolation-counterfactuals": {
        "tags": ["simulation", "isolation", "research-methods"],
        "excerpt": "Counterfactual simulations require isolated memory, Redis state, snapshots, and simulation IDs.",
        "question": "How can two runs be compared if they quietly share state?",
        "system": "I added simulation-scoped memory, ScopedRedis, snapshots, clone support, CLI paths, tool-level simulation IDs, and database error logs. Isolation became a prerequisite for meaningful comparisons.",
        "evidence": [
            "Issue #252 tracked the simulation isolation work.",
            "Commits `02d3ea65`, `4dd5338b`, `ecc0934b`, `99e5a0d4`, and `7a5807fb` landed the isolation phases.",
            "`core/simulation/`, `research/RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md`, and snapshot paths define the counterfactual surface.",
        ],
        "broke": "Isolation bugs can invalidate a run without looking dramatic in the UI.",
        "signal": "The signal is experimental discipline: state boundaries are research validity boundaries.",
        "next": "Longer runs then exposed a different scaling problem: token bloat.",
    },
    "token-bloat-memory-compaction": {
        "tags": ["memory", "context", "long-running-agents"],
        "excerpt": "Long-running agents need compaction because the context window becomes a survival constraint.",
        "question": "What happens when a persistent agent carries too much history into every turn?",
        "system": "I added memory compaction for long-running simulations and treated token pressure as an architectural constraint. The goal was not just lower cost; it was preserving useful identity and recall under bounded context.",
        "evidence": [
            "Commit `b01cc321` addressed token bloat and added memory compaction for long-running simulations.",
            "`core/memory/` contains the compaction and memory-management code paths.",
            "`specs/MEMORY-SYSTEM.md` defines why core, recall, and archival tiers need separate behavior.",
        ],
        "broke": "Compaction can erase the wrong detail. Compression is not neutral when identity and goals are encoded in the data.",
        "signal": "The signal is long-horizon systems thinking: context limits shape behavior, cost, and reliability.",
        "next": "The next wave of work made simulations easier to browse, run, and evaluate from the dashboard.",
    },
    "dashboard-walkthrough-product-shift": {
        "tags": ["dashboard", "simulation", "product"],
        "excerpt": "A dashboard QA walkthrough pushed the system toward simulations as the product surface.",
        "question": "What does a researcher need to inspect after a run finishes?",
        "system": "The dashboard work added clearer world chunks, recent events, simulation pickers, lore explanations, backfilled snapshot dates, and UI fixes. It made the simulation record easier to navigate and less dependent on raw logs.",
        "evidence": [
            "Epic 417 issues #395-#416 covered the admin dashboard QA walkthrough.",
            "Commits `955e7f5b`, `7e6d2322`, `9ee4497e`, `cf3726fe`, and `6c1f5e68` landed the fixes and merge.",
            ".alpha-loop learnings for epic 417 capture the QA-driven product shift.",
        ],
        "broke": "A dashboard can make gaps visible but cannot fill them; several pages still depended on whether simulations produced meaningful artifacts.",
        "signal": "The signal is product taste for research systems: evidence has to be browsable.",
        "next": "The next pivot made that explicit: simulations became the primary product.",
    },
    "simulation-first-pivot": {
        "tags": ["simulation", "product", "research"],
        "excerpt": "The project pivoted to make simulations the primary product and evidence surface.",
        "question": "What if the most valuable output is not the stream itself, but the run record?",
        "system": "I added hypotheses, outcomes, learnings, factions, memory seeds, energy timelines, public submissions, magic-link auth, simulation creator flows, workspace tabs, MP4 rendering, and YouTube publishing. Simulations became packages of evidence.",
        "evidence": [
            "Epic 435 issues #418-#435 covered the simulation-first pivot.",
            "Commits `f2e46cd6`, `7286d909`, `75e895f4`, `69b94f16`, `062a4920`, and `80e8ce1a` landed the product surface.",
            ".alpha-loop summary `session-summary-session-epic-435-epic-simulation-first-pivot-make-simulations-the-primary-product.md` records the batch learnings.",
        ],
        "broke": "A simulation-first product still depends on replay fidelity. If exported evidence is wrong, the research surface is wrong.",
        "signal": "The signal is strategic pivoting: I moved toward the artifact that best served measurement.",
        "next": "That made replay correctness the next hard gate.",
    },
    "replay-fidelity-research-fidelity": {
        "tags": ["replay", "video", "evidence"],
        "excerpt": "Replay fidelity became research fidelity because bad replay means bad evidence.",
        "question": "Can I trust a rendered artifact if it does not match the actual simulation?",
        "system": "I fixed turn-level replay cues, real office rendering, roster fidelity, current port targeting, fail-closed cue loading, MP4 status exposure, and visual regression checks.",
        "evidence": [
            "Epic 468/475 issues #462-#495 covered replay and MP4 export correctness.",
            "Commits `27752b3f`, `77bcf622`, `ea948328`, `a19e662c`, `dde34a60`, and `039d148b` landed the fixes.",
            ".alpha-loop summaries for epic 468 and 475 capture the replay fidelity learnings.",
        ],
        "broke": "The first exports could look plausible while being wrong about turns, rosters, or routes.",
        "signal": "The signal is evidence discipline: visual output is not evidence unless it is faithful.",
        "next": "The same concern pushed the project toward a world where action could be independently verified: Minecraft.",
    },
    "minecraft-pivot": {
        "tags": ["minecraft", "embodiment", "pivot"],
        "excerpt": "Minecraft became the action space because symbolic office movement was not enough evidence of collaboration.",
        "question": "What world makes agent action inspectable rather than merely narrated?",
        "system": "I pivoted from a Phaser office to Minecraft because blocks, movement, inventory, and world changes provide an external action surface. The goal was not better visuals. It was independent verification.",
        "evidence": [
            "Commit `65e67b25` added the Minecraft pivot context.",
            "`specs/MINECRAFT-PIVOT-CONTEXT.md` explains why tilemap JSON was insufficient.",
            "`docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` translates the pivot into implementation epics.",
        ],
        "broke": "Minecraft did not solve embodiment. It made embodiment failures harder to hide.",
        "signal": "The signal is research judgment: when the environment cannot test the hypothesis, change the environment.",
        "next": "The first Minecraft question was which stack could run locally, safely, and repeatably.",
    },
    "choosing-embodiment-stack": {
        "tags": ["minecraft", "architecture", "decisions"],
        "excerpt": "The embodiment stack was chosen through decision records, not enthusiasm.",
        "question": "Which Minecraft stack gives agents a live world while staying maintainable?",
        "system": "The decision records selected Paper, a pinned Mindcraft path, Mineflayer, Node, Java, offline development auth, OBS capture expectations, and licensing/hosting constraints.",
        "evidence": [
            "Commit `427e658f` recorded the Minecraft pivot decisions.",
            "`docs/decisions/0000-summary.md` through `docs/decisions/0007-licensing.md` capture the stack choices.",
            "Issues #518-#524 and `docs/minecraft/server-setup.md` define early launch gates.",
        ],
        "broke": "Every dependency choice created an integration boundary: Java server ops, Node bot control, Python orchestration, and video capture all had to agree.",
        "signal": "The signal is ADR discipline: fast pivots still need written constraints.",
        "next": "With the stack chosen, I needed a Mindcraft fork that served this project rather than swallowing it.",
    },
    "forking-mindcraft": {
        "tags": ["mindcraft", "minecraft", "model-routing"],
        "excerpt": "The Mindcraft fork had to be reproducible, minimal, and subordinate to the research thesis.",
        "question": "How do I use an existing Minecraft agent stack without losing control of model routing and profile semantics?",
        "system": "I pinned a fork, verified install, connected a stock bot, mapped model assignments into profile schema, stripped unused features, and documented upstream-merge policy.",
        "evidence": [
            "E3 issues #533-#539 tracked the Mindcraft fork evaluation.",
            "Commits `a9cedf41`, `f0eb5878`, `f7bdaeed`, `dfc7b9b7`, and `38820654` landed the fork work.",
            "`docs/minecraft/mindcraft-fork.md`, `docs/minecraft/model-routing.md`, and the epic-505 alpha-loop summary document the choices.",
        ],
        "broke": "A fork can become a second product. I had to keep divergence small and generated from the canonical agent config.",
        "signal": "The signal is integration discipline: reuse the runtime without surrendering the experiment design.",
        "next": "Next came the bridge between Minecraft bodies and the Python brain.",
    },
    "python-node-bridge": {
        "tags": ["bridge", "minecraft", "architecture"],
        "excerpt": "The Python-to-Node bridge connected Minecraft embodiment to memory, Management, cost gates, and observability.",
        "question": "How should a Node bot ask the Python system for memory, safety review, and decisions?",
        "system": "I built an authenticated bridge contract between Mindcraft and the Python backend. The bridge preserved Management review, model routing, cost visibility, kill-switch compatibility, and observability instead of letting the Node side become a parallel brain.",
        "evidence": [
            "E4 issues #540-#548 covered the bridge contract and integration.",
            "Commit `0daec3fe` completed the Python-Node bridge epic.",
            "`docs/decisions/0010-bridge-protocol.md`, `docs/minecraft/bridge-contract.md`, and `.alpha-loop/learnings/session-session-epic-506-epic-e4-python-node-bridge.json` describe the protocol.",
        ],
        "broke": "Every bridge verb is a distributed-systems contract; success labels from one side are not proof of world-state change.",
        "signal": "The signal is boundary design across languages and runtimes.",
        "next": "The first service to expose through that bridge was memory.",
    },
    "memory-leaves-office": {
        "tags": ["memory", "embodiment", "minecraft"],
        "excerpt": "Embodied agents needed the same three-tier memory semantics, not a new bridge-specific memory system.",
        "question": "Can Minecraft agents remember through the canonical memory architecture?",
        "system": "I exposed memory read/write paths through the bridge, preserved tool-facing parity, wired perception and action events into recall and archival memory, supported memory seeds, and added regression/performance gates.",
        "evidence": [
            "E5 issues #549-#555 and #658 covered memory service exposure.",
            "Commits `acc1961b`, `96f0f136`, `b2bec526`, `1d662024`, `f581bb1d`, and `ce851eb5` landed the memory bridge pieces.",
            "`docs/minecraft/memory-bridge-performance.md` and the epic-507 alpha-loop summary document the lesson: bridge adapters must stay thin.",
        ],
        "broke": "Duplicating memory semantics in bridge handlers would create divergent identity between simulated and embodied agents.",
        "signal": "The signal is architectural restraint: expose canonical managers instead of reinventing them at integration boundaries.",
        "next": "Memory made embodied action persistent; the next challenge was verifying action itself.",
    },
    "verification-over-vibes": {
        "tags": ["verification", "embodiment", "minecraft"],
        "excerpt": "Embodied action required independent verification of movement, placement, perception, and failure modes.",
        "question": "How do I know a bot did something in Minecraft rather than merely reported success?",
        "system": "The embodiment layer added curated skills, movement, observation, block placement, crafting/gathering categories, failure taxonomy, and Python-side verification. The bridge started treating action outcomes as evidence to check.",
        "evidence": [
            "E6 issues #556-#564 covered the embodiment action layer.",
            ".alpha-loop summary `session-summary-session-epic-508-epic-e6-embodiment-action-layer.md` emphasizes independent verification.",
            "`docs/minecraft/failure-taxonomy.md`, `docs/minecraft/action-command-reliability.md`, and `core/embodiment/` define the reliability surface.",
        ],
        "broke": "Runtime success labels were not enough. The system needed to verify position, inventory, block mutations, and failure reasons.",
        "signal": "The signal is empirical discipline: trust the world state, not the bot's narration.",
        "next": "Alpha became the first vertical slice through the whole embodied stack.",
    },
    "alpha-vertical-slice": {
        "tags": ["alpha", "minecraft", "vertical-slice"],
        "excerpt": "Alpha proved the first end-to-end embodied slice across profile, task, memory, Management, cost, and kill-switch paths.",
        "question": "Can one agent complete a small embodied loop through every load-bearing system?",
        "system": "Alpha got a profile, errand verbs, poll/complete bridge calls, verified world action, memory writes, Management review, cost gate participation, and an acceptance report.",
        "evidence": [
            "E7 issues #565-#571 tracked the Alpha vertical slice.",
            ".alpha-loop summary `session-summary-session-epic-509-epic-e7-alpha-vertical-slice.md` documents evidence freshness and contract-first bridge verbs.",
            "`docs/minecraft/alpha-slice-report.md`, `docs/minecraft/alpha-profile.md`, and `docs/minecraft/alpha-errand.md` capture the slice.",
        ],
        "broke": "A stale acceptance artifact can be worse than no artifact. Evidence freshness had to become part of the gate.",
        "signal": "The signal is vertical-slice discipline: prove one narrow path end to end before broadening.",
        "next": "The next expansion was all-agent embodiment and a move away from one central director.",
    },
    "retiring-central-director": {
        "tags": ["decentralization", "minecraft", "multi-agent"],
        "excerpt": "All-agent embodiment forced a rethink of centralized conversation control.",
        "question": "What changes when every agent has a body instead of sharing a single simulated room?",
        "system": "I generated profiles for all agents, mapped personalities into Minecraft, kept Management out of band, and tested decentralized conversation behavior. The move made local perception and embodied context more important than a single conversation scheduler.",
        "evidence": [
            "E8 issues #572-#580 and #706-#721 covered all-agent embodiment and decentralized conversation.",
            "`docs/decisions/0004-decentralized-conversation.md` records the architectural move.",
            "`docs/minecraft/personality-mapping.md`, `docs/minecraft/multi-agent-soak.md`, and the epic-510 alpha-loop summary capture the embodiment work.",
        ],
        "broke": "Pure decentralization created coordination gaps. Bodies alone did not guarantee shared scene understanding.",
        "signal": "The signal is willingness to retire an early architecture when the environment changes.",
        "next": "Persistent embodied autonomy raised the stakes for cost controls and kill switches.",
    },
    "autonomy-needs-kill-switch": {
        "tags": ["safety", "cost-governance", "autonomy"],
        "excerpt": "Persistent autonomy needs hard caps, spend alerts, and kill paths that halt both bots and world loops.",
        "question": "What safeguards are required before agents run continuously in a live world?",
        "system": "I hardened per-simulation caps, per-agent hourly spend caps, phone-accessible kill switch paths, Node bot halt behavior, world-loop halt behavior, spend alerting, and regression gates.",
        "evidence": [
            "E11 issues #594-#600 covered cost and kill-switch hardening.",
            "Commits `2dd70dc2`, `61078296`, `4a806ff9`, `c0ff268c`, `cc36eace`, and `ccac1382` landed the hardening work.",
            "`docs/cost-kill-audit.md`, `docs/kill-switch-operator.md`, and the epic-513 alpha-loop summary document the gates.",
        ],
        "broke": "Several failures were environmental or preflight failures rather than code failures, which is exactly why operator-facing checks matter.",
        "signal": "The signal is safety engineering for autonomous systems with real spend and public output.",
        "next": "The streaming pipeline needed the same operational posture.",
    },
    "livestream-pipeline-ops-system": {
        "tags": ["livestream", "ops", "reliability"],
        "excerpt": "The livestream pipeline is an operations system, not a media accessory.",
        "question": "What has to be reliable for a 24/7 agent world to be public?",
        "system": "I added capture prototypes, encoder/RTMP push, overlays, TTS audio routing, stream resilience, stream kill path, health monitoring, alerting, and runbooks.",
        "evidence": [
            "E13 issues #609-#616 covered the livestream pipeline.",
            "Commits `bf7a6cc7`, `fddabc29`, `22b35eb7`, `571dbd5c`, `20eeb4fd`, `59aadebf`, and `cc72037a` landed the pipeline.",
            "`docs/livestream/` and the epic-515 alpha-loop summary define the operational surface.",
        ],
        "broke": "Streaming failures often show up as environment problems: missing devices, encoder drift, readiness timing, or stale credentials.",
        "signal": "The signal is reliability thinking: public research systems need operator runbooks.",
        "next": "The next coordination layer came from a surprising place: reintroducing direction, but with evidence.",
    },
    "director-v2-evidence-coordination": {
        "tags": ["director-v2", "coordination", "minecraft"],
        "excerpt": "Director V2 reintroduced coordination as evidence-backed scene management rather than centralized puppeteering.",
        "question": "How can agents coordinate without erasing decentralized embodiment?",
        "system": "Director V2 added scene inboxes, spatial hearing, turn scheduling, prompt gates, memory digests, tool parity, macro scheduling, and scale gates. It was a coordination layer grounded in what agents could perceive and do.",
        "evidence": [
            "E8.5 issues #750-#758 covered Director V2 tool parity and architecture.",
            "`docs/decisions/0011-director-v2-architecture.md` and `docs/minecraft/director-v2-architecture.md` define the design.",
            ".alpha-loop summary `session-summary-session-epic-749-epic-e8-5-minecraft-director-v2-tool-parity.md` captures the tool-parity lesson.",
        ],
        "broke": "Without tool parity, a director can ask agents to coordinate around capabilities they cannot actually use.",
        "signal": "The signal is nuanced architecture: coordination is useful when it is bounded by evidence and tools.",
        "next": "Before testing commands live, I wanted a text-only harness.",
    },
    "minecraft-commands-without-minecraft": {
        "tags": ["minecraft", "evals", "commands"],
        "excerpt": "The E17 command harness tested Minecraft command generation before risking live-world execution.",
        "question": "Can command understanding be evaluated before a bot touches the world?",
        "system": "I built a text-only harness with command schema extraction, skill cards, fixture generation, provider runner, parser, semantic evaluator, report artifacts, package scripts, docs, and regression tests.",
        "evidence": [
            "E17 issues #777-#783 covered the text-only Minecraft command eval harness.",
            "Commits `abceb0fd`, `313dae0f`, `d6cb92f2`, `b7f84203`, and `37659c78` landed the harness.",
            "`docs/minecraft/command-eval.md` and the epic-772 alpha-loop summary define the eval flow.",
        ],
        "broke": "Text-only correctness does not prove live-world reliability. It only reduces the category of errors that reach Minecraft.",
        "signal": "The signal is staged evaluation: test contracts before expensive or stateful execution.",
        "next": "The next step was replaying passing command artifacts in a live flat world.",
    },
    "flat-world-live-evals": {
        "tags": ["minecraft", "live-evals", "verification"],
        "excerpt": "E18 moved from text command artifacts to live flat-world evaluation with action telemetry.",
        "question": "What breaks when passing text commands meet a real Minecraft world?",
        "system": "I added a deterministic flat-world profile, individual command smoke CLI, dataset replay runner, pathfinding/collision categories, inventory and block mutation evals, death-loop and safe-spawn checks, multi-agent timing, and live reports.",
        "evidence": [
            "E18 issues #784-#791 covered flat-world live eval jobs.",
            "Commits `f5c8f389`, `3fca4e54`, `aa4f67c4`, `95145173`, `e4b1b03d`, `d96b5663`, `dafbeaa2`, and `6c9765c8` landed the categories.",
            "`docs/minecraft/open-settlement-smoke.md`, `docs/minecraft/failure-taxonomy.md`, and the epic-773 alpha-loop summary ground the live evals.",
        ],
        "broke": "Live-world failures include pathfinding, timing, inventory, spawn, and bridge issues that pure text evals cannot see.",
        "signal": "The signal is validation layering from cheap static checks to stateful world checks.",
        "next": "Before opening the repo wider, I needed public safety and readiness gates.",
    },
    "open-source-readiness-safety-gate": {
        "tags": ["open-source", "safety", "readiness"],
        "excerpt": "Open-source readiness became a safety gate, not just a documentation task.",
        "question": "What must be disabled, documented, or guarded before a public launch?",
        "system": "I added readiness gates around unsafe public paths, Management-disabled broadcasts, builder spend visibility, Minecraft-first documentation, and public audit reporting.",
        "evidence": [
            "Issues #808-#813 covered open-source readiness work.",
            "Commits `17446920` and `bd029665` added readiness gates and docs.",
            "`docs/OPEN_SOURCE_READINESS.md` and `docs/OPEN_SOURCE_AUDIT_REPORT.md` capture the safety posture.",
        ],
        "broke": "A public repo can make experimental paths look supported if unsafe or incomplete routes are not clearly gated.",
        "signal": "The signal is launch judgment: public access needs safety posture and documentation alignment.",
        "next": "The next challenge was preserving the agent inner-life features through embodiment.",
    },
    "preserving-dreams-journals-embodiment": {
        "tags": ["journals", "dreams", "embodiment"],
        "excerpt": "Dreams, journals, image generation, and website publishing had to survive the move into embodied Minecraft runs.",
        "question": "Can reflective systems survive a change in world substrate?",
        "system": "I preserved reflection, dreams, journals, generated journal illustrations, website publishing, and regression tests while the agent world moved from simulation to Minecraft embodiment.",
        "evidence": [
            "E9 issues #581-#586 and #709 covered dreams, journals, and website publishing preservation.",
            "Commits `3cf773e5`, `bb4749a0`, `5816287f`, and `94cab199` landed the preservation work.",
            "`docs/run-modes.md`, journal code paths, and the epic-511 alpha-loop records anchor the feature migration.",
        ],
        "broke": "World-layer migrations can silently drop reflective features if tests only cover action execution.",
        "signal": "The signal is continuity discipline: preserve identity and reflection while changing embodiment.",
        "next": "Evals also had to adapt to embodied events.",
    },
    "embodied-eval-reporting": {
        "tags": ["evals", "embodiment", "reporting"],
        "excerpt": "The eval system had to understand embodied events and build verification, not only dialogue.",
        "question": "How should the evaluation suite change when agents act in a physical world?",
        "system": "I added embodied event loaders, build-verification categories, existing suite preservation, run-mode scorecards, regression gates, and build-quality feedback.",
        "evidence": [
            "E10 issues #587-#593 and #714 covered embodied eval reporting.",
            "Commits `c559fab7`, `ca78b3ab`, `fb2f7029`, `af6be0a6`, and `3b670f48` landed the work.",
            "`docs/eval-embodied.md` and `evals/prompts/build_verification.yaml` define the embodied eval additions.",
        ],
        "broke": "Dialogue categories alone can miss the central question: did the world change in the intended way?",
        "signal": "The signal is metric evolution as the system's action space changes.",
        "next": "The next foundation was a run-mode system that could vary starting conditions.",
    },
    "run-modes-starting-conditions": {
        "tags": ["run-modes", "simulation", "minecraft"],
        "excerpt": "Run modes made starting conditions explicit: personas, memory seeds, factions, goals, world inputs, and blackboards.",
        "question": "How do I compare persistent worlds, blank-slate experiments, and scenario-driven runs?",
        "system": "I added a RunSpec, personas, factions and goals, seeded versus blank memory, world inputs, persistent and experimental modes, shared blackboard mechanics, and distress/rescue loops.",
        "evidence": [
            "E12 issues #601-#608, #708-#713, and #775 covered run modes and starting conditions.",
            "Commits `f6d37142`, `9715e971`, `21ad82dc`, `e971cebe`, `20ea55c4`, `c5c4d56b`, and `70fc4195` landed the system.",
            "`docs/run-modes.md`, `docs/run-modes/blank-slate-embodied.md`, and the epic-514 alpha-loop summary define the modes.",
        ],
        "broke": "If starting conditions are implicit, differences between runs become anecdotal rather than experimental.",
        "signal": "The signal is experimental control over initial conditions.",
        "next": "Those modes made it easier to see a negative result: activity was not the same as collaboration.",
    },
    "negative-result-activity-not-collaboration": {
        "tags": ["negative-results", "collaboration", "minecraft"],
        "excerpt": "A lot of visible activity still did not prove rich multi-turn collaboration.",
        "question": "When does agent activity become collaboration rather than parallel motion?",
        "system": "Soak and settlement reports showed actions, build events, queues, and world changes, but they did not always show durable coordination, shared planning, or multi-agent dependency.",
        "evidence": [
            "`logs/andy42-defaults-shakeout/20260525T053712Z/action-reliability.json` and related shakeout logs capture action reliability evidence.",
            "`logs/trial-2026-05-27/20260528T060953Z/acceptance-report.md` records settlement acceptance evidence.",
            "`docs/minecraft/director-v2-acceptance-soak.md` and `docs/minecraft/open-settlement-smoke.md` frame the collaboration criteria.",
        ],
        "broke": "The system could be busy without being meaningfully collaborative.",
        "signal": "The signal is scientific honesty: do not relabel activity as collaboration just because it looks alive.",
        "next": "The next pipeline connected headless simulations to Minecraft replay so world changes could be inspected better.",
    },
    "headless-sim-minecraft-replay": {
        "tags": ["headless", "replay", "minecraft"],
        "excerpt": "Headless simulation and Minecraft replay connected decisions, world events, and visual artifacts.",
        "question": "How can I run a scenario headlessly and still inspect the world evidence afterward?",
        "system": "I added headless RunMode, an EmbodimentExecutor abstraction, decision-log JSONL schema, scenario eval targets, world-event scheduling, needs simulation, headless scoring, website integration, replay viewer paths, and artifacts.",
        "evidence": [
            "E22 issues #851-#861 covered the headless sim and Minecraft replay pipeline.",
            "Commits `e00931d9`, `50713cb5`, `6bad5b36`, `e5836150`, `9f7ba740`, and `2ba1cf13` landed the pipeline.",
            "`docs/MINECRAFT-REPLAY.md`, `core/simulation/decision_log_schema.py`, and the epic-850 alpha-loop summary document the system.",
        ],
        "broke": "The E22 learning was blunt: unit-green features can be production no-ops when per-run services are not threaded into real construction sites.",
        "signal": "The signal is integration realism: tests must cover the path users actually run.",
        "next": "The build path then needed a compiler from intent to Minecraft actions.",
    },
    "build-intent-to-build-script": {
        "tags": ["minecraft", "buildscripts", "compiler"],
        "excerpt": "BuildIntent and BuildPlanCompiler turned agent build proposals into executable Minecraft actions.",
        "question": "How does an agent's build idea become blocks in the world?",
        "system": "I added structured BuildIntent, a reference-image library, BuildPlan decomposition, skill-card macro compilation, RCON execution paths, screenshot capture, refinement wiring, and build-quality scoring.",
        "evidence": [
            "E22 issues #855-#858 and #871-#876 covered BuildIntent, compiler, RCON execution, screenshots, and scoring.",
            "Commits `ae463a7a`, `038bcf5c`, `7597bc97`, `cf58e83f`, `2aa6a589`, `d107efcb`, `27462f92`, and `286c46f6` landed the work.",
            "`core/minecraft/`, `scripts/replay_in_minecraft.py`, and `docs/MINECRAFT-REPLAY.md` define the compiler and replay paths.",
        ],
        "broke": "A compiler can produce plausible instructions that fail structurally in-world, such as hollow walls or openings carved in the wrong order.",
        "signal": "The signal is compiler-minded tool design for agent action.",
        "next": "The next milestone was streaming those BuildScripts into a live server.",
    },
    "streaming-buildscripts-live-world": {
        "tags": ["minecraft", "rcon", "buildscripts"],
        "excerpt": "BuildScripts started streaming into a live Minecraft world through RCON, with failures surfaced instead of skipped.",
        "question": "What changes when the build plan touches a live server?",
        "system": "I wired `propose_build` through the embodied path to stream BuildScripts via RCON, fixed async MCRcon behavior, increased throttling for multi-fill commands, guaranteed wall spans, and connected the compiler/catalog resolver into the headless executor.",
        "evidence": [
            "Commits `b6ed368d`, `2ad9d974`, `1dae306f`, `c2425af2`, `ac89bac5`, and `5cb4d57a` landed live BuildScript streaming.",
            "Issues #885-#888 covered async RCON, throttle, compiler walls, and executor wiring.",
            "`core/minecraft/`, `core/embodiment/`, and `docs/MINECRAFT-REPLAY.md` define the live build path.",
        ],
        "broke": "Bridge failures cannot be silent in a live world; otherwise the agent appears to have acted when nothing changed.",
        "signal": "The signal is production hardening for embodied action pipelines.",
        "next": "Once agents could build, the next question was social infrastructure: ownership, trade, theft, diplomacy, and conflict.",
    },
    "civilization-mechanics-social-infrastructure": {
        "tags": ["civilization", "minecraft", "social-systems"],
        "excerpt": "Civilization mechanics are social infrastructure: ledgers, permissions, incentives, and consequences.",
        "question": "What does a Minecraft civilization need beyond more agents and more blocks?",
        "system": "I added ownership ledgers, claim/release/list tools, trade and pricing, theft and detection, diplomacy, alliances, factions, treaties, conflict categories, and scoring hooks.",
        "evidence": [
            "E21 issues #891-#895 covered ownership, trade, theft, diplomacy, and conflict.",
            "Commits `6b934cf8`, `571b1210`, `b1d3cb03`, `a2e31af7`, and `d02f909e` landed the mechanics.",
            "`docs/minecraft/two-team-civilization-plan.md` and civilization mechanics code paths frame the social system.",
        ],
        "broke": "Social mechanics can become bookkeeping unless agents actually use them to coordinate meaningful work.",
        "signal": "The signal is understanding that collaboration requires institutions, not just chat.",
        "next": "The task board became the next institution.",
    },
    "emergent-task-board": {
        "tags": ["tasks", "emergence", "minecraft"],
        "excerpt": "The emergent task board replaced phase-machine scripting with first-claim-wins coordination.",
        "question": "Can agents coordinate around shared objectives without a rigid settlement script?",
        "system": "I added settlement objective seeding, atomic first-claim-wins task board behavior, Director tool adapter wiring, environment-driven model resolution, emergent build mode, prompt teaching, acceptance tests, and embodied bot bridge commands.",
        "evidence": [
            "Issues #902-#909 covered task board, shared objectives, tool adapter wiring, emergent mode, prompts, and acceptance tests.",
            "Commits `7dd4b062`, `3fb640b2`, `e3cc8630`, `5e35315d`, `9e7ef3fd`, `d43bd330`, and `31eb63d4` landed the mode.",
            "`docs/minecraft/emergent-mode.md` and the epic-820 alpha-loop summary describe the emergent task loop.",
        ],
        "broke": "Prompting agents to build emergently is not enough; authorization and task ownership have to be explicit.",
        "signal": "The signal is replacing brittle phase scripts with coordination primitives.",
        "next": "That led to claim-task as the gate for build authorization.",
    },
    "claim-task-earn-build-right": {
        "tags": ["authorization", "minecraft", "coordination"],
        "excerpt": "Claiming a task became the authorization primitive for planning and building.",
        "question": "How do I connect social commitment to permission to change the world?",
        "system": "The emergent mode began requiring agents to claim a task before they could plan and build. That linked world mutation to explicit task ownership rather than allowing ungrounded build actions.",
        "evidence": [
            "Issue #918 tracked emergent build authorization.",
            "Commit `8bc34469` landed `claim-a-task -> may planAndBuild`.",
            "`docs/minecraft/emergent-mode.md` and the epic-820 alpha-loop summary record the readiness path.",
        ],
        "broke": "Authorization does not guarantee collaboration. It only makes commitment visible enough to evaluate.",
        "signal": "The signal is socio-technical design: permissions encode the behavior the system is trying to study.",
        "next": "The latest cleanup turned to research debt and observability debt.",
    },
    "research-debt-observability-debt": {
        "tags": ["observability", "research-methods", "maintenance"],
        "excerpt": "Research systems accumulate evidence debt as quickly as code debt.",
        "question": "What debt appears when a research prototype becomes a long-running evidence machine?",
        "system": "I consolidated observability, preserved artifact route lookup, tightened decision-log fields, reviewed graph structure, and cleaned repo hygiene. The work was less visible than Minecraft builds but directly tied to whether future findings are traceable.",
        "evidence": [
            "Commits `92eed67b` and `c373e8b8` landed observability consolidation and artifact route lookup preservation.",
            "`graphify-out/GRAPH_REPORT.md` documents code graph structure and review context.",
            "`core/simulation/decision_log_schema.py` and replay/artifact routes define the evidence trail.",
        ],
        "broke": "Research debt appears when artifacts exist but readers cannot trace how decisions, tools, models, and world changes connect.",
        "signal": "The signal is maintenance maturity: observability is part of the research result.",
        "next": "The next phase is to publish the notebook, invite scrutiny, and continue the Minecraft civilization work with the evidence trail intact.",
    },
}


def load_manifest() -> list[dict[str, str]]:
    with MANIFEST.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def wrap(text: str) -> str:
    return "\n".join(textwrap.wrap(text, width=88))


def render_post(row: dict[str, str], previous_slug: str | None, next_slug: str | None) -> str:
    details = DETAILS[row["slug"]]
    tags = json.dumps(details["tags"])
    evidence = "\n".join(f"- {item}" for item in details["evidence"])
    nav_lines: list[str] = []
    if previous_slug:
        nav_lines.append(f"- Previous: `/blog/{previous_slug}`")
    if next_slug:
        nav_lines.append(f"- Next: `/blog/{next_slug}`")
    navigation = "\n".join(nav_lines)

    body = f"""---
title: "{row['title']}"
date: "{row['date']}"
excerpt: "{details['excerpt']}"
tags: {tags}
author: "Brad Taylor"
---

# {row['title']}

This research note is backdated to {row['date']}, the point in the repository
history when this part of the system became concrete enough to write about.

## Research Question

{wrap(str(details['question']))}

## System Move

{wrap(str(details['system']))}

## Evidence

{evidence}

## What Broke

{wrap(str(details['broke']))}

## Why It Matters

{wrap(str(details['signal']))}

## What Changed Next

{wrap(str(details['next']))}

## Series Navigation

{navigation}
"""
    return body


def main() -> int:
    rows = load_manifest()
    missing = sorted({row["slug"] for row in rows} - DETAILS.keys())
    extra = sorted(DETAILS.keys() - {row["slug"] for row in rows})
    if missing or extra:
        raise SystemExit(f"Manifest/detail mismatch. Missing={missing}; extra={extra}")

    if BLOG_DIR.exists():
        for path in BLOG_DIR.glob("*.mdx"):
            path.unlink()
    else:
        BLOG_DIR.mkdir(parents=True)

    for index, row in enumerate(rows):
        previous_slug = rows[index - 1]["slug"] if index > 0 else None
        next_slug = rows[index + 1]["slug"] if index < len(rows) - 1 else None
        (BLOG_DIR / f"{row['slug']}.mdx").write_text(
            render_post(row, previous_slug, next_slug), encoding="utf-8"
        )

    shutil.rmtree(BLOG_DIR / "__pycache__", ignore_errors=True)
    print(f"Wrote {len(rows)} posts to {BLOG_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
