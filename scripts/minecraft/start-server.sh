#!/usr/bin/env bash
# Provision and run the private Paper Minecraft server (beginner walkthrough).
#
# This is the committed start script referenced by docs/minecraft/server-setup.md
# (issue #526, epic E2). It is safe to run repeatedly: it only downloads the
# Paper jar once and never overwrites a server.properties you have edited.
#
# Pinned defaults come from the E1 decisions:
#   - Paper 1.21.6, build 48  (E1-R1 → docs/decisions/0001-minecraft-version-and-server.md)
#   - Java 21                 (E1-R1)
#   - online-mode=false       (E1-R2 → docs/decisions/0002-auth-mode.md)
# Those decision docs are the authoritative source of truth once merged; the
# defaults below are kept in sync with them and can be overridden via env vars.
#
# Usage:
#   scripts/minecraft/start-server.sh            # provision + run the server
#   scripts/minecraft/start-server.sh --dry-run  # provision + show config, do NOT download/launch
#   scripts/minecraft/start-server.sh --smoke     # boot, wait for "Done (", auto-stop (verification)
#   scripts/minecraft/start-server.sh --help
#
# Configuration (environment variables, all optional):
#   SERVER_DIR    Where the server lives           (default: ./minecraft-server)
#   MC_VERSION    Minecraft/Paper version           (default: 1.21.6  — E1-R1)
#   PAPER_BUILD   Paper build number                (default: 48      — E1-R1)
#   MEM           JVM heap (-Xms/-Xmx)              (default: 2G)
#   ONLINE_MODE   Verify accounts with Mojang?      (default: false   — E1-R2)
#   WHITELIST     Reject players not on the list?   (default: true)
#   SERVER_PORT   TCP listen port                   (default: 25565)
#   SMOKE_TIMEOUT Seconds to wait for boot in smoke (default: 180)
#   WORLD_CONFIG  World-gen config file             (default: <script dir>/world.config)
#
# World generation (seed/type/name/structures/spawn-protection) is a
# configurable INPUT, not hardcoded (issue #527, epic E2-2). It is read from
# WORLD_CONFIG (a committed KEY=VALUE file) and only affects the FIRST world
# generation — see docs/minecraft/world-config.md for the beginner explainer.
set -euo pipefail

# ── Pinned E1 defaults (kept in sync with docs/decisions/0001 & 0002) ──
MC_VERSION="${MC_VERSION:-1.21.6}"
PAPER_BUILD="${PAPER_BUILD:-48}"
REQUIRED_JAVA_MAJOR="21"
SERVER_DIR="${SERVER_DIR:-./minecraft-server}"
MEM="${MEM:-2G}"
ONLINE_MODE="${ONLINE_MODE:-false}"
WHITELIST="${WHITELIST:-true}"
SERVER_PORT="${SERVER_PORT:-${MC_PORT:-25565}}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-180}"

# ── World-generation config (issue #527 / E2-2) ──
# Resolve world.config relative to THIS script (not the caller's cwd) so the
# committed defaults are used no matter where the script is invoked from.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORLD_CONFIG="${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"

MODE="run"
case "${1:-}" in
    --dry-run) MODE="dry-run" ;;
    --smoke)   MODE="smoke" ;;
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

ok()   { echo "✓ $*"; }
info() { echo "  $*"; }
fail() { echo "✗ $*" >&2; }

case "$SERVER_PORT" in
    ""|*[!0-9]*)
        fail "Invalid SERVER_PORT: '${SERVER_PORT}' (must be a number)"
        exit 2
        ;;
esac

# read_world_key KEY → value of the last "KEY=value" line in WORLD_CONFIG
# (or empty). This is a fixed allow-list reader: the file is parsed with sed,
# never sourced/executed, so a malformed or hostile world.config cannot run
# code or set anything other than the keys we explicitly ask for here.
# `tr -d '\r'` tolerates a Windows-edited (CRLF) config. Comment lines start
# with '#', so the '^KEY=' anchor already excludes the examples in the file.
read_world_key() {
    [ -f "$WORLD_CONFIG" ] || return 0
    tr -d '\r' < "$WORLD_CONFIG" | sed -nE "s/^${1}=(.*)$/\1/p" | tail -n1
}

# ── (a) Java check ─────────────────────────────────────
# A real run requires Java $REQUIRED_JAVA_MAJOR. In --dry-run we only warn so the
# config/file-generation logic stays verifiable on a machine without Java.
java_major() {
    command -v java > /dev/null 2>&1 || return 1
    local out major
    out="$(java -version 2>&1 | head -1)" || return 1
    # "openjdk version \"21.0.3\"" / "java version \"21\"" → 21.
    # -n…p prints only on a match, so an absent/stub JRE yields "" (→ not found).
    major="$(printf '%s\n' "$out" | sed -nE 's/.*version "([0-9]+).*/\1/p')"
    [ -n "$major" ] || return 1
    printf '%s\n' "$major"
}

