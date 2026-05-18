# Decision 0005: Skill And Bridge Extension Point

Status: accepted for coding; in-game no-op spike still belongs in E4

Research date: 2026-05-18

Related issue: #522, E1-R5

## Non-Technical Summary

Mindcraft does not have a clean plugin manifest where we can drop in a Python
bridge. It does have clear source-level extension points. We will fork Mindcraft
and add a small bridge module plus explicit commands/skills.

This is not a blocker. It means the bridge is a controlled fork patch, not an
external plugin.

## Decision

Use a fork-level patch with three extension points:

1. Add a Node bridge client module:
   `src/agent/bridge/python_bridge.js`.
2. Add explicit commands/actions in `src/agent/commands/actions.js` and/or
   `src/agent/commands/queries.js`.
3. Add code-generation skills in `src/agent/library/skills.js` only when the
   action is safe for generated code to call.

The first spike action should be `!bridgePing("payload")`, returning a Python
response through the bridge. After that, add domain-specific actions instead of
one unbounded generic command.

## Bridge Transport

Use an authenticated WebSocket from each bot process to the FastAPI backend:

- Python endpoint: `/api/minecraft/bridge/ws`.
- Auth: bearer token from `MINECRAFT_BRIDGE_TOKEN`.
- Envelope fields:
  - `version`
  - `request_id`
  - `agent_id`
  - `run_id` or `simulation_id`
  - `service`
  - `method`
  - `payload`
  - `deadline_ms`
  - `cost_context`
- Response fields:
  - `request_id`
  - `ok`
  - `payload`
  - `error`
  - `retryable`

This fits the repo's existing FastAPI/WebSocket posture and gives E4 room for
reconnect, backpressure, and Python-initiated control messages.

## What Mindcraft Provides Today

Mindcraft has a Python wrapper under `src/mindcraft-py`, but it starts the Node
MindServer and emits `create-agent`. It is useful as reference, not the bridge
we need. It does not expose Python memory, Management, cost gates, or bot action
services to live agents.

Mindcraft command parsing is intentionally simple. Commands are registered in
arrays, parsed from `!command("arg", 1, true)` strings, and dispatched to
`perform(agent, ...)`. That is fine for small commands, but too limited for rich
bridge payloads unless we encode JSON as a string.

Mindcraft code-generation skills are ordinary exported JS functions from
`skills.js` and `world.js`. Docs are harvested from JSDoc comments, and the code
sandbox exposes only `skills`, `world`, `Vec3`, and `log`.

## Guardrails

- Do not expose a generic "execute arbitrary Python" tool to the LLM.
- Do not let generated `!newAction` code call sensitive Python services unless
  that skill is explicitly safe.
- Management review and cost gates should be direct hooks in Mindcraft runtime
  paths, not optional LLM commands.
- Bridge calls must fail closed for broadcast output. If Management/cost cannot
  be reached, do not publish agent speech to the livestream.
- Use typed service names such as `memory.recall`, `memory.write`,
  `management.review`, `cost.reserve`, `journal.event`, and `kill.status`.

## First No-Op Spike

E4 should prove this before building memory:

1. Add `python_bridge.js` with connect/auth/call timeout.
2. Add `!bridgePing("hello")` to `actionsList`.
3. Start FastAPI with a temporary bridge handler.
4. Spawn one bot.
5. Send `!bridgePing("hello")`.
6. Confirm the bot receives `pong: hello` and the Python side logs the
   `agent_id` and `request_id`.

## Evidence

- Command registry and parser:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/commands/index.js#L7-L29
- Command dispatch:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/commands/index.js#L212-L230
- Existing actions list:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/commands/actions.js#L28-L52
- Skill library docs:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/library/index.js#L1-L22
- Code sandbox exposes skills/world:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/agent/coder.js#L185-L195
- Mindcraft Python wrapper:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/mindcraft-py/mindcraft.py#L23-L66
- MindServer control/socket routes:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/mindcraft/mindserver.js#L123-L156
