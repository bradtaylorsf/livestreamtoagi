// Node→Python bridge client (issue #543 E4-4 + #544 E4-5 + #546 E4-7 — epic
// E4 #506).
//
// `./mindcraft` is git-ignored, so this file is the committed source of truth.
// `scripts/minecraft/connect-bridge-bot.sh` copies it verbatim into the pinned
// clone as `src/agent/bridge/python_bridge.js` — the E1-R5 / decision 0005
// extension point (docs/decisions/0005-skill-extension-point.md: "Add a Node
// bridge client module: src/agent/bridge/python_bridge.js"). The directory
// layout under `fork-src/` mirrors the clone's `src/` so the relative import in
// the sibling action (`../bridge/python_bridge.js`) resolves identically
// staged-in-the-clone or driven directly by the contract test.
//
// What this module is:
//   * A single authenticated WebSocket call (`_callBridgeOnce`) that builds a
//     contract-valid BridgeRequest envelope, correlates the response by
//     `request_id`, enforces a local timeout == `deadline_ms`, and fails CLOSED
//     with a typed structured error on auth/handshake/protocol failure — never
//     an uncaught throw. This is the unchanged E4-4 one-shot
//     connect→send→await→close round-trip; it stays the base call mechanism.
//   * (E4-5 #544) A module-level resilience layer around that one-shot:
//       - a circuit breaker that, after N consecutive connect-class failures,
//         fail-fasts new calls with `bridge_unreachable` instead of paying the
//         full per-call deadline / opening a doomed socket;
//       - a single background `bridge.ping` reconnect probe on exponential
//         backoff + jitter (capped) that auto-closes the circuit when Python
//         comes back (auto-recover);
//       - a bounded in-flight semaphore (fail-closed backpressure): once
//         MAX_INFLIGHT round-trips are concurrent, extra calls reject
//         immediately with `bridge_overloaded` — never an unbounded queue,
//         never more sockets.
//     A disconnected/saturated bridge is therefore a CLOSED gate, never an
//     unsafe action: callers (the action layer) degrade to safe-idle. This is
//     exactly the fail-closed rule ADR 0010 §5 says E4-5 must preserve.
//   * (E4-7 #546) Observability with no wire-contract change: each call carries
//     an additive `trace_id` (introduced in protocol 1.1) the Python server echoes/mints, so
//     one request greps end-to-end across BOTH logs by a single id; every call
//     start and settle path emits a fixed `key=value` line to STDERR (matching
//     core/bridge/observability.py) and feeds in-process counters exposed via
//     `bridgeMetrics()`. Logging is best-effort and never crashes the bot.
//   * IS NOT: a persistent pooled connection or the inbound Python→Node push
//     channel — that is E4-6 (#545). Each successful call is still its own
//     one-shot socket; the probe is the only added socket and only one is ever
//     in flight.
//
// Wire format is fixed by ADR docs/decisions/0010-bridge-protocol.md (§2
// envelope, §3 versioning, §4 bearer auth, §5 deadline/fail-closed) and the
// versioned contract in core/bridge/contract.py (#541, E4-2). The committed
// JSON Schema core/bridge/schemas/bridge-protocol.schema.json is treated as
// REFERENCE only: this module does deliberately lightweight *structural*
// checks (object / boolean `ok` / `request_id` echo / typed `error` shape) and
// does NOT add a JSON-Schema validator dependency — the Mindcraft lockfile
// (scripts/minecraft/mindcraft-package-lock.json) is frozen. The same
// constraint forbids a new npm dependency, so backoff/jitter/the semaphore are
// all hand-rolled below.
//
// Transport: prefer the `ws` package (a transitive dep already pinned in that
// lockfile at 8.20.1 — it supports the `Authorization: Bearer` handshake header
// ADR §4 mandates). Fall back to the Node ≥20 global WHATWG `WebSocket` when
// `ws` is absent (e.g. the CI/contract-test environment with no Mindcraft
// install); that implementation cannot set request headers, so it uses the
// server's documented `?token=` query-param fallback. The server accepts that
// fallback only when `MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN=1` is explicitly
// enabled because bearer tokens in URLs are easier to leak. It is still the
// SAME shared secret, still fail-closed, no anonymous path.