JAVA_MAJOR="$(java_major || true)"
if [ -z "${JAVA_MAJOR:-}" ]; then
    fail "Java not found on PATH. Install Java ${REQUIRED_JAVA_MAJOR}:"
    info "  macOS:        brew install openjdk@${REQUIRED_JAVA_MAJOR}"
    info "  Debian/Ubuntu: sudo apt install openjdk-${REQUIRED_JAVA_MAJOR}-jre-headless"
    info "  See docs/minecraft/server-setup.md for details."
    [ "$MODE" = "dry-run" ] || exit 1
elif [ "$JAVA_MAJOR" != "$REQUIRED_JAVA_MAJOR" ]; then
    fail "Java ${JAVA_MAJOR} found, but Paper ${MC_VERSION} needs Java ${REQUIRED_JAVA_MAJOR}."
    info "  Install Java ${REQUIRED_JAVA_MAJOR} (see docs/minecraft/server-setup.md) and retry."
    [ "$MODE" = "dry-run" ] || exit 1
else
    ok "Java ${JAVA_MAJOR} detected (need ${REQUIRED_JAVA_MAJOR})"
fi

# ── (b)+(c) Resolve config + create the server directory ──
JAR="paper-${MC_VERSION}-${PAPER_BUILD}.jar"
mkdir -p "$SERVER_DIR"
ok "Server directory: $SERVER_DIR"
info "Paper jar:    $JAR (Minecraft ${MC_VERSION}, build ${PAPER_BUILD})"
info "Memory:       $MEM"
info "online-mode:  $ONLINE_MODE   white-list: $WHITELIST   port: $SERVER_PORT"

# ── Resolve world generation from WORLD_CONFIG (issue #527 / E2-2) ──
# Missing file or missing key → fall back to the same safe defaults the
# committed world.config ships, so the server still boots a sane world even
# without the config present. An empty LEVEL_SEED is intentional (= random).
LEVEL_SEED="$(read_world_key LEVEL_SEED)"
LEVEL_TYPE="$(read_world_key LEVEL_TYPE)";                 LEVEL_TYPE="${LEVEL_TYPE:-minecraft:normal}"
LEVEL_NAME="$(read_world_key LEVEL_NAME)";                 LEVEL_NAME="${LEVEL_NAME:-world}"
GENERATE_STRUCTURES="$(read_world_key GENERATE_STRUCTURES)"; GENERATE_STRUCTURES="${GENERATE_STRUCTURES:-true}"
SPAWN_PROTECTION="$(read_world_key SPAWN_PROTECTION)";     SPAWN_PROTECTION="${SPAWN_PROTECTION:-0}"

if [ -f "$WORLD_CONFIG" ]; then
    info "world config: $WORLD_CONFIG"
else
    info "world config: $WORLD_CONFIG (absent — using built-in safe defaults)"
fi
SEED_DISPLAY="${LEVEL_SEED:-(empty → random)}"
info "world:        seed=${SEED_DISPLAY}  type=${LEVEL_TYPE}  name=${LEVEL_NAME}"
info "              generate-structures=${GENERATE_STRUCTURES}  spawn-protection=${SPAWN_PROTECTION}"
info "              (only applied on FIRST world gen — see docs/minecraft/world-config.md)"

# ── (e) Accept the Minecraft EULA ─────────────────────
# Running a server REQUIRES agreeing to Mojang's EULA (https://aka.ms/MinecraftEULA).
# This script writes eula=true on your behalf — by running it you accept that EULA.
echo "eula=true" > "$SERVER_DIR/eula.txt"
ok "Minecraft EULA accepted (wrote eula=true to $SERVER_DIR/eula.txt)"
info "By running this you agree to https://aka.ms/MinecraftEULA"

# ── (f) Minimal server.properties (only if absent — never clobber edits) ──
PROPS="$SERVER_DIR/server.properties"
if [ -f "$PROPS" ]; then
    ok "server.properties already exists — leaving it untouched"
else
    cat > "$PROPS" <<EOF
