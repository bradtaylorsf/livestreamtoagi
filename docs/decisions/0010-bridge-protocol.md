# Decision 0010: Bridge Protocol And Transport

Status: accepted for coding; bridge security review is a separate gate (#548)

Research date: 2026-05-18

Related issue: #540, E4-1

## Non-Technical Summary

The Minecraft bots run in Node. Memory, the Management content filter, the cost
governor, the kill switch, and the journal all live in Python. Those two halves
need one reliable way to talk to each other.

This decision fixes that one way: each Node bot opens a single authenticated
WebSocket to the Python backend, and every message uses the same versioned
envelope. We do **not** use plain HTTP request/response and we do **not** use OS
pipes/IPC. Python must be able to push a message to a bot (for example, "stop
talking, Management vetoed that line"), so the channel has to be two-directional
and long-lived, which is exactly what a WebSocket gives us.

This ADR only fixes the **shape and the rules** of the conversation: the
transport, the envelope fields, how versions are negotiated, how the connection
is authenticated, and what happens on timeout or failure. The concrete schemas
for each service call are E4-2's deliverable, not this issue. There is no LLM
runtime path here — this is a design/ADR-only change with no model calls.

## Decision

### 1. Transport: authenticated FastAPI WebSocket

Each Node bot process opens **one** authenticated WebSocket to the Python
backend at:

```
/api/minecraft/bridge/ws
```

This matches the bridge-transport row already recorded in
[0000-summary.md](0000-summary.md) and the "Bridge Transport" section of
[0005-skill-extension-point.md](0005-skill-extension-point.md). It fits the
repo's existing FastAPI/WebSocket posture — `core/main.py` already serves a
`/ws` endpoint (`core/main.py:181`) fed by `core/event_bus.py`, so the bridge is
a second, namespaced WebSocket surface rather than a new kind of server.

**Rejected alternatives:**

- **Plain HTTP request/response.** A bot can call Python with HTTP, but Python
  cannot cleanly call *into* a running bot. We need Python-initiated control
  messages (Management veto, cost kill, "abort current action", kill-switch
  broadcast) delivered to a bot that did not just ask a question. HTTP would
  force long-polling or a second inbound server inside each Node process; a
  WebSocket gives a single bidirectional channel for free.
- **OS IPC (pipes / domain sockets / shared memory).** IPC assumes Python and
  the bots are always co-located in the same process tree on the same host.
  That is true for the first local slice but bakes a topology assumption into
  the contract. It also gives us no framing, no auth handshake, and no
  reconnect story, all of which we get from a WebSocket. The same envelope can
  later run over a private-network WebSocket without a protocol change.

Reconnect, heartbeat/keepalive, and backpressure are intentionally **left to
E4-4** and the perception/action result channel to **E4-5/E4-6**. This ADR only
guarantees the transport choice leaves room for them (a persistent,
server-pushable channel does).

### 2. Message envelope

Every message is a JSON object using a fixed envelope. The **field set and
semantics are fixed here**; the per-service payload schemas are E4-2's
deliverable. These fields match
[0005-skill-extension-point.md](0005-skill-extension-point.md) lines 39–54
exactly so the two ADRs cannot drift.

**Request (Node → Python, or Python → Node for control):**

| Field | Meaning |
| --- | --- |
| `version` | Protocol semver string (see §3). Required on every message. |
| `request_id` | Unique id for this request; used for correlation and idempotency (see §5). |
| `agent_id` | Stable agent identity (e.g. `vera`, `alpha`) — never the raw Minecraft username, which is unauthenticated in offline mode. |
| `run_id` / `simulation_id` | The run/simulation this message belongs to, for journal + cost attribution. |
| `service` | Typed service name (see §6). |
| `method` | Method within the service (e.g. `recall`, `write`). |
| `payload` | Service-specific body. Schema owned by E4-2. |
| `deadline_ms` | Caller's hard deadline in milliseconds (see §5). |
| `cost_context` | Cost-attribution hints (agent tier, run, budget bucket) so `cost.*` and observability can charge the right account. |

**Response (the other direction):**

| Field | Meaning |
| --- | --- |
| `request_id` | Echoes the originating request's `request_id`. |
| `ok` | Boolean. `true` = success, `false` = handled failure. |
| `payload` | Result body on success. Schema owned by E4-2. |
| `error` | Typed error (code + message) when `ok` is `false`. |
| `retryable` | Boolean. Whether the caller may safely retry (see §5). |

Unsolicited Python→Node control messages (veto, abort, kill) use the **request**
shape with a `service`/`method` the bot understands; the bot replies with the
**response** shape. There is no separate third message type.

### 3. Versioning

- Every message carries a semver-style `version` string (e.g. `1.0`).
- The contract is **additive-compatible**: new optional fields and new
  `service`/`method` values are minor/patch changes and must not break an older
  peer.
- The server **rejects an unknown major version** with a typed, non-retryable
  error (`ok: false`, `error.code = "unsupported_version"`, `retryable: false`)
  rather than guessing. The bot logs and fails closed (see §5).
- The version negotiation and the concrete schema registry are **owned by
  E4-2**. This ADR only fixes that the field exists, is mandatory, and that the
  unknown-major rule is fail-closed.

### 4. Authentication

- **Shared-secret bearer token.** The Node client presents a bearer token read
  from the `MINECRAFT_BRIDGE_TOKEN` environment variable on the WebSocket
  handshake (matching [0005-skill-extension-point.md](0005-skill-extension-point.md)).
  The Python server compares it with a constant-time check.
- **Authorization header is the default credential transport.** The primary
  path is `Authorization: Bearer <token>`. The `?token=` fallback exists only
  for constrained local clients that cannot set WebSocket headers, and the
  server accepts it only when `MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN=1` is
  explicitly enabled. Leave it off for real runs because tokens in URLs can
  leak through logs/history.
- **Local-only / private-network binding.** The bridge endpoint is bound to
  localhost or a private network only, never the public internet. This
  cross-references [0002-auth-mode.md](0002-auth-mode.md): in Minecraft offline
  mode the Minecraft username is *not* trustworthy identity, so the bridge token
  — not `agent_id` — is the authentication boundary, and `agent_id` is treated
  as a claim, not proof.
- **Fail-closed on auth failure.** A missing, malformed, or wrong token causes
  the handshake to be rejected and the socket closed before any `service` is
  dispatched. There is **no unauthenticated path to spend or in-world actions**.
  No anonymous degraded mode, no "auth optional in dev" switch.
- The full adversarial analysis of this boundary is the **bridge security
  review's** job (#548); this ADR states the rule the review will verify.

### 5. Failure semantics

- **Deadlines.** Every request carries `deadline_ms`. The server abandons work
  that exceeds the deadline and returns `ok: false` with a timeout `error` and
  `retryable: true` when the operation was side-effect-free, `retryable: false`
  when it may have partially applied.
- **`retryable` contract.** The caller may only retry when `retryable` is
  explicitly `true`. Absence/ambiguity is treated as not retryable.
- **Idempotency via `request_id`.** A retried request reuses the original
  `request_id` so the server can de-duplicate side-effecting calls
  (`memory.write`, `cost.reserve`, `journal.event`). Handlers for
  side-effecting services must be idempotent on `request_id`.
- **Fail-closed gating.** Mirroring the guardrails in
  [0005-skill-extension-point.md](0005-skill-extension-point.md): if
  `management.review` or the cost gate cannot be reached or does not answer
  before the deadline, the bot must **not** publish agent speech to the
  livestream and must **not** proceed with the gated in-world action. A bridge
  failure degrades to silence/no-op, never to unfiltered or unbudgeted output.
- **Operator kill switch.** `kill.status` and `bridge.ping` remain ungated
  health/state probes. While the global kill switch is active,
  `action.result`, `code.execute`, and `errand.complete` fail closed with
  `error.code="kill_switch_active"` and `retryable=true`; `perception.report`
  and `errand.poll` return safe-idle success payloads. Node bots poll
  `kill.status` every `MINECRAFT_BRIDGE_KILL_POLL_MS` (default 2 seconds), so
  the documented stop window is that poll interval plus at most one in-flight
  `deadline_ms`.
- **Reconnect & backpressure deferred.** Connection loss, reconnect/backoff,
  heartbeat, and queue/backpressure policy are explicitly **out of scope for
  this ADR and owned by E4-4** (and E4-5/E4-6 for the result channel). The
  contract here only requires that those layers preserve the fail-closed rule
  above: a disconnected bridge is a closed gate, not an open one.

### 6. Typed service names

The bridge dispatches on a **closed set of typed service names**, never a
generic "run arbitrary Python" verb (consistent with the
[0005-skill-extension-point.md](0005-skill-extension-point.md) guardrails). The
live closed set:

| Service | Direction | Purpose |
| --- | --- | --- |
| `memory.recall` | Node → Python | Semantic/recall memory read. |
| `memory.write` | Node → Python | Persist a memory (idempotent on `request_id`). |
| `management.review` | Node → Python | Content-filter gate before broadcast. |
| `cost.reserve` | Node → Python | Reserve budget before a spend. |
| `cost.gate` | Node → Python | Check whether a spend/action is allowed. |
| `journal.event` | Node → Python | Append a structured journal/event record. |
| `kill.status` | Node → Python (and Python → Node push) | Query/receive kill-switch state. |
| `perception.report` | Node → Python | Bot-observed world state (E4-6). |
| `action.result` | Node → Python | Outcome of an in-world action (E4-5). |
| `code.execute` | Node → Python | Run code in the existing gVisor sandbox. |

`perception.report` and `action.result` are listed so the envelope and naming
scheme are fixed now; their schemas and the inbound channel are E4-5/E4-6.

### First proof: `!bridgePing`

Consistent with [0005-skill-extension-point.md](0005-skill-extension-point.md)
and the plan, the first end-to-end proof is an in-game `!bridgePing("hello")`
action that round-trips a request envelope and receives a `pong` response with
the Python side logging `agent_id` and `request_id`. That proof is implemented
in the E4-2/E4-3/E4-4 issues, not here.

## Consistency Check

| Source | What this ADR must match | Status |
| --- | --- | --- |
| [0005-skill-extension-point.md](0005-skill-extension-point.md) | Endpoint `/api/minecraft/bridge/ws`, `MINECRAFT_BRIDGE_TOKEN`, the 9 envelope request fields + 5 response fields, typed service names, fail-closed broadcast rule, `!bridgePing` first spike | Matched verbatim |
| [0002-auth-mode.md](0002-auth-mode.md) | Local-only/private-network binding; offline-mode username is not identity | Matched (token is the boundary, not `agent_id`) |
| [0000-summary.md](0000-summary.md) | "Bridge transport = authenticated FastAPI WebSocket with versioned request/response envelopes" (#522) | Matched |
| `core/main.py:181` | FastAPI already serves a WebSocket; bridge is a second namespaced WS surface | Matched |
| Plan §5 E4-1 | Decide transport, envelope, versioning, auth (shared secret/local-only), failure semantics; ADR only, no code | Matched |

## Scope

- **In:** transport choice, envelope field set + semantics, versioning policy,
  auth model, failure/idempotency/fail-closed semantics, typed service names.
- **Out:** code, the concrete per-service schemas (E4-2), the Python endpoint
  (E4-3), the Node client (E4-4), reconnect/backpressure (E4-4), the
  perception/action result channel (E4-5/E4-6), observability/trace IDs (E4-7),
  and the adversarial security review (E4-9 / #548).

This issue has **no LLM runtime path**: it is design/ADR-only and makes no model
calls, so no LM Studio simulation is required. The nearest local smoke path is
the dependency-free contract test
`pnpm verify:bridge-protocol`
(`tests/backend/test_bridge_protocol_decision.py`), which runs headless in the
existing `backend-test` CI job and enforces this ADR's consistency with ADRs
0005/0002 and the summary index.

## Evidence

- FastAPI already serves a WebSocket the bridge mirrors:
  `core/main.py:181` (`@app.websocket("/ws")`), fed by `core/event_bus.py`.
- Bridge transport, endpoint, token, and envelope fields this ADR fixes:
  [0005-skill-extension-point.md](0005-skill-extension-point.md) lines 33–57
  (Bridge Transport) and 76–85 (Guardrails / typed service names).
- Offline-mode network rules and "username is not identity":
  [0002-auth-mode.md](0002-auth-mode.md) (Required Security Rules For Offline
  Mode).
- Summary index bridge-transport / bridge-extension rows (#522):
  [0000-summary.md](0000-summary.md) Final Decisions table.
- Plan section that scopes this ADR:
  [docs/MINECRAFT-PIVOT-ISSUE-PLAN.md](../MINECRAFT-PIVOT-ISSUE-PLAN.md) §5,
  "E4-1 — Bridge transport & protocol decision record".