import { randomUUID } from 'node:crypto';

// ── Protocol / env constants (kept identical to the Python side) ─────────────

// contract.PROTOCOL_VERSION (ADR §3). 1.6 is the E7-3 (#567) minor bump:
// `errand.complete` lets Alpha report verified errand outcomes over the bridge.
// The server only gates on the major, so this stays wire-compatible with
// earlier 1.x peers.
export const PROTOCOL_VERSION = '1.6';
export const BRIDGE_URL_ENV = 'MINECRAFT_BRIDGE_URL';
export const BRIDGE_TOKEN_ENV = 'MINECRAFT_BRIDGE_TOKEN'; // ADR §4 / server.BRIDGE_TOKEN_ENV
export const DEFAULT_BRIDGE_URL = 'ws://127.0.0.1:8010/api/minecraft/bridge/ws';

// E4-5 (#544) tuning knobs — all optional with sane production defaults; the
// integration test overrides them with small values so the policy is fast to
// exercise. Read at call time (like the token) so a test/subprocess env is
// honored without a module reload.
export const BRIDGE_MAX_INFLIGHT_ENV = 'MINECRAFT_BRIDGE_MAX_INFLIGHT';
export const BRIDGE_RECONNECT_BASE_MS_ENV = 'MINECRAFT_BRIDGE_RECONNECT_BASE_MS';
export const BRIDGE_RECONNECT_MAX_MS_ENV = 'MINECRAFT_BRIDGE_RECONNECT_MAX_MS';
export const BRIDGE_CIRCUIT_THRESHOLD_ENV = 'MINECRAFT_BRIDGE_CIRCUIT_THRESHOLD';

const DEFAULT_MAX_INFLIGHT = 8;
const DEFAULT_RECONNECT_BASE_MS = 500;
const DEFAULT_RECONNECT_MAX_MS = 30000;
const DEFAULT_CIRCUIT_THRESHOLD = 3;
// Fixed exponential factor — not env-tunable (base/cap/threshold are the knobs
// operators actually reach for; a custom multiplier is needless rope).
const BACKOFF_MULTIPLIER = 2;

const DEFAULT_DEADLINE_MS = 5000;
const DEFAULT_AGENT_ID = 'bridge-bot';
const DEFAULT_RUN_ID = 'run-local';
// simulation_id only needs to be a non-empty string (contract min_length=1); a
// zeroed UUID is an obvious "local default, not a real run" marker.
const DEFAULT_SIMULATION_ID = '00000000-0000-0000-0000-000000000000';

function _posIntEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const n = Number.parseInt(raw, 10);
    return Number.isFinite(n) && n > 0 ? n : fallback;
}

function _config() {
    return {
        maxInflight: _posIntEnv(BRIDGE_MAX_INFLIGHT_ENV, DEFAULT_MAX_INFLIGHT),
        reconnectBaseMs: _posIntEnv(BRIDGE_RECONNECT_BASE_MS_ENV, DEFAULT_RECONNECT_BASE_MS),
        reconnectMaxMs: _posIntEnv(BRIDGE_RECONNECT_MAX_MS_ENV, DEFAULT_RECONNECT_MAX_MS),
        circuitThreshold: _posIntEnv(BRIDGE_CIRCUIT_THRESHOLD_ENV, DEFAULT_CIRCUIT_THRESHOLD),
    };
}

// ── E4-7 (#546): structured logs + in-process metrics ───────────────────────
//
// Correlation is the point: every call logs the same `trace_id` the envelope
// carries, and the Python server logs that identical id, so one request greps
// end-to-end across both languages. Logs go to STDERR only — stdout is the
// data channel some callers/harnesses parse — in the same fixed `key=value`
// shape the Python side emits (core/bridge/observability.py) so a single id
// lines up across the two logs. No new dependency (frozen lockfile): the
// logger is a stderr write and the metrics are a plain module object.

