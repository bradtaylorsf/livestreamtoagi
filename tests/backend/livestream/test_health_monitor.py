from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.livestream import (
    BLACK_FRAME,
    RECOVERED,
    SILENCE,
    STREAM_DOWN,
    BlackFrameDetector,
    ProbeResult,
    SilenceDetector,
    StreamDownDetector,
    StreamHealthMonitor,
)
from core.livestream.health_monitor import HealthEvent


def _log_line(at: datetime, message: str) -> str:
    return f"{at.isoformat().replace('+00:00', 'Z')} {message}\n"


@pytest.mark.asyncio
async def test_stream_down_detector_reports_stale_child_exit_without_restart(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    supervisor_log = tmp_path / "supervisor.log"
    supervisor_log.write_text(
        _log_line(now - timedelta(seconds=45), "supervisor: child-exited exit=1"),
        encoding="utf-8",
    )
    detector = StreamDownDetector(
        supervisor_log=supervisor_log,
        child_pid_file=tmp_path / "missing.pid",
        down_threshold_seconds=30,
    )

    result = await detector.check(now=now)

    assert not result.healthy
    assert result.details["reason"] == "child_exited_without_restart"
    assert result.details["pid_state"] == "pid_file_missing"


@pytest.mark.asyncio
async def test_stream_down_detector_treats_matching_restart_as_healthy(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    supervisor_log = tmp_path / "supervisor.log"
    supervisor_log.write_text(
        _log_line(now - timedelta(seconds=45), "supervisor: child-exited exit=1")
        + _log_line(now - timedelta(seconds=40), "supervisor: restarting in 10s"),
        encoding="utf-8",
    )
    detector = StreamDownDetector(
        supervisor_log=supervisor_log,
        child_pid_file=tmp_path / "missing.pid",
        down_threshold_seconds=30,
    )

    result = await detector.check(now=now)

    assert result.healthy
    assert result.details["state"] == "restart_recorded"


@pytest.mark.asyncio
async def test_black_frame_detector_parses_ffmpeg_blackdetect_output() -> None:
    calls: list[Sequence[str]] = []

    def probe(command: Sequence[str]) -> ProbeResult:
        calls.append(command)
        return ProbeResult(
            returncode=0,
            stderr="[blackdetect @ 0x1] black_start:0 black_end:6 black_duration:6\n",
        )

    detector = BlackFrameDetector(
        source_url="rtmp://example/live",
        window_seconds=8,
        probe=probe,
        min_black_seconds=5,
    )

    result = await detector.check()

    assert not result.healthy
    assert result.details["durations"] == [6.0]
    assert "blackdetect=d=5" in " ".join(calls[0])


@pytest.mark.asyncio
async def test_silence_detector_parses_ffmpeg_silencedetect_output() -> None:
    calls: list[Sequence[str]] = []

    def probe(command: Sequence[str]) -> ProbeResult:
        calls.append(command)
        return ProbeResult(
            returncode=0,
            stderr=(
                "[silencedetect @ 0x1] silence_start:0\n"
                "[silencedetect @ 0x1] silence_end:11 | silence_duration: 11\n"
            ),
        )

    detector = SilenceDetector(
        source_url="rtmp://example/live",
        window_seconds=12,
        probe=probe,
        min_silence_seconds=10,
    )

    result = await detector.check()

    assert not result.healthy
    assert result.details["durations"] == [11.0]
    assert "silencedetect=noise=-50dB:d=10" in " ".join(calls[0])


@pytest.mark.asyncio
async def test_monitor_alerts_once_per_outage_type_suppresses_cooldown_and_recovers(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    supervisor_log = tmp_path / "supervisor.log"
    supervisor_log.write_text(
        _log_line(now - timedelta(seconds=60), "supervisor: child-exited exit=1"),
        encoding="utf-8",
    )
    probe_state = {"black": True, "silence": True}
    delivered: list[HealthEvent] = []

    def black_probe(command: Sequence[str]) -> ProbeResult:
        del command
        if probe_state["black"]:
            return ProbeResult(returncode=0, stderr="black_duration:6\n")
        return ProbeResult(returncode=0, stderr="")

    def silence_probe(command: Sequence[str]) -> ProbeResult:
        del command
        if probe_state["silence"]:
            return ProbeResult(returncode=0, stderr="silence_duration: 11\n")
        return ProbeResult(returncode=0, stderr="")

    async def sink(event: HealthEvent) -> None:
        delivered.append(event)

    monitor = StreamHealthMonitor(
        [
            StreamDownDetector(
                supervisor_log=supervisor_log,
                child_pid_file=tmp_path / "missing.pid",
                down_threshold_seconds=30,
                interval_seconds=1,
            ),
            BlackFrameDetector(
                source_url="rtmp://example/live",
                window_seconds=8,
                interval_seconds=1,
                probe=black_probe,
                min_black_seconds=5,
            ),
            SilenceDetector(
                source_url="rtmp://example/live",
                window_seconds=12,
                interval_seconds=1,
                probe=silence_probe,
                min_silence_seconds=10,
            ),
        ],
        alert_sink=sink,
        alert_cooldown_seconds=300,
        poll_interval_seconds=1,
    )

    first = await monitor.poll_once(now=now)
    second = await monitor.poll_once(now=now + timedelta(seconds=10))
    supervisor_log.write_text(
        supervisor_log.read_text(encoding="utf-8")
        + _log_line(now + timedelta(seconds=15), "supervisor: restarting in 10s"),
        encoding="utf-8",
    )
    probe_state["black"] = False
    probe_state["silence"] = False
    third = await monitor.poll_once(now=now + timedelta(seconds=20))

    assert {event.type for event in first} == {STREAM_DOWN, BLACK_FRAME, SILENCE}
    assert second == []
    assert [event.type for event in third] == [RECOVERED, RECOVERED, RECOVERED]
    assert {event.details["recovered_type"] for event in third} == {
        STREAM_DOWN,
        BLACK_FRAME,
        SILENCE,
    }
    assert delivered == first + third
