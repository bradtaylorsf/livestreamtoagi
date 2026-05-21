# Minecraft Cohort Monitor

Issue: #719 E8-13

The cohort monitor is a local-only HTML dashboard over the structured soak
timeline from E8-12. It is meant for Brad during a local embodied soak: one
page shows run status, the action pipeline, each agent's latest public
chat/action/LLM state, idle time, restart count, errors, token totals, and
recent feeds.

## Open After A Soak

`scripts/minecraft/soak.sh` renders the monitor after `timeline.ndjson` and
`timeline-totals.json` are exported:

```bash
open logs/soak/<UTC timestamp>/monitor.html
```

If the monitor was not rendered during the soak, rebuild it from the evidence
directory:

```bash
python3 scripts/minecraft/build_monitor.py --run-dir logs/soak/<UTC timestamp>
open logs/soak/<UTC timestamp>/monitor.html
```

Pass `--rebuild-timeline` if raw `bots/`, `logs/`, or `timeline-raw/` evidence
changed and the canonical `timeline.ndjson` should be regenerated first.

The generated file is self-contained. It has inline CSS/JS, embeds the monitor
data as JSON, and does not fetch assets from a production website or CDN.

## Action Pipeline

The headline reliability view is a pipeline, not a single ambiguous completion
percentage:

`LLM requests -> generated responses -> discarded stale responses -> accepted commands -> executed actions -> verified successes`

Discarded stale responses are shown separately from action failures. If a stale
response contained a command, it increments `discarded_commands` but does not
create an `action.intent`. Bridge settle telemetry is displayed as lifecycle
telemetry, while `action.result` is reserved for grouped `Agent executed:`
blocks from the bot logs.

## Watch An In-Progress Soak

Use the loopback-only dev server while the soak is still running:

```bash
python3 scripts/minecraft/serve_monitor.py --run-dir logs/soak/<UTC timestamp>
```

Then open:

```text
http://localhost:8765/monitor.html
```

The server rebuilds the canonical timeline and HTML every 5 seconds by default
and binds to `127.0.0.1`, so it is not publicly exposed. To change the refresh
interval:

```bash
python3 scripts/minecraft/serve_monitor.py \
  --run-dir logs/soak/<UTC timestamp> \
  --refresh-seconds 2
```

Binding to a non-loopback host is refused unless `--allow-remote` is passed.

## Warning Badges

| Badge | Default rule | Override |
| --- | --- | --- |
| `Stalled` | No chat, action, or LLM activity for 120 seconds. | `SOAK_MONITOR_STALL_SECONDS` |
| `Blank responses` | 3 consecutive blank LLM responses. | `SOAK_MONITOR_REPEAT_BLANK_COUNT` |
| `Repeated command` | 3 consecutive identical action intents. | `SOAK_MONITOR_REPEAT_COMMAND_COUNT` |
| `Crash/restart` | Any lifecycle disconnect, reconnect, restart, exit, kick, shutdown, or crash event. | n/a |
| `Recent restart` | Restart-class lifecycle event within 300 seconds of the monitor reference time. | `SOAK_MONITOR_RESTART_RECENT_SECONDS` |
| `Undefined result` | One or more action executions returned `undefined`. | n/a |
| `Interrupted` | Five or more interrupted action results for one agent. | n/a |
| `Stuck loop` | 3 consecutive blocked, unreachable, stuck, or timed-out action results. | `SOAK_MONITOR_STUCK_LOOP_COUNT` |
| `No recent LLM` | No LLM request or response for 120 seconds. | `SOAK_MONITOR_LLM_IDLE_SECONDS` |

For completed runs, the monitor uses `summary.txt` `end_utc` as the reference
time when present. For in-progress runs, it uses the current UTC time.

## Filters

The feed filters toggle visible rows for:

- chat
- LLM
- action
- movement
- error
- lifecycle

The per-agent cards remain visible while filters are changed.
