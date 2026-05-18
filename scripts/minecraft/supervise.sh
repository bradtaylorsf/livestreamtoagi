#!/usr/bin/env bash
# Supervise the private Paper Minecraft server: auto-restart on crash, with a
# retained log — for hosts WITHOUT systemd (the macOS local-validation box,
# dev machines, anything that isn't the Linux 24/7 host).
#
# This is the committed portable supervisor referenced by
# docs/minecraft/supervision.md (issue #529, epic E2-4). On the recommended
# Linux 24/7 host use the systemd unit instead — scripts/minecraft/minecraft.service.
#
# It wraps the E2-1 start script (scripts/minecraft/start-server.sh, issue
# #526): it launches it, waits for it to exit, records the exit to a retained
# log, waits a documented delay, and relaunches — forever, until you ask it
# to stop.
#
# Pins (Paper 1.21.6 / Java 21 — E1-R1) live in start-server.sh and the E1
# decision docs. This script adds none of its own; it only restarts what
# E2-1 launches.
#
# An operator-requested stop (Ctrl+C, SIGINT/SIGTERM, `kill <pid>`) is
# forwarded to the server and does NOT trigger a restart — only an unexpected
# server exit does. A crash-loop guard aborts if the server dies repeatedly
# in a short window so a broken config cannot spin forever.
#
# Usage:
#   scripts/minecraft/supervise.sh              # supervise the real server forever
#   scripts/minecraft/supervise.sh --self-test  # supervise an injected fake (no Java/network)
#   scripts/minecraft/supervise.sh --help
#
# Configuration (environment variables, all optional):
#   SERVER_DIR        Where the server lives             (default: ./minecraft-server)
#   SERVER_CMD        Executable command to supervise    (default: <script dir>/start-server.sh)
#   RESTART_DELAY     Seconds to wait before a restart   (default: 10  — the documented window)
#   CRASH_LOOP_LIMIT  Max restarts allowed per window    (default: 5)
#   CRASH_LOOP_WINDOW Crash-loop window, seconds         (default: 60)
#   SUPERVISOR_LOG    Retained supervisor log file       (default: $SERVER_DIR/logs/supervisor.log)
#   CHILD_PID_FILE    Where the live server PID is written(default: $SERVER_DIR/logs/supervise-child.pid)
#
# --self-test requires SERVER_CMD to point at a fast fake "server" so the
# kill->restart behaviour is verifiable with no Java and no network. It also
# lowers RESTART_DELAY/CRASH_LOOP_WINDOW defaults so the check is quick.
set -euo pipefail

info() { echo "  $*"; }
fail() { echo "✗ $*" >&2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

MODE="run"
case "${1:-}" in
    --self-test) MODE="self-test" ;;
    --help|-h)
        # Print the contiguous comment header (skip the shebang, stop at the
        # first non-comment line) so help never leaks script code, and stays
        # correct if the header length changes.
        awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next}{exit}' "$0"
        exit 0
        ;;
    "") ;;
    *)
        echo "✗ Unknown argument: $1 (try --help)" >&2
        exit 2
        ;;
esac

# Capture the raw SERVER_CMD env BEFORE defaulting so --self-test can require
# it (a test must never accidentally launch the real Minecraft server).
SERVER_CMD_ENV="${SERVER_CMD:-}"
if [ "$MODE" = "self-test" ] && [ -z "$SERVER_CMD_ENV" ]; then
    fail "--self-test requires SERVER_CMD to point at a fake/test command"
    info "  e.g. SERVER_CMD=/path/to/fake-server.sh scripts/minecraft/supervise.sh --self-test"
    exit 2
fi

SERVER_DIR="${SERVER_DIR:-./minecraft-server}"
SERVER_CMD="${SERVER_CMD_ENV:-$SCRIPT_DIR/start-server.sh}"
if [ "$MODE" = "self-test" ]; then
    RESTART_DELAY="${RESTART_DELAY:-1}"
    CRASH_LOOP_WINDOW="${CRASH_LOOP_WINDOW:-30}"
