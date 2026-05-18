#!/usr/bin/env bash
# Health check for the private Paper Minecraft server: is the world UP?
#
# This is the committed, dependency-free liveness probe referenced by
# docs/minecraft/health.md (issue #531, epic E2-6). The Python brain /
# livestream needs a single command that answers "is the world reachable?"
# — this is that command. It opens a TCP connection to the Minecraft listen
# port: a server accepting connections on its port is "up". No Java, no
# Minecraft client, no extra tools (just bash's built-in /dev/tcp).
#
# It builds on E2-1 (scripts/minecraft/start-server.sh, issue #526 — the
# server this probes) and E2-4 (scripts/minecraft/supervise.sh, issue #529
# — what keeps it up). It does NOT restart, alert, or graph anything; it
# only reports liveness.
#
# Usage:
#   scripts/minecraft/health.sh              # human-readable up/down, exit 0/1
#   scripts/minecraft/health.sh --json       # one-line JSON status (for the brain)
#   scripts/minecraft/health.sh --quiet      # no output, exit code only (probes)
#   scripts/minecraft/health.sh --self-test  # verify the probe with no Java/network
#   scripts/minecraft/health.sh --help
#
# Exit status: 0 = server up, 1 = server down, 2 = bad usage/config.
#
# Configuration (environment variables, all optional):
#   SERVER_HOST      Host to probe                       (default: 127.0.0.1)
#   SERVER_DIR       Where the server lives              (default: ./minecraft-server)
#   SERVER_PORT      Port to probe. If unset, parsed from
#                    server-port= in
#                    $SERVER_DIR/server.properties, else
#                    25565 (Paper's default — the port
#                    documented in server-setup.md).
#   CONNECT_TIMEOUT  Seconds to wait for the TCP connect
#                    before calling the server down      (default: 5)
#
# Integrating with scripts/check-services.sh: that script runs this probe as
# an OPT-IN check, gated on CHECK_MINECRAFT=1, so the default 5-service dev
# gate (and CI, which has no Minecraft server) keeps passing. See
# docs/minecraft/health.md.
set -euo pipefail

ok()   { echo "✓ $*"; }
info() { echo "  $*"; }
fail() { echo "✗ $*" >&2; }

MODE="human"
case "${1:-}" in
    --json)      MODE="json" ;;
    --quiet|-q)  MODE="quiet" ;;
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

SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
SERVER_DIR="${SERVER_DIR:-./minecraft-server}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-5}"

# read_prop KEY → value of the last "KEY=value" line in server.properties
# (or empty). Fixed allow-list reader: the file is parsed with sed, never
# sourced/executed, so a malformed or hostile server.properties cannot run
# code or set anything other than the key we explicitly ask for here. This
# mirrors start-server.sh's read_world_key; `tr -d '\r'` tolerates a
# Windows-edited (CRLF) file.
read_prop() {
    local file="$SERVER_DIR/server.properties"
    [ -f "$file" ] || return 0
    tr -d '\r' < "$file" | sed -nE "s/^${1}=(.*)$/\1/p" | tail -n1
}

# Resolve the port: explicit SERVER_PORT wins; else server.properties'
# server-port=; else Paper's default 25565 (the port documented in
# docs/minecraft/server-setup.md).
if [ -z "${SERVER_PORT:-}" ]; then
    SERVER_PORT="$(read_prop server-port)"
    SERVER_PORT="${SERVER_PORT:-25565}"
fi
case "$SERVER_PORT" in
    ''|*[!0-9]*)
        fail "Invalid server port: '${SERVER_PORT}' (must be a number)"
        exit 2
        ;;
esac

