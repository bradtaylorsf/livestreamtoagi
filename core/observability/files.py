"""Shared file writers for runtime artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

JsonDefault = Callable[[Any], Any]


def write_text_file(
    path: str | Path,
    text: str,
    *,
    trailing_newline: bool = False,
) -> Path:
    """Write a UTF-8 text artifact and create parent directories."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = text
    if trailing_newline and not body.endswith("\n"):
        body += "\n"
    target.write_text(body, encoding="utf-8")
    return target


def write_json_file(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    default: JsonDefault | None = str,
    trailing_newline: bool = False,
) -> Path:
    """Write a JSON artifact and create parent directories."""

    text = json.dumps(
        payload,
        indent=indent,
        sort_keys=sort_keys,
        default=default,
    )
    return write_text_file(path, text, trailing_newline=trailing_newline)