// Any whitespace (incl. newline/CR/tab) or control char in a string value
// would break the single-line, space-delimited `key=value` shape the trace id
// greps on, and let a caller-controlled field (`trace_id`/`request_id`/…)
// forge an extra `bridge_event` line. Collapse each to `_` and cap the length
// so a hostile/oversized id can neither corrupt the line nor flood stderr.
// Mirrors `_safe_str` in core/bridge/observability.py verbatim so both sides
// render the same token for the same id.
const _MAX_LOG_VALUE_LEN = 256;

function _safeStr(s) {
    // `\s` covers space/tab/newline/CR; \u0000-\u001f and \u007f add the
    // remaining C0 controls + DEL. A literal hyphen is NOT in the class
    // (it is the range operator), so `trace-<uuid>` ids survive.
    // eslint-disable-next-line no-control-regex
    const cleaned = s.replace(/[\s\u0000-\u001f\u007f]/g, '_');
    return cleaned.length <= _MAX_LOG_VALUE_LEN
        ? cleaned
        : cleaned.slice(0, _MAX_LOG_VALUE_LEN) + '~';
}

function _fmtLogVal(v) {
    if (v === undefined || v === null) return '-';
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3);
    return _safeStr(String(v));
}

// Fixed key order so the line is stable/diffable and matches the Python side.
const _LOG_KEY_ORDER = [
    'trace_id',
    'request_id',
    'direction',
    'service',
    'method',
    'phase',
    'ok',
    'outcome',
    'latency_ms',
    'echoed_trace_id',
];

function _logBridge(fields) {
    try {
        const parts = [];
        for (const k of _LOG_KEY_ORDER) {
            if (k in fields) parts.push(`${k}=${_fmtLogVal(fields[k])}`);
        }
        // STDERR, never stdout — logging must never corrupt a caller's data
        // channel and (issue #543 contract) must never crash the bot.
        process.stderr.write(`bridge_event ${parts.join(' ')}\n`);
    } catch {
        /* best-effort: a logging failure must never mask/crash the call */
    }
}

function _newMetrics() {
    return {
        calls: {}, // "<service>.<method>" -> count
        callsTotal: 0,
        errors: {}, // error code -> count
        errorsTotal: 0,
        latencyMs: { count: 0, sum: 0, max: 0 },
    };
}

let _metrics = _newMetrics();

function _recordCall({ verb, ok, code, latencyMs }) {
    _metrics.calls[verb] = (_metrics.calls[verb] || 0) + 1;
    _metrics.callsTotal += 1;
    if (!ok) {
        const c = code || 'unknown';
        _metrics.errors[c] = (_metrics.errors[c] || 0) + 1;
        _metrics.errorsTotal += 1;
    }
    const l = _metrics.latencyMs;
    l.count += 1;
    l.sum += latencyMs;
    if (latencyMs > l.max) l.max = latencyMs;
}

/**
 * A deep copy of the in-process bridge counters (calls by verb, errors by
 * code, latency aggregate). Every settled `callBridge` is counted exactly once
 * so `errorsTotal / callsTotal` is the true error rate. A real exporter can
 * read this later without changing the contract.
 * @returns {{calls: object, callsTotal: number, errors: object,
 *            errorsTotal: number, latencyMs: {count:number,sum:number,max:number}}}
 */
export function bridgeMetrics() {
    return {
        calls: { ..._metrics.calls },
        callsTotal: _metrics.callsTotal,
        errors: { ..._metrics.errors },
        errorsTotal: _metrics.errorsTotal,
        latencyMs: { ..._metrics.latencyMs },
    };
}

/** Reset the in-process counters (test isolation; not used in production). */
export function resetBridgeMetrics() {
    _metrics = _newMetrics();
}

// ── Typed structured error (carries a stable machine-readable code) ─────────

export class BridgeClientError extends Error {
    constructor(code, message, extra = {}) {
        super(message);
        this.name = 'BridgeClientError';
        this.code = code;
        // ADR §5: absence/ambiguity is treated as NOT retryable.
        this.retryable = extra.retryable === true;
        if (extra.response !== undefined) this.response = extra.response;
    }
}

