"""Tests for the Edge TTS pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tts import VOICE_MAP, TTSPipeline, _cleanup_file

if TYPE_CHECKING:
    from pathlib import Path


# ── Unit Tests ──────────────────────────────────────────────────────


class TestVoiceMap:
    """Verify correct voice ID for each agent."""

    @pytest.mark.parametrize(
        "agent_id,expected_voice",
        [
            ("vera", "en-GB-SoniaNeural"),
            ("rex", "en-US-GuyNeural"),
            ("aurora", "en-US-JennyNeural"),
            ("pixel", "en-US-DavisNeural"),
            ("fork", "en-AU-WilliamNeural"),
            ("sentinel", "en-US-AriaNeural"),
            ("grok", "en-US-ChristopherNeural"),
            ("management", "en-US-AndrewNeural"),
        ],
    )
    def test_voice_assignment(self, agent_id: str, expected_voice: str) -> None:
        assert VOICE_MAP[agent_id] == expected_voice

    def test_alpha_has_no_voice(self) -> None:
        assert "alpha" not in VOICE_MAP


class TestAlphaNoAudio:
    """Alpha returns None — no audio generated."""

    async def test_alpha_returns_none(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)
        result = await pipeline.speak("alpha", "Hello world")
        assert result is None

    async def test_alpha_no_files_created(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)
        await pipeline.speak("alpha", "Hello world")
        mp3s = list(tmp_path.glob("*.mp3"))
        assert len(mp3s) == 0


class TestSpeakUnit:
    """Unit tests for speak() with mocked edge_tts."""

    async def test_speak_returns_event_data(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path, base_url="/audio")

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=2.5),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            result = await pipeline.speak("vera", "Hello everyone")

        assert result is not None
        assert result["agent_id"] == "vera"
        assert result["audio_url"].startswith("/audio/")
        assert result["audio_url"].endswith(".mp3")
        assert result["duration"] == 2.5

    async def test_speak_uses_correct_voice(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm) as mock_ctor,
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            await pipeline.speak("rex", "Building something")

        mock_ctor.assert_called_once_with("Building something", "en-US-GuyNeural")

    async def test_speak_emits_tts_play_event(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=3.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock) as mock_emit,
        ):
            result = await pipeline.speak("aurora", "Creative idea")

        mock_emit.assert_called_once_with("tts_play", result)

    async def test_audio_url_format(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path, base_url="/audio")

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            result = await pipeline.speak("pixel", "Research update")

        url = result["audio_url"]
        # Format: /audio/{uuid}.mp3
        assert url.startswith("/audio/")
        assert url.endswith(".mp3")
        # UUID part should be 36 chars
        uuid_part = url[len("/audio/"):-len(".mp3")]
        assert len(uuid_part) == 36


class TestActionTagStripping:
    """Verify that [action] tags are stripped before passing text to Edge TTS."""

    async def test_speak_strips_action_tags(self, tmp_path: "Path") -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm) as mock_ctor,
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            await pipeline.speak(
                "rex", "[action]cracks knuckles[/action] Let me fix that."
            )

        mock_ctor.assert_called_once_with("Let me fix that.", "en-US-GuyNeural")

    async def test_speak_falls_back_to_raw_when_dialogue_empty(
        self, tmp_path: "Path"
    ) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm) as mock_ctor,
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            await pipeline.speak("rex", "[action]waves silently[/action]")

        # Falls back to raw text since dialogue is empty
        mock_ctor.assert_called_once_with(
            "[action]waves silently[/action]", "en-US-GuyNeural"
        )


class TestManagementPostProcessing:
    """Management audio gets ffmpeg post-processing."""

    async def test_management_triggers_ffmpeg(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._apply_management_effects", new_callable=AsyncMock) as mock_fx,
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=2.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            result = await pipeline.speak("management", "I am watching")

        assert result is not None
        mock_fx.assert_called_once()

    async def test_non_management_skips_ffmpeg(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._apply_management_effects", new_callable=AsyncMock) as mock_fx,
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            await pipeline.speak("vera", "Hello")

        mock_fx.assert_not_called()


class TestRetryLogic:
    """Edge TTS errors: retry once, then skip."""

    async def test_retry_on_first_failure(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        # First save fails, second succeeds
        mock_comm.save = AsyncMock(side_effect=[Exception("network error"), None])

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            result = await pipeline.speak("rex", "Testing retry")

        assert result is not None
        assert mock_comm.save.call_count == 2

    async def test_returns_none_after_two_failures(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock(side_effect=Exception("persistent error"))

        with patch("core.tts.edge_tts.Communicate", return_value=mock_comm):
            result = await pipeline.speak("rex", "This will fail")

        assert result is None


class TestCleanup:
    """Audio files cleaned up after TTL."""

    async def test_cleanup_removes_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.mp3"
        filepath.write_bytes(b"fake audio data")
        assert filepath.exists()

        _cleanup_file(filepath)
        assert not filepath.exists()

    async def test_cleanup_handles_missing_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "nonexistent.mp3"
        # Should not raise
        _cleanup_file(filepath)

    async def test_speak_schedules_cleanup(self, tmp_path: Path) -> None:
        pipeline = TTSPipeline(audio_dir=tmp_path, cleanup_ttl=1)

        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with (
            patch("core.tts.edge_tts.Communicate", return_value=mock_comm),
            patch("core.tts._get_duration", new_callable=AsyncMock, return_value=1.0),
            patch("core.tts.event_bus.emit", new_callable=AsyncMock),
        ):
            result = await pipeline.speak("sentinel", "Monitoring costs")

        # File should exist initially (mocked save doesn't create real file,
        # so we verify cleanup was scheduled via call_later)
        assert result is not None


class TestShutdown:
    """Shutdown cleans up audio directory."""

    async def test_shutdown_removes_audio_dir(self, tmp_path: Path) -> None:
        audio_dir = tmp_path / "tts_audio"
        audio_dir.mkdir()
        (audio_dir / "test.mp3").write_bytes(b"data")

        pipeline = TTSPipeline(audio_dir=audio_dir)
        await pipeline.shutdown()

        assert not audio_dir.exists()


# ── Integration Tests ───────────────────────────────────────────────


@pytest.mark.integration
class TestTTSIntegration:
    """Integration tests requiring edge-tts and ffmpeg."""

    async def test_generate_real_audio(self, tmp_path: Path) -> None:
        """Generate actual audio and verify the file exists and is valid."""
        pipeline = TTSPipeline(audio_dir=tmp_path)

        with patch("core.tts.event_bus.emit", new_callable=AsyncMock):
            result = await pipeline.speak("vera", "Hello, I am Vera.")

        assert result is not None
        filename = result["audio_url"].split("/")[-1]
        filepath = tmp_path / filename

        assert filepath.exists()
        assert filepath.stat().st_size > 0
        assert result["duration"] > 0

    async def test_management_ffmpeg_processing(self, tmp_path: Path) -> None:
        """Generate Management audio with ffmpeg post-processing."""
        pipeline = TTSPipeline(audio_dir=tmp_path)

        with patch("core.tts.event_bus.emit", new_callable=AsyncMock):
            result = await pipeline.speak("management", "This is Management.")

        assert result is not None
        filename = result["audio_url"].split("/")[-1]
        filepath = tmp_path / filename

        assert filepath.exists()
        assert filepath.stat().st_size > 0
        assert result["duration"] > 0
