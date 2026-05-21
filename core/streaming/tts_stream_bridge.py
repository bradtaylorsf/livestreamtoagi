"""Bridge approved TTS events into a PCM FIFO consumed by the livestream."""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or str(default))


@dataclass(frozen=True)
class TTSStreamBridgeConfig:
    """Runtime settings for the TTS stream bridge."""

    enabled: bool = False
    fifo_path: Path = Path("/tmp/livestream_tts.fifo")
    sample_rate: int = 44100
    channels: int = 2
    audio_base_url: str = "/audio"
    queue_size: int = 32
    silence_chunk_seconds: float = 0.1
    post_utterance_silence_seconds: float = 0.15

    @classmethod
    def from_env(cls) -> TTSStreamBridgeConfig:
        """Build config from the documented livestream TTS environment."""
        return cls(
            enabled=_env_bool("TTS_STREAM_ENABLED", default=False),
            fifo_path=Path(os.environ.get("TTS_STREAM_FIFO") or "/tmp/livestream_tts.fifo"),
            sample_rate=_env_int("TTS_STREAM_SAMPLE_RATE", 44100),
            channels=_env_int("TTS_STREAM_CHANNELS", 2),
        )


class TTSStreamBridge:
    """Subscribe to ``tts_play`` and write decoded PCM into a livestream FIFO."""

    sample_width_bytes = 2

    def __init__(
        self,
        *,
        event_bus: EventBus,
        audio_dir: Path,
        config: TTSStreamBridgeConfig | None = None,
        ffmpeg_bin: str = "ffmpeg",
    ) -> None:
        self._event_bus = event_bus
        self._audio_dir = audio_dir.resolve()
        self._config = config or TTSStreamBridgeConfig.from_env()
        self._ffmpeg_bin = ffmpeg_bin
        self._queue: asyncio.Queue[Path] = asyncio.Queue(maxsize=self._config.queue_size)
        self._worker_task: asyncio.Task[None] | None = None
        self._fifo_fd: int | None = None
        self._registered = False

    @property
    def fifo_path(self) -> Path:
        return self._config.fifo_path

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @classmethod
    def from_env(
        cls,
        *,
        event_bus: EventBus,
        audio_dir: Path,
        ffmpeg_bin: str = "ffmpeg",
    ) -> TTSStreamBridge:
        return cls(
            event_bus=event_bus,
            audio_dir=audio_dir,
            config=TTSStreamBridgeConfig.from_env(),
            ffmpeg_bin=ffmpeg_bin,
        )

    async def start(self) -> None:
        """Create the FIFO, subscribe to TTS events, and start the writer loop."""
        if not self.enabled:
            logger.info("TTS stream bridge disabled")
            return

        self._ensure_fifo()
        if not self._registered:
            self._event_bus.on(EventType.TTS_PLAY.value, self._on_tts_play)
            self._registered = True

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._worker_loop(),
                name="tts-stream-bridge",
            )
        logger.info("TTS stream bridge writing PCM to %s", self.fifo_path)

    async def stop(self, *, unlink_fifo: bool = False) -> None:
        """Stop the bridge and optionally remove the FIFO it created."""
        if self._registered:
            self._event_bus.off(EventType.TTS_PLAY.value, self._on_tts_play)
            self._registered = False

        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        self._close_fifo()
        if unlink_fifo:
            try:
                self.fifo_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to unlink TTS stream FIFO %s", self.fifo_path)

    async def _on_tts_play(self, event: dict[str, Any]) -> None:
        data = event.get("data", event)
        audio_url = data.get("audio_url") if isinstance(data, dict) else None
        if not isinstance(audio_url, str) or not audio_url:
            logger.warning("Skipping TTS stream event without audio_url")
            return

        audio_path = self._resolve_audio_url(audio_url)
        if audio_path is None:
            return

        try:
            self._queue.put_nowait(audio_path)
        except asyncio.QueueFull:
            logger.warning("TTS stream queue full; dropping %s", audio_path.name)

    def _resolve_audio_url(self, audio_url: str) -> Path | None:
        parsed = urlparse(audio_url)
        path = unquote(parsed.path or audio_url)
        base_url = self._config.audio_base_url.rstrip("/")

        if path.startswith(f"{base_url}/") or (not parsed.scheme and "/" not in path):
            filename = Path(path).name
        else:
            logger.warning("Skipping TTS stream URL outside %s: %s", base_url, audio_url)
            return None

        if Path(filename).suffix.lower() != ".mp3":
            logger.warning("Skipping non-mp3 TTS stream asset: %s", filename)
            return None

        candidate = (self._audio_dir / filename).resolve()
        try:
            candidate.relative_to(self._audio_dir)
        except ValueError:
            logger.warning("Skipping TTS stream path outside audio_dir: %s", audio_url)
            return None

        if not candidate.is_file():
            logger.warning("Skipping missing TTS stream audio file: %s", candidate)
            return None
        return candidate

    def _ensure_fifo(self) -> None:
        self.fifo_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            mode = self.fifo_path.stat().st_mode
        except FileNotFoundError:
            os.mkfifo(self.fifo_path, 0o600)
            return

        if not stat.S_ISFIFO(mode):
            raise RuntimeError(f"TTS stream path exists but is not a FIFO: {self.fifo_path}")

    def _ensure_fifo_open(self) -> bool:
        if self._fifo_fd is not None:
            return True
        try:
            self._fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            return True
        except OSError as exc:
            if exc.errno == errno.ENXIO:
                return False
            raise

    async def _worker_loop(self) -> None:
        while True:
            if not self._ensure_fifo_open():
                await self._drop_or_wait_for_reader()
                continue

            try:
                audio_path = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._config.silence_chunk_seconds,
                )
            except TimeoutError:
                await self._write_silence(self._config.silence_chunk_seconds)
                continue

            try:
                await self._play_audio_path(audio_path)
            finally:
                self._queue.task_done()

    async def _drop_or_wait_for_reader(self) -> None:
        try:
            audio_path = await asyncio.wait_for(
                self._queue.get(),
                timeout=self._config.silence_chunk_seconds,
            )
        except TimeoutError:
            return

        logger.warning("Dropping TTS audio because no FIFO reader is connected: %s", audio_path)
        self._queue.task_done()

    async def _play_audio_path(self, audio_path: Path) -> None:
        await self._stream_audio_file(audio_path)
        await self._write_silence(self._config.post_utterance_silence_seconds)

    async def _stream_audio_file(self, audio_path: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            self._ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-i",
            str(audio_path),
            "-f",
            "s16le",
            "-ar",
            str(self._config.sample_rate),
            "-ac",
            str(self._config.channels),
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if proc.stdout is None:
            logger.warning("ffmpeg did not expose stdout for TTS stream decode")
            return

        while True:
            chunk = await proc.stdout.read(16384)
            if not chunk:
                break
            if not await self._write_bytes(chunk):
                proc.kill()
                await proc.wait()
                return

        returncode = await proc.wait()
        if returncode != 0:
            logger.warning("ffmpeg failed decoding TTS audio %s (exit %s)", audio_path, returncode)

    async def _write_silence(self, seconds: float) -> bool:
        if seconds <= 0:
            return True
        byte_count = int(
            self._config.sample_rate * self._config.channels * self.sample_width_bytes * seconds
        )
        return await self._write_bytes(b"\0" * byte_count)

    async def _write_bytes(self, data: bytes) -> bool:
        if not data:
            return True
        if not self._ensure_fifo_open():
            return False
        assert self._fifo_fd is not None

        view = memoryview(data)
        while view:
            try:
                written = os.write(self._fifo_fd, view)
                view = view[written:]
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except BrokenPipeError:
                logger.warning("TTS stream FIFO reader disconnected")
                self._close_fifo()
                return False
        return True

    def _close_fifo(self) -> None:
        if self._fifo_fd is None:
            return
        try:
            os.close(self._fifo_fd)
        except OSError:
            pass
        finally:
            self._fifo_fd = None