// Connect-class failure codes — "Python looks down / unreachable", the only
// failures the circuit counts. Auth/protocol/`ok:false`/no-transport are
// config/contract errors a backoff probe would never fix, so they pass
// through untouched and never trip the breaker (counting them would mask the
// real cause).
const CONNECT_CLASS_CODES = new Set(['bridge_connect_failed', 'bridge_timeout']);

// ── WebSocket implementation resolution (ws → global fallback) ──────────────

let _wsImpl = null;
let _wsSupportsHeaders = false;

async function resolveWebSocket() {
    if (_wsImpl) return;
    try {
        const mod = await import('ws');
        _wsImpl = mod.WebSocket || mod.default;
        _wsSupportsHeaders = true; // `ws` honors { headers: { Authorization } }
    } catch {
        _wsImpl = globalThis.WebSocket; // Node ≥20 WHATWG WebSocket (no headers)
        _wsSupportsHeaders = false;
    }
    if (!_wsImpl) {
        throw new BridgeClientError(
            'bridge_no_transport',
            'no WebSocket implementation: install the "ws" package or run Node >=20 (global WebSocket)',
        );
    }
}

function makeSocket(url, token) {
    if (_wsSupportsHeaders) {
        // ADR §4 primary: bearer token on the handshake request header.
        return new _wsImpl(url, { headers: { Authorization: `Bearer ${token}` } });
    }
    // Global WebSocket cannot set request headers — use the server's
    // documented ?token= fallback (same shared secret, still fail-closed).
    const u = new URL(url);
    u.searchParams.set('token', token);
    return new _wsImpl(u.toString());
}

// Normalize the `ws` EventEmitter API and the WHATWG addEventListener API so
// the call logic below is transport-agnostic.
function attachHandlers(sock, { onOpen, onMessage, onClose, onError }) {
    if (typeof sock.on === 'function') {
        // `ws` package (Node EventEmitter): message data is a Buffer/string.
        sock.on('open', () => onOpen());
        sock.on('message', (data) =>
            onMessage(typeof data === 'string' ? data : data.toString('utf8')),
        );
        sock.on('close', (code, reason) =>
            onClose(code, reason ? reason.toString() : ''),
        );
        sock.on('error', (err) => onError(err));
        // Emitted by `ws` when the HTTP upgrade is refused (e.g. 403 from a
        // fail-closed handshake rejection in core/bridge/server.py).
        sock.on('unexpected-response', (_req, res) =>
            onError(
                new Error(`unexpected server response: ${res && res.statusCode}`),
                res && res.statusCode,
            ),
        );
    } else {
        // WHATWG global WebSocket: message arrives as a MessageEvent.
        sock.addEventListener('open', () => onOpen());
        sock.addEventListener('message', (ev) =>
            onMessage(typeof ev.data === 'string' ? ev.data : String(ev.data)),
        );
        sock.addEventListener('close', (ev) => onClose(ev.code, ev.reason || ''));
        sock.addEventListener('error', (ev) =>
            onError((ev && ev.error) || new Error((ev && ev.message) || 'websocket error')),
        );
    }
}

// ── Envelope construction (ADR §2 — exact field set) ───────────────────────

function buildEnvelope({ service, method, payload, deadlineMs, agentId, traceId, costContext }) {
    return {
        version: PROTOCOL_VERSION,
        request_id: `bridge-${randomUUID()}`, // unique correlation + idempotency key (ADR §5)
        agent_id: agentId || process.env.LTAG_AGENT_ID || DEFAULT_AGENT_ID,
        run_id: process.env.LTAG_RUN_ID || DEFAULT_RUN_ID,
        simulation_id: process.env.LTAG_SIMULATION_ID || DEFAULT_SIMULATION_ID,
        service,
        method,
        payload: payload || {},
        deadline_ms: deadlineMs,
        cost_context: costContext || {
            agent_tier: 'conversation',
            budget_bucket: 'bridge',
            estimated_cost_usd: 0.0,
        },
        // E4-7 (#546): end-to-end correlation id. Accept a caller-supplied id
        // (so a chain of related calls shares one trace) and otherwise mint a
        // unique one per call. Additive/optional since protocol 1.1 — the server
        // echoes it back, or mints its own when this is somehow absent.
        trace_id: traceId || `trace-${randomUUID()}`,
    };
}

