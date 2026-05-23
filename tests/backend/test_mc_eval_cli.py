"""Tests for the Minecraft command eval CLI."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from typing import Any

from core.minecraft.eval.cli import main
from core.minecraft.eval.provider import ProviderConfig
from core.models import LLMResponse


class FakeClient:
    provider = "fake-provider"

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        agent_id: str | None = None,
        *,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(
            content="!observe 8 all false",
            model=model,
            input_tokens=11,
            output_tokens=7,
            estimated_cost=Decimal("0.002"),
            latency_ms=4,
        )

    async def close(self) -> None:
        self.closed = True


def test_cli_dry_run_json_uses_bundled_fixtures_and_redacts_env_secrets() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    secret = "local-secret-value"

    exit_code = main(
        ["--dry-run", "--json"],
        env={
            "LOCAL_LLM_BASE_URL": "http://localhost:1234/v1",
            "LOCAL_LLM_API_KEY": secret,
            "LOCAL_LLM_MODEL": "qwen-local",
        },
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0
    assert secret not in stdout.getvalue()
    assert secret not in stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert data["provider"] == "lmstudio"
    assert data["model"] == "qwen-local"
    assert data["base_url"] == "http://localhost:1234/v1"
    assert data["key_present"] is True
    assert data["request_count"] == 3
    assert data["collected_count"] == 3
    assert data["estimated_cost"] == "0"
    assert stderr.getvalue() == ""


def test_cli_uses_injected_client_factory_without_network() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    captured: dict[str, Any] = {}
    fake_client = FakeClient()

    def factory(config: ProviderConfig) -> FakeClient:
        captured["config"] = config
        return fake_client

    exit_code = main(
        ["--limit", "1", "--json"],
        env={
            "LOCAL_LLM_BASE_URL": "http://localhost:1234/v1",
            "LOCAL_LLM_API_KEY": "local-secret-value",
            "LOCAL_LLM_MODEL": "qwen-local",
        },
        client_factory=factory,
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0
    assert captured["config"].provider == "lmstudio"
    assert fake_client.closed is True
    assert len(fake_client.calls) == 1
    data = json.loads(stdout.getvalue())
    assert data["request_count"] == 1
    assert data["prompt_tokens"] == 11
    assert data["completion_tokens"] == 7
    assert data["estimated_cost"] == "0.002"
    assert "local-secret-value" not in stdout.getvalue()
    assert "local-secret-value" not in stderr.getvalue()


def test_cli_openrouter_without_key_exits_nonzero_with_clear_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "--provider",
            "openrouter",
            "--model",
            "openai/gpt-4o-mini",
            "--dry-run",
        ],
        env={},
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "OPENROUTER_API_KEY is required" in stderr.getvalue()
