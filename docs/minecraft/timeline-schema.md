# Minecraft Run Timeline Schema

Issue: #718 E8-12

Embodied Minecraft soaks write a canonical timeline to:

- `logs/soak/<UTC timestamp>/timeline.ndjson`
- `logs/soak/<UTC timestamp>/timeline-totals.json`
- raw best-effort Node events in `logs/soak/<UTC timestamp>/timeline-raw/<agent>.ndjson`

Manual exports use the same defaults, or can write to explicit paths:

```bash
python3 scripts/minecraft/build_timeline.py \
  --run-dir logs/soak/<UTC timestamp> \
  --output /tmp/timeline.ndjson \
  --totals /tmp/timeline-totals.json
```

Each `timeline.ndjson` line is one JSON object:

```json
{
  "event_id": "timeline-000001",
  "ts": "2026-05-20T22:14:03Z",
  "seq": 1,
  "event_type": "llm.response",
  "agent": "vera",
  "trace_id": "trace-llm-...",
  "source": "timeline-raw/vera.ndjson",
  "payload": {}
}
```

## Event Types

| Type | Meaning |
| --- | --- |
| `chat.public` | Public Minecraft chat from Paper or bot logs. Payload includes `speaker` and `message`. |
| `llm.request` | Local LM Studio request started. Payload includes `model`, `purpose`, `reason`, and prompt token count. |
| `llm.response` | Local LM Studio response or failure. Payload includes `model`, `latency_ms`, `outcome`, prompt/completion/total tokens, and usage source. |
| `action.intent` | High-level intended action from model output or command text. This is not emitted for every tick or pathfinder step. |
| `action.start` | A discrete bridge/action start, usually tied to a trace id. |
| `action.result` | Terminal action result such as placed, reached, blocked, failed, invalid, or timed out. |
| `heartbeat.fired` | Autonomous idle/stall heartbeat prompt was sent. Payload includes reason, idle window, action state, cooldown, and prompt excerpt. |
| `heartbeat.skipped` | Heartbeat considered an idle/stall check but did not prompt, such as active action, cooldown, disabled, or max no-command state. |
| `heartbeat.outcome` | Result of a heartbeat prompt. Payload includes command detection, no-command streak, response excerpt, and error status when applicable. |
| `heartbeat.halted` | Heartbeat stopped itself after repeated blank/no-command outcomes. The soak treats this as a failure/restart signal. |
| `state.sample` | Sampled world state or perception, including position when available. High-frequency position lines are interval-collapsed. |
| `error` | Parser, bridge, runtime, malformed NDJSON, or model-call error. |
| `lifecycle` | Bot, bridge, server, connection, circuit, spawn, join, disconnect, or shutdown lifecycle event. |

## Token Usage

LLM events prefer provider-reported LM Studio usage metadata:

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `usage_source: "provider_reported"`
- `estimated: false`

If LM Studio omits usage, the Node shim and Python exporter use the same
deterministic local estimate: serialized character count divided by four,
rounded up. Estimated records set:

- `usage_source: "estimated"`
- `estimated: true`

`timeline-totals.json` aggregates counts by event type, agent, model, and token
source. It includes a top-level `tokens` quick summary with `total`,
`estimated`, and `provider_reported` token counts, plus the richer
`token_totals`, `tokens_by_agent`, and `tokens_by_model` breakdowns. Token totals
are de-duplicated by LLM trace where a request and response pair both exist.

## Trace Correlation

The strongest correlation key is `trace_id`. When a trace is present, it links:

`llm.request -> llm.response -> action.intent -> action.start -> action.result`

Mindcraft does not always expose one trace across all stages, so the exporter
uses a deterministic fallback per agent:

1. nearest prior `llm.response`
2. nearest prior `action.intent`
3. nearest prior `action.start`

This fallback only fills missing trace ids; it does not merge or delete events.
Every event still has a stable `event_id` and monotonic `seq`.

## Sources

The exporter reads these inputs from a soak evidence directory:

- `bots/*.log` for Mindcraft stdout/stderr, command text, action traces, parser errors, lifecycle, and sampled position.
- `logs/*.log` for Paper chat, bridge structured logs, and server errors.
- `timeline-raw/*.ndjson` for Node-side timeline events from `timeline_emitter.js`.
- `*lmstudio*.ndjson` for explicit LM Studio request/response traces when present.

The committed Mindcraft overlay stages:

- `scripts/minecraft/fork-src/agent/bridge/timeline_emitter.js`
- `scripts/minecraft/fork-src/agent/skills/lmstudio_usage.js`
- `scripts/minecraft/fork-src/agent/skills/heartbeat.js`

Launchers inject the usage shim into staged `settings.js` and patch `agent.js`
to install the heartbeat, so the git-ignored Mindcraft clone does not need a
committed edit.
