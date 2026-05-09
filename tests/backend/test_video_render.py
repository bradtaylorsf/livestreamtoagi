"""Tests for the simulation → MP4 video render pipeline.

These tests stub out the heavy parts (Playwright + ffmpeg) and assert the
state transitions, idempotency, and graceful-failure paths required by the
acceptance criteria for issue #425.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import Simulation
from core.video.audio_timeline import StitchResult, TurnAudioCue
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

VIDEO_ENV_KEYS = (
    "MAX_VIDEO_RENDER_MINUTES",
    "VIDEO_STORAGE",
    "VIDEO_S3_BUCKET",
    "VIDEO_OUTPUT_DIR",
    "PUBLIC_BASE_URL",
    "VIDEO_REPLAY_URL_TEMPLATE",
)


class TestRenderConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in VIDEO_ENV_KEYS:
                os.environ.pop(k, None)
            cfg = load_video_render_config()
        sim_id = uuid.uuid4()
        assert cfg.max_render_minutes == 30
        assert cfg.max_render_seconds == 30 * 60
        assert cfg.storage_backend == "local"
        assert cfg.s3_bucket is None
        assert cfg.public_base_url == "http://localhost:4000"
        assert cfg.replay_url_for(str(sim_id)) == (
            f"http://localhost:4000/simulations/{sim_id}/replay?renderMode=1"
        )

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

    def test_public_base_url_override_builds_default_replay_route(self):
        sim_id = uuid.uuid4()
        with patch.dict(
            os.environ,
            {
                "PUBLIC_BASE_URL": "https://show.example/",
            },
            clear=False,
        ):
            os.environ.pop("VIDEO_REPLAY_URL_TEMPLATE", None)
            cfg = load_video_render_config()

        assert cfg.public_base_url == "https://show.example"
        assert cfg.replay_url_for(str(sim_id)) == (
            f"https://show.example/simulations/{sim_id}/replay?renderMode=1"
        )

    def test_blank_replay_url_template_env_uses_default(self):
        sim_id = uuid.uuid4()
        with patch.dict(
            os.environ,
            {
                "PUBLIC_BASE_URL": "http://localhost:4000",
                "VIDEO_REPLAY_URL_TEMPLATE": "",
            },
            clear=False,
        ):
            cfg = load_video_render_config()

        assert cfg.replay_url_for(str(sim_id)) == (
            f"http://localhost:4000/simulations/{sim_id}/replay?renderMode=1"
        )

    def test_replay_url_template_override_takes_precedence(self):
        sim_id = uuid.uuid4()
        with patch.dict(
            os.environ,
            {
                "PUBLIC_BASE_URL": "https://show.example",
                "VIDEO_REPLAY_URL_TEMPLATE": "http://renderer.local/replay/{sim_id}",
            },
            clear=False,
        ):
            cfg = load_video_render_config()

        assert cfg.replay_url_for(str(sim_id)) == (
            f"http://renderer.local/replay/{sim_id}"
        )


# ── Replay capture URL construction ──────────────────────────


class TestRenderPipelineReplayUrls:
    @pytest.mark.asyncio
    async def test_capture_canvas_receives_website_replay_url(self, tmp_path):
        from core.video.render_pipeline import render_simulation_video

        sim_id = uuid.uuid4()
        cfg = VideoRenderConfig(
            max_render_minutes=5,
            storage_backend="local",
            s3_bucket=None,
            output_dir="videos",
            public_base_url="http://localhost:4000",
            replay_url_template="{base_url}/simulations/{sim_id}/replay?renderMode=1",
        )
        capture = AsyncMock(return_value=(tmp_path / "canvas.webm", False))
        stitch = AsyncMock(
            return_value=StitchResult(
                output_path=tmp_path / "audio.wav",
                duration_seconds=1.0,
                cues_rendered=1,
            )
        )

        with (
            patch("core.video.render_pipeline._capture_canvas", new=capture),
            patch("core.video.render_pipeline.stitch_audio_timeline", new=stitch),
            patch("core.video.render_pipeline._mux_final_mp4") as mux,
        ):
            result = await render_simulation_video(
                sim_id,
                cues=[TurnAudioCue("vera", "hello", 0.0)],
                tts=MagicMock(),
                config=cfg,
                work_dir=tmp_path,
            )

        capture.assert_awaited_once()
        assert capture.await_args.kwargs["replay_url"] == (
            f"http://localhost:4000/simulations/{sim_id}/replay?renderMode=1"
        )
        assert capture.await_args.kwargs["max_seconds"] == 5 * 60
        mux.assert_called_once()
        assert result.output_path == tmp_path / f"{sim_id}.mp4"

    def test_bad_replay_response_error_is_actionable(self):
        from core.video.render_pipeline import (
            RenderError,
            _raise_for_bad_replay_response,
        )

        replay_url = "http://localhost:4000/simulations/sim-1/replay?renderMode=1"
        with pytest.raises(RenderError) as exc:
            _raise_for_bad_replay_response(SimpleNamespace(status=404), replay_url)

        message = str(exc.value)
        assert "HTTP 404" in message
        assert replay_url in message
        assert "localhost:4000" in message
        assert "localhost:8010" in message
        assert "PUBLIC_BASE_URL" in message
        assert "VIDEO_REPLAY_URL_TEMPLATE" in message


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

    def test_splits_intra_row_multi_speaker_turns(self):
        """A single row with multiple [speaker]: markers becomes multiple cues."""
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["grok", "sentinel"],
                "content": "[grok]: hi [sentinel]: yo [unknown]: ?",
                "created_at": base,
            },
        ]
        cues = build(rows)
        # Unknown speaker is skipped; grok + sentinel survive.
        assert [c.agent_id for c in cues] == ["grok", "sentinel"]
        assert cues[0].text == "hi"
        assert cues[1].text == "yo"
        # No cue text retains a [speaker] fragment.
        for c in cues:
            assert "[" not in c.text

    def test_embedded_marker_stripped_from_each_cue(self):
        """Multiple inline markers split cleanly with no leaked '[' fragments."""
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["vera", "rex"],
                "content": "[vera]: hello [rex]: world",
                "created_at": base,
            },
        ]
        cues = build(rows)
        assert len(cues) == 2
        assert [c.agent_id for c in cues] == ["vera", "rex"]
        assert cues[0].text == "hello"
        assert cues[1].text == "world"
        for c in cues:
            assert "[" not in c.text
            assert "]" not in c.text

    def test_skips_malformed_speaker_prefixes(self):
        """Empty, whitespace-only, and unclosed brackets are not voiced."""
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": [],
                "content": "[]: nothing here",
                "created_at": base,
            },
            {
                "participants": [],
                "content": "[ ]: also nothing",
                "created_at": base.replace(second=1),
            },
            {
                "participants": [],
                "content": "[grok unfinished bracket",
                "created_at": base.replace(second=2),
            },
        ]
        cues = build(rows)
        assert cues == []

    def test_intra_row_timestamp_ordering_preserved(self):
        """Cues from one row share timestamp but are monotonically ordered."""
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["vera", "rex", "grok"],
                "content": "[vera]: a [rex]: b [grok]: c",
                "created_at": base,
            },
            {
                "participants": ["sentinel"],
                "content": "[sentinel]: d",
                "created_at": base.replace(second=10),
            },
        ]
        cues = build(rows)
        # Three intra-row cues + one from the next row.
        assert [c.agent_id for c in cues] == ["vera", "rex", "grok", "sentinel"]
        # Strictly increasing within the first row.
        assert cues[0].start_seconds < cues[1].start_seconds < cues[2].start_seconds
        # Intra-row cues stay clustered before the next row at t=10.
        assert cues[2].start_seconds < cues[3].start_seconds
        assert cues[3].start_seconds == 10.0

    def test_drops_narration_before_first_marker(self):
        """Text preceding the first [speaker] marker is not attached to it."""
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["vera"],
                "content": "the room is quiet. [vera]: morning",
                "created_at": base,
            },
        ]
        cues = build(rows)
        assert len(cues) == 1
        assert cues[0].agent_id == "vera"
        assert cues[0].text == "morning"

    def test_known_agents_filter_applied(self):
        """Speakers absent from known_agents are skipped."""
        from datetime import UTC, datetime

        build = self._import()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        rows = [
            {
                "participants": ["vera", "ghost"],
                "content": "[vera]: hi [ghost]: boo",
                "created_at": base,
            },
        ]
        cues = build(rows, known_agents={"vera"})
        assert [c.agent_id for c in cues] == ["vera"]


# ── Replay duration helper ────────────────────────────────────


class TestReplayDuration:
    def test_duration_is_last_cue_start_plus_read_time(self):
        from core.video.audio_timeline import TurnAudioCue
        from core.video.cue_parser import compute_replay_duration, estimate_read_seconds

        cues = [
            TurnAudioCue("vera", "hello", 0.0),
            TurnAudioCue("rex", "this is a longer sentence to read out loud", 30.0),
        ]
        expected = 30.0 + estimate_read_seconds(cues[-1].text)
        assert compute_replay_duration(cues) == expected
        # Sanity: end-of-replay strictly exceeds last cue start.
        assert compute_replay_duration(cues) > 30.0

    def test_empty_cues_duration_zero(self):
        from core.video.cue_parser import compute_replay_duration

        assert compute_replay_duration([]) == 0.0

    def test_read_time_has_floor(self):
        from core.video.cue_parser import (
            DEFAULT_READ_FLOOR_SECONDS,
            estimate_read_seconds,
        )

        assert estimate_read_seconds("hi") == DEFAULT_READ_FLOOR_SECONDS
        assert estimate_read_seconds("") == DEFAULT_READ_FLOOR_SECONDS


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