// Lightweight *structural* validation only — the JSON Schema is reference, not
// a runtime dependency (frozen lockfile). Returns a BridgeClientError to reject
// with, or null when the envelope shape is acceptable.
function validateResponseShape(response, expectedRequestId) {
    if (response === null || typeof response !== 'object' || Array.isArray(response)) {
        return new BridgeClientError('bridge_protocol', 'bridge response was not a JSON object');
    }
    if (typeof response.ok !== 'boolean') {
        return new BridgeClientError(
            'bridge_protocol',
            'bridge response is missing a boolean "ok" field',
        );
    }
    if (response.request_id !== expectedRequestId) {
        return new BridgeClientError(
            'bridge_protocol',
            `bridge response request_id ${JSON.stringify(response.request_id)} does not echo ` +
                `the request ${JSON.stringify(expectedRequestId)}`,
        );
    }
    if (
        response.ok === false &&
        (response.error === null ||
            typeof response.error !== 'object' ||
            typeof response.error.code !== 'string')
    ) {
        return new BridgeClientError(
            'bridge_protocol',
            'failed bridge response (ok=false) did not carry a typed error',
        );
    }
    return null;
}

// ── The one-shot round-trip (unchanged E4-4 base call mechanism) ───────────

/**
 * Round-trip one contract message through the Python bridge ONCE.
 *
 * This is the unmodified E4-4 connect→send→await→close call: no reconnect, no
 * circuit, no semaphore. The resilience layer ({@link callBridge}) and the
 * reconnect probe both delegate here so there is exactly one socket code path.
 *
 * Resolves with the parsed BridgeResponse envelope on success (`ok===true`).
 * Rejects with a {@link BridgeClientError} (never an uncaught throw) on:
 *   - missing token / no transport               → fail closed before connect
 *   - handshake auth refusal (1008 / HTTP 403)   → `bridge_auth_refused`
 *   - connection error or early close            → `bridge_connect_failed`
 *   - local deadline exceeded                    → `bridge_timeout`
 *   - malformed / non-echoing response           → `bridge_protocol`
 *   - server `ok:false`                          → passes through `error.code`
 */
