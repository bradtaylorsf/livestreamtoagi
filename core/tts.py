"""Edge TTS pipeline with per-agent voices and Management post-processing."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import edge_tts

from core.event_bus import EventType, event_bus
from core.speech_parser import parse_speech, parse_speech_segments

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)


class TTSPipeline:
    """Generates TTS audio via Edge TTS with per-agent voice selection."""

    def __init__(
        self,
        agent_registry: AgentRegistry | None = None,
        audio_dir: Path | None = None,
        cleanup_ttl: int = 60,
        base_url: str = "/audio",
    ) -> None:
        self._agent_registry = agent_registry
        self.audio_dir = audio_dir or Path(tempfile.mkdtemp(prefix="tts_"))
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_ttl = cleanup_ttl
        self.base_url = base_url.rstrip("/")

    def _get_voice_id(self, agent_id: str) -> str | None:
        """Look up voice ID from agent registry."""
        if self._agent_registry is not None:
            agent = self._agent_registry.get_agent(agent_id)
            if agent is not None:
                return agent.voice_id
        return None

    def _get_audio_effects(self, agent_id: str) -> str | None:
        """Look up audio effects from agent registry."""
        if self._agent_registry is not None:
            agent = self._agent_registry.get_agent(agent_id)
            if agent is not None:
                return agent.audio_effects
        return None

    async def generate(self, agent_id: str, text: str, *, cleanup_ttl: int | None = None) -> dict[str, Any] | None:
        """Generate TTS audio and return the result WITHOUT emitting any event.

        Use this when you want to pre-generate audio (e.g. batch mode) and will
        emit the event yourself later. Returns the same payload as speak().

        *cleanup_ttl* overrides the instance default for how long (seconds) to
        keep the audio file before deleting it.  Pass a larger value when audio
        won't be played back immediately (e.g. batch pre-generation).
        """
        voice_id = self._get_voice_id(agent_id)
        if voice_id is None:
            return None

        parsed = parse_speech(text)
        tts_text = parsed.dialogue or parsed.raw

        filename = f"{uuid.uuid4()}.mp3"
        filepath = self.audio_dir / filename

        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(tts_text, voice_id)
                await communicate.save(str(filepath))
                break
            except Exception:
                if attempt < 2:
                    logger.warning("Edge TTS failed for %s (attempt %d/3), retrying", agent_id, attempt + 1)
                    await asyncio.sleep(1.0)
                    continue
                logger.warning("Edge TTS failed for %s after 3 attempts", agent_id)
                return None

        if self._get_audio_effects(agent_id) == "reverb_pitch_down":
            processed_path = self.audio_dir / f"{uuid.uuid4()}.mp3"
            try:
                await _apply_management_effects(filepath, processed_path)
                filepath.unlink(missing_ok=True)
                filepath = processed_path
                filename = processed_path.name
            except Exception:
                logger.warning("Management ffmpeg post-processing failed, using raw audio")
                processed_path.unlink(missing_ok=True)

        duration = await _get_duration(filepath)
        audio_url = f"{self.base_url}/{filename}"

        ttl = cleanup_ttl if cleanup_ttl is not None else self.cleanup_ttl
        loop = asyncio.get_running_loop()
        loop.call_later(ttl, _cleanup_file, filepath)

        return {
            "agent_id": agent_id,
            "audio_url": audio_url,
            "duration": duration,
            "text": tts_text,
        }

    async def speak(self, agent_id: str, text: str) -> dict[str, str | float] | None:
        """Generate TTS audio and emit a tts_play event.

        Returns None for Alpha (no voice) or on failure after retry.
        Returns dict with agent_id, audio_url, duration, and text on success.
        """
        result = await self.generate(agent_id, text)
        if result is None:
            return None

        # Emit TTS_PLAY event so AudioManager picks it up
        await event_bus.emit(EventType.TTS_PLAY.value, result)
        return result

    async def speak_segmented(
        self, agent_id: str, text: str
    ) -> list[dict[str, Any]] | None:
        """Generate TTS audio per dialogue segment and return segment descriptors.

        Splits *text* on [action] tags so each short dialogue chunk becomes its
        own audio file, enabling the frontend to start playback immediately after
        the first (usually short) segment is ready.

        Returns ``None`` for silent agents (Alpha) or when the agent has no voice.
        Returns a list of segment dicts, each with:
        - ``text``      – cleaned dialogue text for this segment
        - ``audio_url`` – URL to the generated MP3
        - ``duration``  – audio duration in seconds
        - ``action``    – (optional) action description preceding this segment
        """
        voice_id = self._get_voice_id(agent_id)
        if voice_id is None:
            return None

        segments = parse_speech_segments(text)
        if not segments:
            # Action-only text — nothing to speak
            return None

        results: list[dict[str, Any]] = []

        for dialogue_text, preceding_action in segments:
            filename = f"{uuid.uuid4()}.mp3"
            filepath = self.audio_dir / filename

            success = False
            for attempt in range(2):
                try:
                    communicate = edge_tts.Communicate(dialogue_text, voice_id)
                    await communicate.save(str(filepath))
                    success = True
                    break
                except Exception:
                    if attempt == 0:
                        logger.warning(
                            "Edge TTS segment failed for %s, retrying", agent_id
                        )
                        continue
                    logger.warning(
                        "Edge TTS segment failed for %s after retry, skipping segment",
                        agent_id,
                    )

            if not success:
                continue

            # Post-processing (Management only)
            if self._get_audio_effects(agent_id) == "reverb_pitch_down":
                processed_path = self.audio_dir / f"{uuid.uuid4()}.mp3"
                try:
                    await _apply_management_effects(filepath, processed_path)
                    filepath.unlink(missing_ok=True)
                    filepath = processed_path
                    filename = processed_path.name
                except Exception:
                    logger.warning(
                        "Management ffmpeg post-processing failed for segment, using raw audio"
                    )
                    processed_path.unlink(missing_ok=True)

            duration = await _get_duration(filepath)
            audio_url = f"{self.base_url}/{filename}"

            loop = asyncio.get_running_loop()
            loop.call_later(self.cleanup_ttl, _cleanup_file, filepath)

            segment: dict[str, Any] = {
                "text": dialogue_text,
                "audio_url": audio_url,
                "duration": duration,
            }
            if preceding_action:
                segment["action"] = preceding_action

            results.append(segment)

        return results if results else None

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
