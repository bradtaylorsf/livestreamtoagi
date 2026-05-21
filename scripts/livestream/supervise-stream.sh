#!/usr/bin/env bash
# Supervise the livestream capture/encode/push pipeline: auto-restart on
# crash, with a retained gap log for hosts WITHOUT systemd (Mac/dev/local
# validation hosts, or any machine where installing a unit is not the right
# path).
#
# This wraps the E13-2 stream push command:
# scripts/livestream/stream-push.sh. That command owns capture, encode, and
# RTMP push setup; this script owns only process supervision around it.
#
# On the recommended Linux 24/7 host use systemd instead:
# scripts/livestream/livestream.service. systemd is the supervisor there.
#
# An operator-requested stop (Ctrl+C, SIGINT/SIGTERM, kill <pid>) is
# forwarded to the stream process and does NOT trigger a restart. Any child
# exit without an operator stop is treated as an unexpected stream gap and is
# restarted after the documented delay.
#
# Gap logging is retained in SUPERVISOR_LOG. The key lines are intentionally
# simple for humans and future alerting:
#   <ISO8601> child-exited exit_code=<n> uptime_seconds=<n>
#   <ISO8601> restarting attempt=<n> gap_seconds=<n>
#
# Usage:
#   scripts/livestream/supervise-stream.sh
#   scripts/livestream/supervise-stream.sh --self-test
#   scripts/livestream/supervise-stream.sh --help
#
# Configuration (environment variables, all optional):
#   LOG_DIR           Livestream log directory          (default: ./logs/livestream)
#   STREAM_CMD        Executable command to supervise   (default: <script dir>/stream-push.sh)
#   RESTART_DELAY     Seconds to wait before restart    (default: 10)
#   CRASH_LOOP_LIMIT  Max restarts allowed per window   (default: 5)
#   CRASH_LOOP_WINDOW Crash-loop window, seconds        (default: 60)
#   SUPERVISOR_LOG    Retained supervisor log file      (default: $LOG_DIR/livestream-supervisor.log)
#   CHILD_PID_FILE    Live child PID file               (default: $LOG_DIR/supervise-stream-child.pid)
#
# --self-test requires STREAM_CMD to point at a fast fake command so restart
# behaviour can be verified without ffmpeg, Twitch/YouTube, or network.
# It also lowers RESTART_DELAY/CRASH_LOOP_WINDOW defaults so tests are quick.
set -euo pipefail

info() { echo "  $*"; }
fail() { echo "ERROR: $*" >&2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

MODE="run"
case "${1:-}" in
    --self-test) MODE="self-test" ;;
    --help|-h)
        awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next}{exit}' "$0"
        exit 0
        ;;
    "") ;;
    *)
        fail "Unknown argument: $1 (try --help)"
        exit 2
        ;;
esac

STREAM_CMD_ENV="${STREAM_CMD:-}"
if [ "$MODE" = "self-test" ] && [ -z "$STREAM_CMD_ENV" ]; then
    fail "--self-test requires STREAM_CMD to point at a fake/test command"
    info "e.g. STREAM_CMD=/path/to/fake-stream.sh scripts/livestream/supervise-stream.sh --self-test"
    exit 2
fi

LOG_DIR="${LOG_DIR:-./logs/livestream}"
STREAM_CMD="${STREAM_CMD_ENV:-$SCRIPT_DIR/stream-push.sh}"
if [ "$MODE" = "self-test" ]; then
    RESTART_DELAY="${RESTART_DELAY:-1}"
    CRASH_LOOP_WINDOW="${CRASH_LOOP_WINDOW:-30}"
else
    RESTART_DELAY="${RESTART_DELAY:-10}"
    CRASH_LOOP_WINDOW="${CRASH_LOOP_WINDOW:-60}"
fi
CRASH_LOOP_LIMIT="${CRASH_LOOP_LIMIT:-5}"
SUPERVISOR_LOG="${SUPERVISOR_LOG:-$LOG_DIR/livestream-supervisor.log}"
CHILD_PID_FILE="${CHILD_PID_FILE:-$LOG_DIR/supervise-stream-child.pid}"

require_uint() {
    local name="$1"
    local value="$2"
    case "$value" in
        ""|*[!0-9]*)
            fail "$name must be a non-negative integer, got: $value"
            exit 2
            ;;
    esac
}

