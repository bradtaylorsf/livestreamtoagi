#!/usr/bin/env python3
"""Small OpenAI-compatible priority queue proxy for local LM Studio.

The Minecraft cohort can otherwise fan out eight simultaneous chat completion
requests to LM Studio. This proxy keeps the OpenAI-compatible surface area tiny:
it forwards requests to an upstream `/v1` server while limiting active
in-flight calls and emitting NDJSON queue telemetry.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass
class ProxyStats:
    enqueued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self, queued: int) -> dict[str, int]:
        with self.lock:
            return {
                "queued": queued,
                "running": self.running,
                "completed": self.completed,
                "failed": self.failed,
                "enqueued": self.enqueued,
            }


@dataclass
class ProxyJob:
    request_id: str
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    enqueued_ms: int
    event: threading.Event = field(default_factory=threading.Event)
    response_status: int = 502
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: bytes = b""
    error: str | None = None


class QueueProxy:
    def __init__(
        self,
        upstream: str,
        concurrency: int,
        telemetry_path: Path | None,
        retry_attempts: int = 2,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        self.upstream = upstream.rstrip("/")
        self.concurrency = max(1, concurrency)
        self.telemetry_path = telemetry_path
        self.retry_attempts = max(0, retry_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.jobs: queue.PriorityQueue[tuple[int, int, ProxyJob | None]] = queue.PriorityQueue()
        self.stats = ProxyStats()
        self._telemetry_lock = threading.Lock()
        self._sequence_lock = threading.Lock()
        self._sequence = 0
        self._workers: list[threading.Thread] = []

    def start(self) -> None:
        for index in range(self.concurrency):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"lmstudio-queue-worker-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def stop(self) -> None:
        for _ in self._workers:
            self.jobs.put((100, self._next_sequence(), None))
        for worker in self._workers:
            worker.join(timeout=2)

    def enqueue(self, job: ProxyJob) -> None:
        with self.stats.lock:
            self.stats.enqueued += 1
        self._emit(
            "llm.queue.enqueued",
            job,
            {
                "method": job.method,
                "path": job.path,
                "queued": self.jobs.qsize() + 1,
                "concurrency": self.concurrency,
                "model": self._model_from_body(job.body),
            },
        )
        self.jobs.put((self._priority(job), self._next_sequence(), job))

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "upstream": self.upstream,
            "concurrency": self.concurrency,
            "retry_attempts": self.retry_attempts,
            **self.stats.snapshot(self.jobs.qsize()),
        }

    def _worker_loop(self) -> None:
        while True:
            _, _, job = self.jobs.get()
            if job is None:
                self.jobs.task_done()
                return
            wait_ms = _now_ms() - job.enqueued_ms
            with self.stats.lock:
                self.stats.running += 1
            self._emit(
                "llm.queue.started",
                job,
                {
                    "wait_ms": wait_ms,
                    "queued": self.jobs.qsize(),
                    "running": self.stats.snapshot(self.jobs.qsize())["running"],
                    "model": self._model_from_body(job.body),
                },
            )
            started_ms = _now_ms()
            try:
                self._forward(job)
                latency_ms = _now_ms() - started_ms
                with self.stats.lock:
                    self.stats.completed += 1
                payload = {
                    "wait_ms": wait_ms,
                    "latency_ms": latency_ms,
                    "status": job.response_status,
                    "model": self._model_from_body(job.body),
                    "tokens": self._usage_from_body(job.response_body),
                }
                self._emit("llm.queue.completed", job, payload)
            except Exception as exc:  # noqa: BLE001 - proxy must convert any failure
                latency_ms = _now_ms() - started_ms
                job.error = str(exc)
                job.response_status = 502
                job.response_headers = {"content-type": "application/json"}
                job.response_body = _json_dumps(
                    {"error": {"message": str(exc), "type": "lmstudio_queue_proxy_error"}}
                ).encode()
                with self.stats.lock:
                    self.stats.failed += 1
                self._emit(
                    "llm.queue.failed",
                    job,
                    {
                        "wait_ms": wait_ms,
                        "latency_ms": latency_ms,
                        "error": str(exc),
                        "model": self._model_from_body(job.body),
                    },
                )
            finally:
                with self.stats.lock:
                    self.stats.running = max(0, self.stats.running - 1)
                job.event.set()
                self.jobs.task_done()

    def _forward(self, job: ProxyJob) -> None:
        url = self._upstream_url(job.path)
        headers = {
            key: value
            for key, value in job.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
        }
        request_body = None if job.method in {"GET", "HEAD"} and not job.body else job.body
        for attempt in range(self.retry_attempts + 1):
            request = urllib.request.Request(url, data=request_body, headers=headers, method=job.method)
            try:
                with urllib.request.urlopen(request, timeout=600) as response:
                    job.response_status = int(response.status)
                    job.response_headers = {
                        key.lower(): value
                        for key, value in response.headers.items()
                        if key.lower()
                        not in {"transfer-encoding", "connection", "content-length", "content-encoding"}
                    }
                    job.response_body = response.read()
                    return
            except urllib.error.HTTPError as exc:
                body = exc.read()
                if self._should_retry_http_error(job, int(exc.code), body) and attempt < self.retry_attempts:
                    delay = self.retry_delay_seconds * (attempt + 1)
                    self._emit(
                        "llm.queue.retry",
                        job,
                        {
                            "attempt": attempt + 1,
                            "delay_ms": int(delay * 1000),
                            "status": int(exc.code),
                            "model": self._model_from_body(job.body),
                            "error_preview": body.decode("utf-8", errors="replace")[:240],
                        },
                    )
                    if delay > 0:
                        time.sleep(delay)
                    continue
                job.response_status = int(exc.code)
                job.response_headers = {
                    key.lower(): value
                    for key, value in exc.headers.items()
                    if key.lower()
                    not in {"transfer-encoding", "connection", "content-length", "content-encoding"}
                }
                job.response_body = body
                return

    @staticmethod
    def _should_retry_http_error(job: ProxyJob, status: int, body: bytes) -> bool:
        if status != 400:
            return False
        path = urllib.parse.urlparse(job.path).path
        if not (path.endswith("/chat/completions") or path.endswith("/completions")):
            return False
        lowered = body.decode("utf-8", errors="replace").lower()
        return any(
            marker in lowered
            for marker in (
                "model unloaded",
                "failed to load model",
                "operation canceled",
            )
        )

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._sequence += 1
            return self._sequence

    @staticmethod
    def _priority(job: ProxyJob) -> int:
        path = urllib.parse.urlparse(job.path).path
        if path.endswith("/chat/completions") or path.endswith("/completions"):
            return 0
        return 10

    def _upstream_url(self, path: str) -> str:
        """Join proxy paths to an upstream that may already include `/v1`."""
        parsed_upstream = urllib.parse.urlparse(self.upstream)
        upstream_path = parsed_upstream.path.rstrip("/")
        request = urllib.parse.urlparse(path)
        request_path = request.path
        if upstream_path and request_path == upstream_path:
            forward_path = upstream_path
        elif upstream_path and request_path.startswith(f"{upstream_path}/"):
            forward_path = request_path
        else:
            forward_path = f"{upstream_path}/{request_path.lstrip('/')}".rstrip("/")
        rebuilt = parsed_upstream._replace(path=forward_path or "/", query=request.query)
        return urllib.parse.urlunparse(rebuilt)

    def _emit(self, event_type: str, job: ProxyJob, payload: dict[str, Any]) -> None:
        if not self.telemetry_path:
            return
        event = {
            "ts": _iso_now(),
            "event_type": event_type,
            "agent": None,
            "trace_id": job.request_id,
            "source": "lmstudio_queue_proxy",
            "payload": {
                "request_id": job.request_id,
                "path": job.path,
                **payload,
                **self.stats.snapshot(self.jobs.qsize()),
            },
        }
        with self._telemetry_lock:
            self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            with self.telemetry_path.open("a", encoding="utf-8") as handle:
                handle.write(_json_dumps(event) + "\n")

    @staticmethod
    def _model_from_body(body: bytes) -> str | None:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        return parsed.get("model") if isinstance(parsed, dict) else None

    @staticmethod
    def _usage_from_body(body: bytes) -> dict[str, int]:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        usage = parsed.get("usage") if isinstance(parsed, dict) else None
        if not isinstance(usage, dict):
            return {}
        result: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                result[key] = value
        return result


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "LMStudioQueueProxy/1.0"

    @property
    def proxy(self) -> QueueProxy:
        return self.server.proxy  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[lmstudio-queue] " + fmt % args + "\n")

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in {"/healthz", "/metrics"}:
            body = _json_dumps(self.proxy.health()).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._handle_proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._handle_proxy()

    def _handle_proxy(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        job = ProxyJob(
            request_id=f"queue-{uuid.uuid4()}",
            method=self.command,
            path=self.path,
            headers={key: value for key, value in self.headers.items()},
            body=body,
            enqueued_ms=_now_ms(),
        )
        self.proxy.enqueue(job)
        job.event.wait()
        self.send_response(job.response_status)
        headers = dict(job.response_headers)
        headers.setdefault("content-type", "application/json")
        headers["content-length"] = str(len(job.response_body))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(job.response_body)
        except BrokenPipeError:
            return


class ProxyServer(ThreadingHTTPServer):
    proxy: QueueProxy


def telemetry_path_from_env(value: str | None) -> Path | None:
    if value:
        return Path(value)
    run_dir = os.environ.get("MC_RUN_DIR")
    if run_dir:
        return Path(run_dir) / "timeline-raw" / "llm-queue.ndjson"
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("MINECRAFT_LLM_PROXY_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MINECRAFT_LLM_PROXY_PORT", "1235")),
    )
    parser.add_argument(
        "--upstream",
        default=os.environ.get("LOCAL_LLM_UPSTREAM_URL", "http://localhost:1234/v1"),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("MINECRAFT_LLM_CONCURRENCY", "1")),
    )
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=int(os.environ.get("MINECRAFT_LLM_RETRY_ATTEMPTS", "2")),
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=float(os.environ.get("MINECRAFT_LLM_RETRY_DELAY_SECONDS", "2")),
    )
    parser.add_argument("--telemetry", default=os.environ.get("MINECRAFT_LLM_QUEUE_TELEMETRY"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    proxy = QueueProxy(
        upstream=args.upstream,
        concurrency=args.concurrency,
        telemetry_path=telemetry_path_from_env(args.telemetry),
        retry_attempts=args.retry_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
    )
    proxy.start()
    server = ProxyServer((args.host, args.port), ProxyHandler)
    server.proxy = proxy

    def _shutdown(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, name="lmstudio-queue-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(
        f"LM Studio queue proxy listening on http://{args.host}:{args.port} -> {args.upstream} "
        f"(concurrency={proxy.concurrency}, retry_attempts={proxy.retry_attempts})",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        proxy.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
