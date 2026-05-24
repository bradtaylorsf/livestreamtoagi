# Minecraft Pivot — Epic & Issue Plan

> Source of truth: `specs/MINECRAFT-PIVOT-CONTEXT.md` (Option C, disciplined).
> GitHub issues have been created for this plan: epics `#503`-`#517` and child
> issues `#518`-`#630`.
> It is dependency-ordered, flags every unverified technical assumption, and
> routes anything unconfirmed to an explicit research issue rather than guessing.
> E1 research is complete as of 2026-05-18; use `docs/decisions/` as the binding
> decision record for downstream implementation.

---

## 0. Accuracy posture (read this first)

The project owner has never played Minecraft. Per the task's critical accuracy
rule, the following are treated as **unverified** and are NOT baked into
implementation issues as fact. Each has a dedicated research issue in **Epic 1**,
and downstream issues depend on those research issues instead of hardcoding a guess.

### 0.0 Current tracker status

- **E1 / #503 is complete pending GitHub closure.** Decision records live in
  `docs/decisions/0000-summary.md` through `docs/decisions/0007-licensing.md`.
- **Implementation may begin.** The critical path starts with `E2-1 / #526`
  (local Paper server setup), then `E3-1 / #533` (Mindcraft fork/pin), then the
  E4 bridge contract.
- **All pivot implementation must validate locally through LM Studio before it
  is accepted.** Use `LLM_PROVIDER=lmstudio`, `LOCAL_LLM_BASE_URL`, and
  `LOCAL_LLM_MODEL`; use `LOCAL_LLM_MODEL_BUILDING` when an issue exercises
  building/reflection/dream tiers. OpenRouter spend is not required for
  acceptance.

### 0.1 What I verified (from the live Mindcraft repo / Mineflayer docs, May 2026)

| # | Fact | Confidence | Source |
|---|------|-----------|--------|
| V1 | Mindcraft (`github.com/kolbytn/mindcraft`) is an LLM+Mineflayer agent framework; Minecraft **Java Edition**, supports "up to v1.21.11, recommends v1.21.6" | High | repo README |
| V2 | Default connection is to a **LAN world on `localhost:55916`**; online servers require Microsoft auth | High | repo README |
| V3 | Config files: `keys.json` (API keys), per-agent profile JSON (e.g. `andy.json`), `settings.js` (host, port, `auth`, `allow_insecure_coding`, `profiles`, `auto_open_ui`) | High | repo README |
| V4 | Per-agent profiles support distinct model roles: `model` (chat), `code_model` (newAction codegen), `vision_model`, `embedding`, `speak_model`; each can be a string or an object with `api`/`model`/`url`/`params` | High | repo README |
| V5 | OpenRouter appears in the README's supported-provider list | Medium — see U1 | repo README + open issue #493 |
| V6 | Multi-agent: `--num_agents`, task JSON with `agent_count`, `initial_inventory`, `blocked_actions`, `goal`, `conversation` | Medium | `minecollab.md` |
| V7 | Docker is supported (`docker build -t mindcraft`, `host.docker.internal`); ViaProxy bridges unsupported MC versions | Medium | repo README |
| V8 | No Python bridge is shipped by Mindcraft. A `requirements.txt` exists but is undocumented. **The Python↔Node bridge is greenfield — we build it.** | High | repo README (absence) |
| V9 | This codebase has **no real livestream/OBS/RTMP integration today** — `grep` for rtmp/obs/restream in `core/` and `scripts/` returns nothing. The only video path is a post-hoc Playwright capture of the Phaser replay page (`core/video/render_pipeline.py`). **The livestream pipeline is greenfield.** | High | code inspection |
| V10 | There is **no hard per-agent hourly spend cap** in code today — only a per-simulation total `max_cost` (`core/simulation/orchestrator.py:_check_cost_limit`). The kill switch is real (`core/admin/kill_switch_routes.py`, Redis `kill_switch` key). | High | code inspection |

### 0.2 Questions E1 resolved — downstream issues bind to these

| # | Question | Resolution | Record |
|---|----------------|----------------|-----------|
| U1 | Is model routing wired in Mindcraft? | Native `model` and `code_model` routing exists. Downstream work should validate with LM Studio local model IDs, not require OpenRouter spend. | `0003-mindcraft-model-routing.md` |
| U2 | How does decentralized respond/ignore work? | Mindcraft supports pairwise bot conversations; we need our own personality/proximity/eavesdrop layer. | `0004-decentralized-conversation.md` |
| U3 | Where should the Python bridge attach? | Use a fork patch with an explicit Node bridge module and commands/skills. | `0005-skill-extension-point.md` |
| U4 | What server/auth posture? | Use Paper `1.21.6` locally with offline/private auth for development; production auth/legal remains a human launch gate. | `0001-minecraft-version-and-server.md`, `0002-auth-mode.md`, `0007-licensing.md` |
| U5 | How do we capture livestream video? | Use a real Minecraft Java camera client plus OBS for production; Prismarine Viewer is diagnostic/fallback only. | `0006-video-capture.md` |
| U6 | What version/commit pins the stack? | Paper `1.21.6-48`, Mindcraft `35be480b4cc0bca990278e6103a1426392559d96`, Node 20 LTS, Java 21. | `0001-minecraft-version-and-server.md` |

> **Rule applied after E1:** downstream issues should link back to the decision
> records instead of re-litigating the research. If a later implementation
> discovers contradictory evidence, update the relevant decision record first,
> then update affected issues.

---

## 1. Epic list (dependency-ordered)