require_uint "RESTART_DELAY" "$RESTART_DELAY"
require_uint "CRASH_LOOP_LIMIT" "$CRASH_LOOP_LIMIT"
require_uint "CRASH_LOOP_WINDOW" "$CRASH_LOOP_WINDOW"

if [ ! -x "$STREAM_CMD" ]; then
    fail "STREAM_CMD is not an executable file: $STREAM_CMD"
    info "Point STREAM_CMD at stream-push.sh, or at a chmod +x fake in --self-test."
    exit 2
fi

mkdir -p "$(dirname -- "$SUPERVISOR_LOG")" "$(dirname -- "$CHILD_PID_FILE")"

log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" \
        | tee -a "$SUPERVISOR_LOG" >&2
}

STOP_REQUESTED=0
CHILD_PID=""
SLEEP_PID=""

# shellcheck disable=SC2317,SC2329
on_signal() {
    STOP_REQUESTED=1
    log "stop-requested reason=operator"
    if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2> /dev/null; then
        kill -TERM "$CHILD_PID" 2> /dev/null || true
    fi
    if [ -n "$SLEEP_PID" ] && kill -0 "$SLEEP_PID" 2> /dev/null; then
        kill -TERM "$SLEEP_PID" 2> /dev/null || true
    fi
}

# shellcheck disable=SC2317,SC2329
on_exit() {
    local rc=$?
    if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2> /dev/null; then
        kill -TERM "$CHILD_PID" 2> /dev/null || true
    fi
    if [ -n "$SLEEP_PID" ] && kill -0 "$SLEEP_PID" 2> /dev/null; then
        kill -TERM "$SLEEP_PID" 2> /dev/null || true
    fi
    rm -f "$CHILD_PID_FILE"
    return "$rc"
}

trap on_signal INT TERM
trap on_exit EXIT

log "supervisor-started mode=${MODE} stream_cmd=${STREAM_CMD}"
log "supervisor-config restart_delay=${RESTART_DELAY} crash_loop_limit=${CRASH_LOOP_LIMIT} crash_loop_window=${CRASH_LOOP_WINDOW} log=${SUPERVISOR_LOG}"

restart_count=0
window_start=$(date +%s)
attempt=1

while :; do
    log "starting-child attempt=${attempt}"

    child_started_at=$(date +%s)
    "$STREAM_CMD" &
    CHILD_PID=$!
    printf '%s\n' "$CHILD_PID" > "$CHILD_PID_FILE"

    set +e
    wait "$CHILD_PID"
    rc=$?
    set -e

    if [ "$STOP_REQUESTED" -eq 1 ] && kill -0 "$CHILD_PID" 2> /dev/null; then
        set +e
        wait "$CHILD_PID"
        rc=$?
        set -e
    fi

    child_exited_at=$(date +%s)
    uptime_seconds=$((child_exited_at - child_started_at))
    CHILD_PID=""
    rm -f "$CHILD_PID_FILE"

    if [ "$STOP_REQUESTED" -eq 1 ]; then
        log "child-stopped exit_code=${rc} uptime_seconds=${uptime_seconds} reason=operator-stop"
        break
    fi

    log "child-exited exit_code=${rc} uptime_seconds=${uptime_seconds}"

    now="$child_exited_at"
    if [ $((now - window_start)) -gt "$CRASH_LOOP_WINDOW" ]; then
        window_start="$now"
        restart_count=0
    fi

    if [ "$restart_count" -ge "$CRASH_LOOP_LIMIT" ]; then
        log "crash-loop-abort restarts=${restart_count} window_seconds=${CRASH_LOOP_WINDOW} limit=${CRASH_LOOP_LIMIT}"
        exit 1
    fi

    restart_count=$((restart_count + 1))
    down_started_at="$child_exited_at"

    sleep "$RESTART_DELAY" &
    SLEEP_PID=$!
    set +e
    wait "$SLEEP_PID"
    set -e
    SLEEP_PID=""

    if [ "$STOP_REQUESTED" -eq 1 ]; then
        log "restart-skipped reason=operator-stop"
        break
    fi

    restarted_at=$(date +%s)
    gap_seconds=$((restarted_at - down_started_at))
    attempt=$((attempt + 1))
    log "restarting attempt=${attempt} gap_seconds=${gap_seconds}"
done

log "supervisor-exited status=clean"
exit 0
