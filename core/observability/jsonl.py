"""Small append-only JSONL helpers for runtime evidence files."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

JsonSerializer = Callable[[Any], str]


def serialize_jsonl_record(
    record: Any,
    *,
    sort_keys: bool = False,
) -> str:
    """Serialize a record as one JSONL line without the trailing newline."""

    model_dump_json = getattr(record, "model_dump_json", None)
    if callable(model_dump_json) and not sort_keys:
        return str(model_dump_json())
    return json.dumps(record, sort_keys=sort_keys, default=str)


def append_jsonl(
    path: str | Path,
    record: Any,
    *,
    sort_keys: bool = False,
    serializer: JsonSerializer | None = None,
) -> Path:
    """Append one JSON-serializable record and create parent directories."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = serializer(record) if serializer is not None else serialize_jsonl_record(
        record, sort_keys=sort_keys
    )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return target


def write_jsonl(
    path: str | Path,
    records: Iterable[Any],
    *,
    sort_keys: bool = False,
    serializer: JsonSerializer | None = None,
) -> Path:
    """Write a complete JSONL file and create parent directories."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            line = serializer(record) if serializer is not None else serialize_jsonl_record(
                record, sort_keys=sort_keys
            )
            handle.write(line + "\n")
    return target


class JsonlWriter:
    """Reusable open-handle JSONL writer for hot paths."""

    def __init__(
        self,
        path: str | Path,
        *,
        flush_per_write: bool = False,
        serializer: JsonSerializer | None = None,
        closed_message: str = "JsonlWriter is closed; cannot write more rows",
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: io.TextIOBase | None = self.path.open("a", encoding="utf-8")
        self._flush_per_write = flush_per_write
        self._serializer = serializer
        self._closed_message = closed_message

    def write(self, record: Any) -> None:
        if self._file is None:
            raise RuntimeError(self._closed_message)
        line = (
            self._serializer(record)
            if self._serializer is not None
            else serialize_jsonl_record(record)
        )
        self._file.write(line + "\n")
        if self._flush_per_write:
            self._file.flush()

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
            finally:
                self._file.close()
                self._file = None

    def __enter__(self) -> JsonlWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
