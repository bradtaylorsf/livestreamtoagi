# Multi-Agent Stability Soak

Issue: #579 E8-8 - Multi-agent stability soak (hours)  
Epic: #510 E8 - All Agents Embodied + Decentralized Conversation  
Prepared: 2026-05-20 PDT  
Scope: BridgeBot plus Alpha, Vera, Rex, Aurora, Pixel, Fork, Sentinel, and Grok

## Decision

Status: **PARTIAL LIVE STARTUP SMOKE in this Codex run; NO-GO for E8-9 until a
full multi-hour LM Studio soak is rerun and appended here.**

The operator entrypoint now exists at `scripts/minecraft/soak.sh` and is wired
for a multi-hour local run using LM Studio, the existing bot launchers, the
Minecraft health probe, backend health, log capture, and the `cost_events`
ledger. If the local Paper server is down, the soak runner starts
`scripts/minecraft/supervise.sh` and waits for `scripts/minecraft/health.sh`
to pass before launching bots.

Post-loop manual review found and fixed a live startup blocker: every isolated
bot launch was trying to bind the default MindServer port `8080`. The soak
runner now assigns unique `MINDSERVER_PORT` values from
`SOAK_MINDSERVER_BASE_PORT` upward. A short 0.02-hour live startup smoke then
launched BridgeBot plus all eight agents and completed without unrecovered bot
exits. This proves startup wiring, not the required multi-hour acceptance gate.

Default validation remains local-only and does not require OpenRouter spend.
OpenRouter can be enabled only for builder-plan JSON generation with explicit
caps, described below.

## What The Soak Runs

The soak starts one process for each committed Mindcraft launcher:

| Bot | Launcher | Cost agent |
| --- | --- | --- |
| BridgeBot | `scripts/minecraft/connect-bridge-bot.sh` | n/a |
| Alpha | `scripts/minecraft/connect-alpha-bot.sh` | `alpha` |
| Vera | `scripts/minecraft/connect-vera-bot.sh` | `vera` |
| Rex | `scripts/minecraft/connect-rex-bot.sh` | `rex` |
| Aurora | `scripts/minecraft/connect-aurora-bot.sh` | `aurora` |
| Pixel | `scripts/minecraft/connect-pixel-bot.sh` | `pixel` |
| Fork | `scripts/minecraft/connect-fork-bot.sh` | `fork` |
| Sentinel | `scripts/minecraft/connect-sentinel-bot.sh` | `sentinel` |
| Grok | `scripts/minecraft/connect-grok-bot.sh` | `grok` |

Each bot gets an isolated local clone of the pinned Mindcraft checkout, with
`node_modules` symlinked from the base `./mindcraft` install. That prevents the
single-bot staging scripts from racing over `settings.js`, profile JSON, or
patched action files while still reusing the reviewed launchers. These clones
are created outside the repository by default so `pnpm dev` / uvicorn reload
watchers do not restart the backend when the soak prepares bot worktrees. The
evidence directory records their location in `worktrees.path`; set
`SOAK_KEEP_WORKTREES=1` to inspect them after a run.

## Pre-Flight Checklist

Run from the repository root:

```bash
bash scripts/check-services.sh
pnpm llm:local --list-only
scripts/minecraft/health.sh --json
curl -fsS http://127.0.0.1:8010/api/health
```

For the Minecraft service gate, the soak uses the same probe documented in
the health runbook:

```bash
CHECK_MINECRAFT=1 bash scripts/check-services.sh
```

Required runtime state:

| Requirement | Expected |
| --- | --- |
| Node | Node 20 LTS |
| Java | Java 21 for Paper |
| Mindcraft | `./mindcraft` at `35be480b4cc0bca990278e6103a1426392559d96` with `node_modules/` installed |
| Paper | `scripts/minecraft/health.sh --json` returns `"up":true`; if down, `soak.sh` starts `scripts/minecraft/supervise.sh` by default. |
| Backend | `core.main:app` reachable on `http://127.0.0.1:8010/api/health` |
| Bridge auth | `MINECRAFT_BRIDGE_TOKEN` exported and matching the backend |
| LM Studio | OpenAI-compatible server reachable at `http://localhost:1234/v1` |

## Live Soak Command

Use local models only:

```bash
export LLM_PROVIDER=lmstudio
export LOCAL_LLM_BASE_URL=http://localhost:1234/v1
export LOCAL_LLM_MODEL=<model-id-from-LM-Studio>
export LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id-if-available>
export EMBEDDING_PROVIDER=deterministic
export CONVERSATION_MODE=embodied
export MINECRAFT_BRIDGE_TOKEN=<same-secret-as-backend>

scripts/minecraft/soak.sh --duration-hours 2 --log-dir logs/soak
```

By default the soak starts `scripts/minecraft/lmstudio_queue_proxy.py` and
points `LOCAL_LLM_BASE_URL` at the proxy, while
`LOCAL_LLM_UPSTREAM_URL` keeps the real LM Studio endpoint. Set
`MINECRAFT_LLM_QUEUE_PROXY=0` to bypass it, or raise
`MINECRAFT_LLM_CONCURRENCY` from `1` to `2` for a slightly wider local queue.