# probe_tcp HOST PORT TIMEOUT → 0 if a TCP connection succeeds within
# TIMEOUT seconds, else 1. bash's /dev/tcp has no native connect timeout, so
# the connect runs in a backgrounded subshell that a watchdog SIGKILLs if it
# stalls — otherwise a filtered port / wrong host would hang for the OS
# default (~75s) instead of reporting "down" promptly.
probe_tcp() {
    local host="$1" port="$2" timeout="$3" rc=0

    # Subshell exits 0 iff the socket opens (then closes on subshell exit).
    # 2>/dev/null swallows bash's "Connection refused" message.
    ( exec 3<>"/dev/tcp/${host}/${port}" ) 2> /dev/null &
    local connect_pid=$!

    # Watchdog: SIGKILL the connect if it is still running after $timeout.
    # Its std fds go to /dev/null (not the caller's pipes): we SIGKILL the
    # watchdog subshell below, which orphans its `sleep` child to run out
    # its (bounded, idle) timeout detached — but because that orphan holds
    # only /dev/null, it can NEVER keep a caller capturing our stdout/stderr
    # blocked after we return (the brain, check-services.sh, pytest).
    ( sleep "$timeout"; kill -KILL "$connect_pid" ) < /dev/null > /dev/null 2>&1 &
    local watchdog_pid=$!

    wait "$connect_pid" 2> /dev/null || rc=$?

    # Stop the watchdog (it may already be gone) and reap it.
    kill -KILL "$watchdog_pid" 2> /dev/null || true
    wait "$watchdog_pid" 2> /dev/null || true

    [ "$rc" -eq 0 ]
}

# --self-test: prove the probe is correct with no Java and no real network.
# Bind a throwaway loopback listener, assert the probe says UP & exits 0,
# kill it, assert the probe says DOWN & exits non-zero. Mirrors
# supervise.sh --self-test (a single self-contained verification).
if [ "$MODE" = "self-test" ]; then
    if ! command -v python3 > /dev/null 2>&1; then
        fail "--self-test needs python3 to bind a throwaway loopback listener"
        info "  (python3 is the project runtime; install it or run the real probe)"
        exit 2
    fi

    PORT_FILE="$(mktemp)"
    # shellcheck disable=SC2317,SC2329  # invoked indirectly via the trap below
    cleanup_selftest() {
        if [ -n "${LISTENER_PID:-}" ]; then
            kill "$LISTENER_PID" 2> /dev/null || true
        fi
        rm -f "$PORT_FILE"
    }
    trap cleanup_selftest EXIT

    python3 -c '
import socket, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(1)
print(s.getsockname()[1], flush=True)
while True:
    time.sleep(3600)
' > "$PORT_FILE" &
    LISTENER_PID=$!

    waited=0
    while [ ! -s "$PORT_FILE" ]; do
        sleep 0.1
        waited=$((waited + 1))
        if [ "$waited" -gt 100 ]; then
            fail "--self-test: throwaway listener did not start"
            exit 1
        fi
    done
    TEST_PORT="$(head -n1 "$PORT_FILE" | tr -dc '0-9')"
    info "self-test: bound a throwaway listener on 127.0.0.1:${TEST_PORT}"

    if probe_tcp 127.0.0.1 "$TEST_PORT" "$CONNECT_TIMEOUT"; then
        ok "self-test: probe correctly reported UP (and would exit 0)"
    else
        fail "self-test: probe reported DOWN while a listener was bound"
        exit 1
    fi

    kill "$LISTENER_PID" 2> /dev/null || true
    wait "$LISTENER_PID" 2> /dev/null || true
    LISTENER_PID=""

    if probe_tcp 127.0.0.1 "$TEST_PORT" "$CONNECT_TIMEOUT"; then
        fail "self-test: probe reported UP after the listener was killed"
        exit 1
    fi
    ok "self-test: probe correctly reported DOWN (and would exit non-zero)"
    ok "self-test passed — probe is correct with no Java/network"
    exit 0
fi

CHECKED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
if probe_tcp "$SERVER_HOST" "$SERVER_PORT" "$CONNECT_TIMEOUT"; then
    UP=1
else
    UP=0
fi

case "$MODE" in
    json)
        # One line so the Python brain / livestream can read it directly.
        # This is the lightweight "status endpoint" — no dashboard (E11/E13).
        if [ "$UP" -eq 1 ]; then up_json="true"; else up_json="false"; fi
        printf '{"up":%s,"host":"%s","port":%s,"checked_at":"%s"}\n' \
            "$up_json" "$SERVER_HOST" "$SERVER_PORT" "$CHECKED_AT"
        ;;
    quiet)
        : # exit code only — used as a check-services.sh probe
        ;;
    *)
        if [ "$UP" -eq 1 ]; then
            ok "Minecraft server up (${SERVER_HOST}:${SERVER_PORT})"
        else
            fail "Minecraft server down (${SERVER_HOST}:${SERVER_PORT})"
        fi
        ;;
esac

[ "$UP" -eq 1 ] && exit 0 || exit 1
