#!/usr/bin/env python3
"""Serve the local Minecraft cohort monitor on a loopback interface."""

from __future__ import annotations

import argparse
import functools
import ipaddress
import sys
import tempfile
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_monitor

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_REFRESH_SECONDS = 5


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class RefreshState:
    def __init__(self, run_dir: Path, output: Path, refresh_seconds: int) -> None:
        self.run_dir = run_dir
        self.output = output
        self.refresh_seconds = refresh_seconds
        self.next_refresh = 0.0
        self.last_error: str | None = None

    def refresh_if_due(self) -> None:
        now = time.monotonic()
        if now < self.next_refresh and self.output.exists():
            return
        self.next_refresh = now + self.refresh_seconds
        try:
            build_monitor.build(self.run_dir, output=self.output, rebuild_timeline=True)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"monitor refresh failed: {exc}", file=sys.stderr)
        else:
            self.last_error = None


class MonitorHandler(SimpleHTTPRequestHandler):
    refresh_state: RefreshState

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler hook
        self.refresh_state.refresh_if_due()
        if self.path in {"", "/"}:
            self.path = "/monitor.html"
        super().do_GET()

    def log_message(self, message_format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {message_format % args}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve a refreshing local Minecraft cohort monitor from a soak run directory."
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Soak evidence directory")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host. Default: {DEFAULT_HOST}")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Bind port. Default: {DEFAULT_PORT}"
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Rebuild monitor interval. Default: {DEFAULT_REFRESH_SECONDS}",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow binding to a non-loopback host. Default is loopback only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.allow_remote and not is_loopback_host(args.host):
        print(
            f"refusing to bind non-loopback host {args.host!r}; pass --allow-remote to override",
            file=sys.stderr,
        )
        return 2

    run_dir = args.run_dir.resolve()
    refresh_seconds = max(1, args.refresh_seconds)
    with tempfile.TemporaryDirectory(prefix="minecraft-cohort-monitor-") as tmp:
        serve_dir = Path(tmp)
        output = serve_dir / "monitor.html"
        state = RefreshState(run_dir, output, refresh_seconds)
        state.refresh_if_due()

        handler_class = type("BoundMonitorHandler", (MonitorHandler,), {"refresh_state": state})
        handler = functools.partial(handler_class, directory=str(serve_dir))
        server = ThreadingHTTPServer((args.host, args.port), handler)
        url_host = "localhost" if args.host == "127.0.0.1" else args.host
        print(f"serving monitor at http://{url_host}:{server.server_port}/monitor.html")
        print(f"run dir: {run_dir}")
        print("press Ctrl-C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
