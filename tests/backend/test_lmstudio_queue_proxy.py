"""Tests for the local LM Studio FIFO queue proxy."""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "lmstudio_queue_proxy.py"


def _load_proxy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lmstudio_queue_proxy", PROXY_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    starts: list[float] = []
    ends: list[float] = []
    models: list[str | None] = []

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        self.__class__.starts.append(time.monotonic())
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        parsed = json.loads(body.decode("utf-8"))
        self.__class__.models.append(parsed.get("model"))
        time.sleep(0.08)
        payload = {
            "id": "fake",
            "object": "chat.completion",
            "model": parsed.get("model"),
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        response = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)
        self.__class__.ends.append(time.monotonic())


class _TransientModelLoadHandler(BaseHTTPRequestHandler):
    attempts = 0

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        self.__class__.attempts += 1
        if self.__class__.attempts == 1:
            response = b'{"error":"Model unloaded."}'
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return

        response = json.dumps(
            {
                "id": "fake",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def _start_fake_upstream() -> ThreadingHTTPServer:
    _FakeUpstreamHandler.starts = []
    _FakeUpstreamHandler.ends = []
    _FakeUpstreamHandler.models = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _start_transient_model_load_upstream() -> ThreadingHTTPServer:
    _TransientModelLoadHandler.attempts = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TransientModelLoadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_proxy_joins_paths_without_double_v1_prefix() -> None:
    proxy_mod = _load_proxy()
    proxy = proxy_mod.QueueProxy(
        upstream="http://localhost:1234/v1",
        concurrency=1,
        telemetry_path=None,
    )

    assert proxy._upstream_url("/v1/chat/completions") == "http://localhost:1234/v1/chat/completions"
    assert proxy._upstream_url("/chat/completions") == "http://localhost:1234/v1/chat/completions"
    assert proxy._upstream_url("/v1/models?x=1") == "http://localhost:1234/v1/models?x=1"


def test_proxy_serializes_requests_and_emits_queue_telemetry(tmp_path: Path) -> None:
    proxy_mod = _load_proxy()
    upstream = _start_fake_upstream()
    telemetry = tmp_path / "llm-queue.ndjson"
    proxy = proxy_mod.QueueProxy(
        upstream=f"http://127.0.0.1:{upstream.server_address[1]}/v1",
        concurrency=1,
        telemetry_path=telemetry,
    )
    proxy.start()
    try:
        jobs = []
        for index in range(2):
            body = json.dumps({"model": f"local/test-{index}", "messages": []}).encode()
            job = proxy_mod.ProxyJob(
                request_id=f"queue-test-{index}",
                method="POST",
                path="/v1/chat/completions",
                headers={"content-type": "application/json"},
                body=body,
                enqueued_ms=proxy_mod._now_ms(),
            )
            proxy.enqueue(job)
            jobs.append(job)

        for job in jobs:
            assert job.event.wait(timeout=5), f"{job.request_id} did not finish"

        assert [job.response_status for job in jobs] == [200, 200]
        assert len(_FakeUpstreamHandler.starts) == 2
        assert len(_FakeUpstreamHandler.ends) == 2
        assert _FakeUpstreamHandler.starts[1] >= _FakeUpstreamHandler.ends[0]

        events = [
            json.loads(line)
            for line in telemetry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        event_types = [event["event_type"] for event in events]
        started = [event for event in events if event["event_type"] == "llm.queue.started"]
        completed = [event for event in events if event["event_type"] == "llm.queue.completed"]
        assert event_types.count("llm.queue.enqueued") == 2
        assert len(started) == 2
        assert len(completed) == 2
        assert started[1]["payload"]["wait_ms"] > 0
        assert completed[0]["payload"]["tokens"]["total_tokens"] == 5
        assert proxy.health()["completed"] == 2
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()


def test_proxy_prioritizes_chat_completions_over_queued_embeddings(tmp_path: Path) -> None:
    proxy_mod = _load_proxy()
    upstream = _start_fake_upstream()
    proxy = proxy_mod.QueueProxy(
        upstream=f"http://127.0.0.1:{upstream.server_address[1]}/v1",
        concurrency=1,
        telemetry_path=tmp_path / "llm-queue.ndjson",
    )
    proxy.start()
    try:
        active_embedding = proxy_mod.ProxyJob(
            request_id="queue-embedding-active",
            method="POST",
            path="/v1/embeddings",
            headers={"content-type": "application/json"},
            body=json.dumps({"model": "embedding-active", "input": "a"}).encode(),
            enqueued_ms=proxy_mod._now_ms(),
        )
        queued_embedding = proxy_mod.ProxyJob(
            request_id="queue-embedding-waiting",
            method="POST",
            path="/v1/embeddings",
            headers={"content-type": "application/json"},
            body=json.dumps({"model": "embedding-waiting", "input": "b"}).encode(),
            enqueued_ms=proxy_mod._now_ms(),
        )
        chat = proxy_mod.ProxyJob(
            request_id="queue-chat",
            method="POST",
            path="/v1/chat/completions",
            headers={"content-type": "application/json"},
            body=json.dumps({"model": "chat-priority", "messages": []}).encode(),
            enqueued_ms=proxy_mod._now_ms(),
        )

        proxy.enqueue(active_embedding)
        deadline = time.monotonic() + 2
        while len(_FakeUpstreamHandler.starts) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(_FakeUpstreamHandler.starts) == 1

        proxy.enqueue(queued_embedding)
        proxy.enqueue(chat)

        for job in (active_embedding, queued_embedding, chat):
            assert job.event.wait(timeout=5), f"{job.request_id} did not finish"

        assert _FakeUpstreamHandler.models == [
            "embedding-active",
            "chat-priority",
            "embedding-waiting",
        ]
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()


def test_proxy_retries_transient_lmstudio_model_load_errors(tmp_path: Path) -> None:
    proxy_mod = _load_proxy()
    upstream = _start_transient_model_load_upstream()
    telemetry = tmp_path / "llm-queue.ndjson"
    proxy = proxy_mod.QueueProxy(
        upstream=f"http://127.0.0.1:{upstream.server_address[1]}/v1",
        concurrency=1,
        telemetry_path=telemetry,
        retry_attempts=1,
        retry_delay_seconds=0,
    )
    proxy.start()
    try:
        job = proxy_mod.ProxyJob(
            request_id="queue-retry-chat",
            method="POST",
            path="/v1/chat/completions",
            headers={"content-type": "application/json"},
            body=json.dumps({"model": "chat-model", "messages": []}).encode(),
            enqueued_ms=proxy_mod._now_ms(),
        )
        proxy.enqueue(job)

        assert job.event.wait(timeout=5), "retrying chat job did not finish"
        assert job.response_status == 200
        assert _TransientModelLoadHandler.attempts == 2

        events = [
            json.loads(line)
            for line in telemetry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [event["event_type"] for event in events].count("llm.queue.retry") == 1
        retry = next(event for event in events if event["event_type"] == "llm.queue.retry")
        assert retry["payload"]["status"] == 400
        assert retry["payload"]["model"] == "chat-model"
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()


def test_proxy_exits_on_sigterm() -> None:
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(PROXY_SCRIPT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--upstream",
            "http://localhost:1234/v1",
            "--concurrency",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5) as resp:
                    assert resp.status == 200
                    break
            except OSError:
                time.sleep(0.05)
        else:
            stdout, stderr = proc.communicate(timeout=1)
            raise AssertionError(f"proxy did not become ready\nstdout={stdout}\nstderr={stderr}")

        proc.terminate()
        proc.wait(timeout=5)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