If you want the soak to fail instead of auto-starting Paper:

```bash
SOAK_START_MINECRAFT_IF_DOWN=0 scripts/minecraft/soak.sh --duration-hours 2
```

Package aliases:

```bash
pnpm mc:sim:smoke
pnpm mc:sim:soak
pnpm mc:sim -- --duration-hours 0.5 --log-dir logs/soak
pnpm mc:soak -- --duration-hours 2 --log-dir logs/soak
pnpm verify:minecraft-soak
```

`pnpm mc:sim*` loads the same repo `.env` used by `pnpm dev`, adds the common
local Java 21 / Node 20 Homebrew paths on macOS, then delegates to
`scripts/minecraft/soak.sh`. Use it for the normal local operator flow: start
`pnpm dev`, then run the desired Minecraft sim command in a second terminal.
By default the local sim uses an isolated easy-mode Paper server at
`127.0.0.1:25566`, with files in `minecraft-server-easy/` and world-generation
inputs from `scripts/minecraft/world-easy.config`. This avoids disturbing the
normal `minecraft-server/` world on `25565`. `SOAK_EASY_SPAWN=1` runs
`scripts/minecraft/setup-easy-spawn.mjs` before and after bot launch: it writes
access files for a temporary op setup bot, sets peaceful/daylight rules, creates
a flat grass starter meadow with visible resource piles and work blocks, resets
the above-ground build volume plus the top soil layers, then teleports online
bots onto a cleared staging strip with separated spawn offsets and a small
starter kit. The easy arena also pins spawn radius to zero, disables
drowning/fall/freeze damage for local validation, and wraps the starter meadow
in a glass boundary so agents have a small safe place to learn before exploring.
Set `MC_SIM_EASY_MODE=0` to use the normal Minecraft target instead, or set
`MC_SIM_MC_PORT=<port>` if `25566` is busy. In easy mode,
`MC_SIM_KEEP_SERVER_RUNNING=1` by default so the Paper
server remains available after the timed bot run for manual inspection; set it
to `0` when you want the runner to stop its auto-started server. Local sims
also choose a high run-specific MindServer base port by default to avoid stale
`8080+` listeners from previous experiments; set
`MC_SIM_MINDSERVER_BASE_PORT=<port>` if you need a fixed range.
The sim wrapper defaults to the real character cast only:
Alpha, Vera, Rex, Aurora, Pixel, Fork, Sentinel, and Grok. BridgeBot is excluded
unless `MC_SIM_INCLUDE_BRIDGE_BOT=1` is set, because it is a technical bridge
test bot rather than a character. The wrapper also sets
`SOAK_BLOCK_PRIVATE_CONVERSATIONS=1` by default so isolated MindServer launches
do not use Mindcraft's private `!startConversation`/`!endConversation` channel;
the characters coordinate through ordinary public Minecraft chat and visible
actions instead. It also blocks slow startup code-generation via `!newAction`,
the noisy local `!observe` action, generated plan building, and code execution
by default, while leaving simple `!place`, `!placeHere`, and `!break` available
so the agents can make visible camp markers during short runs. In this local
public-chat mode the wrapper also hides command syntax from in-game chat, so one
character's command does not get rebroadcast as a forced command for every other
isolated MindServer instance. Set `MC_SIM_BUILD_MODE=plan` to unblock
`!buildFromPlan` / `!planAndBuild` for builder-model plan execution while
keeping arbitrary `!executeCode` blocked by
`MC_SIM_BLOCK_EXECUTE_CODE_ACTIONS=1`. Low-level bridge action result chatter is
suppressed by default with `MC_SIM_SUPPRESS_ACTION_CHAT=1`; the action still
logs to each bot log and still reports over the Python bridge, but it does not
interrupt the other local models mid-turn. Safe terrain behavior is also on by
default: `MC_SIM_SAFE_TERRAIN_ACTIONS=1` sets
`SOAK_SAFE_TERRAIN_ACTIONS=1` and `MINECRAFT_ALLOW_DESTRUCTIVE_PATHS=0`, which
disables automatic elbow-room/item-pickup/torch modes in the disposable
Mindcraft clones and refuses pathfinder routes that require digging or
one-block towers. Set `MC_SIM_ALLOW_NEW_ACTION=1` only when you deliberately
want the local model to spend extra time synthesizing custom action code.

## Multi-Agent Runtime Queues

The staged Mindcraft overlay now treats each character as a queued actor:

| Layer | Behavior | Evidence |
| --- | --- | --- |
| Per-agent inbox | `handleMessage` appends incoming chat to a pending inbox, debounces for `MINECRAFT_TURN_DEBOUNCE_MS` (default `2000`), batches recent messages, and saves messages that arrive during generation for the next turn. Lifecycle chatter such as `I'm stuck` stays telemetry-only. | `inbox.queued`, `inbox.turn_started`, `inbox.turn_completed`, `inbox.telemetry_ignored`, `inbox.immediate_command`. |
| Director V2 gate | When `CONVERSATION_MODE=director_v2`, each compacted inbox batch calls `director.gate` before Mindcraft can enqueue `shouldRespond`. Selected agents receive scene context and affordances; unselected agents resolve the inbox turn without an LLM call. | `director_gate.selected`, `director_gate.suppressed`, `director_gate.stale_discarded`. |
| LM Studio queue | `lmstudio_queue_proxy.py` serializes OpenAI-compatible requests to LM Studio with `MINECRAFT_LLM_CONCURRENCY` workers and emits wait/latency telemetry. | `timeline-raw/llm-queue.ndjson`, plus `llm.queue.enqueued`, `llm.queue.started`, `llm.queue.completed`, `llm.queue.failed`. |
| Per-agent action queue | `ActionManager._executeAction` keeps one active action slot per agent. New embodied actions are queued instead of interrupting `placeHere`, `move`, or plan builds; queue overflow emits a busy rejection. | `action.queued`, `action.started`, `action.completed`, `action.rejected_busy`. |

Useful knobs:

| Env var | Default | Meaning |
| --- | --- | --- |
| `MINECRAFT_TURN_DEBOUNCE_MS` | `2000` | Inbox debounce before one batched conversation turn. |
| `MINECRAFT_TURN_BATCH_MAX` | `12` | Max inbox messages sent to one prompt. |
| `CONVERSATION_MODE` | `embodied` | `embodied` preserves the #510 decentralized prompt mode; `director_v2` enables Director V2 prompt gating. |
| `DIRECTOR_V2_GATE` | `0` | Automatically set to `1` by the wrappers when `CONVERSATION_MODE=director_v2`. |
| `MINECRAFT_ACTION_QUEUE_MAX` | `16` | Max deferred embodied actions per agent. |
| `MINECRAFT_LLM_QUEUE_PROXY` | `1` | Start the local FIFO proxy and route bot LLM traffic through it. |
| `MINECRAFT_LLM_CONCURRENCY` | `1` | Active upstream LM Studio requests allowed by the proxy. |
| `LOCAL_LLM_UPSTREAM_URL` | `$LOCAL_LLM_BASE_URL` | Real LM Studio upstream when the proxy is enabled. |

## Builder-Plan Mode

Plan mode is for visible shared construction instead of one-block-at-a-time
chat loops:

```bash
MC_SIM_BUILD_MODE=plan pnpm mc:sim:smoke
```

In this mode the local wrapper lets agents call
`!planAndBuild("small shared cabin")`. By default the action asks the profile
`code_model` (the `LOCAL_LLM_MODEL_BUILDING` tier) for strict JSON, validates
allowed materials, bounds, and max steps, logs the plan as JSON evidence, and
executes it through the verified `!buildFromPlan` path. Invalid local model
plans are rejected and replaced with a starter blueprint such as marker camp,
3x3 hut, simple wall, or torch-lit storage corner.

OpenRouter builder routing is opt-in and applies only to this
`purpose=plan_generation` path:

```bash
MC_SIM_BUILD_MODE=plan \
MC_SIM_BUILDER_PROVIDER=openrouter \
MC_SIM_BUILDER_OPENROUTER_MODEL=<openrouter-model-id> \
MC_SIM_BUILDER_OPENROUTER_API_KEY=<key> \
MC_SIM_BUILDER_MAX_CALLS_PER_RUN=12 \
MC_SIM_BUILDER_MAX_CALLS_PER_AGENT=3 \
pnpm mc:sim:smoke
```

Normal chat completions and ordinary action selection still use the local LM
Studio model. `MC_SIM_BUILDER_FALLBACK=fail` is the default and fails preflight
when OpenRouter provider/model configuration is missing. Set
`MC_SIM_BUILDER_FALLBACK=local` to keep plan generation on the local
`code_model` when OpenRouter is unavailable. `MC_SIM_BUILDER_MAX_USD_PER_RUN`
is optional; estimated USD uses `MC_SIM_BUILDER_USD_PER_1K_INPUT` and
`MC_SIM_BUILDER_USD_PER_1K_OUTPUT` when provided.

Director V2 treats `!planAndBuild` as a scheduled macro, not a normal tool that
every character may invoke independently. One scene has one build-plan owner;
the owner receives `!planAndBuild`, while nearby non-owners receive normal
support roles such as gathering, clearing, guarding, or conversation support.
The Node governor mirrors that scene lock so stale direct commands are skipped
with `reason=scene_locked` before any provider call.

The build governor runs before any provider call. Each agent may have one
active build at a time, each scene may have one active plan owner, equivalent
completed builds are cooled down for `MC_SIM_BUILD_COOLDOWN_SEC` seconds, and
cached plans are reused without a new builder-model call. Defaults:

| Env var | Default | Meaning |
| --- | --- | --- |
| `MC_SIM_BUILD_MAX_PER_AGENT` | `6` | Max non-cached plan generations per agent. |
| `MC_SIM_BUILD_COOLDOWN_SEC` | `300` | Cooldown for equivalent completed build requests. |
| `MC_SIM_BUILD_ZONE_STRIDE` | `12` | Deterministic per-agent origin offset so plans do not all occupy the same blocks. |
| `MC_SIM_BUILD_CACHE_TTL_SEC` | `3600` | Time to keep validated plans in the per-agent cache. |

