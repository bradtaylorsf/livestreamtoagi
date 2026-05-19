# Minecraft Bridge Threat Model

Issue: #548, E4-9

Scope: the local Python FastAPI WebSocket bridge at
`/api/minecraft/bridge/ws`, the committed Node client under
`scripts/minecraft/fork-src/agent/bridge/python_bridge.js`, and the typed
request/response contract in `core/bridge/contract.py`.

## Assets

- Management and cost gates that decide whether speech/spend/actions may
  proceed.
- Agent memory writes and recalls.
- In-world action results and perception reports.
- Bridge bearer secret (`MINECRAFT_BRIDGE_TOKEN`).
- Trace/request IDs used for audit and idempotency.

## Trust Boundaries

- Minecraft offline usernames are not identity. `agent_id` is an attribution
  claim inside an already-authenticated bridge message, not proof.
- The shared bearer token is the local trust boundary.
- The bridge must be bound only to localhost/private network. It is not a
  public internet API.

## Threats And Mitigations

| Threat | Risk | Mitigation |
| --- | --- | --- |
| Unauthenticated calls trigger spend or actions | A local or network peer could bypass Management/cost gates. | The server requires `MINECRAFT_BRIDGE_TOKEN`, checks it with `hmac.compare_digest`, rejects before `accept()` with WebSocket code `1008`, and dispatches no service on failure. There is no anonymous/dev bypass. |
| Token leakage through URL logs/history | Query-string tokens can be captured by logs, shell history, or proxy tooling. | The primary path is `Authorization: Bearer`. `?token=` is disabled by default and accepted only when `MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN=1` is explicitly set for constrained local harnesses. |
| Replay of side-effecting messages | A retry could duplicate memory writes, spend reservations, or action records. | The envelope carries `request_id` as the idempotency key. E5/E8/E11 handlers must de-duplicate side-effecting operations on `request_id` when they replace the E4 stubs. |
| Service or payload injection | A bot could ask Python to run an arbitrary service or smuggle extra fields. | The contract uses Pydantic `extra="forbid"` and a closed service registry. Unknown `service.method` pairs return `unsupported_service`; payload shape errors return `invalid_payload`. |
| Prototype/log injection from caller-controlled IDs | Newlines/control characters in trace IDs could forge log lines. | Python and Node observability sanitize log values, cap length, and use fixed key order. |
| Denial of service by hangs or unbounded concurrency | A down bridge could hang the bot or saturate local sockets. | Node enforces `deadline_ms`, a circuit breaker, reconnect backoff, one probe in flight, and `MINECRAFT_BRIDGE_MAX_INFLIGHT` fail-closed backpressure. |
| Version confusion | Peers on incompatible protocols could misinterpret messages. | Every message carries `version`; unknown major versions fail closed with `unsupported_version`. |

## Security Review Result

The E4 bridge has no unauthenticated path to spend or in-world actions. The
remaining side-effecting handlers are still stubs in E4; when E5/E8/E11 wire
real memory, Management, and cost operations, they must preserve the same auth
boundary and add handler-level idempotency keyed by `request_id`.

Local validation path:

```bash
pnpm verify:bridge-security
pnpm verify:bridge-server
pnpm verify:bridge-node-client
```

LM Studio note: this security review has no LLM runtime path. The nearest local
smoke path is the dependency-free bridge test suite above.
