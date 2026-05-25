"""Tests for the /api/simulations/{id}/eval-scores endpoint (issue #859)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.public_routes import (
    _resolve_headless_sim_folder,
    get_simulation_eval_scores,
)


def _seed_sim_folder(root: Path, sim_id: str) -> Path:
    folder = root / "20260520T120000Z_test"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(
        json.dumps({"name": "test", "simulation_id": sim_id})
    )
    (folder / "eval_scores.json").write_text(
        json.dumps(
            {
                "scorer": "headless",
                "categories": {"social_dynamics": {"score": 75.0}},
            }
        )
    )
    return folder


def test_resolve_headless_sim_folder_finds_by_simulation_id(tmp_path: Path) -> None:
    _seed_sim_folder(tmp_path, sim_id="aaaa-bbbb")
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        folder = _resolve_headless_sim_folder("aaaa-bbbb")
    assert folder is not None
    assert folder.name == "20260520T120000Z_test"


def test_resolve_headless_sim_folder_returns_none_when_missing(tmp_path: Path) -> None:
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        folder = _resolve_headless_sim_folder("missing")
    assert folder is None


@pytest.mark.asyncio
async def test_get_simulation_eval_scores_returns_json(tmp_path: Path) -> None:
    _seed_sim_folder(tmp_path, sim_id="abc-123")
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        result = await get_simulation_eval_scores("abc-123")
    assert result["scorer"] == "headless"
    assert result["categories"]["social_dynamics"]["score"] == 75.0


@pytest.mark.asyncio
async def test_get_simulation_eval_scores_404_when_no_folder(tmp_path: Path) -> None:
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        with pytest.raises(HTTPException) as exc:
            await get_simulation_eval_scores("does-not-exist")
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_simulation_eval_scores_404_when_no_scores_file(tmp_path: Path) -> None:
    folder = tmp_path / "20260520T120000Z_test"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(
        json.dumps({"name": "test", "simulation_id": "xxx"})
    )
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        with pytest.raises(HTTPException) as exc:
            await get_simulation_eval_scores("xxx")
        assert exc.value.status_code == 404
