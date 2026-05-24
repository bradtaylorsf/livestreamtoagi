"""Livestream health detectors and alert orchestration."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_SUPERVISOR_LOG = Path("logs/livestream/livestream-supervisor.log")
DEFAULT_CHILD_PID_FILE = Path("logs/livestream/supervise-stream-child.pid")
DEFAULT_DOWN_THRESHOLD_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 15.0
DEFAULT_ALERT_COOLDOWN_SECONDS = 300.0
DEFAULT_BLACK_SECONDS = 5.0
DEFAULT_SILENCE_SECONDS = 10.0

STREAM_DOWN = "stream_down"
BLACK_FRAME = "black_frame"
SILENCE = "silence"
RECOVERED = "recovered"

_BLACK_DURATION_RE = re.compile(r"black_duration:(?P<duration>\d+(?:\.\d+)?)")
_SILENCE_DURATION_RE = re.compile(r"silence_duration:\s*(?P<duration>\d+(?:\.\d+)?)")
_LOG_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[^\s]+)")


@dataclass(frozen=True)
class HealthEvent:
    """An alertable stream-health state transition."""

    type: str
    detected_at: datetime
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectorResult:
    """Current health state reported by one detector."""

    healthy: bool
    details: dict[str, object] = field(default_factory=dict)


class HealthDetector(Protocol):
    """Detector interface used by the monitor."""

    event_type: str
    interval_seconds: float

    async def check(self, *, now: datetime | None = None) -> DetectorResult:
        """Return the current detector health state."""


@dataclass(frozen=True)
class ProbeResult:
    """Captured subprocess probe output."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


