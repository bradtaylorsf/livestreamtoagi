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
| `behavior.event` | Non-chat bot behavior/status telemetry such as gated clean-exit or unstuck messages. |
| `bridge.action.start` | Bridge action-result request start telemetry. This is not counted as an executed Minecraft action. |
| `bridge.action.result` | Bridge action-result settle telemetry. This is not counted as an executed Minecraft action. |
| `chat.public` | Public Minecraft chat from Paper or bot logs. Payload includes `speaker` and `message`. |
| `llm.request` | Model request started. Local chat/action traffic uses LM Studio; explicit builder-plan routing may emit OpenRouter requests with `purpose: "plan_generation"`. Payload includes `model`, `provider`, `purpose`, `reason`, prompt token count, and paid-call metadata when applicable. |
| `llm.response` | Model response or failure. Payload includes `model`, `provider`, `latency_ms`, `outcome`, prompt/completion/total tokens, usage source, and command-discard counters when inferred from bot logs. |
| `llm.queue.enqueued` | Local FIFO LM Studio proxy accepted a request. Payload includes `queued`, `concurrency`, `path`, and `model` when available. |
| `llm.queue.started` | Proxy worker started forwarding a queued request. Payload includes `wait_ms`, `queued`, `running`, and `model`. |
| `llm.queue.completed` | Proxy received an upstream response. Payload includes `wait_ms`, `latency_ms`, HTTP `status`, `model`, and nested provider `tokens` when available. |
| `llm.queue.failed` | Proxy forwarding failed and returned a local 502 response. Payload includes `wait_ms`, `latency_ms`, `error`, and `model` when available. |
| `action.intent` | Accepted executable command from parsed/full-response command paths. Stale generated commands do not emit this event. |
| `action.start` | A discrete bridge/action start, usually tied to a trace id. |
| `action.queued` | Per-agent action queue deferred a new embodied action behind the active slot. Payload includes `action`, `queue_depth`, and `queued_behind`. |
| `action.started` | Serialized action queue started a direct or queued action. Payload includes `action`, `source`, and queue depth. |
| `action.completed` | Serialized action queue finished a direct or queued action. Payload includes `action`, success/interrupted/timed-out flags, and queue depth. |
| `action.rejected_busy` | Serialized action queue rejected an action because the per-agent queue was full. |
| `action.result` | Terminal grouped `Agent executed:` result such as placed, reached, blocked, failed, invalid, interrupted, or timed out. |
| `inbox.queued` | Per-agent inbox accepted a chat message for a future batched turn. Payload includes `source`, `message_preview`, queue depth, and whether generation was already running. |
| `inbox.turn_started` | Inbox debounce fired and a compact message batch was sent to the stock conversation handler. |
| `inbox.turn_completed` | Batched conversation turn finished, including outcome and remaining queue depth. |
| `inbox.telemetry_ignored` | Lifecycle/status chatter was recorded but intentionally not sent to the LLM. |
| `inbox.immediate_command` | Direct user command such as `!stop` bypassed the debounce path. |
| `director_gate.selected` | Director V2 allowed this compacted inbox batch to enter the Mindcraft prompt path. Payload includes `scene_id`, `turn_kind`, `reason`, and `queue_depth`. |
| `director_gate.suppressed` | Director V2 suppressed this compacted inbox batch before `shouldRespond`. Payload includes `scene_id`, `suppression_reason`, `queue_depth`, and suppressed-agent count. |
| `director_gate.stale_discarded` | A Director V2 verdict arrived after a newer gate request superseded it, so the old prompt was discarded. |
| `build_plan.generation.started` | `!planAndBuild` began a builder-model planning request. |
| `build_plan.generation.completed` | A validated plan is ready. Payload includes `source`, `provider`, `builder_model`, paid/local counts, token usage when available, estimated USD, `plan`, `plan_json`, origin, and max steps. |
| `build_plan.generation.rejected` | Builder-model JSON failed schema/material/bounds validation before fallback. |
| `build_plan.generation.provider_failed` | Builder provider setup or request failed before validated JSON was available. Payload includes provider, model, reason, caps, and fallback reason when local fallback is enabled. |
| `build_plan.generation.budget_capped` | Builder provider was not called because per-run, per-agent, or estimated USD cap would be exceeded. |
| `build_plan.generation.skipped` | The build governor avoided a new builder call because an active build exists, an equivalent build is cooling down, the per-agent cap was reached, or a cached plan was reused. |
| `build_plan.execution.started` | The validated plan began execution through `!buildFromPlan`. |
| `build_plan.execution.completed` | Plan execution finished with the terminal build result string. |
| `heartbeat.fired` | Autonomous idle/stall heartbeat prompt was sent. Payload includes reason, idle window, action state, cooldown, and prompt excerpt. |
| `heartbeat.skipped` | Heartbeat considered an idle/stall check but did not prompt, such as active action, cooldown, disabled, or max no-command state. |
| `heartbeat.outcome` | Result of a heartbeat prompt. Payload includes command detection, no-command streak, response excerpt, and error status when applicable. |
| `heartbeat.halted` | Heartbeat stopped itself after repeated blank/no-command outcomes. The soak treats this as a failure/restart signal. |
| `state.sample` | Sampled world state or perception, including position when available. High-frequency position lines are interval-collapsed. |
| `error` | Parser, bridge, runtime, malformed NDJSON, or model-call error. |
| `lifecycle` | Bot, bridge, server, connection, circuit, spawn, join, disconnect, or shutdown lifecycle event. |

