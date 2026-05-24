"""Tests for routing live TTS audio into the livestream FIFO."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from core.event_bus import EventBus, EventType
from core.streaming.tts_stream_bridge import TTSStreamBridge, TTSStreamBridgeConfig


def _config(fifo_path: Path, **overrides: Any) -> TTSStreamBridgeConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "fifo_path": fifo_path,
        "sample_rate": 44100,
        "channels": 2,
        "silence_chunk_seconds": 0.01,
        "post_utterance_silence_seconds": 0.01,
    }
    values.update(overrides)
    return TTSStreamBridgeConfig(**values)


def test_config_from_env_treats_blank_values_as_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTS_STREAM_ENABLED", "1")
    monkeypatch.setenv("TTS_STREAM_FIFO", "")
    monkeypatch.setenv("TTS_STREAM_SAMPLE_RATE", "")
    monkeypatch.setenv("TTS_STREAM_CHANNELS", "")

    config = TTSStreamBridgeConfig.from_env()

    assert config.enabled is True
    assert config.fifo_path == Path("/tmp/livestream_tts.fifo")
    assert config.sample_rate == 44100
    assert config.channels == 2


async def test_start_subscribes_to_tts_play_and_queues_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = EventBus()
    audio = tmp_path / "one.mp3"
    audio.write_bytes(b"fake mp3")
    bridge = TTSStreamBridge(
        event_bus=bus,
        audio_dir=tmp_path,
        config=_config(tmp_path / "tts.fifo"),
    )

    async def parked_worker() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge, "_worker_loop", parked_worker)

    await bridge.start()
    await bus.emit(EventType.TTS_PLAY.value, {"audio_url": f"/audio/{audio.name}"})

    assert bridge._queue.get_nowait() == audio.resolve()

    await bridge.stop(unlink_fifo=True)
    await bus.emit(EventType.TTS_PLAY.value, {"audio_url": f"/audio/{audio.name}"})
    assert bridge._queue.empty()


async def test_tts_events_queue_in_order_and_missing_files_are_skipped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    bridge = TTSStreamBridge(
        event_bus=EventBus(),
        audio_dir=tmp_path,
        config=_config(tmp_path / "tts.fifo"),
    )

    await bridge._on_tts_play({"data": {"audio_url": "/audio/first.mp3"}})
    with caplog.at_level(logging.WARNING):
        await bridge._on_tts_play({"data": {"audio_url": "/audio/missing.mp3"}})
    await bridge._on_tts_play({"data": {"audio_url": "/audio/second.mp3"}})

    assert bridge._queue.get_nowait() == first.resolve()
    assert bridge._queue.get_nowait() == second.resolve()
    assert bridge._queue.empty()
    assert "Skipping missing TTS stream audio file" in caplog.text


async def test_stream_audio_file_invokes_ffmpeg_and_writes_pcm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")
    bridge = TTSStreamBridge(
        event_bus=EventBus(),
        audio_dir=tmp_path,
        config=_config(tmp_path / "tts.fifo", sample_rate=22050, channels=1),
    )
    writes: list[bytes] = []
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class FakeStdout:
        def __init__(self) -> None:
            self._chunks = [b"pcm-a", b"pcm-b", b""]

        async def read(self, _: int) -> bytes:
            return self._chunks.pop(0)

    class FakeProc:
        stdout = FakeStdout()
        returncode = 0

        async def wait(self) -> int:
            return self.returncode

        def kill(self) -> None:
            raise AssertionError("process should not be killed")

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeProc:
        calls.append((args, kwargs))
        return FakeProc()

    async def fake_write_bytes(data: bytes) -> bool:
        writes.append(data)
        return True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(bridge, "_write_bytes", fake_write_bytes)

    await bridge._stream_audio_file(audio)

    assert writes == [b"pcm-a", b"pcm-b"]
    args, kwargs = calls[0]
    assert args == (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-re",
        "-i",
        str(audio),
        "-f",
        "s16le",
        "-ar",
        "22050",
        "-ac",
        "1",
        "pipe:1",
    )
    assert kwargs["stdout"] == asyncio.subprocess.PIPE


async def test_write_bytes_reaches_fifo_reader(tmp_path: Path) -> None:
    fifo = tmp_path / "tts.fifo"
    os.mkfifo(fifo)
    bridge = TTSStreamBridge(
        event_bus=EventBus(),
        audio_dir=tmp_path,
        config=_config(fifo),
    )

    reader_fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        assert bridge._ensure_fifo_open()
        assert await bridge._write_bytes(b"pcm-data")

        data = b""
        for _ in range(20):
            try:
                data += os.read(reader_fd, 1024)
            except BlockingIOError:
                await asyncio.sleep(0.01)
                continue
            if data:
                break
        assert data == b"pcm-data"
    finally:
        bridge._close_fifo()
        os.close(reader_fd)


async def test_play_audio_path_writes_silence_after_utterance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")
    bridge = TTSStreamBridge(
        event_bus=EventBus(),
        audio_dir=tmp_path,
        config=_config(
            tmp_path / "tts.fifo",
            sample_rate=100,
            channels=1,
            post_utterance_silence_seconds=0.01,
        ),
    )
    writes: list[bytes] = []

    async def fake_stream_audio_file(_: Path) -> None:
        writes.append(b"audio")

    async def fake_write_bytes(data: bytes) -> bool:
        writes.append(data)
        return True

    monkeypatch.setattr(bridge, "_stream_audio_file", fake_stream_audio_file)
    monkeypatch.setattr(bridge, "_write_bytes", fake_write_bytes)

    await bridge._play_audio_path(audio)

    assert writes == [b"audio", b"\0\0"]


async def test_stop_unregisters_worker_and_closes_fifo_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = EventBus()
    audio = tmp_path / "one.mp3"
    audio.write_bytes(b"fake")
    bridge = TTSStreamBridge(
        event_bus=bus,
        audio_dir=tmp_path,
        config=_config(tmp_path / "tts.fifo"),
    )

    async def parked_worker() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge, "_worker_loop", parked_worker)

    await bridge.start()
    read_fd, write_fd = os.pipe()
    bridge._fifo_fd = write_fd
    try:
        await bridge.stop(unlink_fifo=True)

        with pytest.raises(OSError):
            os.write(write_fd, b"x")

        await bus.emit(EventType.TTS_PLAY.value, {"audio_url": f"/audio/{audio.name}"})
        assert bridge._queue.empty()
    finally:
        os.close(read_fd)