Probe = Callable[[Sequence[str]], ProbeResult | Awaitable[ProbeResult]]
AlertSink = Callable[[HealthEvent], object | Awaitable[object]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_log_timestamp(line: str) -> datetime | None:
    match = _LOG_TS_RE.match(line.strip())
    if not match:
        return None
    raw = match.group("ts").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _coerce_utc(parsed)


def _line_is_exit(line: str) -> bool:
    lower = line.lower()
    return "child-exited" in lower or "child exited" in lower or "exited unexpectedly" in lower


def _line_is_restart(line: str) -> bool:
    lower = line.lower()
    return "restarting" in lower and "not restarting" not in lower


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("[stream-health] failed to read supervisor log %s: %s", path, exc)
        return []


@dataclass(frozen=True)
class _LogEvent:
    line: str
    timestamp: datetime | None


def _latest_exit_and_restart(lines: Sequence[str]) -> tuple[_LogEvent | None, _LogEvent | None]:
    latest_exit: _LogEvent | None = None
    restart_after_exit: _LogEvent | None = None
    for line in lines:
        if _line_is_exit(line):
            latest_exit = _LogEvent(line=line, timestamp=_parse_log_timestamp(line))
            restart_after_exit = None
        elif latest_exit is not None and _line_is_restart(line):
            restart_after_exit = _LogEvent(line=line, timestamp=_parse_log_timestamp(line))
    return latest_exit, restart_after_exit


def _latest_restart(lines: Sequence[str]) -> _LogEvent | None:
    latest: _LogEvent | None = None
    for line in lines:
        if _line_is_restart(line):
            latest = _LogEvent(line=line, timestamp=_parse_log_timestamp(line))
    return latest


@dataclass
class StreamDownDetector:
    """Detect a dead supervised stream process from supervisor log and PID file."""

    supervisor_log: Path = DEFAULT_SUPERVISOR_LOG
    child_pid_file: Path = DEFAULT_CHILD_PID_FILE
    down_threshold_seconds: float = DEFAULT_DOWN_THRESHOLD_SECONDS
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    max_log_lines: int = 200

    event_type: str = field(default=STREAM_DOWN, init=False)

    async def check(self, *, now: datetime | None = None) -> DetectorResult:
        checked_at = _coerce_utc(now)
        pid_running, pid_details = self._pid_is_running()
        lines = _tail_lines(self.supervisor_log, self.max_log_lines)
        latest_exit, restart_after_exit = _latest_exit_and_restart(lines)
        latest_restart = _latest_restart(lines)

        base_details: dict[str, object] = {
            "supervisor_log": str(self.supervisor_log),
            "child_pid_file": str(self.child_pid_file),
            **pid_details,
        }

        if pid_running:
            return DetectorResult(healthy=True, details=base_details)

        if latest_exit is not None and restart_after_exit is not None:
            restart_details = {
                **base_details,
                "latest_exit": latest_exit.line,
                "latest_restart": restart_after_exit.line,
                "state": "restart_recorded",
            }
            return DetectorResult(healthy=True, details=restart_details)

        if latest_exit is not None:
            elapsed = self._elapsed_seconds(latest_exit.timestamp, checked_at)
            details = {
                **base_details,
                "reason": "child_exited_without_restart",
                "latest_exit": latest_exit.line,
                "elapsed_seconds": elapsed,
                "threshold_seconds": self.down_threshold_seconds,
            }
            if elapsed is None or elapsed >= self.down_threshold_seconds:
                return DetectorResult(healthy=False, details=details)
            return DetectorResult(healthy=True, details={**details, "state": "within_threshold"})

        if latest_restart is not None:
            elapsed = self._elapsed_seconds(latest_restart.timestamp, checked_at)
            details = {
                **base_details,
                "reason": "pid_not_running_after_restart",
                "latest_restart": latest_restart.line,
                "elapsed_seconds": elapsed,
                "threshold_seconds": self.down_threshold_seconds,
            }
            if elapsed is None or elapsed >= self.down_threshold_seconds:
                return DetectorResult(healthy=False, details=details)
            return DetectorResult(healthy=True, details={**details, "state": "restart_in_progress"})

        return DetectorResult(
            healthy=False,
            details={
                **base_details,
                "reason": "pid_not_running_no_restart_recorded",
                "threshold_seconds": self.down_threshold_seconds,
            },
        )

    def _pid_is_running(self) -> tuple[bool, dict[str, object]]:
        try:
            raw = self.child_pid_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return False, {"pid_state": "pid_file_missing"}
        except OSError as exc:
            return False, {"pid_state": "pid_file_unreadable", "pid_error": str(exc)}

        try:
            pid = int(raw)
        except ValueError:
            return False, {"pid_state": "pid_file_invalid", "pid_raw": raw}

        if pid <= 0:
            return False, {"pid_state": "pid_file_invalid", "pid": pid}

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False, {"pid_state": "not_running", "pid": pid}
        except PermissionError:
            return True, {"pid_state": "running_no_permission", "pid": pid}
        except OSError as exc:
            return False, {"pid_state": "pid_check_error", "pid": pid, "pid_error": str(exc)}
        return True, {"pid_state": "running", "pid": pid}

    def _elapsed_seconds(self, started_at: datetime | None, now: datetime) -> float | None:
        if started_at is None:
            return None
        return max(0.0, (now - started_at).total_seconds())


class SubprocessProbe:
    """Default async probe implementation for ffmpeg checks."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def __call__(self, command: Sequence[str]) -> ProbeResult:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            return ProbeResult(
                returncode=124,
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
            )
        return ProbeResult(
            returncode=proc.returncode,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )


@dataclass
class _FfmpegDetector:
    source_url: str
    window_seconds: float
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    ffmpeg_path: str = "ffmpeg"
    probe: Probe | None = None
    probe_timeout_seconds: float | None = None

    event_type: str = field(default="", init=False)

    async def _run_probe(self, command: Sequence[str]) -> ProbeResult:
        probe = self.probe
        if probe is None:
            timeout = self.probe_timeout_seconds or max(30.0, self.window_seconds + 10.0)
            probe = SubprocessProbe(timeout_seconds=timeout)
        result = probe(command)
        if inspect.isawaitable(result):
            return await result
        return result

    def _base_command(self) -> list[str]:
        return [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostats",
            "-i",
            self.source_url,
            "-t",
            str(self.window_seconds),
        ]


@dataclass
class BlackFrameDetector(_FfmpegDetector):
    """Detect sustained black video frames via ffmpeg blackdetect output."""

    min_black_seconds: float = DEFAULT_BLACK_SECONDS
    event_type: str = field(default=BLACK_FRAME, init=False)

    async def check(self, *, now: datetime | None = None) -> DetectorResult:
        del now
        command = [
            *self._base_command(),
            "-vf",
            f"blackdetect=d={self.min_black_seconds}:pic_th=0.98",
            "-an",
            "-f",
            "null",
            "-",
        ]
        result = await self._run_probe(command)
        durations = [
            float(match.group("duration")) for match in _BLACK_DURATION_RE.finditer(result.stderr)
        ]
        tripped = any(duration >= self.min_black_seconds for duration in durations)
        details: dict[str, object] = {
            "source_url": self.source_url,
            "window_seconds": self.window_seconds,
            "min_black_seconds": self.min_black_seconds,
            "durations": durations,
            "probe_returncode": result.returncode,
        }
        return DetectorResult(healthy=not tripped, details=details)


@dataclass
class SilenceDetector(_FfmpegDetector):
    """Detect sustained audio silence via ffmpeg silencedetect output."""

    min_silence_seconds: float = DEFAULT_SILENCE_SECONDS
    event_type: str = field(default=SILENCE, init=False)

    async def check(self, *, now: datetime | None = None) -> DetectorResult:
        del now
        command = [
            *self._base_command(),
            "-af",
            f"silencedetect=noise=-50dB:d={self.min_silence_seconds}",
            "-f",
            "null",
            "-",
        ]
        result = await self._run_probe(command)
        durations = [
            float(match.group("duration")) for match in _SILENCE_DURATION_RE.finditer(result.stderr)
        ]
        tripped = any(duration >= self.min_silence_seconds for duration in durations)
        details: dict[str, object] = {
            "source_url": self.source_url,
            "window_seconds": self.window_seconds,
            "min_silence_seconds": self.min_silence_seconds,
            "durations": durations,
            "probe_returncode": result.returncode,
        }
        return DetectorResult(healthy=not tripped, details=details)


@dataclass
class _DetectorState:
    unhealthy: bool = False
    last_alert_at: datetime | None = None
    next_poll_at: datetime | None = None


class StreamHealthMonitor:
    """Poll detectors, de-duplicate alerts, and emit recovery events."""

    def __init__(
        self,
        detectors: Sequence[HealthDetector],
        *,
        alert_sink: AlertSink,
        alert_cooldown_seconds: float = DEFAULT_ALERT_COOLDOWN_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.detectors = list(detectors)
        self.alert_sink = alert_sink
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._states: dict[str, _DetectorState] = {
            detector.event_type: _DetectorState() for detector in self.detectors
        }

    async def poll_once(
        self,
        *,
        now: datetime | None = None,
        force: bool = True,
    ) -> list[HealthEvent]:
        checked_at = _coerce_utc(now)
        emitted: list[HealthEvent] = []
        for detector in self.detectors:
            state = self._states.setdefault(detector.event_type, _DetectorState())
            if not force and state.next_poll_at is not None and checked_at < state.next_poll_at:
                continue
            state.next_poll_at = checked_at + timedelta(seconds=detector.interval_seconds)

            try:
                result = await detector.check(now=checked_at)
            except Exception as exc:  # noqa: BLE001 - keep the monitor alive
                logger.exception("[stream-health] detector %s failed", detector.event_type)
                result = DetectorResult(
                    healthy=False,
                    details={"reason": "detector_error", "error": str(exc)},
                )

            event = self._event_for_result(detector.event_type, result, state, checked_at)
            if event is None:
                continue
            emitted.append(event)
            await self._deliver(event)
        return emitted

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            await self.poll_once(force=False)
            sleep_for = self._next_sleep_seconds()
            if stop_event is None:
                await asyncio.sleep(sleep_for)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
            except TimeoutError:
                pass

    def _event_for_result(
        self,
        event_type: str,
        result: DetectorResult,
        state: _DetectorState,
        now: datetime,
    ) -> HealthEvent | None:
        if result.healthy:
            if not state.unhealthy:
                return None
            state.unhealthy = False
            state.last_alert_at = None
            return HealthEvent(
                type=RECOVERED,
                detected_at=now,
                details={"recovered_type": event_type, **result.details},
            )

        in_cooldown = (
            state.last_alert_at is not None
            and (now - state.last_alert_at).total_seconds() < self.alert_cooldown_seconds
        )
        state.unhealthy = True
        if in_cooldown:
            return None
        state.last_alert_at = now
        return HealthEvent(type=event_type, detected_at=now, details=result.details)

    async def _deliver(self, event: HealthEvent) -> None:
        try:
            result = self.alert_sink(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - alert failures must not stop detection
            logger.exception("[stream-health] alert sink failed for %s", event.type)

    def _next_sleep_seconds(self) -> float:
        now = _utc_now()
        next_times = [
            state.next_poll_at for state in self._states.values() if state.next_poll_at is not None
        ]
        if not next_times:
            return self.poll_interval_seconds
        seconds = min((next_time - now).total_seconds() for next_time in next_times)
        return max(0.1, min(self.poll_interval_seconds, seconds))
