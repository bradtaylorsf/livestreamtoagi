"""Tests for the simulation → MP4 video render pipeline.

These tests stub out the heavy parts (Playwright + ffmpeg) and assert the
state transitions, idempotency, and graceful-failure paths required by the
acceptance criteria for issue #425.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import Simulation
from core.video.audio_timeline import TurnAudioCue
from core.video.config import VideoRenderConfig, load_video_render_config
from core.video.worker import enqueue_render, mark_unrenderable

# ── Helpers ─────────────────────────────────────────────────


def _make_sim(**overrides) -> Simulation:
    defaults: dict = {
        "id": uuid.uuid4(),
        "name": "render-test",
        "description": None,
        "config": {},
        "status": "completed",
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "total_conversations": 2,
        "total_turns": 7,
        "agents_participated": ["vera", "rex"],
    }
    defaults.update(overrides)
    return Simulation(**defaults)


# ── Config knobs ─────────────────────────────────────────────


class TestRenderConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "MAX_VIDEO_RENDER_MINUTES",
                "VIDEO_STORAGE",
                "VIDEO_S3_BUCKET",
                "VIDEO_OUTPUT_DIR",
            ):
                os.environ.pop(k, None)
            cfg = load_video_render_config()
        assert cfg.max_render_minutes == 30
        assert cfg.max_render_seconds == 30 * 60
        assert cfg.storage_backend == "local"
        assert cfg.s3_bucket is None

    def test_env_overrides(self):
        with patch.dict(
            os.environ,
            {
                "MAX_VIDEO_RENDER_MINUTES": "5",
                "VIDEO_STORAGE": "s3",
                "VIDEO_S3_BUCKET": "my-bucket",
            },
        ):
            cfg = load_video_render_config()
        assert cfg.max_render_minutes == 5
        assert cfg.storage_backend == "s3"
        assert cfg.s3_bucket == "my-bucket"


# ── Worker idempotency ───────────────────────────────────────


class TestEnqueueRender:
    @pytest.mark.asyncio
    async def test_claims_and_starts_when_unrendered(self):
        sim_id = uuid.uuid4()
        repo = MagicMock()
        repo.claim_for_render = AsyncMock(return_value="claimed")
        repo.update_video_status = AsyncMock()

        result = await enqueue_render(sim_id, sim_repo=repo)

        # PYTEST_CURRENT_TEST is set during pytest, so subprocess is skipped
        # but the claim still happens.
        assert result == "started"
        repo.claim_for_render.assert_awaited_once_with(sim_id)

    @pytest.mark.asyncio
    async def test_already_rendering_is_idempotent_noop(self):
        sim_id = uuid.uuid4()
        repo = MagicMock()
        repo.claim_for_render = AsyncMock(return_value="rendering")

        result = await enqueue_render(sim_id, sim_repo=repo)

        assert result == "already_rendering"

    @pytest.mark.asyncio
    async def test_already_done_is_idempotent_noop(self):
        sim_id = uuid.uuid4()
        repo = MagicMock()
        repo.claim_for_render = AsyncMock(return_value="done")

        result = await enqueue_render(sim_id, sim_repo=repo)

        assert result == "already_done"

    @pytest.mark.asyncio
    async def test_skipped_state_is_preserved(self):
        sim_id = uuid.uuid4()
        repo = MagicMock()
        repo.claim_for_render = AsyncMock(return_value="skipped")

        result = await enqueue_render(sim_id, sim_repo=repo)

        assert result == "skipped"

    @pytest.mark.asyncio
    async def test_mark_unrenderable_writes_skipped(self):
        sim_id = uuid.uuid4()
        repo = MagicMock()
        repo.update_video_status = AsyncMock()

        await mark_unrenderable(sim_id, sim_repo=repo, reason="no transcripts")

        repo.update_video_status.assert_awaited_once()
        kwargs = repo.update_video_status.await_args.kwargs
        assert kwargs["status"] == "skipped"


# ── Orchestrator finalize hook ───────────────────────────────


class TestOrchestratorVideoHook:
    @pytest.mark.asyncio
    async def test_completed_sim_with_transcripts_enqueues(self):
        from core.simulation.orchestrator import SimulationOrchestrator

        orch = SimulationOrchestrator.__new__(SimulationOrchestrator)
        orch._sim_repo = MagicMock()

        sim = _make_sim(total_turns=10, total_conversations=2)
        with (
            patch(
                "core.video.worker.enqueue_render",
                new=AsyncMock(return_value="started"),
            ) as enq,
            patch(
                "core.video.worker.mark_unrenderable",
                new=AsyncMock(),
            ) as skip,
        ):
            await orch._enqueue_video_render(sim)

        enq.assert_awaited_once()
        skip.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_transcripts_marks_skipped(self):
        from core.simulation.orchestrator import SimulationOrchestrator

        orch = SimulationOrchestrator.__new__(SimulationOrchestrator)
        orch._sim_repo = MagicMock()

        sim = _make_sim(total_turns=0, total_conversations=0)

        with (
            patch(
                "core.video.worker.enqueue_render",
                new=AsyncMock(),
            ) as enq,
            patch(
                "core.video.worker.mark_unrenderable",
                new=AsyncMock(),
            ) as skip,
        ):
            await orch._enqueue_video_render(sim)

        enq.assert_not_called()
        skip.assert_awaited_once()
        assert skip.await_args.kwargs["reason"] == "no transcript turns"


# ── Storage backend selection ────────────────────────────────


class TestStorage:
    def test_local_storage_writes_under_output_dir(self, tmp_path):
        from core.video.storage import save_video

        src = tmp_path / "render.mp4"
        src.write_bytes(b"fake mp4 bytes")
        cfg = VideoRenderConfig(
            max_render_minutes=30,
            storage_backend="local",
            s3_bucket=None,
            output_dir=str(tmp_path / "out"),
            public_base_url="http://localhost:8000",
            replay_url_template="{base_url}/simulations/{sim_id}/replay",
        )
        sim_id = uuid.uuid4()

        url = save_video(sim_id, src, config=cfg)

        assert url == f"/videos/{sim_id}.mp4"
        assert (tmp_path / "out" / f"{sim_id}.mp4").exists()
        assert not src.exists()  # moved, not copied

    def test_s3_storage_requires_bucket(self, tmp_path):
        from core.video.storage import save_video

        src = tmp_path / "render.mp4"
        src.write_bytes(b"fake")
        cfg = VideoRenderConfig(
            max_render_minutes=30,
            storage_backend="s3",
            s3_bucket=None,
            output_dir="videos",
            public_base_url="http://localhost:8000",
            replay_url_template="{base_url}/simulations/{sim_id}/replay",
        )
        with pytest.raises(ValueError, match="VIDEO_S3_BUCKET"):
            save_video(uuid.uuid4(), src, config=cfg)


# ── Audio timeline construction ─────────────────────────────


class TestAudioTimeline:
    def test_concat_filter_delays_each_clip(self, tmp_path):
        from core.video.audio_timeline import _build_concat_filter

        a = tmp_path / "a.mp3"
        b = tmp_path / "b.mp3"
        a.write_bytes(b"")
        b.write_bytes(b"")

        inputs, graph = _build_concat_filter([(0.0, a), (3.5, b)])

        # Both clips appear as inputs
        assert "-i" in inputs and str(a) in inputs and str(b) in inputs
        # Delay encoded in milliseconds
        assert "adelay=0|0" in graph
        assert "adelay=3500|3500" in graph
        # Output mix label is consistent for the pipeline downstream
        assert graph.endswith("[out]")

    def test_empty_cues_has_no_filter(self, tmp_path):
        from core.video.audio_timeline import _build_concat_filter

        inputs, graph = _build_concat_filter([])

        assert inputs == []
        assert graph == ""

    @pytest.mark.asyncio
    async def test_stitch_silences_when_all_clips_fail(self, tmp_path):
        """No clips → emits a 1s silence wav rather than crashing."""
        from core.video.audio_timeline import stitch_audio_timeline

        tts = MagicMock()
        # generate() returns None for every call → no clips usable
        tts.generate = AsyncMock(return_value=None)
        tts.audio_dir = tmp_path

        recorded_cmds: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            recorded_cmds.append(cmd)
            # Touch the file so downstream code thinks it exists
            from pathlib import Path

            Path(cmd[-1]).write_bytes(b"")

            class R:
                returncode = 0

            return R()

        with patch("core.video.audio_timeline.subprocess.run", side_effect=fake_run):
            result = await stitch_audio_timeline(
                [TurnAudioCue("vera", "hi", 0.0)],
                tts=tts,
                output_path=tmp_path / "audio.wav",
            )

        assert result.cues_rendered == 0
        # Silence path goes through anullsrc
        assert any("anullsrc" in " ".join(c) for c in recorded_cmds)


# ── _build_cues row → TurnAudioCue parsing ───────────────────


class TestBuildCuesFromRows:
    """Regression tests for the render-script transcript→cue parser.

    Real transcripts.event_type values are 'idle' / 'environmental' / 'scheduled'
    / 'coding_challenge' etc. — never 'turn'. The speaker is encoded as a
    '[name]: …' prefix on `content`, NOT in `participants` (which is the
    unordered set of attendees). A prior version of the script filtered
    `event_type = 'turn'` and pulled the speaker from `participants[0]`,
    which produced empty MP4s with the wrong voices for every sim.
    """

    def _import(self):
        from scripts.render_simulation_video import _build_cues_from_rows

        return _build_cues_from_rows

    def test_extracts_speaker_from_content_prefix(self):
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["pixel", "rex", "aurora", "vera"],
                "content": "[vera]: morning team — let's review the budget",
                "created_at": base,
            },
            {
                "participants": ["pixel", "rex", "aurora", "vera"],
                "content": "[rex]: I have concerns about the Q3 spend",
                "created_at": base.replace(second=12),
            },
        ]
        cues = build(rows)
        assert [c.agent_id for c in cues] == ["vera", "rex"]
        assert cues[0].text == "morning team — let's review the budget"
        assert cues[1].text == "I have concerns about the Q3 spend"
        assert cues[0].start_seconds == 0.0
        assert cues[1].start_seconds == 12.0

    def test_skips_rows_without_speaker_prefix(self):
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["vera"],
                "content": "system announcement: budget hit cap",
                "created_at": base,
            },
            {
                "participants": ["vera"],
                "content": "[vera]: copy that, pausing new spend",
                "created_at": base.replace(second=2),
            },
        ]
        cues = build(rows)
        assert len(cues) == 1
        assert cues[0].agent_id == "vera"

    def test_skips_rows_with_empty_text_after_prefix(self):
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["vera"],
                "content": "[vera]:   ",
                "created_at": base,
            },
        ]
        assert build(rows) == []

    def test_empty_input_returns_empty(self):
        build = self._import()
        assert build([]) == []

    def test_speaker_normalized_to_lowercase(self):
        from datetime import UTC, datetime

        build = self._import()
        rows = [
            {
                "participants": ["VERA"],
                "content": "[VERA]: hello",
                "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
            },
        ]
        cues = build(rows)
        assert cues[0].agent_id == "vera"


# ── SimulationRepo claim semantics ───────────────────────────


class TestClaimForRender:
    @pytest.mark.asyncio
    async def test_claim_succeeds_when_null(self):
        from core.repos.simulation_repo import SimulationRepo

        db = MagicMock()
        db.fetchrow = AsyncMock(return_value={"video_render_status": "rendering"})
        repo = SimulationRepo(db)

        state = await repo.claim_for_render(uuid.uuid4())

        assert state == "claimed"
        # The UPDATE only fires when the row was unclaimed.
        sql = db.fetchrow.await_args.args[0]
        assert "video_render_status = 'rendering'" in sql
        assert "IS NULL" in sql

    @pytest.mark.asyncio
    async def test_claim_returns_existing_state_when_locked(self):
        from core.repos.simulation_repo import SimulationRepo

        db = MagicMock()
        # First call: UPDATE returned no row → already claimed by someone else
        # Second call: SELECT returns 'rendering'
        db.fetchrow = AsyncMock(return_value=None)
        db.fetchval = AsyncMock(return_value="rendering")
        repo = SimulationRepo(db)

        state = await repo.claim_for_render(uuid.uuid4())

        assert state == "rendering"

    @pytest.mark.asyncio
    async def test_update_video_status_rejects_invalid(self):
        from core.repos.simulation_repo import SimulationRepo

        db = MagicMock()
        repo = SimulationRepo(db)

        with pytest.raises(ValueError, match="Invalid video_render_status"):
            await repo.update_video_status(uuid.uuid4(), status="bogus")

    @pytest.mark.asyncio
    async def test_update_video_status_done_stamps_url(self):
        from core.repos.simulation_repo import SimulationRepo

        sim_row = {
            "id": uuid.uuid4(),
            "name": "x",
            "description": None,
            "config": {},
            "status": "completed",
            "started_at": datetime.now(UTC),
            "completed_at": datetime.now(UTC),
            "simulated_duration": None,
            "real_duration": None,
            "total_conversations": 1,
            "total_turns": 1,
            "total_tokens": 0,
            "total_cost": Decimal("0"),
            "total_artifacts": 0,
            "total_management_flags": 0,
            "agents_participated": [],
            "error_log": None,
            "model_versions": {},
            "is_live": False,
            "created_at": datetime.now(UTC),
            "hypothesis": None,
            "outcomes": {},
            "learnings": [],
            "factions": [],
            "submitted_by_user_id": None,
            "video_url": "/videos/abc.mp4",
            "video_render_status": "done",
            "video_rendered_at": datetime.now(UTC),
        }
        db = MagicMock()
        db.fetchrow = AsyncMock(return_value=sim_row)
        repo = SimulationRepo(db)

        sim = await repo.update_video_status(
            uuid.uuid4(),
            status="done",
            url="/videos/abc.mp4",
        )

        assert sim is not None
        assert sim.video_url == "/videos/abc.mp4"
        assert sim.video_render_status == "done"
        # The query stamps video_rendered_at only on 'done'
        sql = db.fetchrow.await_args.args[0]
        assert "video_rendered_at = CASE WHEN $1 = 'done'" in sql


# ── Render-pipeline error surfacing ─────────────────────────


class TestRenderPipelineErrors:
    """Issue #462: a fresh checkout with playwright missing, or the package
    installed but Chromium binaries un-fetched, used to crash with terse
    errors that didn't tell the operator how to fix it."""

    @pytest.mark.asyncio
    async def test_missing_playwright_module_points_at_render_extra(self, tmp_path):
        from core.video.render_pipeline import RenderError, _capture_canvas

        # Force the lazy import to fail by hiding the module.
        with patch.dict(sys.modules, {"playwright.async_api": None}):
            with pytest.raises(RenderError) as ei:
                await _capture_canvas(
                    replay_url="http://example.com/replay",
                    output_path=tmp_path / "canvas.webm",
                    max_seconds=1,
                )
        assert ".[render]" in str(ei.value)
        assert "playwright is not installed" in str(ei.value)

    @pytest.mark.asyncio
    async def test_missing_chromium_binary_points_at_install_command(self, tmp_path):
        from core.video.render_pipeline import RenderError, _capture_canvas

        # Stub `async_playwright()` so the launch raises a Playwright-style
        # "Executable doesn't exist" error. We don't need the real package.
        class _FakeChromium:
            async def launch(self, **_kw):
                raise RuntimeError(
                    "Executable doesn't exist at /tmp/.../headless_shell\n"
                    "Looks like Playwright was just installed or updated. "
                    "Please run the following command to download new browsers:\n"
                    "    playwright install"
                )

        class _FakePW:
            chromium = _FakeChromium()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        def fake_async_playwright():
            return _FakePW()

        fake_module = MagicMock()
        fake_module.async_playwright = fake_async_playwright
        with patch.dict(sys.modules, {"playwright.async_api": fake_module}):
            with pytest.raises(RenderError) as ei:
                await _capture_canvas(
                    replay_url="http://example.com/replay",
                    output_path=tmp_path / "canvas.webm",
                    max_seconds=1,
                )
        assert "Chromium binaries not installed" in str(ei.value)
        assert "playwright install chromium" in str(ei.value)

    @pytest.mark.asyncio
    async def test_unrelated_launch_error_is_re_raised(self, tmp_path):
        """Non-binary launch failures shouldn't be re-labelled as missing
        binaries — that would mask real bugs (port conflicts, etc.)."""
        from core.video.render_pipeline import _capture_canvas

        class _FakeChromium:
            async def launch(self, **_kw):
                raise RuntimeError("some unrelated launch failure")

        class _FakePW:
            chromium = _FakeChromium()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        fake_module = MagicMock()
        fake_module.async_playwright = lambda: _FakePW()
        with patch.dict(sys.modules, {"playwright.async_api": fake_module}):
            with pytest.raises(RuntimeError, match="some unrelated launch failure"):
                await _capture_canvas(
                    replay_url="http://example.com/replay",
                    output_path=tmp_path / "canvas.webm",
                    max_seconds=1,
                )


