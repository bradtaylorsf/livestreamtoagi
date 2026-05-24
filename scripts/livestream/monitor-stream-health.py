#!/usr/bin/env python3
"""Run livestream health monitoring and alerting."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from core.livestream import (  # noqa: E402
    BLACK_FRAME,
    SILENCE,
    STREAM_DOWN,
    BlackFrameDetector,
    ProbeResult,
    SilenceDetector,
    StreamDownDetector,
    StreamHealthMonitor,
)
from core.livestream.health_monitor import (  # noqa: E402
    DEFAULT_ALERT_COOLDOWN_SECONDS,
    DEFAULT_BLACK_SECONDS,
    DEFAULT_CHILD_PID_FILE,
    DEFAULT_DOWN_THRESHOLD_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SILENCE_SECONDS,
    DEFAULT_SUPERVISOR_LOG,
    HealthDetector,
)
from core.notifications.stream_alert import send_stream_alert  # noqa: E402

logger = logging.getLogger("livestream.health")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number, got {raw!r}") from exc


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else default


def _build_detectors() -> list[HealthDetector]:
    poll_interval = _env_float(
        "STREAM_HEALTH_POLL_INTERVAL",
        DEFAULT_POLL_INTERVAL_SECONDS,
    )
    down_interval = _env_float("STREAM_HEALTH_DOWN_INTERVAL_SECONDS", poll_interval)
    black_interval = _env_float("STREAM_HEALTH_BLACK_INTERVAL_SECONDS", poll_interval)
    silence_interval = _env_float("STREAM_HEALTH_SILENCE_INTERVAL_SECONDS", poll_interval)
    down_threshold = _env_float(
        "STREAM_HEALTH_DOWN_THRESHOLD_SECONDS",
        DEFAULT_DOWN_THRESHOLD_SECONDS,
    )
    black_seconds = _env_float("STREAM_HEALTH_BLACK_SECONDS", DEFAULT_BLACK_SECONDS)
    silence_seconds = _env_float(
        "STREAM_HEALTH_SILENCE_SECONDS",
        DEFAULT_SILENCE_SECONDS,
    )
    probe_window = _env_float(
        "STREAM_HEALTH_PROBE_WINDOW_SECONDS",
        max(black_seconds, silence_seconds) + 2.0,
    )
    probe_timeout = _env_float(
        "STREAM_HEALTH_PROBE_TIMEOUT_SECONDS",
        max(30.0, probe_window + 10.0),
    )
    ffmpeg_path = os.environ.get("STREAM_HEALTH_FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg"
    source_url = os.environ.get("STREAM_SOURCE_URL", "").strip()

    detectors: list[HealthDetector] = [
        StreamDownDetector(
            supervisor_log=_env_path("SUPERVISOR_LOG", DEFAULT_SUPERVISOR_LOG),
            child_pid_file=_env_path("CHILD_PID_FILE", DEFAULT_CHILD_PID_FILE),
            down_threshold_seconds=down_threshold,
            interval_seconds=down_interval,
        )
    ]

    if not source_url:
        logger.warning("STREAM_SOURCE_URL is unset; black-frame and silence probes are disabled")
        return detectors

    detectors.extend(
        [
            BlackFrameDetector(
                source_url=source_url,
                window_seconds=probe_window,
                interval_seconds=black_interval,
                ffmpeg_path=ffmpeg_path,
                probe_timeout_seconds=probe_timeout,
                min_black_seconds=black_seconds,
            ),
            SilenceDetector(
                source_url=source_url,
                window_seconds=probe_window,
                interval_seconds=silence_interval,
                ffmpeg_path=ffmpeg_path,
                probe_timeout_seconds=probe_timeout,
                min_silence_seconds=silence_seconds,
            ),
        ]
    )
    return detectors


async def _run_monitor() -> None:
    poll_interval = _env_float(
        "STREAM_HEALTH_POLL_INTERVAL",
        DEFAULT_POLL_INTERVAL_SECONDS,
    )
    cooldown = _env_float(
        "STREAM_HEALTH_ALERT_COOLDOWN_SECONDS",
        DEFAULT_ALERT_COOLDOWN_SECONDS,
    )
    detectors = _build_detectors()
    monitor = StreamHealthMonitor(
        detectors,
        alert_sink=send_stream_alert,
        alert_cooldown_seconds=cooldown,
        poll_interval_seconds=poll_interval,
    )
    logger.info("starting livestream health monitor with %d detector(s)", len(detectors))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass
    await monitor.run(stop_event=stop_event)
    logger.info("livestream health monitor stopped")


def _black_or_silence_probe(command: Sequence[str]) -> ProbeResult:
    joined = " ".join(command)
    if "blackdetect" in joined:
        return ProbeResult(
            returncode=0,
            stderr=("[blackdetect @ 0x1] black_start:0 black_end:6.25 black_duration:6.25\n"),
        )
    if "silencedetect" in joined:
        return ProbeResult(
            returncode=0,
            stderr=(
                "[silencedetect @ 0x1] silence_start:0\n"
                "[silencedetect @ 0x1] silence_end:11.5 "
                "| silence_duration: 11.5\n"
            ),
        )
    return ProbeResult(returncode=1, stderr="unexpected self-test probe command")


async def _self_test() -> int:
    old_env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="stream-health-self-test-") as tmp:
        tmp_path = Path(tmp)
        supervisor_log = tmp_path / "livestream-supervisor.log"
        email_log = tmp_path / "emails.jsonl"
        stale = datetime.now(UTC) - timedelta(seconds=120)
        supervisor_log.write_text(
            f"{stale.isoformat().replace('+00:00', 'Z')} supervisor: child-exited exit=1\n",
            encoding="utf-8",
        )
        os.environ.update(
            {
                "EMAIL_PROVIDER": "console",
                "EMAIL_CONSOLE_LOG": str(email_log),
                "EMAIL_CONSOLE_REDIS_STREAM": "",
                "STREAM_ALERT_EMAIL": "stream-ops@example.com",
            }
        )
        try:
            detectors = [
                StreamDownDetector(
                    supervisor_log=supervisor_log,
                    child_pid_file=tmp_path / "missing.pid",
                    down_threshold_seconds=1,
                    interval_seconds=1,
                ),
                BlackFrameDetector(
                    source_url="self-test://video",
                    window_seconds=12,
                    interval_seconds=1,
                    probe=_black_or_silence_probe,
                    min_black_seconds=5,
                ),
                SilenceDetector(
                    source_url="self-test://video",
                    window_seconds=12,
                    interval_seconds=1,
                    probe=_black_or_silence_probe,
                    min_silence_seconds=10,
                ),
            ]
            monitor = StreamHealthMonitor(
                detectors,
                alert_sink=send_stream_alert,
                alert_cooldown_seconds=300,
                poll_interval_seconds=1,
            )
            events = await monitor.poll_once()
            event_types = {event.type for event in events}
            expected = {STREAM_DOWN, BLACK_FRAME, SILENCE}
            if event_types != expected:
                print(
                    f"self-test failed: expected events {sorted(expected)}, "
                    f"got {sorted(event_types)}",
                    file=sys.stderr,
                )
                return 1

            records = [
                json.loads(line)
                for line in email_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            subjects = {record["subject"] for record in records}
            missing = [
                event_type
                for event_type in expected
                if not any(f"[stream-alert] {event_type} " in subject for subject in subjects)
            ]
            if len(records) != 3 or missing:
                print(
                    "self-test failed: expected one console email per event type; "
                    f"records={len(records)} missing={missing}",
                    file=sys.stderr,
                )
                return 1
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    print("livestream health self-test passed: stream_down, black_frame, silence")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor livestream health and send outage alerts.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the induced-outage local self-test and exit",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.self_test:
        return asyncio.run(_self_test())
    asyncio.run(_run_monitor())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