Plan evidence appears as `build_plan.generation.*` and
`build_plan.execution.*` events. `scene_id`, build-plan id, owner,
provider/model, paid/local request counts, token usage, estimated USD,
`fallback_reason`, execution result, and parsed verified block counts are
included in `timeline.ndjson`, `timeline-totals.json`, `summary.txt`, and
`monitor.html`. `build_plan.generation.skipped` records `scene_locked`,
`active_build_exists`, `cache_hit`, `cooldown`, and `per_agent_cap` outcomes.
`!executeCode` remains separately gated by
`SOAK_BLOCK_EXECUTE_CODE_ACTIONS` / `MC_SIM_BLOCK_EXECUTE_CODE_ACTIONS`.

Local-only builder smoke:

```bash
SOAK_BUILDER_PROVIDER=local \
MC_SIM_BUILD_MODE=plan \
scripts/minecraft/soak.sh --dry-run
```

OpenRouter builder smoke, using exactly one paid builder-plan request during
preflight:

```bash
SOAK_BUILDER_PROVIDER=openrouter \
MC_SIM_BUILD_MODE=plan \
MC_SIM_BUILDER_PROVIDER=openrouter \
MC_SIM_BUILDER_OPENROUTER_MODEL=<openrouter-model-id> \
MC_SIM_BUILDER_OPENROUTER_API_KEY=<key> \
MC_SIM_BUILDER_MAX_CALLS_PER_RUN=1 \
MC_SIM_BUILDER_MAX_CALLS_PER_AGENT=1 \
scripts/minecraft/soak.sh --dry-run
```

## Action-Command Reliability Gate

The soak now runs `scripts/minecraft/analyze_action_reliability.py` after the
timed bot loop. This is the E8-10 gate that checks whether local LM Studio
intent becomes parsed, executed, and verified Minecraft action. It writes
`action-reliability.json` and `action-reliability.md` into the evidence
directory, appends an `Action-command reliability` block to `summary.txt`, and
fails the soak by default when an agent with enough intended action events falls
below threshold.

Methodology, caveats, and the issue/PR evidence template live in
[`action-command-reliability.md`](action-command-reliability.md).

Configuration:

| Env var | Default | Meaning |
| --- | --- | --- |
| `SOAK_MIN_INTENT_TO_COMMAND_RATIO` | `0.6` | Minimum commands emitted per intended-action utterance. |
| `SOAK_MIN_PARSE_SUCCESS` | `0.8` | Minimum parse success rate after local-model output. |
| `SOAK_MIN_EXECUTION_RATE` | `0.7` | Minimum emitted-command execution rate. |
| `SOAK_MIN_VERIFIED_SUCCESS` | `0.5` | Minimum execution successes with world-state corroboration. |
| `SOAK_RELIABILITY_MIN_INTENTS` | `5` | Only enforce thresholds for agents with this many intended action events. |
| `SOAK_RELIABILITY_FAIL_ON_VIOLATION` | `1` | Exit nonzero when threshold violations are present. |
| `MC_SIM_MIN_INTENT_TO_COMMAND_RATIO` | unset | Wrapper override forwarded to `SOAK_MIN_INTENT_TO_COMMAND_RATIO` when the soak var is unset. |
| `MC_SIM_MIN_PARSE_SUCCESS` | unset | Wrapper override forwarded to `SOAK_MIN_PARSE_SUCCESS` when the soak var is unset. |
| `MC_SIM_MIN_EXECUTION_RATE` | unset | Wrapper override forwarded to `SOAK_MIN_EXECUTION_RATE` when the soak var is unset. |
| `MC_SIM_MIN_VERIFIED_SUCCESS` | unset | Wrapper override forwarded to `SOAK_MIN_VERIFIED_SUCCESS` when the soak var is unset. |

## Behavioral Acceptance Gate

E8 acceptance cannot be marked complete from process health alone. The soak
runner writes `behavior.tsv` and appends a `Behavioral acceptance` block to
`summary.txt` before making the final decision. The gate is log-derived and
best-effort: if the logs do not prove collaborative embodied behavior, the run
is a NO-GO until the cohort report explains the deviation.

Per-agent counters are parsed from `logs/soak/<timestamp>/bots/<agent>.log`
plus agent-tagged bridge/server logs:

| Counter | Parsed evidence |
| --- | --- |
| `spawn_safe` | A spawn/login line with no `died`, `death`, `respawn`, or drowning line in the next roughly 30 log lines. |
| `movement` | Direct movement/search commands such as `!move`, `!goToPlayer`, `!goToCoordinates`, `!searchForBlock`, `!searchForEntity`, or `!navigate`. |
| `public_chat` | Public chat emits like `<Agent> message`, `Agent: message`, or `chat ... msg=...`, excluding `[action]`, management review lines, and command-only messages. |
| `inter_agent_chat` | Public chat lines that mention another tracked agent by name. |
| `gather` | Gather/equipment commands such as `!collectBlocks`, `!collectAllBlocks`, `!consume`, `!equip`, or `!smeltItem`. |
| `build` | Build/place commands such as `!place`, `!placeHere`, `!placeBlock`, `!build`, `!buildFromPlan`, or `!planAndBuild`. |
| `deaths` / `drownings` | Death, respawn, and drowning terms in the agent log stream. |
| `stuck` / `dig_holes` | Stuck, path-failure, unreachable, trapped, or hole-digging phrases. |
| `restart_count` | Recoverability-risk signatures such as `Exiting.`, nonzero process exits, reconnect/rejoin lines, bot disconnects, or supervisor restarts. |
| `shared_artifact_count` | Cohort-wide shared-work evidence from shared/together camp-marker-wall-chest-shelter-fire language, nearby place coordinates by multiple agents, or at least two distinct agents emitting place/build commands. |