# ── Render-script preflight checks ──────────────────────────


class TestRenderScriptPreflight:
    """The standalone subprocess (scripts/render_simulation_video.py) must
    fail loudly with an actionable message *before* bootstrapping DB/Redis,
    so the orchestrator log makes the misconfiguration obvious."""

    def test_chromium_dir_check_finds_chromium_subdir(self, tmp_path, monkeypatch):
        from scripts.render_simulation_video import _chromium_browser_dir_exists

        (tmp_path / "chromium-1234").mkdir()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert _chromium_browser_dir_exists() is True

    def test_chromium_dir_check_returns_false_when_empty(self, tmp_path, monkeypatch):
        from scripts.render_simulation_video import _chromium_browser_dir_exists

        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert _chromium_browser_dir_exists() is False

    def test_chromium_dir_check_returns_false_for_missing_path(self, tmp_path, monkeypatch):
        from scripts.render_simulation_video import _chromium_browser_dir_exists

        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "does-not-exist"))
        assert _chromium_browser_dir_exists() is False

    def test_preflight_returns_2_when_playwright_missing(self, caplog):
        from scripts.render_simulation_video import (
            EXIT_PLAYWRIGHT_NOT_INSTALLED,
            _preflight_render_dependencies,
        )

        log = logging.getLogger("test_preflight_missing_pw")
        with patch.dict(sys.modules, {"playwright.async_api": None}):
            with caplog.at_level(logging.ERROR, logger=log.name):
                code = _preflight_render_dependencies(log)

        assert code == EXIT_PLAYWRIGHT_NOT_INSTALLED
        assert any(".[render]" in r.message for r in caplog.records)

    def test_preflight_returns_3_when_chromium_missing(self, caplog, monkeypatch):
        from scripts.render_simulation_video import (
            EXIT_CHROMIUM_NOT_INSTALLED,
            _preflight_render_dependencies,
        )

        # Pretend playwright is importable, but no chromium dir exists.
        fake_pw_async = MagicMock()
        log = logging.getLogger("test_preflight_missing_chromium")

        with (
            patch.dict(sys.modules, {"playwright.async_api": fake_pw_async}),
            patch(
                "scripts.render_simulation_video._chromium_browser_dir_exists",
                return_value=False,
            ),
        ):
            with caplog.at_level(logging.ERROR, logger=log.name):
                code = _preflight_render_dependencies(log)

        assert code == EXIT_CHROMIUM_NOT_INSTALLED
        assert any("playwright install chromium" in r.message for r in caplog.records)

    def test_preflight_returns_none_when_dependencies_present(self):
        from scripts.render_simulation_video import _preflight_render_dependencies

        fake_pw_async = MagicMock()
        log = logging.getLogger("test_preflight_ok")

        with (
            patch.dict(sys.modules, {"playwright.async_api": fake_pw_async}),
            patch(
                "scripts.render_simulation_video._chromium_browser_dir_exists",
                return_value=True,
            ),
        ):
            assert _preflight_render_dependencies(log) is None
