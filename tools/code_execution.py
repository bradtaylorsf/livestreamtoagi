"""Code execution tool — run Python/JavaScript in an isolated Docker sandbox."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import TYPE_CHECKING, Any

from core.event_bus import EventType

from .base import BaseTool

if TYPE_CHECKING:
    import docker

    from core.event_bus import EventBus

logger = logging.getLogger(__name__)

_SANDBOX_IMAGE = "livestream-agi-sandbox"
_MAX_TIMEOUT = 120
_DEFAULT_TIMEOUT = 30

_LANGUAGE_CMD: dict[str, list[str]] = {
    "python": ["python", "/tmp/code.py"],
    "javascript": ["node", "/tmp/code.js"],
}

_LANGUAGE_EXT: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
}


class ExecuteCodeTool(BaseTool):
    """Execute Python or JavaScript code in an ephemeral Docker sandbox."""

    name = "execute_code"
    description = "Run Python or JavaScript code in an isolated sandbox container"
    parameters = {
        "language": {"type": "string", "description": "python or javascript"},
        "code": {"type": "string", "description": "Source code to execute"},
        "timeout": {"type": "integer", "description": "Max seconds (default 30, max 120)"},
    }

    ALLOWED_AGENTS = frozenset({"rex", "fork", "sentinel"})

    def __init__(
        self,
        event_bus: EventBus,
        agent_id: str,
        docker_client: docker.DockerClient | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id
        self._docker: docker.DockerClient | None = docker_client

    def _get_docker(self) -> docker.DockerClient:
        if self._docker is None:
            import docker as _docker

            self._docker = _docker.from_env()
        return self._docker

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        language: str = kwargs["language"]
        code: str = kwargs["code"]
        timeout: int = min(max(kwargs.get("timeout", _DEFAULT_TIMEOUT), 1), _MAX_TIMEOUT)

        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        if language not in _LANGUAGE_CMD:
            return {
                "status": "rejected",
                "reason": f"Unsupported language {language!r}. Must be 'python' or 'javascript'.",
            }

        client = self._get_docker()
        container = None
        tmp_path: str | None = None
        start_time = time.monotonic()

        try:
            # Write code to a temp file and bind-mount it into the container
            ext = _LANGUAGE_EXT[language]
            with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            container = client.containers.create(
                image=_SANDBOX_IMAGE,
                command=_LANGUAGE_CMD[language],
                mem_limit="512m",
                nano_cpus=1_000_000_000,
                pids_limit=100,
                network_mode="none",
                read_only=True,
                tmpfs={"/tmp": "size=100m"},
                volumes={tmp_path: {"bind": f"/tmp/code{ext}", "mode": "ro"}},
                runtime="runsc",
                detach=True,
            )
            container.start()

            result = container.wait(timeout=timeout)
            exit_code: int = result["StatusCode"]

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

        except Exception as exc:
            exc_type = type(exc).__name__

            # Timeout or OOM — try to kill the container
            if container is not None:
                try:
                    container.kill()
                except Exception:
                    pass

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # Detect specific error categories
            err_str = str(exc).lower()
            if "read timed out" in err_str or "timeout" in err_str:
                reason = f"Execution timed out after {timeout}s"
            elif "oom" in err_str or "out of memory" in err_str:
                reason = "Container killed: out of memory (512MB limit)"
            else:
                reason = f"{exc_type}: {exc}"

            await self._event_bus.emit(
                EventType.TOOL_EXECUTED,
                {
                    "tool": self.name,
                    "agent": self._agent_id,
                    "language": language,
                    "status": "error",
                    "reason": reason,
                    "execution_time_ms": elapsed_ms,
                },
            )
            return {"status": "error", "reason": reason, "execution_time_ms": elapsed_ms}

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        await self._event_bus.emit(
            EventType.TOOL_EXECUTED,
            {
                "tool": self.name,
                "agent": self._agent_id,
                "language": language,
                "exit_code": exit_code,
                "execution_time_ms": elapsed_ms,
            },
        )

        return {
            "status": "ok",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "execution_time_ms": elapsed_ms,
        }