async function _callBridgeOnce({
    service,
    method,
    payload = {},
    deadlineMs = DEFAULT_DEADLINE_MS,
    agentId,
    traceId,
    costContext,
} = {}) {
    const token = process.env[BRIDGE_TOKEN_ENV];
    if (!token) {
        // ADR §4: no anonymous / "auth optional in dev" path. Fail closed
        // before a socket is even opened.
        throw new BridgeClientError(
            'bridge_no_token',
            `${BRIDGE_TOKEN_ENV} is not set; refusing to open an unauthenticated bridge connection`,
        );
    }
    await resolveWebSocket();

    const url = process.env[BRIDGE_URL_ENV] || DEFAULT_BRIDGE_URL;
    const envelope = buildEnvelope({
        service,
        method,
        payload,
        deadlineMs,
        agentId,
        traceId,
        costContext,
    });

    return await new Promise((resolve, reject) => {
        let settled = false;
        let sock;

        // The deadline timer covers the WHOLE call (connect + round trip), so a
        // hung handshake or a silent server both surface as a structured
        // timeout rather than hanging the bot (ADR §5).
        const timer = setTimeout(() => {
            finish(() =>
                reject(
                    new BridgeClientError(
                        'bridge_timeout',
                        `bridge call ${service}.${method} exceeded local deadline of ${deadlineMs}ms`,
                    ),
                ),
            );
        }, deadlineMs);

        function finish(action) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            try {
                if (sock) sock.close();
            } catch {
                /* closing a half-open socket must never mask the result */
            }
            action();
        }

        try {
            sock = makeSocket(url, token);
        } catch (err) {
            finish(() =>
                reject(
                    new BridgeClientError(
                        'bridge_connect_failed',
                        `could not open bridge socket: ${(err && err.message) || err}`,
                    ),
                ),
            );
            return;
        }

        attachHandlers(sock, {
            onOpen() {
                try {
                    sock.send(JSON.stringify(envelope));
                } catch (err) {
                    finish(() =>
                        reject(
                            new BridgeClientError(
                                'bridge_send_failed',
                                `failed to send bridge request: ${(err && err.message) || err}`,
                            ),
                        ),
                    );
                }
            },
            onMessage(text) {
                let response;
                try {
                    response = JSON.parse(text);
                } catch (err) {
                    finish(() =>
                        reject(
                            new BridgeClientError(
                                'bridge_protocol',
                                `bridge response was not valid JSON: ${(err && err.message) || err}`,
                            ),
                        ),
                    );
                    return;
                }
                const shapeError = validateResponseShape(response, envelope.request_id);
                if (shapeError) {
                    finish(() => reject(shapeError));
                    return;
                }
                if (response.ok === false) {
                    // Pass the server's typed error.code/message straight
                    // through so callers branch on a stable code (ADR §2/§5).
                    finish(() =>
                        reject(
                            new BridgeClientError(response.error.code, response.error.message, {
                                retryable: response.retryable === true,
                                response,
                            }),
                        ),
                    );
                    return;
                }
                finish(() => resolve(response));
            },
            onError(err, statusCode) {
                const authish = statusCode === 401 || statusCode === 403;
                finish(() =>
                    reject(
                        new BridgeClientError(
                            authish ? 'bridge_auth_refused' : 'bridge_connect_failed',
                            `bridge connection error: ${(err && err.message) || err}`,
                        ),
                    ),
                );
            },
            onClose(code, reason) {
                // Reached only if we close BEFORE resolving (settled guards the
                // normal close in finish()): a fail-closed handshake refusal
                // (ADR §4 → WS 1008) or the peer vanishing.
                const authish = code === 1008;
                finish(() =>
                    reject(
                        new BridgeClientError(
                            authish ? 'bridge_auth_refused' : 'bridge_connect_failed',
                            `bridge socket closed before a response (code=${code}` +
                                `${reason ? `, reason=${reason}` : ''})`,
                        ),
                    ),
                );
            },
        });
    });
}

// ── E4-5 (#544): circuit breaker + reconnect probe + bounded in-flight ──────
//
// Breaker terminology follows the electrical metaphor: a CLOSED circuit lets
// calls flow (bridge healthy / reachable); an OPEN circuit is tripped (bridge
// unreachable, calls fail-fast). `bridgeIsReachable()` === circuit closed.

const _circuit = {
    state: 'closed', // 'closed' = healthy/reachable, 'open' = tripped
    consecutiveFailures: 0,
    backoffMs: 0, // current reconnect backoff (0 ⇒ not backing off yet)
    probeTimer: null, // pending background-probe setTimeout handle
    probeInFlight: false, // exactly one probe socket at a time
};

let _inflight = 0; // hand-rolled counting semaphore (no new dependency)

function _makeUnreachableError() {
    // getBridgeUnreachableError()-style single source for the fail-fast error
    // so the message/retryable contract stays consistent everywhere.
    return new BridgeClientError(
        'bridge_unreachable',
        'bridge circuit is open (Python unreachable); failing fast — safe-idle and retry later',
        { retryable: true },
    );
}

function _jitter(ms) {
    // Equal jitter: 50%–100% of `ms`. Bounded (never ~0, never >ms) so the
    // reconnect cadence stays predictable for the integration test while still
    // spreading retries.
    return Math.round(ms * (0.5 + Math.random() * 0.5));
}

function _recordSuccess() {
    // Any successful round-trip (real call OR probe) means Python is back:
    // auto-recover — close the circuit and reset all backoff state.
    _circuit.consecutiveFailures = 0;
    _circuit.backoffMs = 0;
    if (_circuit.probeTimer) {
        clearTimeout(_circuit.probeTimer);
        _circuit.probeTimer = null;
    }
    _circuit.state = 'closed';
}