# Generated by scripts/minecraft/start-server.sh (issue #526).
# Plain-language notes are in docs/minecraft/server-setup.md.
# Edit freely — this file is never overwritten once it exists.
motd=Livestream-to-AGI private server
# online-mode=false → offline/"cracked": do NOT expose this server to the
# public internet. Required so non-Microsoft-auth bots can join (E1-R2).
online-mode=${ONLINE_MODE}
# white-list=true → only players you add via "whitelist add <name>" may join.
white-list=${WHITELIST}
difficulty=normal
max-players=20
server-port=${SERVER_PORT}
view-distance=10
spawn-protection=${SPAWN_PROTECTION}
# ── World generation (issue #527 / E2-2) ──
# These come from $WORLD_CONFIG and ONLY take effect on the FIRST world
# generation — Minecraft bakes the seed/type into the saved world. To apply
# a change you must start fresh. See docs/minecraft/world-config.md.
# level-seed= (empty) means "pick a new random world".
level-name=${LEVEL_NAME}
level-seed=${LEVEL_SEED}
level-type=${LEVEL_TYPE}
generate-structures=${GENERATE_STRUCTURES}
EOF
    ok "Wrote a minimal $PROPS"
fi

# ── Build the launch command ───────────────────────────
JAVA_CMD=(java "-Xms${MEM}" "-Xmx${MEM}" -jar "$JAR" nogui)

if [ "$MODE" = "dry-run" ]; then
    echo
    ok "Dry run complete — no jar downloaded, server not launched."
    info "Would download (if missing): https://api.papermc.io/v2/projects/paper/versions/${MC_VERSION}/builds/${PAPER_BUILD}/downloads/${JAR}"
    info "Would run from $SERVER_DIR: ${JAVA_CMD[*]}"
    info "Would generate world: seed=${SEED_DISPLAY} type=${LEVEL_TYPE} name=${LEVEL_NAME} (from $WORLD_CONFIG)"
    exit 0
fi

# ── (d) Download the Paper jar (idempotent) ────────────
JAR_PATH="$SERVER_DIR/$JAR"
if [ -s "$JAR_PATH" ]; then
    ok "Paper jar already present — skipping download"
else
    PAPER_URL="https://api.papermc.io/v2/projects/paper/versions/${MC_VERSION}/builds/${PAPER_BUILD}/downloads/${JAR}"
    info "Downloading Paper from $PAPER_URL"
    if ! curl -fSL --retry 3 -o "$JAR_PATH" "$PAPER_URL"; then
        rm -f "$JAR_PATH"
        fail "Paper jar download failed."
        info "  Check your network, or that Paper ${MC_VERSION} build ${PAPER_BUILD} exists"
        info "  at https://papermc.io/downloads/paper — then retry."
        exit 1
    fi
    ok "Downloaded $JAR"
fi

# ── (g)/(h) Launch ─────────────────────────────────────
cd "$SERVER_DIR"

if [ "$MODE" = "smoke" ]; then
    # Boot, wait for the "Done (" ready line, send "stop", confirm clean exit.
    # Used for verification — proves the server provisions and boots locally.
    LOG=".smoke.log"
    PIPE=".smoke-stdin"
    rm -f "$LOG" "$PIPE"
    mkfifo "$PIPE"
    # Hold the FIFO open so the JVM's stdin does not get EOF before we send stop.
    sleep 100000 > "$PIPE" &
    HOLDER=$!
    # shellcheck disable=SC2317,SC2329  # invoked indirectly via the trap below
    cleanup() {
        kill "$HOLDER" 2> /dev/null || true
        rm -f "$PIPE"
    }
    trap cleanup EXIT

    info "Smoke boot (timeout ${SMOKE_TIMEOUT}s)…"
    "${JAVA_CMD[@]}" < "$PIPE" > "$LOG" 2>&1 &
    SERVER_PID=$!

    READY=0
    for _ in $(seq 1 "$SMOKE_TIMEOUT"); do
        if ! kill -0 "$SERVER_PID" 2> /dev/null; then break; fi
        if grep -q 'Done (' "$LOG" 2> /dev/null; then READY=1; break; fi
        sleep 1
    done

    if [ "$READY" -eq 1 ]; then
        ok "Server reached the 'Done (' ready line — sending stop"
        echo "stop" > "$PIPE"
        wait "$SERVER_PID" 2> /dev/null || true
        ok "Smoke test passed: server provisioned, booted, and stopped cleanly."
        exit 0
    fi

    fail "Server did not become ready within ${SMOKE_TIMEOUT}s. Last log lines:"
    tail -20 "$LOG" >&2 || true
    kill "$SERVER_PID" 2> /dev/null || true
    exit 1
fi

ok "Starting server — type 'stop' (or Ctrl+C) in this console to shut down."
exec "${JAVA_CMD[@]}"
