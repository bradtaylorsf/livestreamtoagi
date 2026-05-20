# Multi-Agent Stability Soak

Issue: #579 E8-8 - Multi-agent stability soak (hours)  
Epic: #510 E8 - All Agents Embodied + Decentralized Conversation  
Prepared: 2026-05-20 PDT  
Scope: BridgeBot plus Alpha, Vera, Rex, Aurora, Pixel, Fork, Sentinel, and Grok

## Decision

Status: **STATIC-EVIDENCE ONLY in this Codex run; NO-GO for E8-9 until a live
LM Studio soak is rerun and appended here.**

The operator entrypoint now exists at `scripts/minecraft/soak.sh` and is wired
for a multi-hour local run using LM Studio, the existing bot launchers, the
Minecraft health probe, backend health, log capture, and the `cost_events`
ledger. If the local Paper server is down, the soak runner starts
`scripts/minecraft/supervise.sh` and waits for `scripts/minecraft/health.sh`
to pass before launching bots.

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
patched action files while still reusing the reviewed launchers.

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

scripts/minecraft/soak.sh --duration-hours 2
```

If you want the soak to fail instead of auto-starting Paper:

```bash
SOAK_START_MINECRAFT_IF_DOWN=0 scripts/minecraft/soak.sh --duration-hours 2
```

Package aliases:

```bash
pnpm mc:soak -- --duration-hours 2
pnpm verify:minecraft-soak
```

Outputs are written to `logs/soak/<UTC timestamp>/`:

| File | Contents |
| --- | --- |
| `metadata.env` | Start/end plan, host info, git head, model ids, bridge URL, cost cap. |
| `preflight/` | Raw pre-flight command output. |
| `bots/<bot>.log` | Per-bot Mindcraft stdout/stderr. |
| `logs/journalctl-minecraft.log` | Linux `journalctl -u minecraft -f`, or a note when unavailable. |
| `logs/supervisor.log` | Portable supervisor log when present. |
| `logs/minecraft-supervisor-stdout.log` | Supervisor + Paper stdout when `soak.sh` auto-starts the server. |
| `logs/paper-latest.log` | Paper `latest.log` when present. |
| `cost-ledger.tsv` | Per-agent token/USD totals, max hourly USD, cap, and pass/fail. |
| `early-exits.tsv` | Any bot process that exited before the planned end. |
| `summary.txt` | Crash candidates, bridge drops, Management event lines, rough respond/ignore counts, cost table. |

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
- `pnpm verify:minecraft-soak`: 14 passed.
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
| Tunings applied mid-soak |  |
| Final decision | GO / NO-GO |

Decision rule: **GO** only if the run lasts at least 2 hours, every bot either
stays up or recovers automatically, there are no unrecovered bridge drops or
runaway loops, and every tracked agent stays within the E11 hourly cap.