function _recordConnectFailure() {
    _circuit.consecutiveFailures += 1;
    const { circuitThreshold } = _config();
    if (_circuit.state === 'closed' && _circuit.consecutiveFailures >= circuitThreshold) {
        _circuit.state = 'open';
        _scheduleProbe();
    }
}

function _scheduleProbe() {
    if (_circuit.state !== 'open') return;
    if (_circuit.probeTimer || _circuit.probeInFlight) return; // one probe only
    const { reconnectBaseMs, reconnectMaxMs } = _config();
    if (_circuit.backoffMs <= 0) _circuit.backoffMs = reconnectBaseMs;
    _circuit.backoffMs = Math.min(_circuit.backoffMs, reconnectMaxMs);
    _circuit.probeTimer = setTimeout(() => {
        _circuit.probeTimer = null;
        _runProbe();
    }, _jitter(_circuit.backoffMs));
    // Never let the reconnect timer alone keep a short-lived bot process alive.
    if (typeof _circuit.probeTimer.unref === 'function') _circuit.probeTimer.unref();
}

async function _runProbe() {
    if (_circuit.state !== 'open' || _circuit.probeInFlight) return;
    _circuit.probeInFlight = true;
    const { reconnectBaseMs, reconnectMaxMs } = _config();
    // A probe is just a lightweight `bridge.ping`; a small deadline keeps the
    // reconnect cadence honest when Python is hung rather than refusing.
    const probeDeadlineMs = Math.max(250, Math.min(reconnectMaxMs, 2000));
    try {
        await _callBridgeOnce({
            service: 'bridge',
            method: 'ping',
            payload: { message: 'bridge-health-probe' },
            deadlineMs: probeDeadlineMs,
            agentId: 'bridge-reconnect-probe',
        });
        _recordSuccess(); // Python answered — close the circuit (auto-recover).
    } catch {
        // Still down: grow backoff (capped) and reschedule another probe.
        _circuit.backoffMs = Math.min(
            (_circuit.backoffMs > 0 ? _circuit.backoffMs : reconnectBaseMs) * BACKOFF_MULTIPLIER,
            reconnectMaxMs,
        );
    } finally {
        _circuit.probeInFlight = false;
        if (_circuit.state === 'open') _scheduleProbe();
    }
}

/**
 * Reachability snapshot for the action layer's safe-idle decision.
 * @returns {{circuit: string, reachable: boolean, consecutiveFailures: number,
 *            inflight: number, backoffMs: number}}
 */
export function bridgeStatus() {
    return {
        circuit: _circuit.state,
        reachable: _circuit.state === 'closed',
        consecutiveFailures: _circuit.consecutiveFailures,
        inflight: _inflight,
        backoffMs: _circuit.backoffMs,
    };
}

/** True when the circuit is closed (calls will be attempted, not fail-fast). */
export function bridgeIsReachable() {
    return _circuit.state === 'closed';
}

// ── The one public entry point ─────────────────────────────────────────────

/**
 * Round-trip one contract message through the Python bridge, with the E4-5
 * resilience policy applied:
 *
 *   1. Circuit OPEN ⇒ reject immediately with a retryable `bridge_unreachable`
 *      (no socket, no per-call deadline paid) so the bot can safe-idle.
 *   2. In-flight cap reached ⇒ reject immediately with a retryable
 *      `bridge_overloaded` (fail-closed backpressure — never queue, never open
 *      more sockets).
 *   3. Otherwise run the one-shot {@link _callBridgeOnce}. A success closes the
 *      circuit (auto-recover); a connect-class failure
 *      (`bridge_connect_failed` / `bridge_timeout`) advances the breaker and,
 *      past the threshold, opens it and starts the background reconnect probe.
 *      All other errors pass straight through unchanged (E4-4 contract intact).
 *
 * Still never an uncaught throw: every path settles as a typed
 * {@link BridgeClientError} or the parsed response envelope.
 *
 * @param {object}  opts
 * @param {string}  opts.service     typed service name (ADR §6 closed set)
 * @param {string}  opts.method      method within the service
 * @param {object}  [opts.payload]   service-specific body
 * @param {number}  [opts.deadlineMs] hard local deadline (ADR §5), default 5000
 * @param {string}  [opts.agentId]   stable agent identity (a claim, not proof)
 * @param {object}  [opts.costContext] optional cost attribution override
 * @param {string}  [opts.traceId]   E4-7 correlation id; reuse one to tie a
 *                                   chain of related calls together. Defaults
 *                                   to a unique `trace-<uuid>` per call.
 * @returns {Promise<object>} the parsed response envelope
 */
