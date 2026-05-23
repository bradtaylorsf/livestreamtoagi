"""Tests for the Minecraft command eval CLI."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
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


class SequencedFakeClient:
    provider = "fake-provider"

    def __init__(self, outputs: tuple[str, ...]) -> None:
        self.outputs = outputs
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
        index = len(self.calls) - 1
        return LLMResponse(
            content=self.outputs[index],
            model=model,
            input_tokens=10 + index,
            output_tokens=4 + index,
            estimated_cost=Decimal("0.001") * (index + 1),
            latency_ms=index,
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
    assert data["request_count"] == 4
    assert data["collected_count"] == 4
    assert data["estimated_cost"] == "0"
    assert any(result["content"].startswith("!planAndBuild") for result in data["results"])
    assert stderr.getvalue() == ""


def test_cli_list_only_prints_inputs_without_client_construction() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    secret = "local-secret-value"

    def factory(config: ProviderConfig) -> FakeClient:
        raise AssertionError("list-only must not construct a provider client")

    exit_code = main(
        ["--list-only", "--limit", "2"],
        env={
            "LOCAL_LLM_BASE_URL": "http://localhost:1234/v1",
            "LOCAL_LLM_API_KEY": secret,
            "LOCAL_LLM_MODEL": "qwen-local",
        },
        client_factory=factory,
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    text = stdout.getvalue()
    assert exit_code == 0, stderr.getvalue()
    assert "provider: lmstudio" in text
    assert "model: qwen-local" in text
    assert "- baseline-observe-area" in text
    assert "- chat-only-blocked-command" in text
    assert "- movement-with-inventory" not in text
    assert "commands: command_count=" in text
    assert secret not in text
    assert secret not in stderr.getvalue()
    assert stderr.getvalue() == ""


def test_cli_list_only_json_emits_structured_listing_without_client_construction() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    secret = "flag-secret-value"

    def factory(config: ProviderConfig) -> FakeClient:
        raise AssertionError("list-only must not construct a provider client")

    exit_code = main(
        ["--dry-run", "--list-only", "--json", "--limit", "1", "--api-key", secret],
        env={},
        client_factory=factory,
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    data = json.loads(stdout.getvalue())
    assert data["mode"] == "list-only"
    assert data["provider"] == "lmstudio"
    assert data["model"] == "dry-run-local-model"
    assert data["key_present"] is True
    assert data["scenario_count"] == 1
    assert data["scenario_ids"] == ["baseline-observe-area"]
    assert data["commands"]["command_count"] > 0
    assert data["commands"]["disallowed_count"] > 0
    assert data["commands"]["source_counts"]
    assert secret not in stdout.getvalue()
    assert secret not in stderr.getvalue()
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


def test_cli_writes_report_artifacts_passing_prompts_and_comparison(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    report_dir = tmp_path / "report"
    passing_path = tmp_path / "passing-prompts.ndjson"
    previous_scores = tmp_path / "previous-scores.json"
    previous_scores.write_text(
        json.dumps(
            {
                "aggregate": {
                    "completion_tokens": 9,
                    "estimated_cost": "0.009",
                    "prompt_tokens": 30,
                    "total_tokens": 39,
                },
                "base_url": "https://openrouter.ai/api/v1",
                "key_present": True,
                "model": "openai/previous",
                "outcome_counts": {
                    "accepted_chat": 0,
                    "accepted_command": 2,
                    "disallowed_tool": 0,
                    "invalid_arg": 0,
                    "malformed": 1,
                    "semantic_reject": 0,
                    "total": 3,
                    "unknown_command": 0,
                    "unsafe_context": 0,
                    "wrong_args": 0,
                },
                "per_scenario": [],
                "provider": "openrouter",
                "totals": {"collected": 3, "request_count": 3, "scenarios": 3, "total": 3},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    fake_client = SequencedFakeClient(
        (
            "!observe",
            "chat: I cannot run !stop, but I can keep watch.",
            "!stop",
        )
    )

    def factory(config: ProviderConfig) -> SequencedFakeClient:
        return fake_client

    exit_code = main(
        [
            "--limit",
            "3",
            "--report-dir",
            str(report_dir),
            "--passing-prompts",
            str(passing_path),
            "--compare",
            str(previous_scores),
        ],
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

    assert exit_code == 0, stderr.getvalue()
    assert fake_client.closed is True
    assert (report_dir / "generations.ndjson").is_file()
    assert (report_dir / "scores.json").is_file()
    assert (report_dir / "report.md").is_file()
    assert (report_dir / "comparison.md").is_file()
    assert passing_path.is_file()

    scores = json.loads((report_dir / "scores.json").read_text(encoding="utf-8"))
    assert scores["outcome_counts"]["accepted_command"] == 1
    assert scores["outcome_counts"]["accepted_chat"] == 1
    assert scores["outcome_counts"]["disallowed_tool"] == 1

    passing_lines = [
        json.loads(line) for line in passing_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [line["scenario_id"] for line in passing_lines] == ["baseline-observe-area"]
    assert passing_lines[0]["command_token"] == "!observe"

    comparison = (report_dir / "comparison.md").read_text(encoding="utf-8")
    assert "qwen-local" in comparison
    assert "openai/previous" in comparison
    assert "outcomes: malformed=0" in stdout.getvalue()
    assert "disallowed_tool=1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_cli_dry_run_writes_meaningful_command_passing_prompts(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    report_dir = tmp_path / "dry-run-report"
    passing_path = tmp_path / "passing-prompts.ndjson"

    exit_code = main(
        [
            "--dry-run",
            "--report-dir",
            str(report_dir),
            "--passing-prompts",
            str(passing_path),
        ],
        env={
            "LOCAL_LLM_BASE_URL": "http://localhost:1234/v1",
            "LOCAL_LLM_API_KEY": "local-secret-value",
            "LOCAL_LLM_MODEL": "qwen-local",
        },
        stdout=stdout,
        stderr=stderr,
        load_env=False,
    )

    assert exit_code == 0, stderr.getvalue()
    scores = json.loads((report_dir / "scores.json").read_text(encoding="utf-8"))
    assert scores["outcome_counts"]["accepted_command"] == 3
    assert scores["outcome_counts"]["accepted_chat"] == 1

    passing_lines = [
        json.loads(line) for line in passing_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [line["scenario_id"] for line in passing_lines] == [
        "baseline-observe-area",
        "build-owner-starter-cabin",
        "movement-with-inventory",
    ]
    assert [line["command_token"] for line in passing_lines] == [
        "!observe",
        "!planAndBuild",
        "!move",
    ]
    assert "starter cabin" in passing_lines[1]["raw_content"]
    assert stderr.getvalue() == ""
