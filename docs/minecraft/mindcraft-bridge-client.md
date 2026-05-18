# Node bridge client + the `!bridgePing` spike (E4-4 / E4-5)

This runbook takes you from **a pinned Mindcraft install + a running E2 server +
the FastAPI bridge endpoint** to **an in-game bot that round-trips a contract
message through Python and logs the `pong`** — decision 0005's bridge extension
point, proven end to end. E4-5 (#544) adds the resilience policy that keeps a
24/7 bot safe when that bridge drops (see
[Reconnect, backpressure & safe-idle](#reconnect-backpressure--safe-idle-e4-5)).

> **Issues:** E4-4 ([#543](https://github.com/bradtaylorsf/livestreamtoagi/issues/543)),
> E4-5 ([#544](https://github.com/bradtaylorsf/livestreamtoagi/issues/544)) (epic E4).
> **Script:** `scripts/minecraft/connect-bridge-bot.sh` (`pnpm mc:connect-bridge`).
> **Builds on:** the E4-1 ADR [`docs/decisions/0010-bridge-protocol.md`](../decisions/0010-bridge-protocol.md),
> the E4-2 contract ([`docs/minecraft/bridge-contract.md`](bridge-contract.md)),
> and the E4-3 server endpoint.

## What this gets you

- One Mindcraft bot (fixed username **`BridgeBot`**) joining the **E2 Paper
  server** on `127.0.0.1:25565` in **offline** auth mode, driven by a **local
  LM Studio** model only — **zero external model spend**, no `openrouter/...`.
- The committed bridge client `python_bridge.js` and the `!bridgePing` action
  staged into the git-ignored `./mindcraft` clone from the reviewed
  `scripts/minecraft/fork-src/` tree — the same committed-artifact pattern
  `connect-stock-bot.sh` uses for `settings.js` and the mcdata shim.
- The `!bridgePing("hello")` action wired into Mindcraft's `actionsList`. In
  chat, the bot answers with `bridge pong: hello`; the Python bridge logs the
  `agent_id` + `request_id`. A bridge failure is logged as
  `bridge ping failed [<error.code>]: …` — **logged, never a crash**.

## What this does NOT cover (on purpose)

- **A persistent pooled connection / the inbound Python→Node push channel** —
  that is **E4-6 ([#545](https://github.com/bradtaylorsf/livestreamtoagi/issues/545))**.
  Each *successful* call is still its own one-shot `connect → send → await →
  close`; E4-5 adds only one extra socket — the single background reconnect
  probe — and never more than one at a time.
- **The perception/action result channel and observability/trace IDs** — E4-6 /
  E4-7. Real `memory.*` / `management.*` / `cost.*` wiring is E5/E8; the server
  side is still the E4-3 stub.

## How the client is staged

`./mindcraft` is git-ignored, so the reviewed source of truth lives under
`scripts/minecraft/fork-src/`, mirroring the clone's `src/` layout so the
relative import resolves identically staged or driven by the contract test:

| Committed source | Staged into the clone as |
| --- | --- |
| `fork-src/agent/bridge/python_bridge.js` | `src/agent/bridge/python_bridge.js` |
| `fork-src/agent/commands/bridge_ping_action.js` | `src/agent/commands/bridge_ping_action.js` |

`connect-bridge-bot.sh` then injects `bridgePingAction` into
`src/agent/commands/actions.js`'s `actionsList` via an anchored, node-driven
patch (anchor: `export const actionsList = [`, marker `LTAG E4-4 bridge ping
action`). The patched `actions.js`, the mcdata runtime-version shim, and the two
copied files are **all reverted on exit** (the same restore-on-exit trap as the
mcdata shim) so the pinned tree stays clean and re-runnable.

## The bridge contract this client speaks

Fixed by ADR [`0010-bridge-protocol.md`](../decisions/0010-bridge-protocol.md)
and the versioned contract (`core/bridge/contract.py`, E4-2). The client builds
a contract-valid `BridgeRequest`: `version:"1.0"`, a unique `request_id`,
`agent_id`, `run_id`/`simulation_id`, `service`, `method`, `payload`,
`deadline_ms`, and `cost_context:{agent_tier:"conversation",
budget_bucket:"bridge", estimated_cost_usd:0.0}`. It correlates the response by
`request_id`, enforces a **local timeout == `deadline_ms`**, and on any
auth/handshake/protocol/`ok:false` failure rejects with a typed
`BridgeClientError` carrying a stable `code` — it **fails closed** and never
throws uncaught (ADR §4/§5). The committed JSON Schema
`core/bridge/schemas/bridge-protocol.schema.json` is treated as **reference
only**: the client does lightweight structural checks and adds **no** JSON
Schema validator (the Mindcraft lockfile is frozen).

### Transport

The client prefers the `ws` package (a transitive dependency already pinned in
`scripts/minecraft/mindcraft-package-lock.json` at 8.20.1 — it supports the
`Authorization: Bearer` handshake header). When `ws` is absent (e.g. CI, no
Mindcraft install) it falls back to the Node ≥20 global `WebSocket`, which
cannot set request headers, so it uses the server's documented `?token=`
query-param fallback — the **same shared secret**, still fail-closed.

## Reconnect, backpressure & safe-idle (E4-5)

24/7 means the bridge **will** drop (Python restart, deploy, crash). E4-5 makes
that degrade safely instead of hanging the bot or — worse — letting an
unfiltered/unbudgeted in-world action through. A disconnected **or** saturated
bridge is a **closed gate, never an unsafe action** — the fail-closed rule ADR
[0010 §5](../decisions/0010-bridge-protocol.md) requires E4-5 to preserve. All
of this is hand-rolled in `python_bridge.js` (no new npm dependency — the
Mindcraft lockfile is frozen).

- **Circuit breaker (fail-fast when Python is down).** Consecutive
  *connect-class* failures (`bridge_connect_failed` / `bridge_timeout`) are
  counted. After `MINECRAFT_BRIDGE_CIRCUIT_THRESHOLD` of them the circuit
  **opens**: further `callBridge` calls reject *immediately* with
  `bridge_unreachable` — no socket is opened and the per-call deadline is **not**
  paid each time. Auth/protocol/`ok:false` errors are config/contract problems a
  retry can't fix, so they pass through untouched and never trip the breaker.
- **Background reconnect probe (auto-recover).** While the circuit is open a
  single background `bridge.ping` health probe runs on exponential backoff with
  jitter — first delay `MINECRAFT_BRIDGE_RECONNECT_BASE_MS`, doubled each failed
  probe up to `MINECRAFT_BRIDGE_RECONNECT_MAX_MS`. Exactly one probe is ever in
  flight. The first probe that succeeds **closes the circuit and resets
  backoff**, so the next real call goes straight through — no restart, no manual
  step.
- **Bounded in-flight (fail-closed backpressure).** A hand-rolled counting
  semaphore caps concurrent round-trips at `MINECRAFT_BRIDGE_MAX_INFLIGHT`. The
  call that would exceed it rejects *immediately* with `bridge_overloaded`
  rather than queueing unboundedly or opening more sockets.
- **Safe-idle contract.** `bridge_unreachable` and `bridge_overloaded` are both
  `retryable`. The `!bridgePing` action treats them as an explicit **SAFE-IDLE**
  (`bridge unavailable, safe-idling [<code>]: …`): logged, no in-world action,
  still a returned status string, still never a throw/crash. Real gated actions
  must do the same — degrade to silence/no-op, never to an unfiltered or
  unbudgeted action.
- **Reachability accessor.** `bridgeStatus()` / `bridgeIsReachable()` expose the
  circuit state so an action layer can choose to safe-idle *before* it even
  attempts a call.

| Error code | Meaning | Bot behavior |
| --- | --- | --- |
| `bridge_unreachable` | Circuit open — Python is down; failing fast (no socket, no deadline). Retryable; the background probe is auto-recovering. | **Safe-idle**, no in-world action. |
| `bridge_overloaded` | In-flight cap (`MINECRAFT_BRIDGE_MAX_INFLIGHT`) reached — fail-closed backpressure. Retryable once load drops. | **Safe-idle**, no in-world action. |

## Environment variables

| Var | Required | Default | Meaning |
| --- | --- | --- | --- |
| `MINECRAFT_BRIDGE_TOKEN` | **yes** (real run) | — | Shared bearer secret; must match the FastAPI bridge server's. The bridge has no unauthenticated path — unset ⇒ fail closed before connecting. Never committed. |
| `MINECRAFT_BRIDGE_URL` | no | `ws://127.0.0.1:8010/api/minecraft/bridge/ws` | Bridge WebSocket URL the client dials. |
| `MINECRAFT_BRIDGE_MAX_INFLIGHT` | no | `8` | Max concurrent round-trips (E4-5). Past it, calls fail-closed with `bridge_overloaded` — bounded, never an unbounded queue. |
| `MINECRAFT_BRIDGE_CIRCUIT_THRESHOLD` | no | `3` | Consecutive connect-class failures (`bridge_connect_failed`/`bridge_timeout`) before the circuit opens and calls fail-fast `bridge_unreachable` (E4-5). |
| `MINECRAFT_BRIDGE_RECONNECT_BASE_MS` | no | `500` | First reconnect-probe backoff while the circuit is open; doubled + jittered per failed probe (E4-5). |
| `MINECRAFT_BRIDGE_RECONNECT_MAX_MS` | no | `30000` | Reconnect-probe backoff ceiling — the probe never waits longer than this between attempts (E4-5). |
| `LOCAL_LLM_MODEL` | **yes** (real run) | — | LM Studio conversation-tier model id. |
| `LOCAL_LLM_MODEL_BUILDING` | no | `= LOCAL_LLM_MODEL` | LM Studio building-tier model id. |
| `LTAG_RUN_ID` / `LTAG_SIMULATION_ID` / `LTAG_AGENT_ID` | no | `run-local` / zeroed UUID / `bridge-bot` | Attribution defaults for the envelope. |

Both bridge vars are documented in `.env.example`. **Never commit the real
token.**

## Run the documented command

```bash
# 1. List the models LM Studio is serving and pick one (zero external spend):
pnpm llm:local --list-only
export LOCAL_LLM_MODEL=<model-id-from-the-list>

# 2. Export the SAME shared secret the FastAPI bridge server uses:
export MINECRAFT_BRIDGE_TOKEN="$(openssl rand -hex 32)"   # example; use the server's

# 3. Stage the client + action and launch the bot:
pnpm mc:connect-bridge            # = scripts/minecraft/connect-bridge-bot.sh
```

Then, in Minecraft chat:

```
BridgeBot !bridgePing("hello")
```

Success looks like `bridge pong: hello` in chat/console, and the Python bridge
logging the `agent_id` + `request_id`. A failure looks like
`bridge ping failed [bridge_auth_refused]: …` — logged, the bot keeps running.

### Preview without launching (optional)

```bash
scripts/minecraft/connect-bridge-bot.sh --help      # the usage header
scripts/minecraft/connect-bridge-bot.sh --verify    # static asset checks (CI/network-safe)
scripts/minecraft/connect-bridge-bot.sh --dry-run   # resolved plan; no clone/network/launch
```

`--verify` and `--dry-run` never clone, hit the network, run Node, or launch.

## Local LM Studio validation (evidence)

This issue's only runtime path is the Node↔Python round-trip — there is **no
LLM model call in the bridge client itself**, so no LM Studio spend is required
to validate it. The nearest local smoke path is the dependency-free verifier:

```bash
# Confirm LM Studio is reachable (for the bot tier, when doing a full in-game run):
pnpm llm:local --list-only        # or: .venv/bin/python scripts/check_local_llm.py --list-only

# The full Node↔Python contract round-trip (boots the real E4-3 bridge under
# uvicorn on an ephemeral port, drives the committed python_bridge.js via Node;
# no Docker, no network egress, no LLM spend):
pnpm verify:bridge-node-client    # = .venv/bin/pytest tests/backend/test_bridge_node_client.py -v
```

For a full in-game run the bot conversation tier uses the local LM Studio model
in `LOCAL_LLM_MODEL` (`lmstudio/<id>` via `profiles/bridge-bot.json`); set
`LOCAL_LLM_MODEL_BUILDING` to a larger local model when one is available. Record
the LM Studio model id(s) and the commands run in the issue/PR.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `MINECRAFT_BRIDGE_TOKEN is not set` | Export the same secret the server uses (no anonymous path — decision 0010 §4). |
| `bridge ping failed [bridge_auth_refused]` | Token mismatch with the server, or the server has no token configured. |
| `bridge ping failed [bridge_connect_failed]` | The FastAPI bridge endpoint is not running / wrong `MINECRAFT_BRIDGE_URL`. |
| `bridge ping failed [bridge_timeout]` | Server reachable but did not answer within `deadline_ms` — fail closed, not a hang. |
| `bridge unavailable, safe-idling [bridge_unreachable]` | Circuit is open — Python is down. Expected, not an error: the bot is safe-idling and the background probe is retrying on backoff. It auto-recovers once the bridge is back; no manual step. If it never recovers, the FastAPI bridge endpoint is still down or `MINECRAFT_BRIDGE_URL` is wrong. |
| `bridge unavailable, safe-idling [bridge_overloaded]` | More than `MINECRAFT_BRIDGE_MAX_INFLIGHT` concurrent calls — fail-closed backpressure. Transient; raise the cap if it is sustained legitimate load, otherwise it self-clears as in-flight calls settle. |
| `bridge ping failed [unsupported_service]` | The verb is not in the ADR §6 closed registry (a server-side typed error, passed through). |
| Bot kicked “not whitelisted” | `whitelist add BridgeBot` in the E2 console (the script prints this). |

## Where this is recorded

- Script: `scripts/minecraft/connect-bridge-bot.sh` (`pnpm mc:connect-bridge`).
- Client + action: `scripts/minecraft/fork-src/agent/bridge/python_bridge.js`,
  `scripts/minecraft/fork-src/agent/commands/bridge_ping_action.js`.
- Profile: `scripts/minecraft/profiles/bridge-bot.json` (local-only).
- Test: `tests/backend/test_bridge_node_client.py` (`pnpm verify:bridge-node-client`).

### Related

- ADR: [`docs/decisions/0005-skill-extension-point.md`](../decisions/0005-skill-extension-point.md),
  [`docs/decisions/0010-bridge-protocol.md`](../decisions/0010-bridge-protocol.md).
- Contract: [`docs/minecraft/bridge-contract.md`](bridge-contract.md) (E4-2).
- Stock connect walkthrough this mirrors: [`docs/minecraft/mindcraft-connect.md`](mindcraft-connect.md) (E3-2).
