#!/usr/bin/env python3
"""Create the Minecraft-pivot epics + micro-issues on GitHub.

Idempotent & resumable: each issue's title carries its stable key
("E4-3 — ..." / "Epic E4 — ..."). Before creating, we search the repo for
that key in the title and reuse the existing number if found. Key→number
mappings are also cached in docs/.mc-pivot-issues.json.

Two passes after creation:
  B) replace {{KEY}} dependency placeholders in child bodies with #<num>
  C) fill each epic body with its child checklist (parallel vs sequential)
     and epic-level dependencies, using real #<num> references.

Run:  python scripts/minecraft/create_pivot_issues.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "docs" / ".mc-pivot-issues.json"
PLAN = "docs/MINECRAFT-PIVOT-ISSUE-PLAN.md"
SLEEP = 2.0  # be polite to GitHub's secondary rate limiter

LABELS = [
    ("minecraft", "1d7c2f", "Touches Minecraft/Mindcraft/Mineflayer"),
    ("minecraft-beginner", "a2eeef", "Written for someone who has never played Minecraft"),
    ("needs-research", "fbca04", "Must verify a fact before/while implementing"),
    ("parallelizable", "0e8a16", "No intra-epic dependency; safe to run concurrently"),
    ("preserve-no-regress", "b60205", "Must not regress a preserved system"),
    ("area:bridge", "5319e7", "Python<->Node bridge"),
    ("area:embodiment", "5319e7", "Movement/build/skill/action layer"),
    ("area:livestream", "5319e7", "Capture/encode/stream"),
    ("area:run-modes", "5319e7", "Starting-conditions / scenario system"),
    ("area:server", "5319e7", "Minecraft server ops"),
]

# Epics: key -> (title, goal, depends_on_epics)
EPICS = {
    "E1": ("Research, Decisions & Spikes",
           "Resolve every unverified Minecraft/Mindcraft fact (U1-U6) and produce "
           "written decision records the rest of the plan binds to.", []),
    "E2": ("Minecraft Server Setup (beginner)",
           "Stand up a private Minecraft server a non-player can operate 24/7, "
           "with world generation as a configurable input.", ["E1"]),
    "E3": ("Mindcraft Fork & Evaluation",
           "Fork & pin Mindcraft, get one bot connecting, verify/patch per-agent "
           "multi-model OpenRouter routing, strip unused features.", ["E1", "E2"]),
    "E4": ("Python<->Node Bridge",
           "Bidirectional, authenticated, versioned bridge: bots call Python "
           "services; perception/action results flow back.", ["E3"]),
    "E5": ("Memory Service Exposure",
           "Expose the existing 3-tier pgvector memory as a bridge service. "
           "Preserve existing behavior - no regression.", ["E4"]),
    "E6": ("Embodiment / Action Layer",
           "Real movement/building with action-success verification; retain "
           "code-writing as a tool alongside in-world building.", ["E3", "E4"]),
    "E7": ("Alpha Vertical Slice",
           "One embodied agent (Alpha - non-verbal) end-to-end: the integration "
           "crucible proving Option C.", ["E2", "E3", "E4", "E5", "E6"]),
    "E8": ("All Agents Embodied + Decentralized Conversation",
           "Embody all agents with per-agent models; replace the Python "
           "conversation director with Mindcraft's decentralized respond/ignore.",
           ["E7"]),
    "E9": ("Dreams / Journals / Website Publishing Preserved",
           "Keep reflection/dreams/journals running on embodied activity and "
           "publishing. Preserve existing behavior - no regression.", ["E5", "E8"]),
    "E10": ("Eval & Reporting Adapted",
            "Adapt evals/reporting to embodied-world data; add build-"
            "verification signal without losing existing coverage.", ["E8"]),
    "E11": ("Cost Controls & Kill Switch Hardened",
            "Carry over per-sim cap + phone kill switch; BUILD the missing hard "
            "per-agent hourly spend cap; make the kill switch halt the bots.",
            ["E1"]),
    "E12": ("Run-Mode / Starting-Conditions System",
            "Starting conditions drive both the Python brain and the Minecraft "
            "world + Mindcraft profiles; support 24/7 and experimental modes.",
            ["E5", "E8"]),
    "E13": ("Livestream Pipeline",
            "Greenfield: capture the live Minecraft world, encode, stream to "
            "Twitch/YouTube 24/7 with overlays and a kill path.", ["E1", "E2"]),
    "E14": ("Retire the Phaser Layer",
            "Delete the retired Phaser/tilemap/sprite/replay stack - only after "
            "Minecraft capture + adapted website replace them.", ["E13", "E15"]),
    "E15": ("Website Adaptation",
            "World & simulation/replay pages reflect the Minecraft world and "
            "recordings; creator supports the new run modes.", ["E12", "E13"]),
}

# Each issue: key -> dict(epic, title, context, scope_in, scope_out,
#   acceptance, files, deps[list of keys], track('P'|'S'), labels[list])
def I(epic, title, context, scope_in, scope_out, acceptance, files, deps, track, labels):
    return dict(epic=epic, title=title, context=context, scope_in=scope_in,
                scope_out=scope_out, acceptance=acceptance, files=files,
                deps=deps, track=track, labels=labels)

B = "backend"
F = "frontend"
MC = "minecraft"
MCB = "minecraft-beginner"
NR = "needs-research"
PNR = "preserve-no-regress"
ARCH = "architecture"
QA = "qa"
DOC = "documentation"
NHI = "needs-human-input"

ISSUES: dict[str, dict] = {

 # ---- EPIC 1 ----
 "E1-R1": I("E1","Decide & pin Minecraft version + server software for 24/7",
   "U4/U6. Everything pins to this; a non-player must run it.",
   "Compare vanilla server jar vs Paper vs Fabric for headless 24/7; confirm exact MC version compatible with the Mindcraft commit we pin; plain-language explanation of each option.",
   "Actually installing it (E2).",
   "docs/decisions/0001-minecraft-version-and-server.md states chosen MC version, server software, Mindcraft commit hash, compatibility evidence, beginner glossary.",
   "docs/decisions/0001-*.md", [], "P", [NR,MC,MCB,"area:server"]),
 "E1-R2": I("E1","Decide auth/offline mode posture",
   "U4. Private server with no Microsoft accounts implies online-mode=false; security & EULA implications a beginner must understand.",
   "Document what offline mode is, its tradeoffs on a firewalled private server, whether Mindcraft bots need Microsoft auth in our topology; recommend a posture.",
   "Server config (E2).",
   "docs/decisions/0002-auth-mode.md with recommendation + plain-language risk explanation.",
   "docs/decisions/0002-*.md", ["E1-R1"], "P", [NR,MC,MCB,"area:server"]),
 "E1-R3": I("E1","Verify Mindcraft per-agent multi-model OpenRouter routing (U1)",
   "Highest-leverage unknown. Core thesis = each agent on a different OpenRouter model with separate conversation/building tiers.",
   "Inspect the pinned Mindcraft commit's provider code + profile schema; determine if OpenRouter is fully wired and whether model vs code_model map to our conversation vs building tiers; specify exact fork patch if not.",
   "Writing the patch (E3).",
   "docs/decisions/0003-mindcraft-model-routing.md answers: native? per-agent-per-tier? patch scope. Cites file/line in the Mindcraft commit.",
   "docs/decisions/0003-*.md; cross-ref core/llm_client.py", ["E1-R1"], "P", [NR,MC,B]),
 "E1-R4": I("E1","Characterize Mindcraft's decentralized respond/ignore model (U2)",
   "The pivot deletes the Python conversation director and relies on Mindcraft's per-agent respond/ignore behavior.",
   "Document exactly how Mindcraft decides whether a bot responds; what's configurable; map onto our chattiness/initiative/adjacency knobs; flag gaps.",
   "Code.",
   "docs/decisions/0004-decentralized-conversation.md with mechanism from source + a mapping table to agents/<id>/config.yaml knobs, gaps listed.",
   "docs/decisions/0004-*.md; cross-ref agents/*/config.yaml", ["E1-R1"], "P", [NR,MC]),
 "E1-R5": I("E1","Identify Mindcraft custom-skill / custom-action extension point (U3)",
   "The bridge design depends entirely on how we add a 'call Python' action without forking core.",
   "Document the skill/command/action registration mechanism; produce a throwaway spike adding a no-op custom action.",
   "The real bridge (E4).",
   "docs/decisions/0005-skill-extension-point.md + a spike branch proving a custom action registers and fires in-game.",
   "docs/decisions/0005-*.md", ["E1-R1","E2-1"], "S", [NR,MC,"area:bridge"]),
 "E1-R6": I("E1","Decide the Minecraft->video capture method (U5)",
   "Livestream is greenfield (V9). Options: headless spectator client, real client + OBS on GPU host, server-side renderer, third-party.",
   "Evaluate feasibility/cost/24-7-resilience of each; recommend one; note hosting/GPU implications feeding back into E2/E13.",
   "Building it (E13).",
   "docs/decisions/0006-video-capture.md with recommendation, cost/hosting implications, fallback.",
   "docs/decisions/0006-*.md", ["E1-R1"], "P", [NR,MC,"area:livestream"]),
 "E1-R7": I("E1","Minecraft EULA / streaming-licensing posture",
   "24/7 monetized stream with offline-mode servers - confirm permitted and what limits apply.",
   "Summarize Mojang/Microsoft EULA + commercial-use/streaming guidance relevant to a monetized 24/7 AI stream; flag anything needing human/legal decision.",
   "Legal sign-off (escalate).",
   "docs/decisions/0007-licensing.md with findings + explicit 'needs human/legal decision' list.",
   "docs/decisions/0007-*.md", [], "P", [NR,NHI]),
 "E1-R8": I("E1","Consolidated decision record + plan reconciliation",
   "Downstream issues bind to E1 outputs; one place must state final pinned values.",
   "A single docs/decisions/0000-summary.md table of every decided value; reconcile this plan's flagged assumptions against decisions; note epic scope changes.",
   "",
   "Summary doc exists; any epic whose scope changed has a comment noting the delta.",
   "docs/decisions/0000-summary.md", ["E1-R1","E1-R2","E1-R3","E1-R4","E1-R5","E1-R6","E1-R7"], "S", [NR]),

 # ---- EPIC 2 ----
 "E2-1": I("E2","Provision and run the chosen server locally (beginner walkthrough)",
   "Foundation. Reader has never installed a Minecraft server.",
   "Step-by-step: Java install, server jar/Paper per E1-R1, EULA accept, first boot, server.properties essentials in plain language, online-mode per E1-R2; a start script.",
   "Cloud hosting (E2-3), 24/7 supervision (E2-4).",
   "docs/minecraft/server-setup.md runbook; a fresh machine reaches a running server following only the doc; start script committed.",
   "docs/minecraft/server-setup.md, scripts/minecraft/start-server.sh",
   ["E1-R1","E1-R2"], "S", [MC,MCB,"area:server"]),
 "E2-2": I("E2","World generation as a configurable input (seed/type/spawn)",
   "Run modes need world as an input, not hardcoded.",
   "Parameterize world seed/type/spawn via a config file consumed by the start script; explain 'seed' for a beginner.",
   "Wiring into run-mode system (E12).",
   "Changing the world config file produces a different world on a fresh run; documented.",
   "scripts/minecraft/world.config, docs/minecraft/world-config.md",
   ["E2-1"], "P", [MC,MCB,"area:server"]),
 "E2-3": I("E2","Decide & document hosting for 24/7 (local vs cloud)",
   "24/7 needs a durable host; tie to E1-R6 (capture host may co-locate).",
   "Document a recommended host (spec, OS, cost) and tradeoffs; no provisioning automation yet.",
   "IaC.",
   "docs/minecraft/hosting.md with concrete recommendation + cost estimate; cross-refs E1-R6.",
   "docs/minecraft/hosting.md", ["E2-1","E1-R6"], "P", [MC,MCB,"area:server"]),
 "E2-4": I("E2","24/7 supervision: auto-restart + crash recovery",
   "A 24/7 world must survive crashes unattended.",
   "A supervisor (systemd/process manager) that restarts the server on crash, with logs; documented for a beginner.",
   "Alerting (E11/E13).",
   "Killing the server process auto-restarts within a documented window; logs retained.",
   "scripts/minecraft/minecraft.service, docs", ["E2-1"], "P", [MC,MCB,"area:server"]),
 "E2-5": I("E2","World backup & restore",
   "A persistent world is irreplaceable; experimental runs need resets.",
   "Scripted periodic backup + documented restore + a 'reset to fresh world' path used by experimental mode.",
   "Run-mode wiring (E12).",
   "Backup runs on schedule; documented restore recreates a prior world; reset produces a clean world.",
   "scripts/minecraft/backup.sh, scripts/minecraft/restore.sh, docs",
   ["E2-1","E2-2"], "P", [MC,MCB,"area:server"]),
 "E2-6": I("E2","Server health check + status endpoint",
   "The Python brain / livestream must know the world is up.",
   "A lightweight health probe (port/ping) reporting server liveness; integrate with the scripts/check-services.sh pattern.",
   "Dashboards.",
   "A single command reports server up/down; integrates with scripts/check-services.sh.",
   "scripts/minecraft/health.sh, scripts/check-services.sh",
   ["E2-1","E2-4"], "S", [MC,"area:server"]),
 "E2-7": I("E2","Server ops runbook (beginner) + teardown",
   "The owner must operate this without Minecraft knowledge.",
   "Consolidate start/stop/backup/restore/restart/health into one plain-language runbook; include clean teardown.",
   "",
   "docs/minecraft/runbook.md covers every operation with copy-paste commands and what each does.",
   "docs/minecraft/runbook.md", ["E2-1","E2-2","E2-3","E2-4","E2-5","E2-6"], "S",
   [MC,MCB,"area:server"]),

 # ---- EPIC 3 ----
 "E3-1": I("E3","Fork Mindcraft, pin the commit, reproducible install",
   "We need a stable base; upstream moves fast.",
   "Fork to the org, pin the E1-R1 commit, document exact Node/npm versions and install steps, commit a lockfile.",
   "Customizations.",
   "A clean checkout installs deterministically from the documented steps; commit hash recorded in docs/decisions/0000-summary.md.",
   "fork repo, docs", ["E1-R1","E1-R8"], "S", [MC,"area:bridge"]),
 "E3-2": I("E3","One stock bot connects to the E2 server",
   "Prove the fork talks to our server before customizing.",
   "Configure settings.js/profile to point at the E2 server (host/port/auth per E1-R2), launch one stock bot, confirm spawn+move.",
   "Our agents (E8).",
   "Documented command launches a bot that visibly joins the E2 world.",
   "fork settings.js/profile", ["E3-1","E2-1"], "S", [MC,MCB]),
 "E3-3": I("E3","Verify/patch per-agent multi-model OpenRouter routing",
   "Core thesis (U1/E1-R3). preserve-no-regress on model assignments.",
   "Implement E1-R3's conclusion - configure native OpenRouter or apply the specified fork patch - so a profile routes model (conversation tier) and code_model (building tier) to distinct OpenRouter models per agent.",
   "All 9 profiles (E8).",
   "Two bots with different profiles hit two different OpenRouter models for chat vs code; mirrors core/llm_client.py MODEL_NAME_ALIASES/MODEL_REGISTRY; documented.",
   "fork profile/provider config; cross-ref core/llm_client.py",
   ["E1-R3","E3-2"], "S", [MC,B,PNR]),
 "E3-4": I("E3","Map our agent model assignments -> Mindcraft profile schema",
   "Single source of truth (agents/<id>/config.yaml, CLAUDE.md table) must drive Mindcraft profiles.",
   "A generator reading agents/<id>/config.yaml (model_conversation, model_building) emitting Mindcraft profile JSON; one agent proven.",
   "Running all agents (E8).",
   "Generator emits a valid profile for vera whose model/code_model match agents/vera/config.yaml; unit-tested.",
   "scripts/minecraft/gen_profiles.py, tests/backend/test_mc_profile_gen.py",
   ["E3-3"], "P", [MC,B,PNR]),
 "E3-5": I("E3","Strip/disable unused Mindcraft features",
   "Reduce surface area and cost; we own conversation/memory elsewhere.",
   "Disable Mindcraft features superseded by the Python brain (its own memory/persona/voice if redundant) per E1-R3/R4, behind config flags, reversible.",
   "Irreversible deletion of fork core.",
   "Documented list of disabled features + rationale; a bot still connects and acts with them off.",
   "fork config", ["E3-3","E1-R4"], "P", [MC]),
 "E3-6": I("E3","Fork maintenance & upstream-merge policy",
   "We must take upstream fixes without losing patches.",
   "Document branch strategy (patches isolated), how to re-base on upstream, and a CI check that the fork builds.",
   "New CI infra if none exists - open a follow-up.",
   "docs/minecraft/fork-maintenance.md + a green build check.",
   "docs/minecraft/fork-maintenance.md", ["E3-1"], "P", [MC,ARCH]),
 "E3-7": I("E3","(Conditional) OpenRouter routing fork-patch hardening",
   "Only if E1-R3 concluded a patch is required and E3-3 was non-trivial.",
   "Tests for the routing patch (model selection, fallback, cost attribution) so an upstream rebase can't silently break the thesis.",
   "",
   "Tests fail if per-agent/per-tier routing breaks.",
   "fork tests", ["E3-3"], "S", [MC,B,PNR,NR]),

 # ---- EPIC 4 ----
 "E4-1": I("E4","Bridge transport & protocol decision record",
   "Choose HTTP/WebSocket/IPC given E1-R5's extension point; FastAPI app has /ws.",
   "Decide transport, message envelope, versioning, auth (shared secret/local-only), failure semantics; ADR.",
   "Code.",
   "docs/decisions/0010-bridge-protocol.md; consistent with E1-R5.",
   "docs/decisions/0010-*.md", ["E1-R5"], "S", ["area:bridge",ARCH,NR]),
 "E4-2": I("E4","Versioned message contract (schemas both sides)",
   "A shared contract prevents Node/Python drift.",
   "Define request/response schemas for initial verbs (memory.read, memory.write, management.review, cost.gate, perception.report, action.result); Pydantic + JSON schema.",
   "",
   "Schemas committed; a contract test validates both directions against fixtures.",
   "core/bridge/contract.py, tests/backend/test_bridge_contract.py",
   ["E4-1"], "S", ["area:bridge",B]),
 "E4-3": I("E4","Python bridge server endpoint",
   "FastAPI app exists (core/main.py); add the bridge surface.",
   "A mounted bridge router/WS handler that auth-checks and dispatches to stub handlers; no business logic.",
   "Real memory/mgmt wiring (E5/E8).",
   "Bridge endpoint accepts a valid signed message and echoes a contract-valid stub response; rejects unauthenticated calls.",
   "core/bridge/server.py, core/main.py, tests/backend/test_bridge_server.py",
   ["E4-2"], "S", ["area:bridge",B]),
 "E4-4": I("E4","Node bridge client in the fork",
   "Bots need a client to call Python; built at E1-R5's extension point.",
   "A Node module sending contract messages, handling auth/timeout/structured errors; one custom Mindcraft action round-tripping a ping.",
   "",
   "In-game, a bot invokes the ping action and logs the Python response; failure path logged, not crashed.",
   "fork node client + custom action", ["E4-3","E1-R5","E3-2"], "P",
   ["area:bridge",MC]),
 "E4-5": I("E4","Reconnect, backpressure & timeout policy",
   "24/7 means the bridge will drop; bots must degrade safely.",
   "Reconnect with backoff on the Node client; bounded in-flight requests; defined behavior when Python is unreachable (safe-idle, never unsafe action).",
   "",
   "Killing the Python server mid-run causes bots to safe-idle and auto-recover; covered by an integration test.",
   "fork node client", ["E4-4"], "P", ["area:bridge",MC]),
 "E4-6": I("E4","Perception/action result channel (Node->Python)",
   "Option C requires perception/action outcomes flowing back.",
   "Node emits structured perception + action-result events over the bridge; Python stores them (reuse core/event_bus.py).",
   "Memory writes (E5), eval use (E10).",
   "An in-game action produces a perception/result event observable on the Python side; schema-validated.",
   "core/bridge/inbound.py, core/event_bus.py", ["E4-3","E4-4"], "P",
   ["area:bridge",B]),
 "E4-7": I("E4","Bridge observability (logs, metrics, trace IDs)",
   "Debugging a cross-language 24/7 system needs correlation.",
   "Correlation/trace IDs across Node<->Python, structured logs both sides, basic counters (calls, errors, latency).",
   "",
   "A single request is traceable end-to-end via one trace ID in both logs.",
   "core/bridge/*, fork node client", ["E4-3","E4-4"], "P", ["area:bridge"]),
 "E4-8": I("E4","Bridge integration test harness",
   "Future epics need to test against a fake bridge without a server.",
   "A Python-side fake Node client + a Node-side fake Python server, reusable in E5-E12 tests; CI-runnable without Minecraft.",
   "",
   "Harness ships; one example test in tests/integration/ uses it.",
   "tests/integration/bridge_harness.py", ["E4-3","E4-4","E4-5","E4-6"], "S",
   ["area:bridge",QA]),
 "E4-9": I("E4","Bridge security review",
   "A local RPC surface that can trigger spend and in-world actions.",
   "Threat-model the bridge (auth, replay, injection into actions, DoS), apply fixes; uses security-analysis skill standards.",
   "",
   "Documented threat model + mitigations; no unauthenticated path can trigger spend or actions.",
   "core/bridge/*", ["E4-3","E4-4","E4-5","E4-6","E4-7"], "S", ["area:bridge",ARCH]),

 # ---- EPIC 5 ----
 "E5-1": I("E5","Memory bridge service: read paths",
   "Bots must query core/recall/archival memory; logic stays in core/memory/.",
   "Bridge verbs calling existing managers read-only; no new memory logic.",
   "Writes (E5-2).",
   "A bot fetches an agent's core memory + a recall search result via the bridge; results identical to direct manager calls.",
   "core/bridge/handlers/memory.py; cross-ref core/memory/*",
   ["E4-3","E4-4"], "S", ["area:bridge",B,PNR]),
 "E5-2": I("E5","Memory bridge service: write/append paths",
   "Embodied events must be writable to recall/archival.",
   "Bridge verbs delegating to existing append/write methods + core/repos/memory_repo.py; preserve compaction triggers.",
   "Perception auto-write (E5-4).",
   "A bridge write produces the same DB rows/embeddings as a direct manager call; test_recall_memory.py, test_archival_memory.py, test_memory_tools.py green.",
   "core/bridge/handlers/memory.py, core/repos/memory_repo.py",
   ["E5-1"], "S", ["area:bridge",B,PNR]),
 "E5-3": I("E5","Preserve tool-facing memory API parity",
   "tools/memory_tools.py defines the agent-facing memory API; no divergent second API.",
   "Make bridge memory verbs delegate to the same code path as tools/memory_tools.py; document the single source of truth.",
   "",
   "test_memory_tools.py unchanged & green; a parity test asserts bridge and tool paths return equivalent results.",
   "tools/memory_tools.py, core/bridge/handlers/memory.py",
   ["E5-1"], "P", [B,PNR]),
 "E5-4": I("E5","Wire perception/action events -> recall/archival",
   "E4-6 emits embodied events; they should feed memory like conversation turns.",
   "A consumer mapping perception/action-result events into recall/archival via existing managers (no new memory semantics).",
   "",
   "An in-game action results in a retrievable recall memory; embeddings via core/memory/embeddings.py.",
   "core/bridge/inbound.py, core/memory/*", ["E4-6","E5-2"], "P",
   ["area:bridge",B,PNR]),
 "E5-5": I("E5","Memory-seed compatibility with embodied runs",
   "core/memory/memory_seed.py + MemorySeedConfig + scenarios/seeds/* must still apply before embodied agents start.",
   "Confirm the seed path (orchestrator._apply_memory_seed) still runs and seeded memories are visible to bots via the bridge.",
   "New seed formats (E12).",
   "A run seeded from scenarios/seeds/blank-slate.json shows the seeded core memory through the bridge; test_memory_seed.py green.",
   "core/memory/memory_seed.py, core/simulation/orchestrator.py",
   ["E5-1"], "S", [B,PNR,"area:run-modes"]),
 "E5-6": I("E5","Memory regression suite gate",
   "Lock in 'no regression' before E7.",
   "A CI gate running the full memory test set against the bridge path.",
   "",
   "Gate is required and green (test_core_memory*, test_recall_memory, test_archival_memory, test_cross_conversation_memory, test_memory_seed, test_memory_snapshot, test_memory_tools).",
   "CI config", ["E5-1","E5-2","E5-3","E5-4","E5-5"], "S", [QA,PNR]),
 "E5-7": I("E5","Memory bridge performance check",
   "24/7 + many memory reads per action; latency matters.",
   "Measure bridge memory read/write latency vs direct calls; set a documented budget; flag if pgvector recall is too slow per action.",
   "",
   "Latency report committed; within documented budget or a follow-up issue filed.",
   "docs", ["E5-1","E5-2"], "S", ["area:bridge",B]),

 # ---- EPIC 6 ----
 "E6-1": I("E6","Curated skill set definition",
   "Mindcraft ships many actions; we want a deliberate, verifiable set.",
   "Enumerate allowed action/skill set (move, navigate, place, break, craft, inventory, build-from-plan, observe) and excluded ones; document.",
   "Implementation of each (later issues).",
   "docs/minecraft/skill-set.md listing each skill, its inputs, and its verification signal.",
   "docs/minecraft/skill-set.md", ["E1-R4","E1-R5","E3-5"], "S",
   ["area:embodiment",MC]),
 "E6-2": I("E6","Movement & navigation with success verification",
   "Agents must move and KNOW they arrived (the verification mechanism the project lacked).",
   "Movement skills returning a verified outcome (reached/blocked/timed out) via the E4-6 channel.",
   "Building.",
   "A navigate action reports verified success/failure observable on the Python side.",
   "fork skills, core/bridge/inbound.py", ["E6-1","E4-6"], "P",
   ["area:embodiment",MC]),
 "E6-3": I("E6","Block place/break with success verification",
   "Building primitives must be self-verifying.",
   "Place/break skills that confirm the world actually changed (post-action world read), reporting verified result.",
   "",
   "Placing a block reports verified success only if the block is actually present afterward.",
   "fork skills", ["E6-1","E4-6"], "P", ["area:embodiment",MC]),
 "E6-4": I("E6","Build-from-plan skill (multi-block structures)",
   "'Genuinely build things, with verification' is the headline goal.",
   "A skill taking a structured build plan and executing it, returning per-step verified results + overall completion metric.",
   "",
   "A small predefined structure builds and the result reports actual vs intended blocks.",
   "fork skills", ["E6-3"], "P", ["area:embodiment",MC]),
 "E6-5": I("E6","Retain code-writing as a tool alongside building",
   "The pivot keeps coding ability. tools/code_execution.py runs in a Docker sandbox today.",
   "Expose code execution to embodied agents via the bridge, delegating to the existing sandbox path; no new sandbox.",
   "Replacing tilemap_gen (E14).",
   "An embodied agent runs code via the bridge; result returned; sandbox tests still green.",
   "bridge handler -> tools/code_execution.py", ["E4-3"], "P",
   ["area:embodiment","area:bridge",B]),
 "E6-6": I("E6","Perception snapshot API (what the agent can see)",
   "Decisions need a structured world view; replaces tools/world_state.py Redis snapshot with real perception.",
   "A perception verb returning nearby blocks/entities/inventory/pose in a stable schema.",
   "Memory writing (E5-4).",
   "Perception returns a schema-valid snapshot for a known setup.",
   "fork skills, core/bridge/inbound.py", ["E6-1","E4-6"], "S",
   ["area:embodiment","area:bridge"]),
 "E6-7": I("E6","Action failure taxonomy & safe-fail behavior",
   "24/7 autonomy must never wedge or act unsafely on failure.",
   "A taxonomy (blocked, timeout, invalid, unreachable, bridge-down) and safe behavior for each (idle, retry-bounded, abandon).",
   "",
   "Each failure class has a test asserting safe behavior.",
   "fork skills, tests", ["E6-2","E6-3"], "S", ["area:embodiment",QA]),
 "E6-8": I("E6","Embodiment unit/integration tests (no live server)",
   "Must be CI-testable without Minecraft (uses E4-8 harness).",
   "Tests for skills against the fake bridge + mocked perception.",
   "",
   "Skill tests run in CI without a server.",
   "tests/integration/", ["E4-8","E6-2","E6-3","E6-4","E6-5","E6-6"], "S",
   ["area:embodiment",QA]),
 "E6-9": I("E6","Skill cost attribution hook",
   "Codegen/LLM-backed skills must attribute spend per agent (feeds E11).",
   "Ensure any LLM call a skill triggers flows through the existing cost path (core/llm_client.py -> core/repos/cost_repo.py) with correct agent_id.",
   "",
   "A codegen skill call appears in cost_events attributed to the right agent; test_cost_tracking.py green.",
   "core/llm_client.py, core/repos/cost_repo.py", ["E6-5"], "S",
   ["area:embodiment",B,PNR]),

 # ---- EPIC 7 ----
 "E7-1": I("E7","Alpha Mindcraft profile (non-verbal, action-only)",
   "agents/alpha/config.yaml (deepseek/deepseek-v3.2, chattiness 0), agents/alpha/system_prompt.md (symbols only).",
   "Generate Alpha's profile via E3-4; no chat participation; routed via OpenRouter per E3-3.",
   "",
   "Alpha spawns in the E2 world using its configured model; emits no chat.",
   "scripts/minecraft/gen_profiles.py, agents/alpha/*",
   ["E3-4","E2-1"], "S", [MC,"area:embodiment"]),
 "E7-2": I("E7","Alpha receives a dispatched errand via the bridge",
   "tools/alpha_dispatch.py is the existing dispatch path; preserve its semantics (allowed agents, 60s timeout).",
   "Another process/agent dispatches Alpha; the errand reaches the bot via the bridge; preserve tools/alpha_dispatch.py behavior.",
   "",
   "A dispatched task arrives at Alpha; alpha-dispatch tests stay green.",
   "tools/alpha_dispatch.py, core/bridge/*", ["E7-1","E4-4"], "S",
   ["area:bridge",B,PNR]),
 "E7-3": I("E7","Alpha executes a verified in-world errand",
   "Proves embodiment + verification.",
   "Alpha performs a simple fetch/move/place errand and reports verified success/failure (symbols ✓/✗ semantics).",
   "",
   "A known errand completes with a verified result surfaced.",
   "fork skills", ["E7-2","E6-2","E6-3"], "S", ["area:embodiment"]),
 "E7-4": I("E7","Alpha writes the outcome to memory",
   "Prove the preserved memory path end-to-end.",
   "Errand outcome persists via E5 to recall/archival.",
   "",
   "The outcome is retrievable via the memory bridge; memory tests green.",
   "core/bridge/handlers/memory.py", ["E7-3","E5-2"], "S", [PNR,B]),
 "E7-5": I("E7","Management out-of-band on Alpha's (symbolic) output",
   "Management is a filter, never a bot (core/management.py).",
   "Route Alpha's emitted output through Management.review out-of-band; confirm it is not spawned as a world bot.",
   "",
   "Alpha output passes through the filter; test_management.py green; no Management entity exists in-world.",
   "core/management.py", ["E7-3"], "S", [PNR,B]),
 "E7-6": I("E7","Cost gate + kill switch enforced on the slice",
   "Prove safety before scaling. Ties to E11.",
   "Alpha's LLM spend attributed and gated; activating the kill switch (Redis kill_switch) halts Alpha's bot within a documented window.",
   "",
   "Kill switch stops Alpha acting; spend appears in cost_events; test_cost_tracking.py green.",
   "core/llm_client.py, core/admin/kill_switch_routes.py",
   ["E7-3","E11-3","E11-5"], "S", [PNR,"area:bridge"]),
 "E7-7": I("E7","Vertical-slice acceptance report",
   "Explicit go/no-go before E8.",
   "A documented run-through of E7-1..E7-6 with evidence; list any deviations from MINECRAFT-PIVOT-CONTEXT.md.",
   "",
   "docs/minecraft/alpha-slice-report.md shows the full chain working; sign-off recorded.",
   "docs/minecraft/alpha-slice-report.md",
   ["E7-1","E7-2","E7-3","E7-4","E7-5","E7-6"], "S", [MC,NHI]),

 # ---- EPIC 8 ----
 "E8-1": I("E8","Generate all agent profiles from config (single source of truth)",
   "agents/<id>/config.yaml + CLAUDE.md model table must drive all profiles.",
   "Extend the E3-4 generator to all 9 agents incl. special handling for management (NOT a bot) and alpha (non-verbal).",
   "",
   "Generator emits valid profiles for all conversational agents; excludes Management as a world bot; test_model_versions.py green.",
   "scripts/minecraft/gen_profiles.py", ["E3-4","E7-7"], "S", [MC,B,PNR]),
 "E8-2": I("E8","Embody cohort 1: Vera + Rex",
   "Each agent has distinct personality/model; embody in parallel.",
   "Spawn Vera & Rex with correct OpenRouter models, basic act/build, memory wired.",
   "",
   "Vera & Rex spawn with correct models and perform a verified action; per-agent model verified against config.",
   "fork profiles, scripts/minecraft/gen_profiles.py", ["E8-1"], "P",
   [MC,"area:embodiment",PNR]),
 "E8-3": I("E8","Embody cohort 2: Aurora + Pixel + Fork",
   "Each agent has distinct personality/model; embody in parallel.",
   "Spawn Aurora, Pixel, Fork with correct OpenRouter models, basic act/build, memory wired.",
   "",
   "All three spawn with correct models and perform a verified action; per-agent model verified against config.",
   "fork profiles", ["E8-1"], "P", [MC,"area:embodiment",PNR]),
 "E8-4": I("E8","Embody cohort 3: Sentinel + Grok",
   "Each agent has distinct personality/model; embody in parallel.",
   "Spawn Sentinel & Grok with correct OpenRouter models, basic act/build, memory wired.",
   "",
   "Both spawn with correct models and perform a verified action; per-agent model verified against config.",
   "fork profiles", ["E8-1"], "P", [MC,"area:embodiment",PNR]),
 "E8-5": I("E8","Map personality knobs -> Mindcraft conversation behavior",
   "Per E1-R4, map chattiness/initiative/interrupt/eavesdrop/adjacency onto Mindcraft's respond/ignore config.",
   "Implement the mapping decided in E1-R4; document gaps where Mindcraft can't express a knob.",
   "",
   "At least two agents show measurably different respond rates consistent with their chattiness.",
   "fork config, agents/*/config.yaml", ["E8-1","E1-R4"], "P", [MC,NR]),
 "E8-6": I("E8","Retire the Python conversation director for embodied runs",
   "core/conversation_engine.py / core/conversation/speaker_selector.py are the old central director; Option C removes central direction.",
   "Behind a run-mode flag, embodied runs use decentralized respond/ignore instead of the speaker selector; do NOT delete the old engine yet (gate it).",
   "Deleting the legacy engine (E14-era).",
   "An embodied multi-agent run holds a conversation with no central director invoked; legacy path still works behind the flag; selector tests green.",
   "core/conversation_engine.py, core/conversation/speaker_selector.py",
   ["E8-5"], "S", [ARCH,B,PNR]),
 "E8-7": I("E8","Management out-of-band on all bot chat",
   "Every utterance must pass Management.review before it's visible/streamed (3s intervention window).",
   "All bot-emitted chat routed through Management out-of-band; preserve severity ladder + kill-switch-at-sev-5.",
   "",
   "Blocked content is intercepted before display; test_management.py green.",
   "core/management.py, core/bridge/*", ["E8-2","E8-3","E8-4"], "S", [PNR,B]),
 "E8-8": I("E8","Multi-agent stability soak (hours)",
   "24/7 needs proof it doesn't drift/deadlock with all agents.",
   "A multi-hour soak with all agents; capture crashes, runaway loops, bridge drops; tune.",
   "",
   "A documented multi-hour run with no unrecovered failure and spend within E11 caps.",
   "n/a (ops)", ["E8-6","E8-7","E11-3"], "S", [MC,QA]),
 "E8-9": I("E8","Cohort acceptance report",
   "Go/no-go before fan-out epics.",
   "Evidence that all agents run embodied with correct models and decentralized conversation; deviations vs context doc listed.",
   "",
   "docs/minecraft/cohort-report.md + sign-off.",
   "docs/minecraft/cohort-report.md",
   ["E8-1","E8-2","E8-3","E8-4","E8-5","E8-6","E8-7","E8-8"], "S", [MC,NHI]),

 # ---- EPIC 9 ----
 "E9-1": I("E9","Reflection runs on embodied activity",
   "core/memory/reflection.py + reflection_scheduler.py reflect on conversations today; embodied actions must also be reflected on.",
   "Ensure reflection inputs include embodied recall memories (from E5-4); no change to reflection cadence logic.",
   "",
   "A post-action reflection produces a journal entry; test_reflection*.py, test_reflection_scheduler.py green.",
   "core/memory/reflection.py, core/memory/reflection_scheduler.py",
   ["E5-4","E8-2"], "P", [PNR,B]),
 "E9-2": I("E9","Dreams unchanged in embodied runs",
   "core/memory/dreams.py (high-temp idle reflection). Behavior must not regress.",
   "Confirm the dream cycle fires in embodied/idle periods; recombines embodied + conversational memories; no semantic change.",
   "",
   "A dream produces narrative/goals as before; test_dreams.py green; scenarios/dream_cycle_test.yaml still valid (or adapted, documented).",
   "core/memory/dreams.py, scenarios/dream_cycle_test.yaml", ["E5-4"], "P",
   [PNR,B]),
 "E9-3": I("E9","Journal image generation still works",
   "tools/journal_image_tool.py generates journal imagery.",
   "Confirm it functions in embodied runs (provider-side, not Phaser) or document any coupling to retired assets.",
   "",
   "A journal entry with an image renders; documented.",
   "tools/journal_image_tool.py", ["E9-1"], "P", [PNR]),
 "E9-4": I("E9","Website publishing of journals/dreams intact",
   "core/blog.py + website /blog,/agents pages publish journals.",
   "Confirm embodied-run journals/dreams publish unchanged; no Phaser dependency in the publish path.",
   "",
   "A journal from an embodied run appears on the site; no regression.",
   "core/blog.py, website/src/app/blog, website/src/app/agents",
   ["E9-1","E9-2"], "S", [PNR,F]),
 "E9-5": I("E9","Dreams/journals regression gate",
   "Lock in no-regression.",
   "CI gate over test_dreams.py, test_reflection*.py, test_reflection_goals.py, test_reflect_after.py on the embodied path.",
   "",
   "Gate required and green.",
   "CI config", ["E9-1","E9-2","E9-3","E9-4"], "S", [QA,PNR]),
 "E9-6": I("E9","Scenario fixtures updated (dream/reflection)",
   "scenarios/dream_cycle_test.yaml, dream_smoke_test.yaml, goal_generation_test.yaml assume the old world.",
   "Update these fixtures for embodied runs (or document why unchanged); keep them runnable.",
   "",
   "The named scenarios run green under embodied mode.",
   "scenarios/*.yaml", ["E9-5"], "S", [PNR,"area:run-modes"]),

 # ---- EPIC 10 ----
 "E10-1": I("E10","Eval data loader handles embodied events",
   "core/eval/loader.py + EvalEngine load simulation data; embodied perception/action results are new inputs.",
   "Extend the loader to include embodied actions/build outcomes; no change to the LLM-eval mechanism.",
   "",
   "An embodied run's data loads into the eval engine; test_eval_engine.py, test_eval_categories.py green.",
   "core/eval/loader.py, core/eval/engine.py", ["E8-2"], "S", [B,PNR]),
 "E10-2": I("E10","Add a build-verification eval category",
   "The whole pivot premise - agents can now verifiably build. Evals should measure it.",
   "A new category in evals/prompts/ scoring intended-vs-actual build outcomes using the E6 verification signal.",
   "",
   "The category scores a sample run; wired into a suite in core/eval/engine.py EVAL_SUITES.",
   "evals/prompts/, core/eval/engine.py", ["E10-1","E6-4"], "P",
   ["eval-finding",B]),
 "E10-3": I("E10","Preserve existing eval categories/suites",
   "Don't lose entertainment/safety/agency/etc. coverage.",
   "Verify all current categories still run on embodied data; fix loaders where world-shape assumptions break.",
   "",
   "Every pre-existing eval category runs without error on an embodied run; test_agency_eval.py, test_eval_analyzer.py green.",
   "core/eval/*", ["E10-1"], "P", [PNR,B]),
 "E10-4": I("E10","Reporting/scorecard reflects embodied metrics",
   "core/reporting/ (scorecard, timeline_reporter, comparison) and scripts/report_simulation.py.",
   "Add embodied metrics (verified builds, actions) to the scorecard; preserve existing fields.",
   "",
   "A report includes embodied metrics; existing report tests green.",
   "core/reporting/*, scripts/report_simulation.py", ["E10-1"], "P", [B]),
 "E10-5": I("E10","Eval suite for the two run modes",
   "Persistent vs experimental runs may need different suites.",
   "Define which suites apply to 24/7 vs experimental; document.",
   "",
   "Documented suite mapping; scripts/run_eval.py can target either.",
   "core/eval/engine.py, scripts/run_eval.py", ["E10-2","E10-3","E12-1"], "S",
   [B,"area:run-modes"]),
 "E10-6": I("E10","Eval regression gate",
   "Lock in no-regression.",
   "CI gate over the eval/reporting test set on embodied data.",
   "",
   "Gate required and green.",
   "CI config", ["E10-1","E10-2","E10-3","E10-4"], "S", [QA,PNR]),
 "E10-7": I("E10","Eval docs updated",
   "specs/AGENT-AUTONOMY-EVAL-STRATEGY.md references the old world (specs are read-only).",
   "Add a companion doc in docs/ for the embodied eval model rather than editing specs.",
   "",
   "docs/eval-embodied.md explains the adapted eval model.",
   "docs/eval-embodied.md", ["E10-5"], "S", [DOC]),

 # ---- EPIC 11 ----
 "E11-1": I("E11","Audit & document current cost/kill mechanisms",
   "Be precise about what exists (V10): per-sim max_cost, Redis kill_switch, kill_switch_routes.py, Management sev-5.",
   "Written audit of every cost/kill path + the gaps for 24/7.",
   "",
   "docs/cost-kill-audit.md lists mechanisms, owners, and gaps.",
   "docs/cost-kill-audit.md", [], "P", [B,ARCH]),
 "E11-2": I("E11","Carry over per-simulation cost cap to persistent runs",
   "max_cost/CostLimitExceededError exist for sims; a 24/7 run needs a rolling budget guard.",
   "A rolling/periodic spend ceiling for persistent mode reusing the cost_events reconciliation in orchestrator._check_cost_limit.",
   "",
   "Exceeding the rolling ceiling halts the run; test_cost_tracking.py green.",
   "core/simulation/orchestrator.py", ["E11-1"], "P", [B,PNR]),
 "E11-3": I("E11","Build hard per-agent hourly spend cap (NET-NEW)",
   "Does NOT exist today (V10). Context calls this 'preserve' but it must be built; top safety gap for 24/7 (prior runaway burned $38/hr).",
   "Per-agent hourly spend tracked from cost_events (attributed via core/llm_client._log_cost); breaching it disables that agent's LLM/bot actions until the window rolls; configurable per agent.",
   "",
   "A synthetic runaway agent is capped within the hour and stops acting; other agents unaffected; tests added.",
   "core/cost_governor.py (new), core/repos/cost_repo.py, tests/backend/test_cost_governor.py",
   ["E11-1"], "S", [B,"priority-critical",PNR]),
 "E11-4": I("E11","Phone-accessible kill switch verified end-to-end",
   "core/admin/kill_switch_routes.py (X-Kill-Switch-Key, KILL_SWITCH_API_KEY) sets Redis kill_switch.",
   "Verify the existing phone path still works and document the exact request a phone makes; no redesign unless broken.",
   "",
   "A documented curl/shortcut activates the kill switch; orchestrator._terminated() honors it.",
   "core/admin/kill_switch_routes.py", ["E11-1"], "S", [B,PNR]),
 "E11-5": I("E11","Kill switch halts the Node bots & world loop",
   "Today the kill switch stops the Python sim loop only; bots are a new process and must also stop.",
   "The Node bridge client polls/subscribes to kill state; on active, bots safe-idle/disconnect within a documented window.",
   "",
   "Activating the kill switch stops all bot actions within the window; covered by an integration test (E4-8 harness).",
   "fork node client, core/bridge/*", ["E11-4","E4-5"], "S",
   ["area:bridge",MC,"priority-critical"]),
 "E11-6": I("E11","Spend/kill alerting",
   "A 24/7 system must tell a human before/at the cap.",
   "Alert (email/existing notifications in core/notifications/) on cap approach and kill activation.",
   "",
   "Crossing a configurable threshold emits an alert.",
   "core/notifications/*", ["E11-3"], "S", [B]),
 "E11-7": I("E11","Cost/kill hardening regression gate",
   "Lock in no-regression.",
   "CI gate over test_cost_tracking.py, test_management.py, new test_cost_governor.py, kill-switch tests.",
   "",
   "Gate required and green.",
   "CI config", ["E11-2","E11-3","E11-4","E11-5","E11-6"], "S", [QA,PNR]),

 # ---- EPIC 12 ----
 "E12-1": I("E12","Unified run-spec schema",
   "SimulationConfig, scenarios/*.yaml, MemorySeedConfig, scenarios/seeds/*.json, core/config_loader.py already model starting conditions; extend (not replace).",
   "One run-spec covering: agent set, personas/backstories, factions, goals, memory seed, world seed/config (E2-2), run mode. Backward compatible.",
   "",
   "Schema + loader; an existing scenario still loads unchanged; test_public_scenarios.py, test_simulation_scenarios.py green.",
   "core/models.py, core/config_loader.py, core/simulation/orchestrator.py",
   ["E5-5","E8-9"], "S", ["area:run-modes",B,PNR]),
 "E12-2": I("E12","Backstory/persona -> Mindcraft profile injection",
   "Personas live in agents/<id>/system_prompt.md + config; runs may override.",
   "Run-spec persona/backstory overrides flow into generated Mindcraft profiles per run, without editing committed agent files.",
   "",
   "A run with an overridden backstory produces a profile reflecting it.",
   "scripts/minecraft/gen_profiles.py", ["E12-1","E8-1"], "P",
   ["area:run-modes",MC]),
 "E12-3": I("E12","Factions/goals as inputs in embodied runs",
   "FactionConfig + seed_goals already exist in the orchestrator.",
   "Ensure faction membership and seeded goals apply to embodied agents (visible in context/profile); preserve existing faction validation.",
   "",
   "A faction-seeded run shows membership reflected; test_simulation_scenarios.py + faction tests green.",
   "core/simulation/orchestrator.py", ["E12-1"], "P",
   ["area:run-modes",B,PNR]),
 "E12-4": I("E12","Seeded vs blank-slate memory for embodied runs",
   "scenarios/seeds/blank-slate.json + MemorySeedApplier. Blank-slate is an explicit required mode.",
   "Confirm seeded, inherited, and blank-slate memory modes all work for embodied agents via E5-5; document the blank-slate embodied flow.",
   "",
   "Blank-slate and seeded embodied runs both start correctly; test_memory_seed.py green.",
   "core/memory/memory_seed.py", ["E12-1","E5-5"], "P",
   ["area:run-modes",PNR]),
 "E12-5": I("E12","World as an input wired to E2",
   "E2-2 made world generation configurable; connect it to the run-spec.",
   "Run-spec world fields drive the server's world config on run start (fresh for experimental; persistent for 24/7).",
   "",
   "An experimental run provisions a fresh world from the run-spec; persistent mode reuses the durable world.",
   "scripts/minecraft/world.config, core/simulation/orchestrator.py",
   ["E12-1","E2-2","E2-5"], "P", ["area:run-modes",MC]),
 "E12-6": I("E12","Persistent 24/7 mode",
   "Long-lived world, livestreamed, indefinite - distinct from batch sims.",
   "A run mode that runs indefinitely, honoring E11 rolling caps + kill switch, durable world, no fixed end.",
   "",
   "A persistent run starts, survives a restart (E2-4), and is bounded only by caps/kill switch.",
   "core/simulation/orchestrator.py", ["E12-1","E11-2","E11-5","E2-4"], "S",
   ["area:run-modes",B]),
 "E12-7": I("E12","Experimental short-run mode",
   "Tweak starting conditions, short runs, compare.",
   "A run mode with a defined end (duration/goal), fresh world, full starting-condition overrides, results captured for comparison.",
   "",
   "Two experimental runs with different starting conditions produce comparable reports.",
   "core/simulation/orchestrator.py, core/reporting/comparison.py",
   ["E12-2","E12-3","E12-4","E12-5","E10-4"], "S", ["area:run-modes",B]),
 "E12-8": I("E12","Run-mode docs + examples",
   "Document both modes with example run-specs.",
   "Document both modes; add example files alongside scenarios/.",
   "",
   "docs/run-modes.md + at least one example spec per mode that runs.",
   "docs/run-modes.md, scenarios/", ["E12-6","E12-7"], "S",
   [DOC,"area:run-modes"]),

 # ---- EPIC 13 ----
 "E13-1": I("E13","Capture prototype (the E1-R6 method)",
   "Highest greenfield risk; de-risk early (runnable right after E1).",
   "Implement a throwaway prototype of the chosen capture method showing the live world as a video frame source.",
   "Streaming (E13-2).",
   "A recorded clip of the live E2 world via the chosen method; documented limitations.",
   "prototype", ["E1-R6","E2-1"], "S", ["area:livestream",MC]),
 "E13-2": I("E13","Encoder + RTMP push to Twitch/YouTube",
   "Committed integrations are Twitch + YouTube; no streaming code today (V9).",
   "Encode the capture source and push via RTMP to Twitch/YT using stream keys from env (extend .env/CLAUDE.md env list); test stream first.",
   "",
   "A private/test stream is live on both platforms from the capture source.",
   ".env docs, CLAUDE.md, streaming service", ["E13-1"], "P",
   ["area:livestream"]),
 "E13-3": I("E13","Stream overlays (agent labels, status)",
   "The old Phaser stream overlay (frontend/src/ui/StreamOverlay.ts) retires; need an equivalent over the Minecraft capture.",
   "A compositing layer (overlay window/OBS source/ffmpeg filter) showing agent names/status sourced from the Python brain.",
   "",
   "Overlay shows live agent status on the stream.",
   "streaming service", ["E13-1"], "P", ["area:livestream"]),
 "E13-4": I("E13","Audio/TTS in the stream",
   "Edge TTS is committed (core/tts.py); the old pipeline stitched audio post-hoc.",
   "Route live agent TTS into the stream audio (timed to chat that passed Management).",
   "",
   "An approved utterance is heard on the stream.",
   "core/tts.py, streaming service", ["E13-2","E8-7"], "P",
   ["area:livestream"]),
 "E13-5": I("E13","24/7 resilience (auto-recover capture/encoder/stream)",
   "Streams drop; must self-heal unattended.",
   "Supervise capture+encoder+push; auto-restart with backoff; log gaps.",
   "",
   "Killing any component auto-recovers within a documented window; stream resumes.",
   "streaming service", ["E13-2","E2-4"], "S", ["area:livestream",QA]),
 "E13-6": I("E13","Stream kill path tied to the kill switch",
   "The kill switch must also cut the public stream.",
   "Kill-switch-active transitions the stream to a safe state (holding card / cut) consistent with E11.",
   "",
   "Activating the kill switch puts the stream into the safe state.",
   "streaming service, core/bridge/*", ["E13-2","E11-5"], "S",
   ["area:livestream","priority-critical"]),
 "E13-7": I("E13","Stream health monitoring/alerting",
   "A 24/7 system must detect failures.",
   "Detect stream-down/black-frame/silence; alert via core/notifications/.",
   "",
   "An induced outage triggers an alert.",
   "core/notifications/*, streaming service", ["E13-5"], "S",
   ["area:livestream"]),
 "E13-8": I("E13","Livestream ops runbook",
   "Plain-language ops.",
   "Runbook: start/stop stream, rotate keys, recover, kill.",
   "",
   "docs/livestream/runbook.md covers every operation.",
   "docs/livestream/runbook.md",
   ["E13-1","E13-2","E13-3","E13-4","E13-5","E13-6","E13-7"], "S",
   [DOC,"area:livestream"]),

 # ---- EPIC 14 ----
 "E14-1": I("E14","Retirement readiness gate",
   "Do not delete the only working video path until Minecraft capture + adapted site are live.",
   "A checklist verifying E13 (live stream) and E15 (site adapted) are done and in production; explicit go decision.",
   "",
   "docs/phaser-retirement-gate.md all-green + sign-off.",
   "docs/phaser-retirement-gate.md", ["E13-8","E15-7"], "S", [ARCH,NHI]),
 "E14-2": I("E14","Remove the Phaser frontend",
   "Retire the Phaser engine and renderer.",
   "Delete frontend/ (Phaser engine, Pathfinding, WorldManager, AgentSprite*, WorkspaceManager, ChunkLoader, spectator.ts, UI overlays) and its build/CI wiring.",
   "",
   "Repo builds/tests green without frontend/; CI updated.",
   "frontend/", ["E14-1"], "P", [F,ARCH]),
 "E14-3": I("E14","Remove tilemap/office/sprite/PixelLab pipeline",
   "Retire unverified code-as-building + pixel assets.",
   "Delete tools/tilemap_gen.py, core/world/office_generator.py, core/world/sprite_generator.py, core/world/pixellab_client.py, scripts/generate_office_tilemap.py, config/office_layout.json, config/pixellab_*; remove PIXELLAB_API_KEY from required env.",
   "",
   "No references remain; backend tests green; env docs updated.",
   "tools/tilemap_gen.py, core/world/*, config/*, CLAUDE.md",
   ["E14-1","E6-5"], "P", [B,ARCH]),
 "E14-4": I("E14","Remove Phaser-canvas replay + its video render",
   "Replace the only video path only after E15 repoints sim pages at Minecraft recordings.",
   "Delete website/src/components/replay/* and the Playwright Phaser-replay render (core/video/render_pipeline.py + the /simulations/{id}/replay capture coupling).",
   "",
   "Sim pages no longer reference the Phaser replay; tests/integration/test_video_render_e2e.py removed/replaced; tests green.",
   "website/src/components/replay/*, core/video/render_pipeline.py",
   ["E14-1","E15-4"], "P", [F,B]),
 "E14-5": I("E14","Remove tools/world_state.py Redis-snapshot world API",
   "Superseded by embodied perception (E6-6).",
   "Delete/replace the old Redis world:* snapshot tool.",
   "",
   "Agents use perception (E6-6); no references to the old tool; tests green.",
   "tools/world_state.py", ["E14-1","E6-6"], "P", [B]),
 "E14-6": I("E14","Purge retired-system references in docs/CLAUDE.md",
   "Docs must not describe the Phaser world as current (specs read-only).",
   "Update CLAUDE.md architecture diagram + non-spec docs; add deltas in docs/ rather than editing specs.",
   "",
   "CLAUDE.md reflects the Minecraft architecture; no stale 'Phaser world' claims in non-spec docs.",
   "CLAUDE.md, docs/", ["E14-2","E14-3","E14-4","E14-5"], "S", [DOC]),
 "E14-7": I("E14","Post-retirement full regression",
   "Confirm nothing broke after deletions.",
   "Full backend + website test run + a live smoke (stream up, agents acting, site correct) after all deletions.",
   "",
   "Green suite + documented live smoke.",
   "CI", ["E14-2","E14-3","E14-4","E14-5","E14-6"], "S", [QA]),

 # ---- EPIC 15 ----
 "E15-1": I("E15","Inventory website coupling to the Phaser world",
   "world/page.tsx uses WorldViewer/AgentPositions; simulations/[id]/replay + components/replay/* render the Phaser canvas; VideoPlayer.tsx plays the old MP4.",
   "An audit of every page/component that assumes the pixel-office world.",
   "",
   "docs/website-coupling-audit.md lists each and the adaptation needed.",
   "docs/website-coupling-audit.md", ["E8-9"], "S", [F,ARCH]),
 "E15-2": I("E15","World page -> Minecraft world view",
   "Replace the pixel-art world viewer.",
   "Replace the pixel-art world viewer with a Minecraft world representation (embed the live stream player and/or world snapshots from E13).",
   "",
   "/world shows the Minecraft world; no Phaser imports.",
   "website/src/app/world/page.tsx", ["E15-1","E13-2"], "P",
   [F,"area:livestream"]),
 "E15-3": I("E15","Live page embeds the Minecraft stream",
   "website/src/app/simulations/live/page.tsx.",
   "Embed the Twitch/YT player from E13 on the live page.",
   "",
   "The live page plays the running stream.",
   "website/src/app/simulations/live/page.tsx", ["E15-1","E13-2"], "P",
   [F,"area:livestream"]),
 "E15-4": I("E15","Simulation/replay pages -> Minecraft recordings",
   "Replay pages render Phaser; must point at Minecraft recordings (gates E14-4).",
   "Replace replay rendering with a recorded-video player fed by E13 captures; preserve the rest of the simulation detail tabs.",
   "",
   "A simulation page shows its Minecraft recording; non-replay tabs unchanged; website tests green.",
   "website/src/app/simulations/[id]/replay/*, website/src/components/simulation/*",
   ["E15-1","E13-1"], "P", [F]),
 "E15-5": I("E15","Simulation creator/list support new run modes",
   "simulations/new/, scenarios/page.tsx, components/simulationCreator/* create runs; must expose the E12 run-spec.",
   "Extend the creator UI + submission to the unified run-spec (mode, world seed, backstory/faction/memory overrides); preserve public-submission validation.",
   "",
   "A user can create both a persistent and an experimental run from the site; test_public_scenarios.py green.",
   "website/src/app/simulations/new/*, website/src/components/simulationCreator/*",
   ["E15-1","E12-1"], "P", [F,"area:run-modes"]),
 "E15-6": I("E15","Website regression + visual check",
   "Confirm the world swap didn't break the site.",
   "Run website Vitest + Playwright E2E; fix breakage from the world swap.",
   "",
   "website test + E2E suites green.",
   "website/", ["E15-2","E15-3","E15-4","E15-5"], "S", [QA,F]),
 "E15-7": I("E15","Website adaptation acceptance",
   "Go/no-go; gates E14.",
   "Documented walkthrough that /world, /simulations, live, and creator all reflect Minecraft.",
   "",
   "docs/website-adaptation-report.md + sign-off.",
   "docs/website-adaptation-report.md", ["E15-6"], "S", [F,NHI]),
}


def sh(args: list[str], check: bool = True) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(args)}\n{r.stderr}")
    return r.stdout.strip()


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"labels_done": False, "numbers": {}}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=2))


def ensure_labels() -> None:
    for name, color, desc in LABELS:
        r = subprocess.run(
            ["gh", "label", "create", name, "--color", color, "--description", desc],
            capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(
                ["gh", "label", "edit", name, "--color", color, "--description", desc],
                capture_output=True, text=True)
        print(f"  label: {name}")


def find_existing(title_key: str) -> int | None:
    """Search issues whose title starts with the stable key."""
    out = sh(["gh", "issue", "list", "--state", "all", "--limit", "200",
              "--search", f'in:title "{title_key}"',
              "--json", "number,title"], check=False)
    try:
        items = json.loads(out) if out else []
    except json.JSONDecodeError:
        items = []
    for it in items:
        if it["title"].startswith(title_key):
            return it["number"]
    return None


def child_title(key: str) -> str:
    return f"{key} — {ISSUES[key]['title']}"


def epic_title(key: str) -> str:
    return f"Epic {key} — {EPICS[key][0]}"


def child_body(key: str, numbers: dict) -> str:
    d = ISSUES[key]
    deps = ", ".join(f"#{numbers[k]}" if k in numbers else f"`{k}`" for k in d["deps"]) or "none"
    track = "Parallelizable (no intra-epic dependency)" if d["track"] == "P" else "Sequential"
    epic_no = numbers.get(d["epic"])
    epic_ref = f"#{epic_no}" if epic_no else d["epic"]
    out = d["scope_out"] or "—"
    return f"""**Epic:** {epic_ref} ({d['epic']} — {EPICS[d['epic']][0]})
