"""Livestream safe-state configuration.

The public stream has two emergency safe-state modes:

* ``holding_card``: replace live output with an operator-provided card.
* ``cut``: terminate the RTMP push so the public feed stops.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class StreamState(str, Enum):
    """Controller state visible to the kill-switch monitor."""

    ACTIVE = "active"
    SAFE = "safe"


@dataclass(frozen=True)
class SafeStateConfig:
    """Configuration for moving the public livestream into a safe state."""

    holding_card_path: Path | None = None
    cut_on_kill: bool = False
    transition_seconds: float = 0.0

    @property
    def kill_mode(self) -> str:
        return "cut" if self.cut_on_kill else "holding_card"


def load_safe_state_config(
    environ: Mapping[str, str] | None = None,
) -> SafeStateConfig:
    """Load safe-state settings from environment variables."""

    env = environ if environ is not None else os.environ
    mode = env.get("LIVESTREAM_KILL_MODE", "").strip().lower() or "holding_card"
    if mode not in {"holding_card", "cut"}:
        raise ValueError("LIVESTREAM_KILL_MODE must be either 'holding_card' or 'cut'")

    raw_transition = env.get("LIVESTREAM_SAFE_TRANSITION_SECONDS", "").strip() or "0"
    try:
        transition_seconds = float(raw_transition)
    except ValueError as exc:
        raise ValueError("LIVESTREAM_SAFE_TRANSITION_SECONDS must be a number") from exc
    if transition_seconds < 0:
        raise ValueError("LIVESTREAM_SAFE_TRANSITION_SECONDS must be >= 0")

    raw_holding_card = env.get("LIVESTREAM_HOLDING_CARD", "").strip()
    holding_card_path = Path(raw_holding_card).expanduser() if raw_holding_card else None

    return SafeStateConfig(
        holding_card_path=holding_card_path,
        cut_on_kill=mode == "cut",
        transition_seconds=transition_seconds,
    )


def livestream_enabled_from_env(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the livestream safety monitor should start."""

    env = environ if environ is not None else os.environ
    return env.get("LIVESTREAM_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
