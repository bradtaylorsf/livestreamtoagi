"""Tests for E6-7 action failure taxonomy and safe-fail behavior (#562)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.embodiment import (
    FAILURE_CLASSES,
    SAFE_FAIL_POLICY,
    RetryBudget,
    classify,
    decide_safe_fail,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
SAFE_FAIL_HELPERS = FORK_SRC / "agent" / "skills" / "safe_fail.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str) -> dict:
    harness = tmp_path / "safe_fail_harness.mjs"
    harness.write_text(source)
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
        cwd=tmp_path,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_taxonomy_and_policy_are_exact() -> None:
    assert {
        "blocked",
        "timeout",
        "invalid",
        "unreachable",
        "bridge-down",
        "kill-switch-active",
    } == FAILURE_CLASSES
    assert SAFE_FAIL_POLICY == {
        "blocked": "idle",
        "timeout": "retry-bounded",
        "invalid": "abandon",
        "unreachable": "idle",
        "bridge-down": "abandon",
        "kill-switch-active": "idle",
    }


@pytest.mark.parametrize(
    ("failure_class", "expected_policy", "expected_action", "expected_retryable"),
    [
        ("blocked", "idle", "idle", False),
        ("timeout", "retry-bounded", "retry", True),
        ("invalid", "abandon", "abandon", False),
        ("unreachable", "idle", "idle", False),
        ("bridge-down", "abandon", "abandon", False),
        ("kill-switch-active", "idle", "idle", False),
    ],
)
def test_each_failure_class_has_safe_behavior(
    failure_class: str,
    expected_policy: str,
    expected_action: str,
    expected_retryable: bool,
) -> None:
    result = decide_safe_fail(failure_class, attempt=1, budget=RetryBudget(max_attempts=2))

    assert result["class"] == failure_class
    assert result["policy"] == expected_policy
    assert result["action"] == expected_action
    assert result["retryable"] is expected_retryable


def test_timeout_retry_is_bounded_and_then_abandons() -> None:
    budget = RetryBudget(max_attempts=2)

    first = decide_safe_fail("timed-out", attempt=1, budget=budget)
    second = decide_safe_fail("bridge_timeout", attempt=2, budget=budget)
    exhausted = decide_safe_fail("timeout", attempt=3, budget=budget)

    assert first["action"] == "retry"
    assert first["next_backoff_ms"] == 500
    assert second["action"] == "retry"
    assert second["next_backoff_ms"] == 1000
    assert exhausted == {
        "class": "timeout",
        "policy": "retry-bounded",
        "action": "abandon",
        "retryable": False,
        "attempt": 3,
        "next_backoff_ms": None,
    }


def test_retry_budget_uses_capped_exponential_backoff_defaults() -> None:
    budget = RetryBudget(max_attempts=6)

    assert [budget.next_backoff_ms(n) for n in (1, 2, 3, 10)] == [
        500,
        1000,
        2000,
        30000,
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("blocked", "blocked"),
        ("timed-out", "timeout"),
        ("timeout", "timeout"),
        ("protected", "invalid"),
        ("tool-missing", "invalid"),
        ("invalid", "invalid"),
        ("unreachable", "unreachable"),
        ("bridge-down", "bridge-down"),
        ("kill_switch_active", "kill-switch-active"),
        ("reached", None),
        ("placed", None),
        ("removed", None),
        ("success", None),
        ("partial", None),
    ],
)
def test_classify_normalizes_skill_classes(raw: str, expected: str | None) -> None:
    assert classify(raw, source="skill") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bridge_unreachable", "unreachable"),
        ("bridge_timeout", "timeout"),
        ("bridge_overloaded", "timeout"),
        ("bridge_connect_failed", "bridge-down"),
        ("bridge_auth_refused", "invalid"),
        ("bridge_no_token", "invalid"),
        ("bridge_no_transport", "invalid"),
        ("bridge_protocol", "invalid"),
        ("kill_switch_active", "kill-switch-active"),
    ],
)
def test_classify_normalizes_bridge_error_codes(raw: str, expected: str) -> None:
    assert classify(raw, source="bridge") == expected


def test_classify_reads_mapping_shapes_and_treats_unknown_as_invalid() -> None:
    assert classify({"error": {"code": "bridge_no_token"}}, source="bridge") == "invalid"
    assert classify({"failureClass": "timed-out"}, source="node-action") == "timeout"
    assert classify({"class": "success"}, source="node-action") is None
    assert classify("unexpected-failure-label", source="unknown") == "invalid"
    assert classify(None, source="unknown") is None


def test_decide_safe_fail_rejects_non_failure_success_labels() -> None:
    with pytest.raises(ValueError):
        decide_safe_fail("success")


@requires_node
def test_node_safe_fail_helpers_mirror_python_policy(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(SAFE_FAIL_HELPERS))}).href);
const timeoutFirst = mod.decideSafeFail('timed-out', 1, {{ max_attempts: 2 }});
const timeoutExhausted = mod.decideSafeFail('bridge_overloaded', 3, {{ max_attempts: 2 }});
process.stdout.write(JSON.stringify({{
    classes: mod.FAILURE_CLASSES,
    policies: mod.SAFE_FAIL_POLICY,
    blocked: mod.decideSafeFail('blocked', 1),
    invalid: mod.decideSafeFail('protected', 1),
    unreachable: mod.decideSafeFail('bridge_unreachable', 1),
    bridgeDown: mod.decideSafeFail('bridge_connect_failed', 1),
    killSwitch: mod.decideSafeFail('kill_switch_active', 1),
    timeoutFirst,
    timeoutExhausted,
    nonFailure: mod.classify('placed'),
}}) + '\\n');
"""
    result = _run_node_harness(tmp_path, source)

    assert result["classes"] == [
        "blocked",
        "timeout",
        "invalid",
        "unreachable",
        "bridge-down",
        "kill-switch-active",
    ]
    assert result["policies"] == {
        "blocked": "idle",
        "timeout": "retry-bounded",
        "invalid": "abandon",
        "unreachable": "idle",
        "bridge-down": "abandon",
        "kill-switch-active": "idle",
    }
    assert result["blocked"]["action"] == "idle"
    assert result["invalid"]["action"] == "abandon"
    assert result["unreachable"]["action"] == "idle"
    assert result["bridgeDown"]["action"] == "abandon"
    assert result["killSwitch"]["action"] == "idle"
    assert result["timeoutFirst"]["action"] == "retry"
    assert result["timeoutFirst"]["next_backoff_ms"] == 500
    assert result["timeoutExhausted"]["action"] == "abandon"
    assert result["nonFailure"] is None


def test_committed_safe_fail_file_and_staging_match_contract() -> None:
    helper_src = SAFE_FAIL_HELPERS.read_text()
    assert "FAILURE_CLASSES" in helper_src
    assert "decideSafeFail" in helper_src
    assert "bridge-overloaded" in helper_src
    assert "kill-switch-active" in helper_src
    assert "callBridge" not in helper_src

    script_src = CONNECT_SCRIPT.read_text()
    assert "SAFE_FAIL_SKILL_REL" in script_src
    assert "src/agent/skills/safe_fail.js" in script_src
    assert "Copied safe-fail helpers" in script_src


def test_package_json_wires_embodiment_failure_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-failure")
        == ".venv/bin/pytest tests/backend/test_embodiment_failure.py -v"
    )
