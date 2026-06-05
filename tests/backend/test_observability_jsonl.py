"""Tests for shared JSONL observability helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.observability.jsonl import JsonlWriter, append_jsonl, write_jsonl


def test_append_jsonl_creates_parent_dirs_and_writes_one_record(tmp_path: Path) -> None:
    path = tmp_path / "timeline-raw" / "events.ndjson"

    written = append_jsonl(path, {"b": 2, "a": 1}, sort_keys=True)

    assert written == path
    assert path.read_text(encoding="utf-8") == '{"a": 1, "b": 2}\n'


def test_jsonl_writer_appends_and_raises_after_close(tmp_path: Path) -> None:
    path = tmp_path / "decision_log.jsonl"
    writer = JsonlWriter(path, closed_message="closed")

    writer.write({"event_type": "first"})
    writer.close()

    assert json.loads(path.read_text(encoding="utf-8")) == {"event_type": "first"}
    with pytest.raises(RuntimeError, match="closed"):
        writer.write({"event_type": "late"})


def test_write_jsonl_truncates_and_writes_sorted_records(tmp_path: Path) -> None:
    path = tmp_path / "reports" / "generations.ndjson"
    path.parent.mkdir()
    path.write_text("stale\n", encoding="utf-8")

    written = write_jsonl(path, [{"b": 2, "a": 1}, {"c": 3}], sort_keys=True)

    assert written == path
    assert path.read_text(encoding="utf-8") == '{"a": 1, "b": 2}\n{"c": 3}\n'