## Token Usage

LLM request/response events prefer provider-reported LM Studio usage metadata:

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

Queue proxy events (`llm.queue.*`) are operational telemetry, not model-spend
records. They may carry nested upstream token metadata on completion, but token
totals are de-duplicated from `llm.request` / `llm.response` only.

`timeline-totals.json` aggregates counts by event type, agent, model, and token
source. It includes a top-level `tokens` quick summary with `total`,
`estimated`, and `provider_reported` token counts, plus the richer
`token_totals`, `tokens_by_agent`, and `tokens_by_model` breakdowns. Token totals
are de-duplicated by LLM trace where a request and response pair both exist.
Builder-plan usage is also broken out under `builder_usage` and
`builder_usage_by_agent`, separating paid OpenRouter plan-generation calls from
local LM Studio chat/action usage.

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

For bot-log inference, the exporter uses the same parser as
`analyze_action_reliability.py`. `Generated response:` text becomes
`llm.response`; stale generations set `outcome: "discarded_stale"` and expose
`discarded_commands`; only accepted commands become `action.intent`; and each
multi-line `Agent executed:` block becomes one `action.result`.

## Sources

The exporter reads these inputs from a soak evidence directory:

- `bots/*.log` for Mindcraft stdout/stderr, command text, action traces, parser errors, lifecycle, and sampled position.
- `logs/*.log` for Paper chat, bridge structured logs, and server errors.
- `timeline-raw/*.ndjson` for Node-side timeline events from `timeline_emitter.js`.
- `timeline-raw/llm-queue.ndjson` for FIFO proxy wait/running/completed/failed telemetry.
- `*lmstudio*.ndjson` for explicit LM Studio request/response traces when present.

The committed Mindcraft overlay stages:

- `scripts/minecraft/fork-src/agent/bridge/timeline_emitter.js`
- `scripts/minecraft/fork-src/agent/skills/lmstudio_usage.js`
- `scripts/minecraft/fork-src/agent/skills/inbox_queue.js`
- `scripts/minecraft/fork-src/agent/skills/director_gate.js`
- `scripts/minecraft/fork-src/agent/skills/action_queue.js`
- `scripts/minecraft/fork-src/agent/skills/heartbeat.js`
- `scripts/minecraft/fork-src/agent/commands/plan_and_build_action.js`

Launchers inject the usage shim into staged `settings.js` and patch `agent.js`
to install the inbox, Director gate, action queue, and heartbeat wrappers, so the git-ignored
Mindcraft clone does not need a committed edit.
