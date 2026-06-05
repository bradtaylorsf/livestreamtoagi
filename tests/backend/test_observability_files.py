"""Tests for shared runtime artifact file writers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from core.observability.files import write_json_file, write_text_file


def test_write_text_file_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "reports" / "summary.md"

    written = write_text_file(path, "# Summary")

    assert written == path
    assert path.read_text(encoding="utf-8") == "# Summary"


def test_write_text_file_can_normalize_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "reports" / "summary.md"

    write_text_file(path, "# Summary", trailing_newline=True)

    assert path.read_text(encoding="utf-8") == "# Summary\n"


def test_write_json_file_supports_sorted_newline_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "reports" / "scores.json"

    written = write_json_file(
        path,
        {"b": 2, "a": 1},
        sort_keys=True,
        trailing_newline=True,
    )

    assert written == path
    assert path.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_write_json_file_defaults_to_stringifying_non_json_values(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"

    write_json_file(path, {"started_at": datetime(2026, 6, 5, tzinfo=UTC)})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "started_at": "2026-06-05 00:00:00+00:00"
    }
