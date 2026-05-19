"""Example tests for the reusable E4 bridge harness."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.integration.bridge_harness import (
    FakeNodeBridgeClient,
    FakePythonBridgeServer,
    copy_bridge_client_with_header_ws,
    run_node_bridge_call,
)

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


def test_fake_node_client_round_trips_without_uvicorn_or_minecraft() -> None:
    """Python tests can fake the Node side and drive the real bridge endpoint."""

    with FakeNodeBridgeClient() as client:
        response = client.call(payload={"message": "from-python-fake-node"})

    assert response["ok"] is True
    assert response["payload"] == {"pong": "from-python-fake-node"}
    assert response["trace_id"].startswith("trace-")


@requires_node
def test_fake_python_server_accepts_the_committed_node_client(tmp_path: Path) -> None:
    """Node tests can fake the Python side without a Minecraft server."""

    bridge_module = copy_bridge_client_with_header_ws(tmp_path)
    with FakePythonBridgeServer() as server:
        result = run_node_bridge_call(
            tmp_path,
            bridge_module=bridge_module,
            env=server.node_env(),
            message="from-node-client",
        )

    assert result["status"] == "ok", result
    assert result["response"]["payload"] == {"pong": "from-node-client"}