The default behavioral thresholds are env-overridable:

| Env var | Default | Gate |
| --- | ---: | --- |
| `SOAK_MIN_MOVEMENT_PER_AGENT` | `5` | Every tracked agent must meet or exceed this movement count. |
| `SOAK_MAX_DEATHS_PER_AGENT` | `2` | Any agent above this death/respawn count fails. |
| `SOAK_MAX_STUCK_PER_AGENT` | `5` | Any agent above this stuck/path-failure count fails. |
| `SOAK_MAX_RESTARTS_PER_AGENT` | `1` | Any agent above this restart/disconnect/exit signature count fails. |
| `SOAK_MIN_PUBLIC_CHAT_COHORT` | `10` | The cohort must emit at least this many public chat lines. |
| `SOAK_MIN_GATHER_OR_BUILD_COHORT` | `3` | Gather plus build attempts across the cohort must meet this count. |
| `SOAK_MIN_SHARED_ARTIFACTS` | `1` | The run must show at least one visible shared improvement or shared work artifact. |
| `SOAK_REQUIRE_BEHAVIOR_GATE` | `1` | When `1`, an unmet behavioral threshold exits the soak with status 1. |

Decision rule: any unmet per-agent or cohort threshold is a NO-GO regardless
of stability, cost, process-health, or action-reliability results.
`SOAK_REQUIRE_BEHAVIOR_GATE=0` is only an operator override for collecting a
soft-pass evidence bundle; the `summary.txt` block still records
`behavior_gate_status=fail`, and `docs/minecraft/cohort-report.md` must explain
why the deviation was accepted.

`behavior.tsv` also includes `restart_count` per agent. The parser counts
recoverability-risk signatures such as `Exiting.`, `process exited with code
1`, `rejoining`, `bot disconnected`, and supervisor restart lines. Two restart
signatures for the same agent within 300 seconds always fail the gate, even if
`SOAK_MAX_RESTARTS_PER_AGENT` is raised for exploratory runs. Totals are written
as `total_restarts` and `total_restart_recurrences` in
`behavior-totals.env` and the summary.

## Structured Timeline

Every embodied soak exports a canonical timeline after the reliability and
behavior gates run. The exporter writes `timeline.ndjson` and
`timeline-totals.json` under the evidence directory and appends a `Timeline`
block to `summary.txt` with totals by event type, agent, model, and token
source.

The timeline normalizes:

| Source | Timeline coverage |
| --- | --- |
| `bots/*.log` | Mindcraft chat, accepted command intents, grouped `Agent executed:` results, parser errors, behavior/status telemetry, lifecycle, and sampled position. |
| `logs/*.log` | Paper public chat, bridge `bridge_event` / `bridge_inbound_event` telemetry, server errors. |
| `timeline-raw/*.ndjson` | Best-effort Node events from the staged timeline emitter and LM Studio usage shim. |
| `*lmstudio*.ndjson` | Explicit LM Studio request/response traces when an operator captures them separately. |

LLM events include model, purpose/reason, latency, prompt tokens, completion
tokens, total tokens, outcome, and whether usage is provider-reported or a
deterministic local estimate. High-frequency position logs are collapsed into
interval `state.sample` events; low-level pathfinding chatter is not treated as
an LLM decision.

Queue proxy events are timeline evidence but are not token-spend events. Token
totals count `llm.request` / `llm.response`; queue events report wait time,
active request count, upstream latency, status, and provider token metadata when
LM Studio returns it.

Stale command-bearing generations are exported as `llm.response` events with
`outcome=discarded_stale` and `discarded_commands`; they do not create
`action.intent` events. Bridge action-result settle lines are exported as
`bridge.action.*` telemetry so the executed-action count remains aligned to
grouped bot execution blocks.

Schema details and payload examples live in
[`timeline-schema.md`](timeline-schema.md).

## Heartbeat & Idle Recovery

Embodied bot launchers stage `scripts/minecraft/fork-src/agent/skills/heartbeat.js`
and patch Mindcraft `agent.js` to call `installHeartbeat(this)` when bot events
start. The heartbeat is bounded and coarse: it asks for one high-level visible
next action after an idle/stall window, not per-tick movement.

Configuration:

| Env var | Default | Meaning |
| --- | --- | --- |
| `MC_HEARTBEAT_ENABLED` | `1` | Set `0`/`false`/`off` to disable autonomous prompts. |
| `MC_HEARTBEAT_TICK_MS` | `5000` | How often the heartbeat checks each agent. |
| `MC_HEARTBEAT_IDLE_MS` | `90000` | Idle window before a next-action prompt can fire. |
| `MC_HEARTBEAT_COOLDOWN_MS` | `45000` | Minimum time between heartbeat prompts for one agent. |
| `MC_HEARTBEAT_STALE_ACTION_MS` | `180000` | Active action age that permits a stale-action heartbeat. |
| `MC_HEARTBEAT_MAX_NO_COMMAND` | `3` | Consecutive blank/no-command heartbeat outcomes before halt. |

`scripts/minecraft/run-local-sim.sh` exposes the same knobs as seconds-based
`.env` values: `MC_SIM_HEARTBEAT_ENABLED`, `MC_SIM_HEARTBEAT_TICK_SEC`,
`MC_SIM_HEARTBEAT_IDLE_SEC`, `MC_SIM_HEARTBEAT_COOLDOWN_SEC`,
`MC_SIM_HEARTBEAT_STALE_ACTION_SEC`, and
`MC_SIM_HEARTBEAT_MAX_NO_COMMAND`.

Expected timeline events:

| Event | When it appears |
| --- | --- |
| `heartbeat.fired` | Idle/stale threshold and cooldown allow a prompt. |
| `heartbeat.skipped` | Prompt was suppressed because the heartbeat is disabled, cooling down, or the agent is still in an active non-stale action. |
| `heartbeat.outcome` | A fired prompt finished, with command/no-command detection and response excerpt. |
| `heartbeat.halted` | Repeated blank/no-command outcomes hit `MC_HEARTBEAT_MAX_NO_COMMAND`. |

`heartbeat.halted` is a failure condition. `soak.sh` records it in
`heartbeat-halts.tsv`, stops the affected bot process for supervisor visibility,
counts the line in restart/stability checks, and fails the soak. The summary also
prints `heartbeat_counts` from `timeline-totals.json`.

## Live Cohort Monitor

Every embodied soak also renders `monitor.html` in the evidence directory after
the timeline export. Open it locally for a cohort-level view of run status, the
LLM-to-action pipeline, per-agent latest chat/action/LLM activity, idle time,
restart count, errors, tokens, queue depths, build-plan progress, warning
badges, and recent feeds:

```bash
open logs/soak/<UTC timestamp>/monitor.html
```

For an in-progress run, serve a periodically refreshed local view on loopback:

```bash
python3 scripts/minecraft/serve_monitor.py --run-dir logs/soak/<UTC timestamp>
```

The server binds to `127.0.0.1` by default. Full usage, thresholds, and filter
details live in [`cohort-monitor.md`](cohort-monitor.md).

Outputs are written to `logs/soak/<UTC timestamp>/`:

| File | Contents |
| --- | --- |
| `metadata.env` | Start/end plan, host info, git head, model ids, bridge URL, cost cap. |
| `worktrees.path` | Temp directory containing disposable Mindcraft clones, when kept. |
| `preflight/` | Raw pre-flight command output. |
| `bots/<bot>.log` | Per-bot Mindcraft stdout/stderr. |
| `logs/journalctl-minecraft.log` | Linux `journalctl -u minecraft -f`, or a note when unavailable. |
| `logs/supervisor.log` | Portable supervisor log when present. |
| `logs/minecraft-supervisor-stdout.log` | Supervisor + Paper stdout when `soak.sh` auto-starts the server. |
| `logs/paper-latest.log` | Paper `latest.log` when present. |
| `cost-ledger.tsv` | Per-agent token/USD totals, max hourly USD, cap, and pass/fail. |
| `early-exits.tsv` | Any bot process that exited before the planned end. |
| `action-reliability.json` | Per-agent generated/discarded/accepted command, execution, verification, and threshold metrics. |
| `action-reliability.md` | Human-readable reliability report with discarded-command counters, execution failure classes, and verified-action examples. |
| `behavior.tsv` | Per-agent behavioral counters and pass/fail status for the collaborative acceptance gate. |
| `behavior-totals.env` | Cohort behavioral totals, including `total_restarts`, `total_restart_recurrences`, and `behavior_gate_status`. |
| `heartbeat-halts.tsv` | Bots whose autonomous heartbeat halted after repeated blank/no-command outcomes. |
| `timeline.ndjson` | Canonical structured run timeline covering chat, LLM, accepted action, bridge telemetry, behavior/status, state, error, and lifecycle events. |
| `timeline-totals.json` | Counts by event type, agent, model, plus provider-reported vs estimated token totals. |
| `timeline-raw/*.ndjson` | Raw best-effort per-agent timeline events emitted by the staged Mindcraft overlay. |
| `timeline-raw/llm-queue.ndjson` | FIFO proxy wait/running/completed/failed telemetry. |
| `monitor.html` | Self-contained local cohort monitor rendered from `timeline.ndjson` and `timeline-totals.json`. |
| `summary.txt` | Crash candidates, heartbeat halts, bridge drops, Management event lines, rough respond/ignore counts, cost table, action reliability, behavioral acceptance, and timeline totals. |

## Failure Classes Monitored

The soak captures the canonical failure classes from
`docs/minecraft/failure-taxonomy.md`:

