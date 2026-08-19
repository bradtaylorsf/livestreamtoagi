#!/usr/bin/env bash
# Live demo: six agent bots log in and collaboratively build the starter cabin.
#
# Resets the build site, then replays the collaborative role jobs from a
# headless sim folder through visible Mineflayer bots (Vera, Sentinel, Fork,
# Aurora, Pixel, Rex). Each bot chats its role, teleports to its work zone,
# and issues its own block commands, so the build is watchable in-game.
#
# Prerequisites:
#   - The Paper server is running with RCON enabled (scripts/minecraft/start-server.sh)
#   - A headless sim folder containing collaborative_builds/<intent-id>/
#
# Usage:
#   scripts/minecraft/demo-cabin-build.sh
#   scripts/minecraft/demo-cabin-build.sh --sim-folder <dir> --intent-id <id>
#   scripts/minecraft/demo-cabin-build.sh --no-reset      # keep existing blocks
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

SIM_FOLDER="${SIM_FOLDER:-snapshots/headless/20260818T063655Z_cozy-cabin-demo}"
INTENT_ID="${INTENT_ID:-build-59ed0da92622}"
MC_HOST="${MC_HOST:-127.0.0.1}"
MC_PORT="${MC_PORT:-25565}"
MC_VERSION="${MC_VERSION:-1.21.6}"
THROTTLE_MS="${THROTTLE_MS:-700}"
JOB_PAUSE_MS="${JOB_PAUSE_MS:-2500}"
RESET=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sim-folder) SIM_FOLDER="$2"; shift 2 ;;
        --intent-id)  INTENT_ID="$2";  shift 2 ;;
        --throttle-ms) THROTTLE_MS="$2"; shift 2 ;;
        --job-pause-ms) JOB_PAUSE_MS="$2"; shift 2 ;;
        --no-reset)   RESET=0; shift ;;
        --help|-h)    sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# RCON password comes from the environment, .env, or server.properties.
if [[ -z "${RCON_PASSWORD:-}" ]]; then
    RCON_PASSWORD="$(sed -n 's/^rcon.password=//p' minecraft-server/server.properties | head -1)"
fi
export RCON_PASSWORD
: "${RCON_PASSWORD:?rcon.password not found; set RCON_PASSWORD}"

if [[ "$RESET" == "1" ]]; then
    echo "==> resetting build site"
    .venv/bin/python - <<'PY'
import os
from mcrcon import MCRcon

AGENTS = ("Vera", "Rex", "Aurora", "Fork", "Sentinel", "Pixel")
CMDS = [
    "gamerule commandBlockOutput false",
    "gamerule sendCommandFeedback false",
    "gamerule doDaylightCycle false",
    "gamerule doWeatherCycle false",
    "gamerule doMobSpawning false",
    "time set day",
    "weather clear",
    "difficulty peaceful",
    *[f"op {a}" for a in AGENTS],
    "fill -16 64 -16 24 96 24 air",
    "fill -16 63 -16 24 63 24 grass_block",
    "fill 1 64 -8 5 64 -8 polished_andesite",
    "setworldspawn 3 64 -8 0",
    "say Build site reset. Agent bots may join and build the cabin.",
]
with MCRcon(os.environ.get("RCON_HOST", "127.0.0.1"), os.environ["RCON_PASSWORD"],
            port=int(os.environ.get("RCON_PORT", "25575")), timeout=15) as m:
    for c in CMDS:
        m.command(c)
print(f"    site reset ({len(CMDS)} commands), ops={list(AGENTS)}")
PY
fi

echo "==> starting collaborative replay"
exec node scripts/minecraft/replay_collab_with_mineflayer.mjs \
    --sim-folder "$SIM_FOLDER" \
    --intent-id "$INTENT_ID" \
    --host "$MC_HOST" --port "$MC_PORT" --mc-version "$MC_VERSION" \
    --throttle-ms "$THROTTLE_MS" --job-pause-ms "$JOB_PAUSE_MS"
