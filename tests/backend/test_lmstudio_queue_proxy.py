"""Tests for the local LM Studio FIFO queue proxy."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
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

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        self.__class__.starts.append(time.monotonic())
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        parsed = json.loads(body.decode("utf-8"))
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


def _start_fake_upstream() -> ThreadingHTTPServer:
    _FakeUpstreamHandler.starts = []
    _FakeUpstreamHandler.ends = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


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