| Class | Soak evidence |
| --- | --- |
| `blocked` | Bot/action logs and `action.result` `outcome_class`/detail traces. |
| `interrupted` | Recoverable pathfinder/action interruptions such as `PathStopped` during `mode:unstuck`, reported through `action.result.outcome_class`. |
| `aborted` | Bot/action logs for caller-aborted work that safely returned an action result with `outcome_class=aborted`. |
| `timeout` | Bot logs, bridge logs, Paper/supervisor logs. |
| `invalid` | Bridge contract errors and bot stderr. |
| `unreachable` | Movement/action logs. |
| `bridge-down` | Bridge reconnect/send failures and WebSocket disconnect lines. |

Additional stability counters:

| Counter | Source |
| --- | --- |
| Crashes / unrecovered exits | `early-exits.tsv`; nonzero exits fail the script. |
| Supervisor restarts | `logs/supervisor.log` and `journalctl-minecraft.log`. |
| Bridge drops | `summary.txt` grep over bot and bridge logs. |
| Management interventions | Bot/bridge logs and DB shadow log evidence when available. |
| Per-agent token + USD spend | `cost_events` grouped by agent and hour. |
| Decentralized respond-vs-ignore ratio | Rough `respond`/`ignore` counts from bot logs. |
| Action-command reliability | `action-reliability.json`, `action-reliability.md`, and the `summary.txt` reliability block. |
| Behavioral acceptance | `behavior.tsv`, `behavior-totals.env`, and the `summary.txt` behavioral block. |
| Heartbeat halts / idle recovery | `heartbeat.fired` / `heartbeat.outcome` / `heartbeat.halted` timeline events and `heartbeat-halts.tsv`. |
| Queue health | `inbox.*`, `llm.queue.*`, and action queue timeline events in `monitor.html`. |
| Build-plan progress | `build_plan.generation.*` / `build_plan.execution.*` timeline events and the logged plan JSON. |

For E8-14 interruption recovery, `PathStopped: Path was stopped before it could
be completed` must appear as an `interrupted` action failure and must not be
paired with public `Exiting.` chat from the bot. Repeated `Exiting.` or process
exit lines are counted through `restart_count`.

## Cost Cap Accounting

`scripts/minecraft/soak.sh` queries the authoritative `cost_events` ledger for
the soak window and fails if any tracked agent exceeds the configured hourly
cap. The default cap for local validation is intentionally tiny:

```bash
SOAK_AGENT_HOURLY_CAP_USD=0.01
```

Local LM Studio runs should normally record zero external spend. If E11 adds a
separate cap table in a later branch, this script should be pointed at that
table, but it must keep using `cost_events` as the spend ledger.

## Evidence From This Codex Run

### E8-14 Interruption-Recovery Smoke Attempt

The local live Minecraft smoke for Alpha interruption recovery was not run in
this Codex sandbox because both local prerequisites were unavailable:

```bash
pnpm llm:local --list-only
```

Result: **failed**.

```text
FAIL: could not reach http://localhost:1234/v1/models
      All connection attempts failed
```

```bash
scripts/minecraft/health.sh --quiet
```

Result: **failed**.

The no-server regression evidence for this branch is the focused
`PathStopped` fixture suite:

```bash
.venv/bin/pytest tests/backend/test_embodiment_action_interruption.py -v
```

Result: **passed**. The fixture drives `!move`, `!navigate`, `!place`, and the
upstream `!placeHere` guard against `PathStopped: Path was stopped before it
could be completed`, and asserts the Node process stays alive while
`action.result` records `status=failure`, `outcome_class=interrupted`, and
details containing `interrupted`.

### Post-Loop Manual Live Startup Smoke

After the alpha-loop session, the local environment had LM Studio, Docker
services, Paper, and the FastAPI backend reachable. The smoke used Node 20 from
Homebrew and a throwaway local bridge token shared by the backend and bots.

```bash
pnpm llm:local --list-only
```

Result: **passed**.

```text
OK: connected to http://localhost:1234/v1
Models:
    text-embedding-nomic-embed-text-v1.5
    google/gemma-4-e4b
    google/gemma-4-26b-a4b
```

```bash
CHECK_MINECRAFT=1 bash scripts/check-services.sh
curl -fsS http://127.0.0.1:8010/api/health
```

Result: **passed**. The backend health response was
`{"status":"ok","database":"ok","redis":"ok"}`.

```bash
PATH=/opt/homebrew/opt/node@20/bin:$PATH \
MINECRAFT_BRIDGE_TOKEN=<local-smoke-token> \
DATABASE_URL=postgresql://agi:devpassword@localhost:5434/livestream_agi \
REDIS_URL=redis://:devpassword@localhost:6381 \
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=google/gemma-4-e4b \
LOCAL_LLM_MODEL_BUILDING=google/gemma-4-26b-a4b \
EMBEDDING_PROVIDER=deterministic \
CONVERSATION_MODE=embodied \
SOAK_LAUNCH_STAGGER_SECONDS=1 \
bash scripts/minecraft/soak.sh --duration-hours 0.02 --log-dir /tmp/e8-8-soak-after-port-fix
```

Result: **passed**.

Evidence directory:
`/tmp/e8-8-soak-after-port-fix/20260520T100403Z`

