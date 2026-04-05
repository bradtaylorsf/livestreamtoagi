"""Edge TTS pipeline with per-agent voices and Management post-processing."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

import edge_tts

from core.event_bus import EventType, event_bus
from core.speech_parser import parse_speech

logger = logging.getLogger(__name__)

# Voice assignments per spec (ENGINEERING-SPECS.md Task 2.2)
VOICE_MAP: dict[str, str] = {
    "vera": "en-GB-SoniaNeural",
    "rex": "en-US-GuyNeural",
    "aurora": "en-US-JennyNeural",
    "pixel": "en-US-DavisNeural",
    "fork": "en-AU-WilliamNeural",
    "sentinel": "en-US-AriaNeural",
    "grok": "en-US-ChristopherNeural",
    "management": "en-US-AndrewNeural",
    # alpha has no voice (text-only)
}


class TTSPipeline:
    """Generates TTS audio via Edge TTS with per-agent voice selection."""

    def __init__(
        self,
        audio_dir: Path | None = None,
        cleanup_ttl: int = 60,
        base_url: str = "/audio",
    ) -> None:
        self.audio_dir = audio_dir or Path(tempfile.mkdtemp(prefix="tts_"))
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_ttl = cleanup_ttl
        self.base_url = base_url.rstrip("/")

    async def speak(self, agent_id: str, text: str) -> dict[str, str | float] | None:
        """Generate TTS audio for an agent's speech.

        Returns None for Alpha (no voice) or on failure after retry.
        Returns dict with agent_id, audio_url, and duration on success.
        """
        voice_id = VOICE_MAP.get(agent_id)
        if voice_id is None:
            return None

        # Strip [action] tags so TTS only speaks dialogue
        parsed = parse_speech(text)
        tts_text = parsed.dialogue or parsed.raw

        filename = f"{uuid.uuid4()}.mp3"
        filepath = self.audio_dir / filename

        # Generate audio with one retry on failure
        for attempt in range(2):
            try:
                communicate = edge_tts.Communicate(tts_text, voice_id)
                await communicate.save(str(filepath))
                break
            except Exception:
                if attempt == 0:
                    logger.warning("Edge TTS failed for %s, retrying once", agent_id)
                    continue
                logger.warning(
                    "Edge TTS failed for %s after retry, skipping TTS",
                    agent_id,
                )
                return None

        # Management post-processing: reverb + pitch-down
        if agent_id == "management":
            processed_path = self.audio_dir / f"{uuid.uuid4()}.mp3"
            try:
                await _apply_management_effects(filepath, processed_path)
                filepath.unlink(missing_ok=True)
                filepath = processed_path
                filename = processed_path.name
            except Exception:
                logger.warning("Management ffmpeg post-processing failed, using raw audio")
                processed_path.unlink(missing_ok=True)

        # Get duration
        duration = await _get_duration(filepath)

        audio_url = f"{self.base_url}/{filename}"
        event_data = {
            "agent_id": agent_id,
            "audio_url": audio_url,
            "duration": duration,
        }

        # Emit TTS_PLAY event
        await event_bus.emit(EventType.TTS_PLAY.value, event_data)

        # Schedule cleanup
        loop = asyncio.get_running_loop()
        loop.call_later(self.cleanup_ttl, _cleanup_file, filepath)

        return event_data

    async def shutdown(self) -> None:
        """Clean up the audio directory on shutdown."""
        import shutil

        shutil.rmtree(self.audio_dir, ignore_errors=True)


async def _get_duration(filepath: Path) -> float:
    """Get audio duration in seconds via ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(filepath),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        logger.warning("ffprobe failed, returning 0.0 duration")
        return 0.0


async def _apply_management_effects(input_path: Path, output_path: Path) -> None:
    """Apply reverb + pitch-down via ffmpeg for Management's deadpan voice."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-af",
        "afreeverb=wet_mix=0.3,asetrate=44100*0.85,aresample=44100",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")


def _cleanup_file(filepath: Path) -> None:
    """Remove an audio file after TTL expiry."""
    try:
        filepath.unlink(missing_ok=True)
    except Exception:
        logger.warning("Failed to clean up %s", filepath)