| Epic | Title | Goal (1 paragraph) | Depends on | ~Issues |
|------|-------|--------------------|------------|---------|
| **E1** | Research, Decisions & Spikes | **Complete.** Resolved every unverified Minecraft/Mindcraft fact (U1–U6) and produced written decision records the rest of the plan binds to: pinned MC version + server software, offline/auth posture, model routing status, decentralized-conversation mechanism, bridge extension point, video-capture method, licensing/EULA posture. Output is decisions, not code. | — | 8 |
| **E2** | Minecraft Server Setup (beginner) | Stand up a private Minecraft server a non-player can operate: chosen server software/version, runs 24/7, world generation as a configurable input, backup/restore, health checks, documented in plain language. | E1 | 7 |
| **E3** | Mindcraft Fork & Evaluation | Fork Mindcraft, pin the commit, get one stock bot connecting to the E2 server, verify per-agent multi-model routing with LM Studio local profiles, strip/disable unused features, make install reproducible. | E1, E2 | 8 |
| **E4** | Python↔Node Bridge | A bidirectional, authenticated transport: bots call Python services (memory, management, cost-gate); perception/action results flow back. Versioned contract, reconnect, backpressure, failure semantics. | E3 (impl); E1-R5 (design) | 9 |
| **E5** | Memory Service Exposure | Expose the existing 3-tier pgvector memory (core/recall/archival) as a bridge service the bots query and write. **Preserve existing behavior — no regression.** | E4 | 7 |
| **E6** | Embodiment / Action Layer | Real movement, building, and a curated skill set with **action-success verification**; retain code-writing as a tool alongside in-world building. | E3, E4 | 9 |
| **E7** | Alpha Vertical Slice | One embodied agent (Alpha — non-verbal, action-only) end-to-end: server→bot→bridge→memory→embodiment→cost-gate→kill-switch→Management. The integration crucible that proves Option C. | E2,E3,E4,E5,E6 | 7 |
| **E8** | All Agents Embodied + Decentralized Conversation | Embody the other agents with their per-agent models; replace the Python conversation director with Mindcraft's decentralized respond/ignore; keep Management out-of-band on bot chat. | E7 | 9 |
| **E9** | Dreams / Journals / Website Publishing Preserved | Keep reflection, dreams, and journals running on embodied activity and publishing to the website. **Preserve existing behavior — no regression.** | E5, E8 | 6 |
| **E10** | Eval & Reporting Adapted | Adapt eval categories, loaders, and reporting to embodied-world data (real, verifiable builds/actions) without losing existing eval coverage. | E8 | 7 |
| **E11** | Cost Controls & Kill Switch Hardened | Carry over per-sim cost cap + phone kill switch; **build the missing hard per-agent hourly spend cap**; make the kill switch actually halt the Node bots and the world loop. 24/7 autonomy is more exposed than batch sims. | E1; tightened in E7 | 7 |
| **E12** | Run-Mode / Starting-Conditions System | Extend the existing config/scenario/memory-seed machinery so starting conditions (personas, backstories, factions, goals, seeded memories, blank-slate, world seed) drive both the Python brain AND the Minecraft world + Mindcraft profiles. Support both run modes (persistent 24/7; experimental short runs). | E5, E8 | 8 |
| **E13** | Livestream Pipeline | Greenfield: capture the live Minecraft world (method decided in E1-R6), encode, and stream to Twitch/YouTube with overlays, 24/7 resilience, and a kill path. | E1-R6, E2; full value after E8 | 8 |
| **E14** | Retire the Phaser Layer | Delete the Phaser frontend, tilemap generation, pixel-office layout, sprite/PixelLab pipeline, custom A* pathfinding, and the Phaser-canvas replay + its video render — **only after** Minecraft capture + website adaptation replace them. | E13, E15 | 7 |
| **E15** | Website Adaptation | Replace the world page and simulation/replay pages so they reflect the Minecraft world and Minecraft recordings; adapt the simulation list/creator to the new run modes. | E12, E13 | 7 |
| **E16** | Pluggable Memory Backend + Memory Eval Harness | Behind the E5-8 seam (#658), make recall/archival storage swappable; add an Answer Engine backend to dogfood our own data platform; add a substrate-agnostic write-time / retrieval-time memory eval harness that scores the toy store and real traffic. Preserve `default`-backend behavior — no regression. | E5 (E5-8 #658); real value after E7/E8 | 9 |

**Total: ~120 micro-issues across 16 epics.**

---

## 2. Dependency graph (epic level)

```
                         ┌────────────────────────────┐
                         │  E1  Research & Decisions   │  (gates everything)
                         └──────────────┬──────────────┘
            ┌───────────────────────────┼───────────────────────────┐
            ▼                           ▼                           ▼
   ┌─────────────────┐        ┌──────────────────┐        ┌──────────────────┐
   │ E2 MC Server    │        │ E11 Cost/Kill    │        │ E13(infra) Stream│
   │                 │        │  (Python-side,   │        │  capture spike   │
   │                 │        │   parallel)      │        │  (parallel)      │
   └────────┬────────┘        └──────────────────┘        └──────────────────┘
            ▼
   ┌─────────────────┐
   │ E3 Mindcraft    │
   │   fork+eval     │
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │ E4 Bridge       │
   └────────┬────────┘
        ┌───┴────┐                (E5 ∥ E6 — independent, run in parallel)
        ▼        ▼
 ┌──────────┐ ┌──────────────┐
 │ E5 Memory│ │ E6 Embodiment│
 │  service │ │   /actions   │
 └────┬─────┘ └──────┬───────┘
      └──────┬────────┘
             ▼
   ┌───────────────────────┐
   │ E7 Alpha vertical slice│  (single-track integration crucible)
   └───────────┬────────────┘
               ▼
   ┌───────────────────────┐
   │ E8 All agents +        │
   │  decentralized convo   │
   └───────────┬────────────┘
       ┌───────┼─────────────┬───────────────┐
       ▼       ▼             ▼               ▼
  ┌────────┐ ┌────────┐ ┌──────────┐  ┌──────────────┐
  │ E9     │ │ E10    │ │ E12 run  │  │ E13 livestream│
  │ dreams │ │ eval   │ │  modes   │  │  (full)       │
  └────────┘ └────────┘ └────┬─────┘  └──────┬───────┘
                              └──────┬────────┘
                                     ▼
                          ┌────────────────────┐
                          │ E15 Website adapt   │
                          └─────────┬───────────┘
                                    ▼
                          ┌────────────────────┐
                          │ E14 Retire Phaser   │  (last — needs replacement live)
                          └────────────────────┘
```

### Parallelizable epics (no shared dependency)

- **After E1 completes:** `E2`, `E11`, and the `E13` capture spike can run in
  parallel by 3 different agents/people. `E11` and the `E13` spike are almost
  entirely Python/infra-side and never touch the bridge.
- **After E4 completes:** `E5` and `E6` are independent and parallel.
- **After E8 completes:** `E9`, `E10`, `E12`, and full `E13` are largely
  parallel (E12 also needs E5, already done by then).
- **After E5 completes:** `E16` (pluggable backend + eval harness, #659) runs
  parallel with `E9`, off the critical-path spine. E7/E8 ship on the `default`
  backend; the Answer Engine path is an E16-only concern.

### Strictly sequential spine (critical path)

`E1 → E2 → E3 → E4 → (E5 ∥ E6) → E7 → E8 → E12/E13 → E15 → E14`

`E7` is deliberately a **single-track** epic: it is the first time all pieces
touch, and parallelizing it would hide integration bugs.

---

## 3. Recommended build sequence

1. **Do E1 first, fully.** Nothing else starts until E1's decision records exist.
   E1 is cheap relative to the cost of a wrong pinned version or a bridge
   designed against a non-existent extension point.
2. **Fan out after E1:** one agent on `E2` (critical path), one on `E11`
   (hardening, parallel), one on the `E13` capture spike (de-risks the riskiest
   greenfield piece early).
3. **Critical path resumes:** `E3 → E4`. These are sequential and gate the slice.
4. **Parallel pair:** `E5` and `E6` after `E4`.
5. **Converge on `E7`** — single track, no parallelism, this is the proof.
6. **`E8`** scales the proven slice to all agents.
7. **Fan out again:** `E9/E10/E12` + full `E13` in parallel.
8. **`E15`** then **`E14`** last. **Do not delete the Phaser/video path until the
   Minecraft capture + adapted website are demonstrably live** (E14 depends on
   E13 and E15 for exactly this reason).

### Ordering risks (blunt)

- **E1-R3 (model routing) was resolved.** Mindcraft supports separate `model`
  and `code_model` providers. E3 should validate that locally with LM Studio
  profiles before any OpenRouter-backed comparison.
- **E1-R6 (video capture) is the second risk.** The livestream method is fully
  unverified and greenfield. Starting the E13 spike during E2/E3 is deliberate
  insurance — if the only viable capture is "a real Minecraft client + OBS on a
  GPU box," that has hosting/cost consequences that ripple into E2 and E13.
- **E1-R5 (custom-skill extension point) shapes E4.** If Mindcraft has no clean
  extension point, the bridge may require forking core (more E3 work, more
  upstream-merge risk). The E4 contract issues are written to start only after
  E1-R5.
- **E7 is the real schedule risk, not a research one.** Every "preserve" system
  meets the embodied world for the first time in E7. Budget slack there.
- **E11 cost cap is a build, not a port.** The context says preserve "hard
  per-agent hourly spend caps" — they do **not exist** today (V10). Calling this
  "preserve" is misleading; it is net-new safety work and is more urgent for a
  24/7 world than it ever was for batch sims.

---

## 4. Labels to create (Phase 3)

Existing usable labels: `epic`, `backend`, `frontend`, `priority-critical/high/medium/low`,
`ready`, `needs-human-input`, `architecture`, `qa`.

New labels to create:

| Label | Color | Meaning |
|-------|-------|---------|
| `minecraft` | `#1d7c2f` | Touches Minecraft/Mindcraft/Mineflayer |
| `minecraft-beginner` | `#a2eeef` | Written for someone who has never played Minecraft |
| `needs-research` | `#fbca04` | Must verify a fact before/while implementing |
| `parallelizable` | `#0e8a16` | No intra-epic dependency; safe to run concurrently |
| `preserve-no-regress` | `#b60205` | Must not regress a preserved system; named tests must stay green |
| `area:bridge` | `#5319e7` | Python↔Node bridge |
| `area:embodiment` | `#5319e7` | Movement/build/skill/action layer |
| `area:livestream` | `#5319e7` | Capture/encode/stream |
| `area:run-modes` | `#5319e7` | Starting-conditions / scenario system |
| `area:server` | `#5319e7` | Minecraft server ops |

---

## 5. Epics & micro-issues

> Format per issue — **Context** (why), **Scope** (in/out), **Acceptance**,
> **Files/modules**, **Deps** (other issue titles), **Track**
> (parallelizable/sequential within the epic), **Labels**.

---

### EPIC 1 — Research, Decisions & Spikes

Goal: produce written decision records in `docs/decisions/` that every later
epic binds to. Output is decisions, not production code (spikes may be
throwaway). All issues are `needs-research`. Issues E1-R1..R7 are mostly
**parallelizable** (independent investigations); E1-R8 is sequential (it
consolidates).

- **E1-R1 — Decide & pin Minecraft version + server software for 24/7**
  - Context: U4/U6. Everything pins to this; a non-player must run it.
  - Scope (in): compare vanilla server jar vs Paper vs Fabric for a headless
    24/7 private server; confirm exact MC version compatible with the Mindcraft
    commit we intend to pin; document in plain language what each option means.
    (out): actually installing it (that's E2).
  - Acceptance: `docs/decisions/0001-minecraft-version-and-server.md` states the
    chosen MC version, server software, Mindcraft commit hash, and the
    compatibility evidence (links/quotes). Beginner glossary included.
  - Files: `docs/decisions/0001-*.md`
  - Deps: none. Track: parallelizable. Labels: `needs-research`,`minecraft`,`minecraft-beginner`,`area:server`
- **E1-R2 — Decide auth/offline mode posture**
  - Context: U4. Bots on a private server with no Microsoft accounts implies
    `online-mode=false` ("offline"/"cracked") — security and EULA implications a
    beginner must understand.
  - Scope (in): document what offline mode is, its security tradeoffs on a
    private/firewalled server, and whether Mindcraft bots need Microsoft auth in
    our topology; recommend a posture. (out): server config (E2).
  - Acceptance: `docs/decisions/0002-auth-mode.md` with recommendation +
    plain-language risk explanation.
  - Deps: E1-R1. Track: parallelizable. Labels: `needs-research`,`minecraft`,`minecraft-beginner`,`area:server`
- **E1-R3 — Verify Mindcraft per-agent multi-model routing (U1)**
  - Context: **Highest-leverage unknown.** Core research thesis = each agent can
    run separate conversation/building model tiers.
  - Scope (in): inspect the pinned Mindcraft commit's provider code + profile
    schema; determine whether provider routing is fully wired and whether `model` vs
    `code_model` cleanly maps to our conversation vs building tiers; if not,
    specify the exact fork patch required. (out): writing the patch (E3).
  - Acceptance: `docs/decisions/0003-mindcraft-model-routing.md` answers: is
    LM Studio/OpenRouter routing native? does per-agent-per-tier work? exact patch scope if not.
    Cites file/line in the Mindcraft commit.
  - Deps: E1-R1. Track: parallelizable. Labels: `needs-research`,`minecraft`,`backend`
- **E1-R4 — Characterize Mindcraft's decentralized respond/ignore model (U2)**
  - Context: the pivot deletes the Python conversation director and relies on
    Mindcraft's per-agent decentralized respond/ignore behavior.
  - Scope (in): document exactly how Mindcraft decides whether a bot responds to
    another bot/chat; what's configurable; how it maps onto our agents'
    `chattiness`/`initiative`/`adjacency` knobs. Flag any gap. (out): code.
  - Acceptance: `docs/decisions/0004-decentralized-conversation.md` with the
    mechanism described from source, and a mapping table to our existing
    `agents/<id>/config.yaml` knobs, gaps explicitly listed.
  - Deps: E1-R1. Track: parallelizable. Labels: `needs-research`,`minecraft`
- **E1-R5 — Identify Mindcraft custom-skill / custom-action extension point (U3)**
  - Context: the bridge design depends entirely on how we add a "call Python"
    action without forking core.
  - Scope (in): from the pinned commit, document the skill/command/action
    registration mechanism and whether a custom async action can be added
    cleanly; produce a minimal throwaway spike adding a no-op custom action.
    (out): the real bridge (E4).
  - Acceptance: `docs/decisions/0005-skill-extension-point.md` + a spike branch
    proving a custom action registers and fires in-game.
  - Deps: E1-R1, E2 (a running server to spike against) — may instead spike
    against a throwaway LAN world; note which.
  - Track: sequential (needs a world). Labels: `needs-research`,`minecraft`,`area:bridge`
- **E1-R6 — Decide the Minecraft→video capture method (U5)**
  - Context: livestream is greenfield (V9). Options: headless spectator client,
    real client + OBS on a GPU host, server-side renderer, third-party.
  - Scope (in): evaluate feasibility/cost/24-7-resilience of each; recommend one;
    note hosting/GPU implications that feed back into E2/E13. (out): building it.
  - Acceptance: `docs/decisions/0006-video-capture.md` with a recommendation,
    cost/hosting implications, and a fallback option.
  - Deps: E1-R1. Track: parallelizable. Labels: `needs-research`,`minecraft`,`area:livestream`
- **E1-R7 — Minecraft EULA / streaming-licensing posture**
  - Context: 24/7 monetized stream of Minecraft gameplay with offline-mode
    servers — confirm this is permitted and what attribution/limits apply.
  - Scope (in): summarize Mojang/Microsoft EULA + commercial-use/streaming
    guidance relevant to a monetized 24/7 AI stream; flag anything needing a
    human/legal decision. (out): legal sign-off (escalate via `needs-human-input`).
  - Acceptance: `docs/decisions/0007-licensing.md` with findings + an explicit
    "needs human/legal decision" list.
  - Deps: none. Track: parallelizable. Labels: `needs-research`,`needs-human-input`
- **E1-R8 — Consolidated decision record + plan reconciliation**
  - Context: downstream issues bind to E1 outputs; one place must state the final
    pinned values.
  - Scope (in): a single `docs/decisions/0000-summary.md` table of every decided
    value (MC version, server, commit, auth mode, routing verdict, conversation
    verdict, extension point, capture method); reconcile this plan's flagged
    assumptions against the decisions and note any epic scope changes.
  - Acceptance: summary doc exists; any epic whose scope changed has a comment
    noting the delta.
  - Deps: E1-R1..R7. Track: sequential. Labels: `needs-research`

---

### EPIC 2 — Minecraft Server Setup (beginner)

Goal: a private server a non-player can run 24/7, world as a configurable input.
All issues `minecraft-beginner`. E2-1 is sequential (foundation); E2-2..E2-5
parallelize after it; E2-6/E2-7 sequential at the end.

- **E2-1 — Provision and run the chosen server locally (beginner walkthrough)**
  - Context: foundation. Reader has never installed a Minecraft server.
  - Scope (in): step-by-step (Java install, server jar/Paper per E1-R1, EULA
    accept, first boot, `server.properties` essentials explained in plain
    language, `online-mode` per E1-R2); a `scripts/minecraft/` start script.
    (out): cloud hosting (E2-3), 24/7 supervision (E2-4).
  - Acceptance: documented runbook in `docs/minecraft/server-setup.md`; a fresh
    machine can reach a running server following only the doc; start script
    committed.
  - Files: `docs/minecraft/server-setup.md`, `scripts/minecraft/start-server.sh`
  - Deps: E1-R1, E1-R2. Track: sequential. Labels: `minecraft`,`minecraft-beginner`,`area:server`
- **E2-2 — World generation as a configurable input (seed/type/spawn)**
  - Context: run modes need world as an input, not hardcoded.
  - Scope (in): parameterize world seed/type/spawn via a config file consumed by
    the start script; document what a "seed" is for a beginner. (out): wiring
    into the run-mode system (E12).
  - Acceptance: changing the world config file produces a different world on a
    fresh run; documented.
  - Files: `scripts/minecraft/world.config`, `docs/minecraft/world-config.md`
  - Deps: E2-1. Track: parallelizable. Labels: `minecraft`,`minecraft-beginner`,`area:server`
- **E2-3 — Decide & document hosting for 24/7 (local vs cloud)**
  - Context: 24/7 needs a durable host; tie to E1-R6 (capture host may co-locate).
  - Scope (in): document a recommended host (spec, OS, cost) and the tradeoffs;
    no provisioning automation required yet. (out): IaC.
  - Acceptance: `docs/minecraft/hosting.md` with a concrete recommendation and
    cost estimate; cross-references E1-R6.
  - Deps: E2-1, E1-R6. Track: parallelizable. Labels: `minecraft`,`minecraft-beginner`,`area:server`
- **E2-4 — 24/7 supervision: auto-restart + crash recovery**
  - Context: a 24/7 world must survive crashes unattended.
  - Scope (in): a supervisor (systemd unit or process manager) that restarts the
    server on crash, with logs; documented for a beginner. (out): alerting (E11/E13).
  - Acceptance: killing the server process results in automatic restart within a
    documented window; logs retained.
  - Files: `scripts/minecraft/minecraft.service` (or equivalent), docs.
  - Deps: E2-1. Track: parallelizable. Labels: `minecraft`,`minecraft-beginner`,`area:server`
- **E2-5 — World backup & restore**
  - Context: a persistent world is irreplaceable; experimental runs need resets.
  - Scope (in): scripted periodic backup + a documented restore + a "reset to
    fresh world" path used by experimental run mode. (out): run-mode wiring (E12).
  - Acceptance: backup runs on a schedule; a documented restore recreates a
    prior world; reset produces a clean world.
  - Files: `scripts/minecraft/backup.sh`, `scripts/minecraft/restore.sh`, docs.
  - Deps: E2-1, E2-2. Track: parallelizable. Labels: `minecraft`,`minecraft-beginner`,`area:server`
- **E2-6 — Server health check + status endpoint**
  - Context: the Python brain / livestream must know the world is up.
  - Scope (in): a lightweight health probe (port/ping) and a
    `scripts/check-services.sh`-style addition or new check that reports server
    liveness. (out): dashboards.
  - Acceptance: a single command reports server up/down; integrates with the
    existing `scripts/check-services.sh` pattern.
  - Files: `scripts/minecraft/health.sh`, update `scripts/check-services.sh`
  - Deps: E2-1, E2-4. Track: sequential. Labels: `minecraft`,`area:server`
- **E2-7 — Server ops runbook (beginner) + teardown**
  - Context: the owner must operate this without Minecraft knowledge.
  - Scope (in): consolidate start/stop/backup/restore/restart/health into one
    plain-language runbook; include a clean teardown.
  - Acceptance: `docs/minecraft/runbook.md` covers every operation with copy-paste
    commands and what each does.
  - Deps: E2-1..E2-6. Track: sequential. Labels: `minecraft`,`minecraft-beginner`,`area:server`

---

### EPIC 3 — Mindcraft Fork & Evaluation

Goal: a pinned fork with one bot connecting to the E2 server and verified
per-agent multi-model routing through local LM Studio profiles. E3-1 sequential; E3-2..E3-4 then
E3-5/E3-6 build on it; E3-7 conditional.

- **E3-1 — Fork Mindcraft, pin the commit, reproducible install**
  - Context: we need a stable base; upstream moves fast.
  - Scope (in): fork to the org, pin the E1-R1 commit, document the exact
    Node/npm versions and install steps, commit a lockfile. (out): customizations.
  - Acceptance: a clean checkout installs deterministically from the documented
    steps; commit hash recorded in `docs/decisions/0000-summary.md`.
  - Deps: E1-R1, E1-R8. Track: sequential. Labels: `minecraft`,`area:bridge`
- **E3-2 — One stock bot connects to the E2 server**
  - Context: prove the fork talks to our server before customizing.
  - Scope (in): configure `settings.js`/profile to point at the E2 server
    (host/port/auth per E1-R2), launch one stock bot, confirm it spawns and
    moves. (out): our agents.
  - Acceptance: documented command launches a bot that visibly joins the E2 world.
  - Deps: E3-1, E2-1. Track: sequential. Labels: `minecraft`,`minecraft-beginner`
- **E3-3 — Verify/patch per-agent multi-model routing**
  - Context: **core thesis** (U1/E1-R3). `preserve-no-regress`: our model
    assignments must survive the pivot.
  - Scope (in): implement whatever E1-R3 concluded — either configure native
    LM Studio/OpenRouter routing or apply the specified fork patch — so a
    profile can route `model` (conversation tier) and `code_model` (building
    tier) to distinct models per agent. (out): all 9 profiles (E8).
  - Acceptance: two bots with different profiles demonstrably hit two different
    LM Studio local model IDs for chat vs code; mirrors the mapping in
    `core/llm_client.py` `MODEL_NAME_ALIASES`/`MODEL_REGISTRY`; documented.
  - Files: fork profile/provider config; cross-ref `core/llm_client.py`
  - Deps: E1-R3, E3-2. Track: sequential. Labels: `minecraft`,`backend`,`preserve-no-regress`
- **E3-4 — Map our agent model assignments → Mindcraft profile schema**
  - Context: single source of truth for which agent uses which model
    (`agents/<id>/config.yaml`, `CLAUDE.md` table) must drive Mindcraft profiles.
  - Scope (in): a generator that reads `agents/<id>/config.yaml`
    (`model_conversation`, `model_building`) and emits Mindcraft profile JSON;
    one agent proven. (out): running all agents (E8).
  - Acceptance: generator emits a valid profile for `vera` whose `model`/`code_model`
    match `agents/vera/config.yaml`; unit-tested.
  - Files: `scripts/minecraft/gen_profiles.py`, `tests/backend/test_mc_profile_gen.py`
  - Deps: E3-3. Track: parallelizable (after E3-3). Labels: `minecraft`,`backend`,`preserve-no-regress`
- **E3-5 — Strip/disable unused Mindcraft features**
  - Context: reduce surface area and cost; we own conversation/memory elsewhere.
  - Scope (in): disable Mindcraft features superseded by the Python brain
    (its own memory/persona/voice if redundant) per E1-R3/R4 findings, behind
    config flags, reversible. (out): irreversible deletion of fork core.
  - Acceptance: documented list of disabled features + rationale; a bot still
    connects and acts with them off.
  - Deps: E3-3, E1-R4. Track: parallelizable. Labels: `minecraft`
- **E3-6 — Fork maintenance & upstream-merge policy**
  - Context: we must be able to take upstream fixes without losing patches.
  - Scope (in): document branch strategy (patches isolated), how to re-base on
    upstream, and a CI check that the fork builds. (out): the CI infra itself if
    none exists — then open a follow-up.
  - Acceptance: `docs/minecraft/fork-maintenance.md` + a green build check.
  - Deps: E3-1. Track: parallelizable. Labels: `minecraft`,`architecture`
- **E3-7 — (Conditional) provider-routing fork-patch hardening**
  - Context: only if E1-R3 concluded a patch is required and E3-3 was non-trivial.
  - Scope (in): tests for the routing patch (model selection, fallback, cost
    attribution) so an upstream rebase can't silently break the thesis.
  - Acceptance: tests fail if per-agent/per-tier routing breaks.
  - Deps: E3-3. Track: sequential. Labels: `minecraft`,`backend`,`preserve-no-regress`,`needs-research`

---

### EPIC 4 — Python↔Node Bridge

Goal: a versioned, authenticated, bidirectional bridge. Design issues
(E4-1..E4-3) start after E1-R5; impl after E3. E4-4..E4-7 parallelize once the
contract lands; E4-8/E4-9 sequential.

- **E4-1 — Bridge transport & protocol decision record**
  - Context: choose HTTP/WebSocket/IPC given E1-R5's extension point; bots are
    Node, services are Python/FastAPI (`core/main.py` already has `/ws`).
  - Scope (in): decide transport, message envelope, versioning, auth (shared
    secret/local-only), and failure semantics; ADR. (out): code.
  - Acceptance: `docs/decisions/0010-bridge-protocol.md`; consistent with E1-R5.
  - Deps: E1-R5. Track: sequential. Labels: `area:bridge`,`architecture`,`needs-research`
- **E4-2 — Versioned message contract (schemas both sides)**
  - Context: a shared contract prevents drift between Node and Python.
  - Scope (in): define request/response schemas for the initial verbs
    (memory.read, memory.write, management.review, cost.gate, perception.report,
    action.result); Pydantic models on Python side + JSON schema for Node.
  - Acceptance: schemas committed; a contract test validates both directions
    against fixtures.
  - Files: `core/bridge/contract.py`, `tests/backend/test_bridge_contract.py`
  - Deps: E4-1. Track: sequential. Labels: `area:bridge`,`backend`
- **E4-3 — Python bridge server endpoint**
  - Context: FastAPI app exists (`core/main.py`); add the bridge surface.
  - Scope (in): a mounted bridge router/WS handler that auth-checks and dispatches
    to stub handlers; no business logic yet. (out): real memory/mgmt wiring
    (E5/E8).
  - Acceptance: bridge endpoint accepts a valid signed message and echoes a
    contract-valid stub response; rejects unauthenticated calls.
  - Files: `core/bridge/server.py`, wired in `core/main.py`, `tests/backend/test_bridge_server.py`
  - Deps: E4-2. Track: sequential. Labels: `area:bridge`,`backend`
- **E4-4 — Node bridge client in the fork**
  - Context: bots need a client to call Python; built at E1-R5's extension point.
  - Scope (in): a Node module that sends contract messages, handles auth, timeout,
    and structured errors; one custom Mindcraft action that round-trips a ping.
  - Acceptance: in-game, a bot invokes the ping action and logs the Python
    response; failure path logged, not crashed.
  - Deps: E4-3, E1-R5, E3-2. Track: parallelizable. Labels: `area:bridge`,`minecraft`
- **E4-5 — Reconnect, backpressure & timeout policy**
  - Context: 24/7 means the bridge will drop; bots must degrade safely.
  - Scope (in): reconnect with backoff on the Node client; bounded in-flight
    requests; defined behavior when Python is unreachable (bot pauses vs
    safe-idle, never unsafe action).
  - Acceptance: killing the Python server mid-run causes bots to safe-idle and
    auto-recover when it returns; covered by an integration test.
  - Deps: E4-4. Track: parallelizable. Labels: `area:bridge`,`minecraft`
- **E4-6 — Perception/action result channel (Node→Python)**
  - Context: Option C requires perception/action outcomes flowing back.
  - Scope (in): Node emits structured perception + action-result events over the
    bridge; Python stores them (transient store / event bus, reuse
    `core/event_bus.py`). (out): memory writes (E5), eval use (E10).
  - Acceptance: an in-game action produces a perception/result event observable
    on the Python side; schema-validated.
  - Files: `core/bridge/inbound.py`, cross-ref `core/event_bus.py`
  - Deps: E4-3, E4-4. Track: parallelizable. Labels: `area:bridge`,`backend`
- **E4-7 — Bridge observability (logs, metrics, trace IDs)**
  - Context: debugging a cross-language 24/7 system needs correlation.
  - Scope (in): correlation/trace IDs across Node↔Python, structured logs both
    sides, basic counters (calls, errors, latency).
  - Acceptance: a single request is traceable end-to-end via one trace ID in
    both logs.
  - Deps: E4-3, E4-4. Track: parallelizable. Labels: `area:bridge`
- **E4-8 — Bridge integration test harness**
  - Context: future epics need a way to test against a fake bridge without a server.
  - Scope (in): a Python-side fake Node client + a Node-side fake Python server,
    reusable in E5–E12 tests; CI-runnable without Minecraft.
  - Acceptance: harness ships; one example test in `tests/integration/` uses it.
  - Files: `tests/integration/bridge_harness.py`
  - Deps: E4-3..E4-6. Track: sequential. Labels: `area:bridge`,`qa`
- **E4-9 — Bridge security review**
  - Context: a local RPC surface that can trigger spend and in-world actions.
  - Scope (in): threat-model the bridge (auth, replay, injection into actions,
    DoS), apply fixes; uses the `security-analysis` skill standards.
  - Acceptance: documented threat model + mitigations; no unauthenticated path
    can trigger spend or actions.
  - Deps: E4-3..E4-7. Track: sequential. Labels: `area:bridge`,`architecture`

---

### EPIC 5 — Memory Service Exposure (preserve-no-regress)

Goal: expose the existing 3-tier memory unchanged in behavior, via the bridge.
**Every issue is `preserve-no-regress`.** E5-1 sequential; E5-2..E5-4 parallel;
E5-5..E5-7 sequential.

- **E5-1 — Memory bridge service: read paths**
  - Context: bots must query core/recall/archival memory; logic stays in
    `core/memory/` (`core_memory.py`, `recall_memory.py`, `archival_memory.py`).
  - Scope (in): bridge verbs that call the existing managers read-only; no new
    memory logic. (out): writes (E5-2).
  - Acceptance: a bot can fetch an agent's core memory + a recall search result
    via the bridge; results identical to calling the managers directly.
  - Files: `core/bridge/handlers/memory.py`, cross-ref `core/memory/*`
  - Deps: E4-3, E4-4. Track: sequential. Labels: `area:bridge`,`backend`,`preserve-no-regress`
- **E5-2 — Memory bridge service: write/append paths**
  - Context: embodied events must be writable to recall/archival.
  - Scope (in): bridge verbs delegating to existing append/write methods +
    `core/repos/memory_repo.py`; preserve compaction triggers
    (`core/memory/compaction.py`). (out): perception auto-write (E5-4).
  - Acceptance: a bridge write produces the same DB rows/embeddings as a direct
    manager call; `tests/backend/test_recall_memory.py`,
    `test_archival_memory.py`, `test_memory_tools.py` stay green.
  - Deps: E5-1. Track: sequential. Labels: `area:bridge`,`backend`,`preserve-no-regress`
- **E5-3 — Preserve tool-facing memory API parity**
  - Context: `tools/memory_tools.py` defines the agent-facing memory API; the
    bridge must not introduce a divergent second API.
  - Scope (in): make the bridge memory verbs delegate to the same code path as
    `tools/memory_tools.py`; document the single source of truth.
  - Acceptance: `tests/backend/test_memory_tools.py` unchanged & green; a parity
    test asserts bridge and tool paths return equivalent results.
  - Deps: E5-1. Track: parallelizable. Labels: `backend`,`preserve-no-regress`
- **E5-4 — Wire perception/action events → recall/archival**
  - Context: E4-6 emits embodied events; they should feed memory like
    conversation turns do today.
  - Scope (in): a consumer mapping perception/action-result events into
    recall/archival via existing managers (no new memory semantics).
  - Acceptance: an in-game action results in a retrievable recall memory;
    embeddings generated via `core/memory/embeddings.py`.
  - Deps: E4-6, E5-2. Track: parallelizable. Labels: `area:bridge`,`backend`,`preserve-no-regress`
- **E5-5 — Memory-seed compatibility with embodied runs**
  - Context: `core/memory/memory_seed.py` + `MemorySeedConfig` + `scenarios/seeds/*`
    must still apply before embodied agents start.
  - Scope (in): confirm the seed path (`orchestrator._apply_memory_seed`) still
    runs and seeded memories are visible to bots via the bridge. (out): new seed
    formats (E12).
  - Acceptance: a run seeded from `scenarios/seeds/blank-slate.json` shows the
    seeded core memory through the bridge; `tests/backend/test_memory_seed.py` green.
  - Deps: E5-1. Track: sequential. Labels: `backend`,`preserve-no-regress`,`area:run-modes`
- **E5-6 — Memory regression suite gate**
  - Context: lock in "no regression" before E7.
  - Scope (in): a CI gate running the full memory test set
    (`test_core_memory*.py`, `test_recall_memory.py`, `test_archival_memory.py`,
    `test_cross_conversation_memory.py`, `test_memory_seed.py`,
    `test_memory_snapshot.py`, `test_memory_tools.py`) against the bridge path.
  - Acceptance: gate is required and green.
  - Deps: E5-1..E5-5. Track: sequential. Labels: `qa`,`preserve-no-regress`
- **E5-7 — Memory bridge performance check**
  - Context: 24/7 + many memory reads per action; latency matters.
  - Scope (in): measure bridge memory read/write latency vs direct calls; set a
    documented budget; flag if pgvector recall is too slow per action.
  - Acceptance: latency report committed; within documented budget or a
    follow-up issue filed.
  - Deps: E5-1,E5-2. Track: sequential. Labels: `area:bridge`,`backend`
- **E5-8 — MemoryBackend protocol seam** (#658)
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
  - Deps: E5-3. Positioned in the #507 checklist before E5-6 so the regression
    gate covers the refactor; E5-6's dep list intentionally unchanged.
  - Track: sequential. Labels: `backend`,`preserve-no-regress`

---

### EPIC 6 — Embodiment / Action Layer

Goal: real movement/building with **action-success verification**, code-writing
retained. E6-1 sequential; E6-2..E6-5 parallel; E6-6..E6-9 sequential/integration.

- **E6-1 — Curated skill set definition**
  - Context: Mindcraft ships many actions; we want a deliberate, verifiable set
    aligned to "build/create with verification."
  - Scope (in): enumerate the allowed action/skill set (move, navigate, place,
    break, craft, inventory, build-from-plan, observe) and explicitly excluded
    ones; document. (out): implementation of each (later issues).
  - Acceptance: `docs/minecraft/skill-set.md` listing each skill, its inputs, and
    its verification signal.
  - Deps: E1-R4, E1-R5, E3-5. Track: sequential. Labels: `area:embodiment`,`minecraft`
- **E6-2 — Movement & navigation with success verification**
  - Context: agents must move and *know* they arrived (the verification mechanism
    the project lacked).
  - Scope (in): movement skills returning a verified outcome (reached target /
    blocked / timed out) via the E4-6 channel. (out): building.
  - Acceptance: a navigate action reports verified success/failure observable on
    the Python side.
  - Deps: E6-1, E4-6. Track: parallelizable. Labels: `area:embodiment`,`minecraft`
- **E6-3 — Block place/break with success verification**
  - Context: building primitives must be self-verifying.
  - Scope (in): place/break skills that confirm the world actually changed
    (post-action world read), reporting verified result.
  - Acceptance: placing a block reports verified success only if the block is
    actually present afterward.
  - Deps: E6-1, E4-6. Track: parallelizable. Labels: `area:embodiment`,`minecraft`
- **E6-4 — Build-from-plan skill (multi-block structures)**
  - Context: "genuinely build things, with verification" is the headline goal.
  - Scope (in): a skill that takes a structured build plan and executes it,
    returning per-step verified results + an overall completion metric.
  - Acceptance: a small predefined structure builds and the result reports
    actual vs intended blocks.
  - Deps: E6-3. Track: parallelizable. Labels: `area:embodiment`,`minecraft`
- **E6-5 — Retain code-writing as a tool alongside building**
  - Context: the pivot keeps coding ability. `tools/code_execution.py` runs in a
    Docker sandbox today; keep it available to embodied agents.
  - Scope (in): expose code execution to embodied agents via the bridge,
    delegating to the existing sandbox path; no new sandbox. (out): replacing
    `tilemap_gen` (that retires in E14).
  - Acceptance: an embodied agent can run code via the bridge; result returned;
    `tests/backend/` sandbox tests still green.
  - Files: bridge handler → `tools/code_execution.py`
  - Deps: E4-3. Track: parallelizable. Labels: `area:embodiment`,`area:bridge`,`backend`
- **E6-6 — Perception snapshot API (what the agent can see)**
  - Context: decisions need a structured world view; replaces `tools/world_state.py`'s
    Redis snapshot with real perception.
  - Scope (in): a perception verb returning nearby blocks/entities/inventory/pose
    in a stable schema. (out): memory writing (E5-4).
  - Acceptance: perception returns a schema-valid snapshot for a known setup.
  - Deps: E6-1, E4-6. Track: sequential. Labels: `area:embodiment`,`area:bridge`
- **E6-7 — Action failure taxonomy & safe-fail behavior**
  - Context: 24/7 autonomy must never wedge or act unsafely on failure.
  - Scope (in): a defined taxonomy (blocked, timeout, invalid, unreachable,
    bridge-down) and the safe behavior for each (idle, retry-bounded, abandon).
  - Acceptance: each failure class has a test asserting safe behavior.
  - Deps: E6-2,E6-3. Track: sequential. Labels: `area:embodiment`,`qa`
- **E6-8 — Embodiment unit/integration tests (no live server)**
  - Context: must be CI-testable without Minecraft (uses E4-8 harness).
  - Scope (in): tests for skills against the fake bridge + mocked perception.
  - Acceptance: skill tests run in CI without a server.
  - Deps: E4-8, E6-2..E6-6. Track: sequential. Labels: `area:embodiment`,`qa`
- **E6-9 — Skill cost attribution hook**
  - Context: codegen/LLM-backed skills must attribute spend per agent (feeds E11).
  - Scope (in): ensure any LLM call a skill triggers flows through the existing
    cost path (`core/llm_client.py` → `core/repos/cost_repo.py`) with correct
    `agent_id`.
  - Acceptance: a codegen skill call appears in `cost_events` attributed to the
    right agent; `tests/backend/test_cost_tracking.py` green.
  - Deps: E6-5. Track: sequential. Labels: `area:embodiment`,`backend`,`preserve-no-regress`

---

### EPIC 7 — Alpha Vertical Slice (single track — no parallelism)

Goal: Alpha (non-verbal, action-only — simplest agent, per the context)
end-to-end. This epic is intentionally **all sequential**: it is the first
integration of every piece and parallelizing hides bugs.

- **E7-1 — Alpha Mindcraft profile (non-verbal, action-only)**
  - Context: `agents/alpha/config.yaml` (deepseek/deepseek-v3.2, chattiness 0),
    `agents/alpha/system_prompt.md` (symbols only).
  - Scope: generate Alpha's profile via E3-4; no chat participation; routed via
    local LM Studio profile IDs per E3-3.
  - Acceptance: Alpha spawns in the E2 world using its configured model; emits no
    chat.
  - Deps: E3-4, E2-1, E7 prerequisites (E2–E6). Track: sequential. Labels: `minecraft`,`area:embodiment`
- **E7-2 — Alpha receives a dispatched errand via the bridge**
  - Context: `tools/alpha_dispatch.py` is the existing dispatch path; preserve
    its semantics (allowed agents, 60s timeout).
  - Scope: another process/agent dispatches Alpha; the errand reaches the bot via
    the bridge; preserve `tools/alpha_dispatch.py` behavior.
  - Acceptance: a dispatched task arrives at Alpha; `tests/backend` alpha-dispatch
    tests stay green. Labels: `area:bridge`,`backend`,`preserve-no-regress`
  - Deps: E7-1, E4-4. Track: sequential.
- **E7-3 — Alpha executes a verified in-world errand**
  - Context: proves embodiment + verification.
  - Scope: Alpha performs a simple fetch/move/place errand and reports verified
    success/failure (symbols ✓/✗ semantics from its system prompt).
  - Acceptance: a known errand completes with a verified result surfaced.
  - Deps: E7-2, E6-2,E6-3. Track: sequential. Labels: `area:embodiment`
- **E7-4 — Alpha writes the outcome to memory**
  - Context: prove the preserved memory path end-to-end.
  - Scope: errand outcome persists via E5 to recall/archival.
  - Acceptance: the outcome is retrievable via the memory bridge; memory tests green.
  - Deps: E7-3, E5-2. Track: sequential. Labels: `preserve-no-regress`,`backend`
- **E7-5 — Management out-of-band on Alpha's (symbolic) output**
  - Context: Management is a filter, never a bot (`core/management.py`).
  - Scope: route Alpha's emitted output through `Management.review` out-of-band;
    confirm it is not spawned as a world bot.
  - Acceptance: Alpha output passes through the filter; `tests/backend/test_management.py`
    green; no Management entity exists in-world.
  - Deps: E7-3. Track: sequential. Labels: `preserve-no-regress`,`backend`
- **E7-6 — Cost gate + kill switch enforced on the slice**
  - Context: prove safety before scaling. Ties to E11.
  - Scope: Alpha's LLM spend attributed and gated; activating the kill switch
    (Redis `kill_switch`) halts Alpha's bot within a documented window.
  - Acceptance: kill switch stops Alpha acting; spend appears in `cost_events`;
    `tests/backend/test_cost_tracking.py` green.
  - Deps: E7-3, E11-3, E11-5. Track: sequential. Labels: `preserve-no-regress`,`area:bridge`
- **E7-7 — Vertical-slice acceptance report**
  - Context: explicit go/no-go before E8.
  - Scope: a documented run-through of E7-1..E7-6 with evidence; list any
    deviations from `MINECRAFT-PIVOT-CONTEXT.md`.
  - Acceptance: `docs/minecraft/alpha-slice-report.md` shows the full chain
    working; sign-off recorded.
  - Deps: E7-1..E7-6. Track: sequential. Labels: `minecraft`,`needs-human-input`

---

### EPIC 8 — All Agents Embodied + Decentralized Conversation

Goal: scale the proven slice to all agents; replace the director with Mindcraft's
decentralized model. E8-1 sequential; E8-2..E8-5 parallel (per-agent); E8-6..E8-9
sequential.

- **E8-1 — Generate all agent profiles from config (single source of truth)**
  - Context: `agents/<id>/config.yaml` + `CLAUDE.md` model table must drive all
    profiles; `preserve-no-regress` on model assignments.
  - Scope: extend E3-4 generator to all 9 agents incl. special handling for
    `management` (NOT a bot) and `alpha` (non-verbal).
  - Acceptance: generator emits valid profiles for all conversational agents;
    excludes Management as a world bot; `tests/backend/test_model_versions.py` green.
  - Deps: E3-4, E7-7. Track: sequential. Labels: `minecraft`,`backend`,`preserve-no-regress`
- **E8-2..E8-4 — Embody the agent cohort (parallelizable, 1 issue per small group)**
  - Context: each agent has distinct personality/model; embody in parallel.
  - Scope: E8-2 = Vera+Rex; E8-3 = Aurora+Pixel+Fork; E8-4 = Sentinel+Grok.
    Each: spawn with correct local LM Studio model/profile, basic act/build,
    memory wired.
  - Acceptance (each): the group's agents spawn with correct models and perform a
    verified action; per-agent model verified against config.
  - Deps: E8-1. Track: **parallelizable** (3 agents/people, one per issue).
    Labels: `minecraft`,`area:embodiment`,`preserve-no-regress`
- **E8-5 — Map personality knobs → Mindcraft conversation behavior**
  - Context: per E1-R4, map `chattiness/initiative/interrupt/eavesdrop/adjacency`
    from `agents/<id>/config.yaml` onto Mindcraft's respond/ignore config.
  - Scope: implement the mapping decided in E1-R4; document gaps where Mindcraft
    can't express a knob.
  - Acceptance: at least two agents show measurably different respond rates
    consistent with their `chattiness`.
  - Deps: E8-1, E1-R4. Track: parallelizable. Labels: `minecraft`,`needs-research`
- **E8-6 — Retire the Python conversation director for embodied runs**
  - Context: `core/conversation_engine.py` / `core/conversation/speaker_selector.py`
    are the old central director; Option C removes central direction.
  - Scope: behind a run-mode flag, embodied runs use decentralized
    respond/ignore instead of the speaker selector; **do not delete** the old
    engine yet (still used by legacy/eval until E10/E14) — gate it.
  - Acceptance: an embodied multi-agent run holds a conversation with no central
    director invoked; legacy path still works behind the flag; selector tests green.
  - Deps: E8-5. Track: sequential. Labels: `architecture`,`backend`,`preserve-no-regress`
- **E8-7 — Management out-of-band on all bot chat**
  - Context: every agent utterance must pass `Management.review` before it's
    visible/streamed (3-second intervention window per `CLAUDE.md`).
  - Scope: all bot-emitted chat routed through Management out-of-band; preserve
    severity ladder + kill-switch-at-sev-5.
  - Acceptance: blocked content is intercepted before display; `test_management.py` green.
  - Deps: E8-2..E8-4. Track: sequential. Labels: `preserve-no-regress`,`backend`
- **E8-8 — Multi-agent stability soak (hours)**
  - Context: 24/7 needs proof it doesn't drift/deadlock with all agents.
  - Scope: a multi-hour soak with all agents; capture crashes, runaway loops,
    bridge drops; tune.
  - Acceptance: a documented multi-hour run with no unrecovered failure and spend
    within E11 caps.
  - Deps: E8-6, E8-7, E11-3. Track: sequential. Labels: `minecraft`,`qa`
- **E8-9 — Cohort acceptance report**
  - Context: go/no-go before fan-out epics.
  - Scope: evidence that all agents run embodied with correct models and
    decentralized conversation; deviations vs context doc listed.
  - Acceptance: `docs/minecraft/cohort-report.md` + sign-off.
  - Deps: E8-1..E8-8. Track: sequential. Labels: `minecraft`,`needs-human-input`

---

### EPIC 9 — Dreams / Journals / Website Publishing Preserved (preserve-no-regress)

Goal: keep reflection/dreams/journals working on embodied activity and
publishing. E9-1..E9-3 parallel; E9-4..E9-6 sequential.

- **E9-1 — Reflection runs on embodied activity**
  - Context: `core/memory/reflection.py` + `reflection_scheduler.py` reflect on
    conversations today; embodied actions must also be reflected on.
  - Scope: ensure reflection inputs include embodied recall memories (from E5-4);
    no change to reflection cadence logic.
  - Acceptance: a post-action reflection produces a journal entry; `test_reflection*.py`,
    `test_reflection_scheduler.py` green.
  - Deps: E5-4, E8-2..E8-4. Track: parallelizable. Labels: `preserve-no-regress`,`backend`
- **E9-2 — Dreams unchanged in embodied runs**
  - Context: `core/memory/dreams.py` (high-temp idle reflection). Behavior must
    not regress.
  - Scope: confirm the dream cycle fires in embodied/idle periods; recombines
    embodied + conversational memories; no semantic change.
  - Acceptance: a dream produces narrative/goals as before; `test_dreams.py` green;
    `scenarios/dream_cycle_test.yaml` still valid (or adapted, documented).
  - Deps: E5-4. Track: parallelizable. Labels: `preserve-no-regress`,`backend`
- **E9-3 — Journal image generation still works**
  - Context: `tools/journal_image_tool.py` generates journal imagery.
  - Scope: confirm it functions in embodied runs (it's provider-side, not Phaser)
    or document any coupling to retired assets.
  - Acceptance: a journal entry with an image renders; documented.
  - Deps: E9-1. Track: parallelizable. Labels: `preserve-no-regress`
- **E9-4 — Website publishing of journals/dreams intact**
  - Context: `core/blog.py` + website `/blog`,`/agents` pages publish journals.
  - Scope: confirm embodied-run journals/dreams publish unchanged; no Phaser
    dependency in the publish path.
  - Acceptance: a journal from an embodied run appears on the site; no regression.
  - Deps: E9-1, E9-2. Track: sequential. Labels: `preserve-no-regress`,`frontend`
- **E9-5 — Dreams/journals regression gate**
  - Context: lock in no-regression.
  - Scope: CI gate over `test_dreams.py`, `test_reflection*.py`,
    `test_reflection_goals.py`, `test_reflect_after.py` on the embodied path.
  - Acceptance: gate required and green.
  - Deps: E9-1..E9-4. Track: sequential. Labels: `qa`,`preserve-no-regress`
- **E9-6 — Scenario fixtures updated (dream/reflection)**
  - Context: `scenarios/dream_cycle_test.yaml`, `dream_smoke_test.yaml`,
    `goal_generation_test.yaml` assume the old world.
  - Scope: update these fixtures for embodied runs (or document why unchanged);
    keep them runnable.
  - Acceptance: the named scenarios run green under embodied mode.
  - Deps: E9-5. Track: sequential. Labels: `preserve-no-regress`,`area:run-modes`

---

### EPIC 10 — Eval & Reporting Adapted

Goal: evals/reporting work on embodied data and gain real build-verification
signal. E10-1 sequential; E10-2..E10-4 parallel; E10-5..E10-7 sequential.

- **E10-1 — Eval data loader handles embodied events**
  - Context: `core/eval/loader.py` + `EvalEngine` (`core/eval/engine.py`) load
    simulation data; embodied perception/action results are new inputs.
  - Scope: extend the loader to include embodied actions/build outcomes; no
    change to the LLM-eval mechanism.
  - Acceptance: an embodied run's data loads into the eval engine; existing
    `test_eval_engine.py`, `test_eval_categories.py` green.
  - Deps: E8-2..E8-4. Track: sequential. Labels: `backend`,`preserve-no-regress`
- **E10-2 — Add a build-verification eval category**
  - Context: the whole pivot premise — agents can now *verifiably* build. Evals
    should measure it.
  - Scope: a new category in `evals/prompts/` scoring intended-vs-actual build
    outcomes using the verification signal from E6.
  - Acceptance: the category scores a sample run; wired into a suite in
    `core/eval/engine.py` `EVAL_SUITES`.
  - Deps: E10-1, E6-4. Track: parallelizable. Labels: `eval-finding`,`backend`
- **E10-3 — Preserve existing eval categories/suites**
  - Context: don't lose entertainment/safety/agency/etc. coverage.
  - Scope: verify all current categories still run on embodied data; fix loaders
    where world-shape assumptions break.
  - Acceptance: every pre-existing eval category runs without error on an
    embodied run; `test_agency_eval.py`, `test_eval_analyzer.py` green.
  - Deps: E10-1. Track: parallelizable. Labels: `preserve-no-regress`,`backend`
- **E10-4 — Reporting/scorecard reflects embodied metrics**
  - Context: `core/reporting/` (`scorecard.py`, `timeline_reporter.py`,
    `comparison.py`) and `scripts/report_simulation.py`.
  - Scope: add embodied metrics (verified builds, actions) to the scorecard;
    preserve existing fields.
  - Acceptance: a report includes embodied metrics; existing report tests green.
  - Deps: E10-1. Track: parallelizable. Labels: `backend`
- **E10-5 — Eval suite for the two run modes**
  - Context: persistent vs experimental runs may need different suites.
  - Scope: define which suites apply to 24/7 vs experimental; document.
  - Acceptance: documented suite mapping; `scripts/run_eval.py` can target either.
  - Deps: E10-2, E10-3, E12-1. Track: sequential. Labels: `backend`,`area:run-modes`
- **E10-6 — Eval regression gate**
  - Scope: CI gate over the eval/reporting test set on embodied data.
  - Acceptance: gate required and green.
  - Deps: E10-1..E10-4. Track: sequential. Labels: `qa`,`preserve-no-regress`
- **E10-7 — Eval docs updated**
  - Context: `specs/AGENT-AUTONOMY-EVAL-STRATEGY.md` references the old world.
  - Scope: update eval docs for the embodied world (specs are read-only
    reference — add a companion doc in `docs/` rather than editing specs).
  - Acceptance: `docs/eval-embodied.md` explains the adapted eval model.
  - Deps: E10-5. Track: sequential. Labels: `documentation`

---

### EPIC 11 — Cost Controls & Kill Switch Hardened

Goal: carry over per-sim cap + phone kill switch; **build the missing hard
per-agent hourly spend cap**; make the kill switch halt the Node bots. Mostly
Python-side, parallel after E1. E11-1..E11-2 parallel; E11-3..E11-7 sequential.

- **E11-1 — Audit & document current cost/kill mechanisms**
  - Context: be precise about what exists (V10): per-sim `max_cost`
    (`orchestrator._check_cost_limit`), Redis `kill_switch`,
    `core/admin/kill_switch_routes.py`, Management sev-5.
  - Scope: written audit of every cost/kill path + the gaps for 24/7.
  - Acceptance: `docs/cost-kill-audit.md` lists mechanisms, owners, and gaps.
  - Deps: none (after E1). Track: parallelizable. Labels: `backend`,`architecture`
- **E11-2 — Carry over per-simulation cost cap to persistent runs**
  - Context: `max_cost`/`CostLimitExceededError` exist for sims; a 24/7 run needs
    an equivalent rolling budget guard.
  - Scope: a rolling/periodic spend ceiling for persistent mode reusing the
    `cost_events` reconciliation already in `orchestrator._check_cost_limit`.
  - Acceptance: exceeding the rolling ceiling halts the run; `test_cost_tracking.py` green.
  - Deps: E11-1. Track: parallelizable. Labels: `backend`,`preserve-no-regress`
- **E11-3 — Build hard per-agent hourly spend cap (NET-NEW)**
  - Context: **does not exist today (V10).** The context doc calls this
    "preserve" but it must be built; it's the top safety gap for 24/7 (a prior
    runaway burned $38/hr).
  - Scope: per-agent hourly spend tracked from `cost_events` (attributed via
    `core/llm_client._log_cost`); breaching it disables that agent's LLM/bot
    actions until the window rolls; configurable per agent.
  - Acceptance: a synthetic runaway agent is capped within the hour and stops
    acting; other agents unaffected; tests added.
  - Files: new `core/cost_governor.py` (or extend economy module),
    `core/repos/cost_repo.py`, `tests/backend/test_cost_governor.py`
  - Deps: E11-1. Track: sequential. Labels: `backend`,`priority-critical`,`preserve-no-regress`
- **E11-4 — Phone-accessible kill switch verified end-to-end**
  - Context: `core/admin/kill_switch_routes.py` (`X-Kill-Switch-Key`,
    `KILL_SWITCH_API_KEY`) sets Redis `kill_switch`.
  - Scope: verify the existing phone path still works and document the exact
    request a phone makes; no redesign unless broken.
  - Acceptance: a documented curl/shortcut activates the kill switch; orchestrator
    `_terminated()` honors it.
  - Deps: E11-1. Track: sequential. Labels: `backend`,`preserve-no-regress`
- **E11-5 — Kill switch halts the Node bots & world loop**
  - Context: today the kill switch stops the Python sim loop only; bots are a new
    process and must also stop.
  - Scope: the Node bridge client polls/subscribes to kill state; on active, bots
    safe-idle/disconnect within a documented window.
  - Acceptance: activating the kill switch stops all bot actions within the
    window; covered by an integration test (E4-8 harness).
  - Deps: E11-4, E4-5. Track: sequential. Labels: `area:bridge`,`minecraft`,`priority-critical`
- **E11-6 — Spend/kill alerting**
  - Context: a 24/7 system needs to tell a human before/at the cap.
  - Scope: alert (email/existing notifications in `core/notifications/`) on cap
    approach and kill activation.
  - Acceptance: crossing a configurable threshold emits an alert.
  - Deps: E11-3. Track: sequential. Labels: `backend`
- **E11-7 — Cost/kill hardening regression gate**
  - Scope: CI gate over `test_cost_tracking.py`, `test_management.py`, new
    `test_cost_governor.py`, kill-switch tests.
  - Acceptance: gate required and green.
  - Deps: E11-2..E11-6. Track: sequential. Labels: `qa`,`preserve-no-regress`

---

### EPIC 12 — Run-Mode / Starting-Conditions System

Goal: starting conditions (personas, backstories, factions, goals, seeded
memories, blank-slate, world) drive both the Python brain and the Minecraft
world + Mindcraft profiles; support persistent 24/7 and experimental modes.
E12-1 sequential; E12-2..E12-5 parallel; E12-6..E12-8 sequential.

- **E12-1 — Unified run-spec schema**
  - Context: `SimulationConfig`, `scenarios/*.yaml`, `MemorySeedConfig`,
    `scenarios/seeds/*.json`, `core/config_loader.py` already model starting
    conditions; extend (not replace) to include Minecraft world + Mindcraft profile inputs.
  - Scope: one run-spec covering: agent set, personas/backstories, factions,
    goals, memory seed, world seed/config (E2-2), and run mode (persistent vs
    experimental). Backward compatible with existing scenarios.
  - Acceptance: schema + loader; an existing scenario still loads unchanged;
    `test_public_scenarios.py`, `test_simulation_scenarios.py` green.
  - Files: `core/models.py`, `core/config_loader.py`, `core/simulation/orchestrator.py`
  - Deps: E5-5, E8-9. Track: sequential. Labels: `area:run-modes`,`backend`,`preserve-no-regress`
- **E12-2 — Backstory/persona → Mindcraft profile injection**
  - Context: personas live in `agents/<id>/system_prompt.md` + config; runs may
    override.
  - Scope: run-spec persona/backstory overrides flow into generated Mindcraft
    profiles per run, without editing committed agent files.
  - Acceptance: a run with an overridden backstory produces a profile reflecting it.
  - Deps: E12-1, E8-1. Track: parallelizable. Labels: `area:run-modes`,`minecraft`
- **E12-3 — Factions/goals as inputs in embodied runs**
  - Context: `FactionConfig` + `seed_goals` already exist in the orchestrator.
  - Scope: ensure faction membership and seeded goals apply to embodied agents
    (visible in their context/profile); preserve existing faction validation.
  - Acceptance: a faction-seeded run shows membership reflected; `test_simulation_scenarios.py`,
    faction tests green.
  - Deps: E12-1. Track: parallelizable. Labels: `area:run-modes`,`backend`,`preserve-no-regress`
- **E12-4 — Seeded vs blank-slate memory for embodied runs**
  - Context: `scenarios/seeds/blank-slate.json` + `MemorySeedApplier`. Blank-slate
    ("no backstory, see what emerges") is an explicit required mode.
  - Scope: confirm seeded, inherited, and blank-slate memory modes all work for
    embodied agents via E5-5; document the blank-slate embodied flow.
  - Doc: `docs/run-modes/blank-slate-embodied.md`
  - Acceptance: blank-slate and seeded embodied runs both start correctly;
    `test_memory_seed.py` green.
  - Deps: E12-1, E5-5. Track: parallelizable. Labels: `area:run-modes`,`preserve-no-regress`
- **E12-5 — World as an input wired to E2**
  - Context: E2-2 made world generation configurable; connect it to the run-spec.
  - Scope: run-spec world fields drive the server's world config on run start
    (fresh world for experimental; persistent world for 24/7).
  - Acceptance: an experimental run provisions a fresh world from the run-spec;
    persistent mode reuses the durable world.
  - Deps: E12-1, E2-2, E2-5. Track: parallelizable. Labels: `area:run-modes`,`minecraft`
- **E12-6 — Persistent 24/7 mode**
  - Context: long-lived world, livestreamed, indefinite — distinct from batch sims.
  - Scope: a run mode that runs indefinitely, honoring E11 rolling caps + kill
    switch, durable world, no fixed end.
  - Acceptance: a persistent run starts, survives a restart (E2-4), and is
    bounded only by caps/kill switch.
  - Deps: E12-1, E11-2, E11-5, E2-4. Track: sequential. Labels: `area:run-modes`,`backend`
- **E12-7 — Experimental short-run mode**
  - Context: tweak starting conditions, short runs, compare.
  - Scope: a run mode with a defined end (duration/goal), fresh world, full
    starting-condition overrides, results captured for comparison
    (`core/reporting/comparison.py`).
  - Acceptance: two experimental runs with different starting conditions produce
    comparable reports.
  - Deps: E12-2..E12-5, E10-4. Track: sequential. Labels: `area:run-modes`,`backend`
- **E12-8 — Run-mode docs + examples**
  - Scope: document both modes with example run-specs; add example files
    alongside `scenarios/`.
  - Acceptance: `docs/run-modes.md` + at least one example spec per mode that runs.
  - Deps: E12-6, E12-7. Track: sequential. Labels: `documentation`,`area:run-modes`

---

### EPIC 13 — Livestream Pipeline (greenfield)

Goal: capture the live Minecraft world (method per E1-R6), encode, stream to
Twitch/YouTube 24/7. Capture spike parallel after E1; full pipeline after E8.
E13-1 sequential; E13-2..E13-4 parallel; E13-5..E13-8 sequential.

- **E13-1 — Capture prototype (the E1-R6 method)**
  - Context: highest greenfield risk; de-risk early (this is the "E13 spike"
    runnable right after E1).
  - Scope: implement a throwaway prototype of the chosen capture method showing
    the live world as a video frame source. (out): streaming.
  - Acceptance: a recorded clip of the live E2 world via the chosen method;
    documented limitations.
  - Deps: E1-R6, E2-1. Track: sequential. Labels: `area:livestream`,`minecraft`
- **E13-2 — Encoder + RTMP push to Twitch/YouTube**
  - Context: committed integrations are Twitch + YouTube; no streaming code today (V9).
  - Scope: encode the capture source and push via RTMP to Twitch/YT using
    stream keys from env (extend `.env`/`CLAUDE.md` env list); test stream first.
  - Acceptance: a private/test stream is live on both platforms from the capture source.
  - Deps: E13-1. Track: parallelizable. Labels: `area:livestream`
- **E13-3 — Stream overlays (agent labels, status)**
  - Context: the old Phaser stream overlay (`frontend/src/ui/StreamOverlay.ts`)
    retires; we need an equivalent over the Minecraft capture.
  - Scope: a compositing layer (overlay window/OBS source/ffmpeg filter) showing
    agent names/status sourced from the Python brain.
  - Acceptance: overlay shows live agent status on the stream.
  - Deps: E13-1. Track: parallelizable. Labels: `area:livestream`
- **E13-4 — Audio/TTS in the stream**
  - Context: Edge TTS is a committed integration (`core/tts.py`); the old
    pipeline stitched audio post-hoc.
  - Scope: route live agent TTS into the stream audio (timed to chat that passed
    Management).
  - Acceptance: an approved utterance is heard on the stream.
  - Deps: E13-2, E8-7. Track: parallelizable. Labels: `area:livestream`
- **E13-5 — 24/7 resilience (auto-recover capture/encoder/stream)**
  - Context: streams drop; must self-heal unattended.
  - Scope: supervise capture+encoder+push; auto-restart with backoff; log gaps.
  - Acceptance: killing any component auto-recovers within a documented window;
    stream resumes.
  - Deps: E13-2, E2-4. Track: sequential. Labels: `area:livestream`,`qa`
- **E13-6 — Stream kill path tied to the kill switch**
  - Context: the kill switch must also be able to cut the public stream.
  - Scope: kill-switch-active transitions the stream to a safe state (holding
    card / cut) consistent with E11.
  - Acceptance: activating the kill switch puts the stream into the safe state.
  - Deps: E13-2, E11-5. Track: sequential. Labels: `area:livestream`,`priority-critical`
- **E13-7 — Stream health monitoring/alerting**
  - Scope: detect stream-down/black-frame/silence; alert via `core/notifications/`.
  - Acceptance: an induced outage triggers an alert.
  - Deps: E13-5. Track: sequential. Labels: `area:livestream`
- **E13-8 — Livestream ops runbook**
  - Scope: plain-language runbook: start/stop stream, rotate keys, recover, kill.
  - Acceptance: `docs/livestream/runbook.md` covers every operation.
  - Deps: E13-1..E13-7. Track: sequential. Labels: `documentation`,`area:livestream`

---

### EPIC 14 — Retire the Phaser Layer (last)

Goal: delete the retired stack — **only after** E13 + E15 prove the replacement
is live. Each deletion is its own issue so a regression can be bisected. E14-1
sequential (gate); E14-2..E14-5 parallel; E14-6/E14-7 sequential.

- **E14-1 — Retirement readiness gate**
  - Context: do not delete the only working video path until Minecraft capture +
    adapted site are demonstrably live.
  - Scope: a checklist verifying E13 (live stream) and E15 (site adapted) are
    done and in production; explicit go decision.
  - Acceptance: `docs/phaser-retirement-gate.md` all-green + sign-off.
  - Deps: E13-8, E15-7. Track: sequential. Labels: `architecture`,`needs-human-input`
- **E14-2 — Remove the Phaser frontend**
  - Scope: delete `frontend/` (Phaser engine, `world/Pathfinding.ts`,
    `WorldManager.ts`, `AgentSprite*`, `WorkspaceManager.ts`, `ChunkLoader.ts`,
    `spectator.ts`, UI overlays) and its build/CI wiring.
  - Acceptance: repo builds/tests green without `frontend/`; CI updated.
  - Deps: E14-1. Track: parallelizable. Labels: `frontend`,`architecture`
- **E14-3 — Remove tilemap/office/sprite/PixelLab pipeline**
  - Scope: delete `tools/tilemap_gen.py`, `core/world/office_generator.py`,
    `core/world/sprite_generator.py`, `core/world/pixellab_client.py`,
    `scripts/generate_office_tilemap.py`, `config/office_layout.json`,
    `config/pixellab_assets.json`, `config/pixellab_style_guide.txt`; remove
    `PIXELLAB_API_KEY` from required env (`CLAUDE.md`, `.env` docs).
  - Acceptance: no references remain; backend tests green; env docs updated.
  - Deps: E14-1, E6-5 (codegen tool already migrated off tilemap). Track: parallelizable. Labels: `backend`,`architecture`
- **E14-4 — Remove Phaser-canvas replay + its video render**
  - Scope: delete `website/src/components/replay/*` and the Playwright
    Phaser-replay render (`core/video/render_pipeline.py` and the
    `/simulations/{id}/replay` capture coupling) **only after** E15 repoints
    simulation pages at Minecraft recordings.
  - Acceptance: simulation pages no longer reference the Phaser replay;
    `tests/integration/test_video_render_e2e.py` removed/replaced; tests green.
  - Deps: E14-1, E15-4. Track: parallelizable. Labels: `frontend`,`backend`
- **E14-5 — Remove `tools/world_state.py` Redis-snapshot world API**
  - Scope: delete/replace the old Redis `world:*` snapshot tool now superseded by
    embodied perception (E6-6).
  - Acceptance: agents use perception (E6-6); no references to the old tool; tests green.
  - Deps: E14-1, E6-6. Track: parallelizable. Labels: `backend`
- **E14-6 — Purge retired-system references in docs/CLAUDE.md**
  - Scope: update `CLAUDE.md` architecture diagram + any docs that describe the
    Phaser world as current (specs are read-only — add deltas in `docs/`).
  - Acceptance: `CLAUDE.md` reflects the Minecraft architecture; no stale
    "Phaser world" claims in non-spec docs.
  - Deps: E14-2..E14-5. Track: sequential. Labels: `documentation`
- **E14-7 — Post-retirement full regression**
  - Scope: full backend + website test run + a live smoke (stream up, agents
    acting, site correct) after all deletions.
  - Acceptance: green suite + documented live smoke.
  - Deps: E14-2..E14-6. Track: sequential. Labels: `qa`

---

### EPIC 15 — Website Adaptation

Goal: world & simulation/replay pages reflect the Minecraft world and
recordings; simulation list/creator supports the new run modes. E15-1
sequential; E15-2..E15-5 parallel; E15-6/E15-7 sequential.

- **E15-1 — Inventory website coupling to the Phaser world**
  - Context: `website/src/app/world/page.tsx` uses `WorldViewer`/`AgentPositions`;
    `website/src/app/simulations/[id]/replay/` + `components/replay/*` render the
    Phaser canvas; `components/simulation/VideoPlayer.tsx` plays the old MP4.
  - Scope: an audit of every page/component that assumes the pixel-office world.
  - Acceptance: `docs/website-coupling-audit.md` lists each and the adaptation needed.
  - Deps: E8-9. Track: sequential. Labels: `frontend`,`architecture`
- **E15-2 — World page → Minecraft world view**
  - Scope: replace the pixel-art world viewer with a Minecraft world
    representation (embed the live stream player and/or world snapshots from E13).
  - Acceptance: `/world` shows the Minecraft world; no Phaser imports.
  - Deps: E15-1, E13-2. Track: parallelizable. Labels: `frontend`,`area:livestream`
- **E15-3 — Live page embeds the Minecraft stream**
  - Context: `website/src/app/simulations/live/page.tsx`.
  - Scope: embed the Twitch/YT player from E13 on the live page.
  - Acceptance: the live page plays the running stream.
  - Deps: E15-1, E13-2. Track: parallelizable. Labels: `frontend`,`area:livestream`
- **E15-4 — Simulation/replay pages → Minecraft recordings**
  - Context: replay pages render Phaser; must point at Minecraft recordings
    instead (gates E14-4).
  - Scope: replace replay rendering with a recorded-video player fed by E13
    captures; preserve the rest of the simulation detail tabs
    (`components/simulation/*`).
  - Acceptance: a simulation page shows its Minecraft recording; non-replay tabs
    unchanged; website tests green.
  - Deps: E15-1, E13-1. Track: parallelizable. Labels: `frontend`
- **E15-5 — Simulation creator/list support new run modes**
  - Context: `website/src/app/simulations/new/`, `scenarios/page.tsx`,
    `components/simulationCreator/*` create runs; must expose the E12 run-spec
    (mode, world seed, backstory/faction/memory overrides).
  - Scope: extend the creator UI + submission to the unified run-spec; preserve
    existing public-submission validation.
  - Acceptance: a user can create both a persistent and an experimental run from
    the site; `test_public_scenarios.py` green.
  - Deps: E15-1, E12-1. Track: parallelizable. Labels: `frontend`,`area:run-modes`
- **E15-6 — Website regression + visual check**
  - Scope: run website Vitest + Playwright E2E; fix breakage from the world swap.
  - Acceptance: `website` test + E2E suites green.
  - Deps: E15-2..E15-5. Track: sequential. Labels: `qa`,`frontend`
- **E15-7 — Website adaptation acceptance**
  - Scope: documented walkthrough that `/world`, `/simulations`, live, and
    creator all reflect Minecraft; gates E14.
  - Acceptance: `docs/website-adaptation-report.md` + sign-off.
  - Deps: E15-6. Track: sequential. Labels: `frontend`,`needs-human-input`

---

### EPIC 16 — Pluggable Memory Backend + Memory Eval Harness (#659)

Goal: swap recall/archival storage behind the E5-8 seam; dogfood Answer Engine;
add a substrate-agnostic memory eval harness. `default`-backend behavior is
preserve-no-regress. Off the critical path. E16-1..E16-3 sequential; E16-4..E16-6
parallel; E16-7..E16-9 sequential. Filed: E16-1 #660, E16-2 #662, E16-3 #665,
E16-4 #663, E16-5 #664, E16-6 #661, E16-7 #666, E16-8 #667, E16-9 #668.

- **E16-1 — Recall/Archival backend provider abstraction** (#660)
  - Context: E5-8 (#658) defines the protocol; E16-1 turns it into a provider
    registry with a `default` (in-process Postgres/pgvector) provider that is
    byte-for-byte current behavior, selected by config.
  - Scope (in): provider registry + `default` provider + config switch.
    (out): non-default providers, Core memory.
  - Acceptance: memory regression suite green on `default`; switching providers
    is a config change touching zero callers.
  - Deps: E5-8 (#658). Track: sequential. Labels: `backend`,`preserve-no-regress`
- **E16-2 — Answer Engine adapter: recall + archival** (#662)
  - Context: dogfood `../answer-engine` as durable recall/archival store.
  - Scope (in): `core/memory/backends/answer_engine.py` mapping recall and
    archival onto Answer Engine REST/MCP; namespace by `simulation_id`+`agent_id`;
    1536-dim parity check. (out): graph/edges (E16-4), Core memory, eval (E16-6).
  - Acceptance: recall write→search and transcript store→fetch via the
    `answer_engine` backend return results equivalent to `default`.
  - Deps: E16-1 (#660). Track: sequential. Labels: `backend`,`area:bridge`
- **E16-3 — Embedding ownership boundary + Answer Engine validation path** (#665)
  - Context: Answer Engine owns embedding for the `answer_engine` backend
    (decision recorded); the deterministic/LM Studio bar stays on `default`.
  - Scope (in): let Answer Engine embed; document the boundary and that the
    `answer_engine` path is validated against a live Answer Engine instance;
    feed the E16-9 ADR. (out): precomputed-vector passthrough.
  - Acceptance: recall round-trip via `answer_engine` against a live instance;
    boundary documented.
  - Deps: E16-2 (#662). Track: sequential. Labels: `backend`,`documentation`
- **E16-4 — Typed memory-edge / graph layer** (#663)
  - Context: net-new (neither repo has typed edges/traversal); enables graph
    recall and the harness's edge metrics.
  - Scope (in): edges (ENTITY_LINK, TEMPORAL_NEXT, SUPERSEDES, DERIVED_FROM,
    CONTRADICTS) + 1-hop traversal boost, behind a flag default off; home
    decided in the E16-9 ADR. (out): multi-hop beyond depth 1 (follow-up).
  - Acceptance: a SUPERSEDES edge measurably reorders a recall result with the
    flag on; flag off → regression suite unchanged.
  - Deps: E16-1 (#660). Track: parallelizable. Labels: `backend`,`eval-finding`
- **E16-5 — Write-time decision capture on the compaction path** (#664)
  - Context: `core/memory/compaction.py` already decides what to store; capture
    the decision as a trace so the harness can score it.
  - Scope (in): record `{should_store, granularity, entities, proposed_edges,
    reason}` per decision; no change to what is stored unless a flag flips.
    (out): the judges (E16-6).
  - Acceptance: a run emits a decision trace per compaction; compaction tests
    green.
  - Deps: E16-1 (#660). Track: parallelizable. Labels: `backend`,`eval-finding`
- **E16-6 — Standalone eval harness + MemoryBackend protocol** (#661)
  - Context: the Alpha-Recall IP — substrate-agnostic write/retrieval eval. Own
    public repo `github.com/bradtaylorsf/alpha-recall`; ships a SQLite toy
    backend for the portfolio demo.
  - Scope (in): write-time judge (storage P/R, granularity, entity F1, edge
    P/R), retrieval-time judge (recall@k, precision@k, LLM utility,
    counterfactual delta), benchmark runner, fixtures, report, `MemoryBackend`
    protocol. (out): livestreamtoagi wiring (E16-7).
  - Acceptance: `alpha-recall benchmark --suite all` runs clean with non-zero
    metrics and a real failures section; judge mockable without an API key.
  - Deps: —. Track: parallelizable. Labels: `eval-finding`
- **E16-7 — livestreamtoagi adapter for the eval harness (dogfood)** (#666)
  - Context: run the *same* loops on real simulation traffic.
  - Scope (in): adapter implementing the harness `MemoryBackend` protocol
    against the memory facade (`default` or `answer_engine`) + the E16-5
    decision traces. (out): new memory semantics.
  - Acceptance: the harness scores write-time and retrieval-time metrics on a
    real local run's memory.
  - Deps: E16-1 (#660), E16-5 (#664), E16-6 (#661). Track: sequential.
    Labels: `backend`,`eval-finding`
- **E16-8 — Eval-harness reporting + CI smoke integration** (#667)
  - Context: make memory eval part of normal run reporting (cross-ref E10-4).
  - Scope (in): surface harness output in `core/reporting/` scorecard; CI smoke
    with deterministic embeddings + mocked judge. (out): production tracing.
  - Acceptance: a scorecard includes write/retrieval eval fields; CI smoke green
    without network or API keys.
  - Deps: E16-6 (#661), E16-7 (#666). Track: sequential. Labels: `qa`,`eval-finding`
- **E16-9 — Backend parity + latency gate, ADR, docs** (#668)
  - Context: lock in equivalence and cost-of-indirection.
  - Scope (in): parity test (`default` vs `answer_engine` over the memory
    regression suite); latency comparison vs the E5-7 baseline with a budget;
    ADR `docs/decisions/00NN-pluggable-memory-backend.md`; companion doc.
    (out): perf tuning beyond the budget (follow-up).
  - Acceptance: parity test required + green (or documented divergences);
    latency report within budget or follow-up filed; ADR merged.
  - Deps: E16-2 (#662), E16-3 (#665), E16-4 (#663). Track: sequential.
    Labels: `qa`,`documentation`

---

## 6. Cross-cutting "preserve — do not regress" register

Any issue labelled `preserve-no-regress` must keep these green (run via
`make test-backend` / `pytest tests/backend/`):

| Preserved system | Code | Guarding tests |
|---|---|---|
| Per-agent multi-model routing | `core/llm_client.py`, `core/agent_registry.py`, `agents/*/config.yaml` | `test_llm_client.py`, `test_model_versions.py`, `test_cost_tracking.py` |
| 3-tier memory | `core/memory/*`, `core/repos/memory_repo.py` | `test_core_memory*.py`, `test_recall_memory.py`, `test_archival_memory.py`, `test_cross_conversation_memory.py`, `test_memory_tools.py`, `test_memory_snapshot.py` |
| Memory seeding / scenarios | `core/memory/memory_seed.py`, `scenarios/seeds/*` | `test_memory_seed.py`, `test_public_scenarios.py`, `test_simulation_scenarios.py` |
| Dreams / journals / reflection | `core/memory/dreams.py`, `core/memory/reflection*.py`, `core/blog.py` | `test_dreams.py`, `test_reflection*.py`, `test_reflection_goals.py`, `test_reflect_after.py` |
| Management filter (out-of-band) | `core/management.py`, `agents/management/content_rules.yaml` | `test_management.py` |
| Cost controls / kill switch | `core/llm_client.py`, `core/simulation/orchestrator.py`, `core/admin/kill_switch_routes.py` | `test_cost_tracking.py` (+ new `test_cost_governor.py`) |
| Eval & reporting | `core/eval/*`, `core/reporting/*` | `test_eval_engine.py`, `test_eval_categories.py`, `test_agency_eval.py`, `test_eval_analyzer.py` |

---

## 7. GitHub tracker status

The Phase-3 issue creation pass is complete:

1. Labels were created.
2. Epic issues were created as `#503`-`#517`.
3. Child issues were created as `#518`-`#630`.
4. E1 research decisions were posted back to the relevant E1 issues for
   historical traceability.
5. Future epic parents and the first unblocked starter issues should reference
   `docs/decisions/0000-summary.md` instead of duplicating the entire decision
   payload.