Summary:

| Counter | Result |
| --- | --- |
| Early bot exits | `0` |
| Bridge drop lines | `0` |
| Management event lines | `38` |
| Crash candidate lines | `1` |
| Respond count | `2` |
| Ignore count | `0` |
| Cost cap | pass for all tracked agents |

Paper logs confirmed BridgeBot, Alpha, Vera, Rex, Aurora, Pixel, Fork,
Sentinel, and Grok all logged into the local server. Bot logs also showed
`management_review_event ... outcome=bridge_timeout` during the startup smoke;
that is fail-closed behavior, but the full acceptance soak should either tune
or explicitly accept the local Management review deadline before GO sign-off.

This was deliberately short and does **not** satisfy the E8-8 multi-hour
acceptance criterion.

### Original Alpha-Loop Evidence

Initial Codex execution did not meet live-soak prerequisites. Verification
attempt 1 later confirmed Docker services and LM Studio were reachable, but
the local Minecraft health check was down. The root cause was that the first
soak runner treated Paper as an external precondition instead of starting it
when absent. `scripts/minecraft/soak.sh` now auto-starts the portable
supervisor unless `SOAK_START_MINECRAFT_IF_DOWN=0`.

```bash
pnpm llm:local --list-only
```

Result: **failed**.

```text
FAIL: could not reach http://localhost:1234/v1/models
      All connection attempts failed
```

No LM Studio model IDs were available to record.

Verification attempt 1 later reached LM Studio at `http://localhost:1234/v1`
and listed:

- `text-embedding-nomic-embed-text-v1.5`
- `google/gemma-4-26b-a4b`
- `google/gemma-4-e4b`

```bash
scripts/minecraft/health.sh --json
```

Result: **failed**.

```json
{"up":false,"host":"127.0.0.1","port":25565,"checked_at":"2026-05-20T09:17:28Z"}
```

```bash
curl -fsS http://127.0.0.1:8010/api/health
```

Result: **failed**.

```text
curl: (7) Failed to connect to 127.0.0.1 port 8010 after 0 ms: Couldn't connect to server
```

Local runtime snapshot:

| Check | Result |
| --- | --- |
| `./mindcraft` | missing |
| `./minecraft-server` | missing |
| `.venv` | present |
| Node | `v22.22.2` on PATH; soak requires Node 20 |
| Java | missing on PATH |

Nearest local static smoke paths run for this branch:

```bash
scripts/minecraft/soak.sh --verify
pnpm verify:minecraft-soak
pnpm verify:bridge-server
pnpm verify:embodiment-failure
.venv/bin/pytest \
  tests/backend/test_mc_cohort1_vera_rex.py \
  tests/backend/test_mc_cohort2_aurora_pixel_fork.py \
  tests/backend/test_mc_cohort3_sentinel_grok.py \
  tests/backend/test_management.py \
  tests/backend/test_cost_tracking.py -v
```

Results:

- `scripts/minecraft/soak.sh --verify`: passed.
- `pnpm verify:minecraft-soak`: 15 passed.
- `pnpm verify:bridge-server`: 35 passed.
- `pnpm verify:embodiment-failure`: 34 passed.
- Cohort + Management + cost tracking suite: 152 passed, 1 skipped
  (`test_end_to_end_review_with_llm` is opt-in LLM coverage).

## Live Run Addendum Template

Append the completed live run here before advancing E8-9:

| Field | Value |
| --- | --- |
| Start UTC |  |
| End UTC |  |
| Duration |  |
| LM Studio base URL | `http://localhost:1234/v1` |
| `LOCAL_LLM_MODEL` |  |
| `LOCAL_LLM_MODEL_BUILDING` |  |
| LM queue concurrency / max wait |  |
| Soak command |  |
| Evidence directory | `logs/soak/<timestamp>/` |
| Bot exits |  |
| Crashes / fatal log lines |  |
| Bridge drops |  |
| Supervisor restarts |  |
| Management interventions |  |
| Respond count |  |
| Ignore count |  |
| Cost ledger result |  |
| Action reliability result | PASS / NOT ACCEPTABLE |
| Intent-to-command / parse / execution / verified rates |  |
| Top parser failure classes |  |
| Failed parse examples |  |
| Verified action examples |  |
| Timeline result | PASS / MISSING |
| Timeline event totals |  |
| Timeline token totals | provider-reported / estimated |
| Inbox/action queue max depths |  |
| Build-plan evidence | PASS / MISSING |
| Spawn safety (per agent) |  |
| Movement distance / count |  |
| Public chat lines (cohort) |  |
| Inter-agent mentions |  |
| Gather actions |  |
| Build actions |  |
| Deaths / drownings |  |
| Stuck / dig-hole events |  |
| Shared artifact(s) observed |  |
| Behavioral gate result | PASS / FAIL |
| Tunings applied mid-soak |  |
| Final decision | GO / NO-GO |

Decision rule: **GO** only if the run lasts at least 2 hours, every bot either
stays up or recovers automatically, there are no unrecovered bridge drops or
runaway loops, every tracked agent stays within the E11 hourly cap, and the
action-command reliability gate and behavioral acceptance gate both pass.
