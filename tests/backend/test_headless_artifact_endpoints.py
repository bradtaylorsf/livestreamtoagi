"""Tests for the headless artifact endpoints (issue #860).

Covers ``GET /api/simulations/{id}/build-intents``,
``world-events``, and ``replay-manifest``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from core.public_routes import (
    get_simulation_build_intents,
    get_simulation_replay_manifest,
    get_simulation_world_events,
)
from core.simulation.decision_logger import DecisionLogger


def _seed_folder(root: Path, sim_id: str) -> Path:
    folder = root / "20260520T130000Z_test"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(
        json.dumps({"name": "test", "simulation_id": sim_id})
    )
    return folder


@pytest.mark.asyncio
async def test_build_intents_returns_jsonl_rows(tmp_path: Path) -> None:
    folder = _seed_folder(tmp_path, sim_id="bi-1")
    (folder / "build_intents.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "intent_id": "i1",
                        "agent_id": "rex",
                        "structure_type": "cabin",
                        "motivation_chain": [
                            {"kind": "goal", "description": "shelter"}
                        ],
                    }
                ),
                json.dumps(
                    {
                        "intent_id": "i2",
                        "agent_id": "aurora",
                        "structure_type": "mural",
                    }
                ),
                "",  # blank line should be skipped
            ]
        )
    )
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        result = await get_simulation_build_intents("bi-1")
    assert len(result) == 2
    assert result[0]["intent_id"] == "i1"
    assert result[1]["structure_type"] == "mural"


@pytest.mark.asyncio
async def test_build_intents_returns_empty_when_no_folder(tmp_path: Path) -> None:
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        result = await get_simulation_build_intents("missing")
    assert result == []


@pytest.mark.asyncio
async def test_world_events_returns_world_event_and_needs_rows(tmp_path: Path) -> None:
    folder = _seed_folder(tmp_path, sim_id="we-1")
    # Use the real DecisionLogger so the schema_version is set correctly.
    logger = DecisionLogger(folder)
    logger.log_world_event(event_type="nightfall", severity="medium")
    logger.log_needs_state(actor_id="rex", hunger=0.7)
    logger.log_utterance(actor_id="rex", text="not in the world-events output")
    logger.close()

    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        result = await get_simulation_world_events("we-1")
    assert len(result) == 2
    assert result[0]["event_type"] == "world_event"
    assert result[0]["payload"]["event_type"] == "nightfall"
    assert result[1]["event_type"] == "needs_state"
    assert result[1]["payload"]["hunger"] == 0.7


@pytest.mark.asyncio
async def test_world_events_empty_when_no_log(tmp_path: Path) -> None:
    _seed_folder(tmp_path, sim_id="we-empty")
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        result = await get_simulation_world_events("we-empty")
    assert result == []


@pytest.mark.asyncio
async def test_replay_manifest_returns_available_true(tmp_path: Path) -> None:
    folder = _seed_folder(tmp_path, sim_id="rm-1")
    replay_dir = folder / "replay"
    replay_dir.mkdir()
    (replay_dir / "replay_manifest.json").write_text(
        json.dumps(
            {
                "screenshots": [
                    {"path": "/replay/000.png", "milestone": "build_start"},
                    {"path": "/replay/001.png", "milestone": "build_complete"},
                ],
                "video": None,
            }
        )
    )
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        manifest = await get_simulation_replay_manifest("rm-1")
    assert manifest["available"] is True
    assert len(manifest["screenshots"]) == 2


@pytest.mark.asyncio
async def test_replay_manifest_returns_unavailable_when_missing(tmp_path: Path) -> None:
    _seed_folder(tmp_path, sim_id="rm-missing")
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        manifest = await get_simulation_replay_manifest("rm-missing")
    assert manifest == {"available": False}


@pytest.mark.asyncio
async def test_replay_manifest_unavailable_when_no_folder(tmp_path: Path) -> None:
    with patch("core.public_routes._headless_snapshots_dir", return_value=tmp_path):
        manifest = await get_simulation_replay_manifest("does-not-exist")
    assert manifest == {"available": False}