else
    RESTART_DELAY="${RESTART_DELAY:-10}"
    CRASH_LOOP_WINDOW="${CRASH_LOOP_WINDOW:-60}"
fi
CRASH_LOOP_LIMIT="${CRASH_LOOP_LIMIT:-5}"
SUPERVISOR_LOG="${SUPERVISOR_LOG:-$SERVER_DIR/logs/supervisor.log}"
CHILD_PID_FILE="${CHILD_PID_FILE:-$SERVER_DIR/logs/supervise-child.pid}"

if [ ! -x "$SERVER_CMD" ]; then
    fail "SERVER_CMD is not an executable file: $SERVER_CMD"
    info "  Point SERVER_CMD at start-server.sh (or a test fake) and chmod +x it."
    exit 2
fi

mkdir -p "$(dirname -- "$SUPERVISOR_LOG")" "$(dirname -- "$CHILD_PID_FILE")"

# Timestamped line → both the retained log file and stderr.
log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" \
        | tee -a "$SUPERVISOR_LOG" >&2
}

STOP_REQUESTED=0
CHILD_PID=""

# Invoked via the trap below (not called directly).
# shellcheck disable=SC2329
on_signal() {
    STOP_REQUESTED=1
    log "supervisor: stop requested (signal) — stopping the server, NOT restarting"
    if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2> /dev/null; then
        kill -TERM "$CHILD_PID" 2> /dev/null || true
    fi
}
trap on_signal INT TERM

log "supervisor: starting (mode=${MODE}) — server=${SERVER_CMD}"
log "supervisor: restart window=${RESTART_DELAY}s  crash-loop guard=${CRASH_LOOP_LIMIT}/${CRASH_LOOP_WINDOW}s  log=${SUPERVISOR_LOG}"

restart_count=0
window_start=$(date +%s)
attempt=0

while :; do
    attempt=$((attempt + 1))
    log "supervisor: starting server (attempt ${attempt})"

    "$SERVER_CMD" &
    CHILD_PID=$!
    echo "$CHILD_PID" > "$CHILD_PID_FILE"

    # wait may exit non-zero (server crash) or be interrupted by our trap;
    # either is expected, so don't let `set -e` abort the supervisor.
    set +e
    wait "$CHILD_PID"
    rc=$?
    set -e
    CHILD_PID=""

    if [ "$STOP_REQUESTED" -eq 1 ]; then
        log "supervisor: server stopped by operator request (exit ${rc}) — not restarting"
        break
    fi

    # Crash-loop guard: roll the window, then count this failure.
    now=$(date +%s)
    if [ $((now - window_start)) -gt "$CRASH_LOOP_WINDOW" ]; then
        window_start=$now
        restart_count=0
    fi
    restart_count=$((restart_count + 1))
    if [ "$restart_count" -gt "$CRASH_LOOP_LIMIT" ]; then
        log "supervisor: ABORT — server exited ${restart_count} times within ${CRASH_LOOP_WINDOW}s (crash loop). Fix the server, then restart the supervisor."
        rm -f "$CHILD_PID_FILE"
        exit 1
    fi

    log "supervisor: server exited unexpectedly (exit ${rc}) — restarting in ${RESTART_DELAY}s"

    # Interruptible delay: a stop signal during the wait must not be delayed.
    sleep "$RESTART_DELAY" &
    SLEEP_PID=$!
    set +e
    wait "$SLEEP_PID"
    set -e
    kill "$SLEEP_PID" 2> /dev/null || true

    if [ "$STOP_REQUESTED" -eq 1 ]; then
        log "supervisor: stop requested during restart delay — not restarting"
        break
    fi
done

rm -f "$CHILD_PID_FILE"
log "supervisor: exiting cleanly"
exit 0