export async function callBridge(opts = {}) {
    // E4-7 (#546): one correlation id for this whole call, logged at start and
    // on every settle path and carried in the envelope so the Python server
    // logs the SAME id — one request greps end-to-end across both languages.
    const { service, method } = opts;
    const verb = `${service}.${method}`;
    const traceId = opts.traceId || `trace-${randomUUID()}`;
    const startedAt = Date.now();
    _logBridge({ trace_id: traceId, direction: 'outbound', service, method, phase: 'start' });

    // Settle a FAILURE path: record one metrics sample + one structured log,
    // then hand the original typed error back to the caller unchanged.
    const settleError = (err) => {
        const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
        const latencyMs = Date.now() - startedAt;
        _recordCall({ verb, ok: false, code, latencyMs });
        _logBridge({
            trace_id: traceId,
            direction: 'outbound',
            service,
            method,
            phase: 'settle',
            ok: false,
            outcome: code,
            latency_ms: latencyMs,
        });
        return err;
    };

    // 1. Fail fast while the circuit is open — do NOT pay the deadline or open
    //    a doomed socket. A disconnected bridge is a closed gate (ADR §5): the
    //    caller degrades to safe-idle, never an unsafe action.
    if (_circuit.state === 'open') {
        _scheduleProbe(); // defensive: ensure a probe is pending to recover
        throw settleError(_makeUnreachableError());
    }

    // 2. Bounded in-flight: fail-closed backpressure. Never an unbounded queue,
    //    never more concurrent sockets than MAX_INFLIGHT.
    const { maxInflight } = _config();
    if (_inflight >= maxInflight) {
        throw settleError(
            new BridgeClientError(
                'bridge_overloaded',
                `bridge in-flight cap reached (${_inflight}/${maxInflight}); ` +
                    'rejecting to apply backpressure — safe-idle and retry later',
                { retryable: true },
            ),
        );
    }

    // 3. Acquire a slot, run the one-shot, and feed the breaker on every
    //    settle path (decrement no matter how it ends).
    _inflight += 1;
    try {
        const response = await _callBridgeOnce({ ...opts, traceId });
        _recordSuccess();
        const latencyMs = Date.now() - startedAt;
        _recordCall({ verb, ok: true, latencyMs });
        // Tolerate a missing `trace_id` in the response (additive — a 1.0 peer
        // omits it); log the echoed value when present so the round-trip is
        // verifiably one trace.
        _logBridge({
            trace_id: traceId,
            request_id: response && response.request_id,
            direction: 'outbound',
            service,
            method,
            phase: 'settle',
            ok: true,
            outcome: 'ok',
            latency_ms: latencyMs,
            echoed_trace_id: response && response.trace_id,
        });
        return response;
    } catch (err) {
        const code = err instanceof BridgeClientError ? err.code : undefined;
        if (code && CONNECT_CLASS_CODES.has(code)) {
            _recordConnectFailure();
        }
        throw settleError(err); // pass the original typed error through unchanged
    } finally {
        _inflight -= 1;
    }
}

export default {
    callBridge,
    bridgeStatus,
    bridgeIsReachable,
    bridgeMetrics,
    resetBridgeMetrics,
    BridgeClientError,
    PROTOCOL_VERSION,
    DEFAULT_BRIDGE_URL,
};
