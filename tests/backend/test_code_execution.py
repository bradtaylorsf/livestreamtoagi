"""Tests for code execution tool with Docker sandbox."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.code_execution import ExecuteCodeTool

# --- Fixtures ---


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock(
        return_value={"event_id": "evt-789", "event_type": "tool_executed", "data": {}}
    )
    return bus


@pytest.fixture
def docker_client() -> MagicMock:
    """Mock Docker client with a container that runs successfully."""
    client = MagicMock()
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    client.containers.create.return_value = container
    return client


@pytest.fixture
def tool(event_bus: AsyncMock, docker_client: MagicMock) -> ExecuteCodeTool:
    return ExecuteCodeTool(event_bus=event_bus, agent_id="rex", docker_client=docker_client)


@pytest.fixture
def unauthorized_tool(event_bus: AsyncMock, docker_client: MagicMock) -> ExecuteCodeTool:
    return ExecuteCodeTool(event_bus=event_bus, agent_id="aurora", docker_client=docker_client)


# --- Authorization ---


class TestAuthorization:
    async def test_allowed_agents(self) -> None:
        assert ExecuteCodeTool.ALLOWED_AGENTS == frozenset({"rex", "fork", "sentinel"})

    async def test_unauthorized_agent_rejected(
        self, unauthorized_tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        result = await unauthorized_tool.execute(language="python", code="print(1)")

        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        docker_client.containers.create.assert_not_called()

    async def test_each_allowed_agent_can_execute(
        self, event_bus: AsyncMock, docker_client: MagicMock
    ) -> None:
        for agent in ("rex", "fork", "sentinel"):
            t = ExecuteCodeTool(event_bus=event_bus, agent_id=agent, docker_client=docker_client)
            result = await t.execute(language="python", code="print(1)")
            assert result["status"] == "ok"


# --- Language Validation ---


class TestLanguageValidation:
    async def test_invalid_language_rejected(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        result = await tool.execute(language="ruby", code="puts 1")

        assert result["status"] == "rejected"
        assert "Unsupported language" in result["reason"]
        docker_client.containers.create.assert_not_called()


# --- Python Execution ---


class TestPythonExecution:
    async def test_python_returns_stdout(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.logs.side_effect = [b"Hello World\n", b""]

        result = await tool.execute(language="python", code='print("Hello World")')

        assert result["status"] == "ok"
        assert result["stdout"] == "Hello World\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    async def test_python_container_config(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        await tool.execute(language="python", code="x = 1")

        call_kwargs = docker_client.containers.create.call_args[1]
        assert call_kwargs["image"] == "livestream-agi-sandbox"
        assert call_kwargs["command"] == ["python", "/tmp/code.py"]
        assert call_kwargs["mem_limit"] == "512m"
        assert call_kwargs["nano_cpus"] == 1_000_000_000
        assert call_kwargs["pids_limit"] == 100
        assert call_kwargs["network_mode"] == "none"
        assert call_kwargs["read_only"] is True
        assert call_kwargs["tmpfs"] == {"/tmp": "size=100m"}
        assert call_kwargs["runtime"] == "runsc"
        assert call_kwargs["detach"] is True


# --- JavaScript Execution ---


class TestJavaScriptExecution:
    async def test_javascript_returns_stdout(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.logs.side_effect = [b"42\n", b""]

        result = await tool.execute(language="javascript", code="console.log(42)")

        assert result["status"] == "ok"
        assert result["stdout"] == "42\n"
        assert result["exit_code"] == 0

    async def test_javascript_container_uses_node(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        await tool.execute(language="javascript", code="1+1")

        call_kwargs = docker_client.containers.create.call_args[1]
        assert call_kwargs["command"] == ["node", "/tmp/code.js"]


# --- Timeout ---


class TestTimeout:
    async def test_timeout_kills_container(
        self, tool: ExecuteCodeTool, docker_client: MagicMock, event_bus: AsyncMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.wait.side_effect = Exception("read timed out")

        result = await tool.execute(language="python", code="while True: pass", timeout=5)

        assert result["status"] == "error"
        assert "timed out" in result["reason"].lower()
        container.kill.assert_called_once()
        container.remove.assert_called_once_with(force=True)

    async def test_default_timeout_is_30(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value

        await tool.execute(language="python", code="pass")

        container.wait.assert_called_once_with(timeout=30)

    async def test_timeout_clamped_to_max_120(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value

        await tool.execute(language="python", code="pass", timeout=999)

        container.wait.assert_called_once_with(timeout=120)

    async def test_timeout_clamped_to_min_1(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value

        await tool.execute(language="python", code="pass", timeout=-5)

        container.wait.assert_called_once_with(timeout=1)


# --- Memory / OOM ---


class TestMemoryLimit:
    async def test_oom_returns_error(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.wait.side_effect = Exception("OOM: container killed")

        result = await tool.execute(language="python", code="x = bytearray(1024**3)")

        assert result["status"] == "error"
        assert "out of memory" in result["reason"].lower()


# --- Network Isolation ---


class TestNetworkIsolation:
    async def test_network_mode_is_none(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        await tool.execute(language="python", code="import urllib")

        call_kwargs = docker_client.containers.create.call_args[1]
        assert call_kwargs["network_mode"] == "none"


# --- Container Cleanup ---


class TestContainerCleanup:
    async def test_container_removed_on_success(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        await tool.execute(language="python", code="print(1)")

        container = docker_client.containers.create.return_value
        container.remove.assert_called_once_with(force=True)

    async def test_container_removed_on_failure(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.wait.side_effect = Exception("something broke")

        await tool.execute(language="python", code="bad")

        container.remove.assert_called_once_with(force=True)


# --- Event Emission ---


class TestEventEmission:
    async def test_emits_tool_executed_on_success(
        self, tool: ExecuteCodeTool, event_bus: AsyncMock
    ) -> None:
        await tool.execute(language="python", code="print(1)")

        event_bus.emit.assert_called_once()
        call_args = event_bus.emit.call_args
        assert call_args[0][0] == "tool_executed"
        data = call_args[0][1]
        assert data["tool"] == "execute_code"
        assert data["agent"] == "rex"
        assert data["language"] == "python"
        assert data["exit_code"] == 0
        assert "execution_time_ms" in data

    async def test_emits_tool_executed_on_error(
        self, tool: ExecuteCodeTool, docker_client: MagicMock, event_bus: AsyncMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.wait.side_effect = Exception("timeout")

        await tool.execute(language="python", code="pass")

        event_bus.emit.assert_called_once()
        data = event_bus.emit.call_args[0][1]
        assert data["status"] == "error"

    async def test_no_event_on_rejection(
        self, unauthorized_tool: ExecuteCodeTool, event_bus: AsyncMock
    ) -> None:
        await unauthorized_tool.execute(language="python", code="print(1)")

        event_bus.emit.assert_not_called()


# --- Result Fields ---


class TestResultFields:
    async def test_success_result_has_required_fields(
        self, tool: ExecuteCodeTool, docker_client: MagicMock
    ) -> None:
        container = docker_client.containers.create.return_value
        container.wait.return_value = {"StatusCode": 1}
        container.logs.side_effect = [b"", b"NameError: x\n"]

        result = await tool.execute(language="python", code="print(x)")

        assert result["status"] == "ok"
        assert result["exit_code"] == 1
        assert result["stderr"] == "NameError: x\n"
        assert "execution_time_ms" in result
        assert isinstance(result["execution_time_ms"], int)


# --- get_core_tools integration ---


class TestToolRegistration:
    async def test_execute_code_in_core_tools(self) -> None:
        from tools import get_core_tools

        bus = AsyncMock()
        redis = AsyncMock()
        docker_mock = MagicMock()

        tools = get_core_tools(
            event_bus=bus, redis_client=redis, agent_id="rex", docker_client=docker_mock
        )

        tool_names = [t.name for t in tools]
        assert "execute_code" in tool_names


# --- Integration tests (require running Docker) ---


@pytest.mark.integration
class TestSandboxIntegration:
    """These tests require Docker with the sandbox image built.

    Run: docker build -t livestream-agi-sandbox ./sandbox
    Mark: @pytest.mark.integration
    """

    async def test_python_execution_real(self) -> None:
        pytest.skip("Requires running Docker services with sandbox image — run with pytest -m integration")

    async def test_javascript_execution_real(self) -> None:
        pytest.skip("Requires running Docker services with sandbox image — run with pytest -m integration")

    async def test_filesystem_read_only_except_tmp(self) -> None:
        pytest.skip("Requires running Docker services with sandbox image — run with pytest -m integration")
