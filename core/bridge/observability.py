"""Bridge observability — correlation/trace ids, structured logs, counters
(issue #546, E4-7; epic E4 #506).

Debugging a cross-language 24/7 system needs *correlation*: one request must be
followable end-to-end through both the Node logs and the Python logs by a
single id. ADR ``docs/decisions/0010-bridge-protocol.md`` explicitly scopes
"observability/trace IDs" to E4-7 (ADR §Scope → Out). This module is the Python
half of that:

* :func:`log_bridge_event` — one stable, grep-able structured record per
  *settled* bridge frame (success, ``ok=false``, unparseable). The line is a
  fixed ``key=value`` format so a single ``trace_id`` greps cleanly across the
  Node stderr logs and the Python logs (the acceptance bar). The same fields
  are also attached via ``extra={"bridge": {...}}`` so a structured log handler
  can consume them without re-parsing the message.
* :func:`log_bridge_inbound_event` — the same correlation line for the E4-6
  perception/action inbound emit, so a report's bus event joins the same trace.
* A dependency-free, in-process metrics registry — :func:`record_call`,
  :func:`bridge_metrics_snapshot`, :func:`reset_metrics` — counting calls by
  verb, errors by code, and a latency accumulator (count/sum/max + fixed
  buckets). No ``prometheus``/``statsd`` dependency: the bridge keeps the
  no-new-dependency discipline the rest of E4 follows; a real exporter can read
  the snapshot later without changing this contract.

There is no LLM runtime path here: this is pure logging/metrics plumbing with
no model calls. The nearest local smoke path is the dependency-free
``tests/backend/test_bridge_observability.py``
(``pnpm verify:bridge-observability``), which proves one trace id correlates a
Node round-trip with the Python server logs — no Docker/network/LLM.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

# Stable line prefixes. Kept as constants so the tests and any external log
# query reference the exact same token rather than a literal that can drift.
BRIDGE_EVENT_PREFIX = "bridge_event"
BRIDGE_INBOUND_EVENT_PREFIX = "bridge_inbound_event"

# Fixed latency histogram boundaries in milliseconds. Deliberately coarse and
# not env-tunable: this is a basic health signal (is the bridge fast / slow /
# pathological), not a tuned SLO histogram. ``+Inf`` catches everything above
# the last bound so the buckets always sum to the call count.
_LATENCY_BUCKETS_MS: tuple[float, ...] = (5.0, 25.0, 100.0, 500.0, 1000.0, 5000.0)

# Any whitespace (incl. newline/CR/tab) or control char in a rendered string
# value would break the single-line, space-delimited ``key=value`` shape — the
# exact property the trace id greps on — and let an authenticated peer forge
# extra ``bridge_event`` lines through a caller-controlled field (``trace_id``,
# ``request_id``, ``agent_id``; ``service``/``method`` on the unparseable
# path). Collapse each to ``_`` and cap the length so a hostile/oversized id
# can neither corrupt the line nor flood the log. Mirrored verbatim by
# ``_fmtLogVal``/``_safeStr`` in ``python_bridge.js`` so both sides render the
# same token for the same id.
_UNSAFE_LOG_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")
_MAX_LOG_VALUE_LEN = 256


def _safe_str(value: str) -> str:
    cleaned = _UNSAFE_LOG_CHARS.sub("_", value)
    return cleaned if len(cleaned) <= _MAX_LOG_VALUE_LEN else cleaned[:_MAX_LOG_VALUE_LEN] + "~"


def _fmt(value: Any) -> str:
    """Render one field value for the deterministic ``key=value`` log line.

    ``None`` → ``-`` (a missing value is explicit, never an empty token that a
    splitter would lose); bools lowercase so they grep the same on both sides;
    floats fixed to 3 decimals so latency lines are stable/diffable. String
    values are sanitised (:func:`_safe_str`) so a caller-controlled field can
    never break the single-line shape or inject a forged record.
    """
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    return _safe_str(str(value))


def _kv_line(prefix: str, fields: dict[str, Any]) -> str:
    """``<prefix> k1=v1 k2=v2 …`` with a fixed key order (caller-controlled)."""
    return prefix + " " + " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())


def log_bridge_event(
    logger: logging.Logger,
    *,
    trace_id: str,
    request_id: str,
    agent_id: str,
    service: str,
    method: str,
    ok: bool,
    latency_ms: float,
    error_code: str | None = None,
    direction: str = "inbound",
) -> None:
    """Emit one structured record for a settled bridge frame.

    Success logs at INFO; a handled failure (``ok=false``) or an unparseable
    frame logs at WARNING so an operator's default-level logs still show the
    failures. ``trace_id`` is first in the line so a single id greps cleanly
    across both languages — the E4-7 acceptance bar. The structured fields are
    also attached as ``extra={"bridge": {...}}`` (a single non-reserved key, so
    it can never clash with a stdlib ``LogRecord`` attribute) for a structured
    handler to consume without re-parsing the message.
    """
    fields: dict[str, Any] = {
        "trace_id": trace_id,
        "request_id": request_id,
        "agent_id": agent_id,
        "direction": direction,
        "service": service,
        "method": method,
        "ok": ok,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }
    level = logging.INFO if ok else logging.WARNING
    logger.log(level, _kv_line(BRIDGE_EVENT_PREFIX, fields), extra={"bridge": fields})


def log_bridge_inbound_event(
    logger: logging.Logger,
    *,
    trace_id: str,
    request_id: str,
    agent_id: str,
    event_type: str,
) -> None:
    """Emit the correlation line for an E4-6 inbound perception/action emit.

    The bus event itself carries ``trace_id`` (see ``core/bridge/inbound.py``);
    this line ties that emit to the same trace id the server logged for the
    frame so a report is followable from the Node send through the Python bus.
    """
    fields: dict[str, Any] = {
        "trace_id": trace_id,
        "request_id": request_id,
        "agent_id": agent_id,
        "event_type": event_type,
    }
    logger.info(_kv_line(BRIDGE_INBOUND_EVENT_PREFIX, fields), extra={"bridge": fields})


# ── In-process metrics registry (dependency-free) ───────────────────────────


def _new_metrics() -> dict[str, Any]:
    return {
        "calls": {},  # "<service>.<method>" -> count
        "calls_total": 0,
        "errors": {},  # error code -> count
        "errors_total": 0,
        "latency_ms": {
            "count": 0,
            "sum": 0.0,
            "max": 0.0,
            # One bucket per upper bound (string key so the snapshot is JSON
            # safe) plus the open-ended overflow.
            "buckets": {f"<={int(b)}": 0 for b in _LATENCY_BUCKETS_MS} | {"+Inf": 0},
        },
    }


# Module-level singleton: the bridge runs in one process, so a single
# in-process registry is the whole surface. Guarded by a lock because the
# threaded test uvicorn (and any future thread) can mutate/snapshot
# concurrently with the asyncio receive loop.
_lock = threading.Lock()
_metrics: dict[str, Any] = _new_metrics()


def _bucket_key(latency_ms: float) -> str:
    for bound in _LATENCY_BUCKETS_MS:
        if latency_ms <= bound:
            return f"<={int(bound)}"
    return "+Inf"


def record_call(*, verb: str, ok: bool, latency_ms: float, error_code: str | None = None) -> None:
    """Record one settled bridge call into the in-process registry.

    ``verb`` is the canonical ``service.method`` key (or a sentinel such as
    ``unparseable`` when the frame never produced one). Every settled frame is
    counted exactly once — success or failure — so ``calls_total`` is the true
    denominator and ``errors_total / calls_total`` is the error rate.
    """
    with _lock:
        _metrics["calls"][verb] = _metrics["calls"].get(verb, 0) + 1
        _metrics["calls_total"] += 1
        if not ok:
            code = error_code or "unknown"
            _metrics["errors"][code] = _metrics["errors"].get(code, 0) + 1
            _metrics["errors_total"] += 1
        lat = _metrics["latency_ms"]
        lat["count"] += 1
        lat["sum"] += latency_ms
        if latency_ms > lat["max"]:
            lat["max"] = latency_ms
        lat["buckets"][_bucket_key(latency_ms)] += 1


def bridge_metrics_snapshot() -> dict[str, Any]:
    """A deep, JSON-safe copy of the current counters (safe to serialise/assert)."""
    with _lock:
        lat = _metrics["latency_ms"]
        return {
            "calls": dict(_metrics["calls"]),
            "calls_total": _metrics["calls_total"],
            "errors": dict(_metrics["errors"]),
            "errors_total": _metrics["errors_total"],
            "latency_ms": {
                "count": lat["count"],
                "sum": lat["sum"],
                "max": lat["max"],
                "buckets": dict(lat["buckets"]),
            },
        }


def reset_metrics() -> None:
    """Reset the registry to zero (test isolation; not used in production)."""
    global _metrics
    with _lock:
        _metrics = _new_metrics()
