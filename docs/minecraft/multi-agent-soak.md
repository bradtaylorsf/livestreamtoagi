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

No OpenRouter validation was run or required.

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
export MINECRAFT_BRIDGE_TOKEN=<same-secret-as-backend>

scripts/minecraft/soak.sh --duration-hours 2 --log-dir logs/soak
```

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
a flat grass starter meadow with visible resource piles and work blocks, then
teleports online bots into the meadow with a small starter kit. The easy arena
also pins spawn radius to zero, disables drowning/fall/freeze damage for local
validation, and wraps the starter meadow in a glass boundary so agents have a
small safe place to learn before exploring. Set `MC_SIM_EASY_MODE=0` to use the
normal Minecraft target instead, or set `MC_SIM_MC_PORT=<port>` if `25566` is
busy. In easy mode, `MC_SIM_KEEP_SERVER_RUNNING=1` by default so the Paper
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
isolated MindServer instance. Low-level bridge action result chatter is
suppressed by default with `MC_SIM_SUPPRESS_ACTION_CHAT=1`; the action still
logs to each bot log and still reports over the Python bridge, but it does not
interrupt the other local models mid-turn. Safe terrain behavior is also on by
default: `MC_SIM_SAFE_TERRAIN_ACTIONS=1` sets
`SOAK_SAFE_TERRAIN_ACTIONS=1` and `MINECRAFT_ALLOW_DESTRUCTIVE_PATHS=0`, which
disables automatic elbow-room/item-pickup/torch modes in the disposable
Mindcraft clones and refuses pathfinder routes that require digging or
one-block towers. Set `MC_SIM_ALLOW_NEW_ACTION=1` only when you deliberately
want the local model to spend extra time synthesizing custom action code.

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
| `build` | Build/place commands such as `!place`, `!placeHere`, `!placeBlock`, `!build`, or `!buildFromPlan`. |
| `deaths` / `drownings` | Death, respawn, and drowning terms in the agent log stream. |
| `stuck` / `dig_holes` | Stuck, path-failure, unreachable, trapped, or hole-digging phrases. |
| `shared_artifact_count` | Cohort-wide shared-work evidence from shared/together camp-marker-wall-chest-shelter-fire language, nearby place coordinates by multiple agents, or at least two distinct agents emitting place/build commands. |

The default behavioral thresholds are env-overridable:

| Env var | Default | Gate |
| --- | ---: | --- |
| `SOAK_MIN_MOVEMENT_PER_AGENT` | `5` | Every tracked agent must meet or exceed this movement count. |
| `SOAK_MAX_DEATHS_PER_AGENT` | `2` | Any agent above this death/respawn count fails. |
| `SOAK_MAX_STUCK_PER_AGENT` | `5` | Any agent above this stuck/path-failure count fails. |
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
| `action-reliability.json` | Per-agent intent, parse, execution, verification metrics and threshold violations. |
| `action-reliability.md` | Human-readable reliability report with failed-parse and verified-action examples. |
| `behavior.tsv` | Per-agent behavioral counters and pass/fail status for the collaborative acceptance gate. |
| `summary.txt` | Crash candidates, bridge drops, Management event lines, rough respond/ignore counts, cost table, action reliability, and behavioral acceptance. |

## Failure Classes Monitored

The soak captures the canonical failure classes from
`docs/minecraft/failure-taxonomy.md`:

| Class | Soak evidence |
| --- | --- |
| `blocked` | Bot/action logs and `action.result` traces. |
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