**Plan:** [{PLAN}]({PLAN}) → §5 {key}

### Context (why)
{d['context']}

### Scope
- **In:** {d['scope_in']}
- **Out:** {out}

### Acceptance criteria
{d['acceptance']}

### Files / modules likely touched
`{d['files']}`

### Dependencies
{deps}

### Track
{track}
"""


def epic_body(key: str, numbers: dict) -> str:
    title, goal, dep_epics = EPICS[key]
    dep_txt = ", ".join(f"#{numbers[e]}" if e in numbers else e for e in dep_epics) or "none"
    children = [k for k in ISSUES if ISSUES[k]["epic"] == key]
    par = [k for k in children if ISSUES[k]["track"] == "P"]
    seq = [k for k in children if ISSUES[k]["track"] == "S"]

    def line(k: str) -> str:
        n = numbers.get(k)
        ref = f"#{n}" if n else k
        deps = ISSUES[k]["deps"]
        dtxt = ""
        if deps:
            dd = ", ".join(f"#{numbers[x]}" if x in numbers else x for x in deps)
            dtxt = f" — deps: {dd}"
        return f"- [ ] {ref} {k} — {ISSUES[k]['title']}{dtxt}"

    body = [f"## Goal\n{goal}\n",
            f"**Depends on epics:** {dep_txt}\n",
            f"**Plan:** [{PLAN}]({PLAN})\n",
            "## Child issues\n",
            "### Parallelizable (can run concurrently)"]
    body += [line(k) for k in par] or ["- (none)"]
    body += ["", "### Sequential"]
    body += [line(k) for k in seq] or ["- (none)"]
    body += ["", "_Generated from the Phase-1 plan. Checklist references are live issue numbers._"]
    return "\n".join(body)


def main() -> None:
    state = load_state()
    numbers: dict = state["numbers"]

    print("== labels ==")
    if not state.get("labels_done"):
        ensure_labels()
        state["labels_done"] = True
        save_state(state)

    print("== create epics (placeholder bodies) ==")
    for k in EPICS:
        if k in numbers:
            print(f"  {k} -> #{numbers[k]} (cached)")
            continue
        t = epic_title(k)
        existing = find_existing(f"Epic {k} —")
        if existing:
            numbers[k] = existing
            print(f"  {k} -> #{existing} (existing)")
        else:
            url = sh(["gh", "issue", "create", "--title", t,
                      "--body", f"_Epic body will be populated with the child checklist._\n\nGoal: {EPICS[k][1]}",
                      "--label", "epic"])
            num = int(re.search(r"/issues/(\d+)", url).group(1))
            numbers[k] = num
            print(f"  {k} -> #{num} (created)")
            time.sleep(SLEEP)
        save_state(state)

    print("== create child issues ==")
    for k in ISSUES:
        if k in numbers:
            print(f"  {k} -> #{numbers[k]} (cached)")
            continue
        existing = find_existing(f"{k} —")
        if existing:
            numbers[k] = existing
            print(f"  {k} -> #{existing} (existing)")
            save_state(state)
            continue
        labels = ["minecraft" if False else l for l in ISSUES[k]["labels"]]
        args = ["gh", "issue", "create", "--title", child_title(k),
                "--body", child_body(k, numbers)]
        for lb in labels:
            args += ["--label", lb]
        url = sh(args)
        num = int(re.search(r"/issues/(\d+)", url).group(1))
        numbers[k] = num
        print(f"  {k} -> #{num} (created)")
        save_state(state)
        time.sleep(SLEEP)

    print("== pass B: rewrite child bodies with resolved #refs ==")
    for k in ISSUES:
        sh(["gh", "issue", "edit", str(numbers[k]), "--body", child_body(k, numbers)])
        print(f"  body {k} -> #{numbers[k]}")
        time.sleep(0.6)

    print("== pass C: fill epic bodies with child checklists ==")
    for k in EPICS:
        sh(["gh", "issue", "edit", str(numbers[k]), "--body", epic_body(k, numbers)])
        print(f"  epic {k} -> #{numbers[k]}")
        time.sleep(0.6)

    save_state(state)
    print(f"\nDONE. {len(EPICS)} epics + {len(ISSUES)} child issues. State: {STATE}")


if __name__ == "__main__":
    sys.exit(main())
