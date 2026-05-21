"""Failure taxonomy and safe-fail decisions for embodied actions.

The action layer has several local, bridge, and skill-specific ways to name
failure. This module collapses them into the small E6-7 taxonomy and returns a
safe next action for autonomous callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

type FailureClass = Literal[
    "blocked", "interrupted", "timeout", "invalid", "unreachable", "bridge-down"
]
type SafeFailPolicy = Literal["idle", "retry-bounded", "abandon"]
type SafeFailAction = Literal["idle", "retry", "abandon"]

FAILURE_CLASSES: frozenset[FailureClass] = frozenset(
    {"blocked", "interrupted", "timeout", "invalid", "unreachable", "bridge-down"}
)

SAFE_FAIL_POLICY: dict[FailureClass, SafeFailPolicy] = {
    "blocked": "idle",
    "interrupted": "idle",
    "timeout": "retry-bounded",
    "invalid": "abandon",
    "unreachable": "idle",
    "bridge-down": "abandon",
}

NON_FAILURE_CLASSES = frozenset({"reached", "placed", "removed", "success", "partial"})

_ALIASES: dict[str, FailureClass] = {
    "blocked": "blocked",
    "interrupted": "interrupted",
    "aborted": "interrupted",
    "path-stopped": "interrupted",
    "pathstopped": "interrupted",
    "mode-interrupted": "interrupted",
    "timed-out": "timeout",
    "time-out": "timeout",
    "timeout": "timeout",
    "bridge-timeout": "timeout",
    "bridge-overloaded": "timeout",
    "invalid": "invalid",
    "invalid-payload": "invalid",
    "protected": "invalid",
    "tool-missing": "invalid",
    "bridge-auth-refused": "invalid",
    "bridge-no-token": "invalid",
    "bridge-no-transport": "invalid",
    "bridge-protocol": "invalid",
    "unreachable": "unreachable",
    "no-path": "unreachable",
    "bridge-unreachable": "unreachable",
    "bridge-down": "bridge-down",
    "bridge-connect-failed": "bridge-down",
    "bridge-send-failed": "bridge-down",
}


SafeFailDecision = TypedDict(
    "SafeFailDecision",
    {
        "class": FailureClass,
        "policy": SafeFailPolicy,
        "action": SafeFailAction,
        "retryable": bool,
        "attempt": int,
        "next_backoff_ms": int | None,
    },
)


@dataclass(frozen=True)
class RetryBudget:
    """Bounded retry/backoff settings shared by action failure handling."""

    max_attempts: int
    base_backoff_ms: int = 500
    cap_ms: int = 30000
    multiplier: int = 2

    def __post_init__(self) -> None:
        if self.max_attempts < 0:
            raise ValueError("max_attempts must be >= 0")
        if self.base_backoff_ms <= 0:
            raise ValueError("base_backoff_ms must be > 0")
        if self.cap_ms <= 0:
            raise ValueError("cap_ms must be > 0")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")

    def next_backoff_ms(self, attempt: int) -> int:
        """Return the capped exponential backoff for a 1-based attempt."""
        normalized_attempt = max(1, int(attempt))
        delay = self.base_backoff_ms * (self.multiplier ** (normalized_attempt - 1))
        return min(delay, self.cap_ms)


DEFAULT_RETRY_BUDGET = RetryBudget(max_attempts=3)


def _normalize_token(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if not token:
        return None
    return "-".join(part for part in token.replace("_", "-").split() if part)


def _raw_candidates(raw: Any) -> list[Any]:
    if isinstance(raw, Mapping):
        candidates: list[Any] = []
        for key in (
            "class",
            "failure_class",
            "failureClass",
            "code",
            "error_code",
            "outcome_class",
            "outcomeClass",
            "status",
        ):
            if key in raw:
                candidates.append(raw[key])
        error = raw.get("error")
        if isinstance(error, Mapping):
            candidates.extend([error.get("code"), error.get("class")])
        return candidates

    code = getattr(raw, "code", None)
    if code is not None:
        return [code]
    return [raw]


def classify(raw: Any, *, source: str) -> FailureClass | None:
    """Normalize a raw failure/status token to the canonical E6-7 class.

    Known success or progress labels return ``None``. Unknown non-empty tokens
    are treated as ``invalid`` so ambiguous failures abandon instead of retrying
    or taking unverified action.
    """
    del source  # reserved for call-site diagnostics without changing the API

    saw_unknown = False
    for candidate in _raw_candidates(raw):
        token = _normalize_token(candidate)
        if token is None:
            continue
        if token in NON_FAILURE_CLASSES:
            return None
        if token in _ALIASES:
            return _ALIASES[token]
        saw_unknown = True

    return "invalid" if saw_unknown else None


def decide_safe_fail(
    failure_class: FailureClass | str,
    attempt: int = 1,
    budget: RetryBudget | None = None,
) -> SafeFailDecision:
    """Return the safe next action for a canonical or normalizable failure."""
    canonical = classify(failure_class, source="safe-fail")
    if canonical is None:
        raise ValueError(f"{failure_class!r} is not a failure class")

    retry_budget = budget or DEFAULT_RETRY_BUDGET
    normalized_attempt = max(1, int(attempt))
    policy = SAFE_FAIL_POLICY[canonical]

    if policy == "retry-bounded" and normalized_attempt <= retry_budget.max_attempts:
        return {
            "class": canonical,
            "policy": policy,
            "action": "retry",
            "retryable": True,
            "attempt": normalized_attempt,
            "next_backoff_ms": retry_budget.next_backoff_ms(normalized_attempt),
        }

    action: SafeFailAction = "abandon" if policy == "retry-bounded" else policy
    return {
        "class": canonical,
        "policy": policy,
        "action": action,
        "retryable": False,
        "attempt": normalized_attempt,
        "next_backoff_ms": None,
    }
