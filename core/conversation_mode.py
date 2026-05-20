"""Run-mode helpers for selecting the conversation implementation."""

from __future__ import annotations

import os
from typing import Literal, cast

ConversationMode = Literal["director", "embodied"]

_ENV_VAR = "CONVERSATION_MODE"
_VALID_MODES: set[ConversationMode] = {"director", "embodied"}


def get_conversation_mode() -> ConversationMode:
    """Return the configured conversation mode.

    The legacy Python director remains the default. Embodied Minecraft runs set
    ``CONVERSATION_MODE=embodied`` to rely on Mindcraft's decentralized
    respond/ignore behavior instead.
    """
    raw_mode = os.environ.get(_ENV_VAR, "director").strip().lower()
    if raw_mode in _VALID_MODES:
        return cast("ConversationMode", raw_mode)
    raise ValueError(
        f"Unknown {_ENV_VAR}={raw_mode!r}; expected one of: director, embodied"
    )


def is_embodied_run() -> bool:
    """Return true when the run should avoid the legacy Python director."""
    return get_conversation_mode() == "embodied"
