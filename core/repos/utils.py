"""Shared utilities for repository classes."""

from __future__ import annotations

import json
from typing import Any


def serialize_jsonb(val: Any) -> str | None:
    """Serialize a value to a JSON string for JSONB columns."""
    if val is None:
        return None
    return json.dumps(val) if not isinstance(val, str) else val
