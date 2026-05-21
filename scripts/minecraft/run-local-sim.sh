#!/usr/bin/env bash
# Run the local embodied Minecraft simulation from .env.
#
# This is the ergonomic operator wrapper for the E8 all-character path:
# start the app with `pnpm dev`, then run this command from another terminal.
# It loads the same repo `.env` that the FastAPI backend uses, adds the common
# macOS Java 21 / Node 20 Homebrew paths, and delegates to soak.sh.
#
# Usage:
#   scripts/minecraft/run-local-sim.sh smoke
#   scripts/minecraft/run-local-sim.sh short
#   scripts/minecraft/run-local-sim.sh soak
#   scripts/minecraft/run-local-sim.sh --duration-hours 0.5 --log-dir logs/soak
#   scripts/minecraft/run-local-sim.sh --help
#
# Modes:
#   smoke  0.25h first live check (default)
#   short  0.25h first live check
#   soak   2h acceptance soak
#
# Required in .env:
#   LLM_PROVIDER=lmstudio
#   LOCAL_LLM_BASE_URL=http://localhost:1234/v1
#   LOCAL_LLM_MODEL=<model-id-from-LM-Studio>
#   LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id-if-available>
#   EMBEDDING_PROVIDER=deterministic
#   CONVERSATION_MODE=embodied
#   MINECRAFT_BRIDGE_TOKEN=<same secret the backend reads>
#
# Optional in .env:
#   MC_SIM_DISABLE_MANAGEMENT=1
#   MC_SIM_INCLUDE_BRIDGE_BOT=0
#   MC_SIM_BLOCK_PRIVATE_CONVERSATIONS=1
#   MC_SIM_ALLOW_NEW_ACTION=0
#   MC_SIM_SUPPRESS_ACTION_CHAT=1
#   MC_SIM_SAFE_TERRAIN_ACTIONS=1
#   MC_SIM_EASY_MODE=1
#   MC_SIM_MC_PORT=25566
#   MC_SIM_MINDSERVER_BASE_PORT=<base port for per-bot MindServer processes>
#   MC_SIM_KEEP_SERVER_RUNNING=1
#   MC_SIM_PLAYER_NAMES=<human names to teleport into the easy meadow>
#   MC_SIM_OPERATOR_NAMES=<human names to op for gamemode/tp>
#   MC_SIM_SPECTATOR_NAMES=<human names to auto-switch to spectator>
#   MC_SIM_INIT_MESSAGE=<initial objective for the character bots>
#   MC_SIM_MIN_INTENT_TO_COMMAND_RATIO=0.6
#   MC_SIM_MIN_PARSE_SUCCESS=0.8
#   MC_SIM_MIN_EXECUTION_RATE=0.7
#   MC_SIM_MIN_VERIFIED_SUCCESS=0.5
#   MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS=10000
#
# Outputs:
#   logs/soak/<UTC timestamp>/timeline.ndjson
#   logs/soak/<UTC timestamp>/timeline-totals.json
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

ok() { echo "ok $*"; }
info() { echo "  $*"; }
fail() { echo "x $*" >&2; }

prepend_path_if_dir() {
    local dir="$1"
    if [ -d "$dir" ]; then
        PATH="$dir:$PATH"
    fi
}

load_env_file() {
    local file="$1" line key value
    if [ ! -f "$file" ]; then
        fail "Missing env file: $file"
        info "  Copy .env.example to .env and fill the Minecraft/LM Studio values."
        exit 1
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            ""|\#*) continue ;;
        esac
        case "$line" in
            export\ *) line="${line#export }" ;;
        esac
        case "$line" in
            *=*) ;;
            *) continue ;;
        esac

        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
            ""|*[!A-Za-z0-9_]*)
                fail "Invalid dotenv key in $file: $key"
                exit 1
                ;;
        esac

        # The management toggle must be bidirectional for hermetic sim tests:
        # a stale parent-shell value should not override an explicit .env value.
        if [ "$key" = "MC_SIM_DISABLE_MANAGEMENT" ] || [ -z "${!key+x}" ]; then
            case "$value" in
                \"*\")
                    value="${value#\"}"
                    value="${value%\"}"
                    ;;
                \'*\')
                    value="${value#\'}"
                    value="${value%\'}"
                    ;;
            esac
            export "$key=$value"
        fi
    done < "$file"
}

has_arg() {
    local needle="$1"
    shift
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "$needle" ]; then
            return 0
        fi
        shift
    done
    return 1
}

arg_value_after() {
    local needle="$1"
    shift
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "$needle" ] && [ "$#" -ge 2 ]; then
            printf '%s\n' "$2"
            return 0
        fi
        shift
    done
    return 1
}

case "${1:-}" in
    --help|-h)
        awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next}{exit}' "$0"
        exit 0
        ;;
esac

if [ "${1:-}" = "--" ]; then
    shift
fi

load_env_file "$ENV_FILE"

mode="${1:-smoke}"
case "$mode" in
    smoke|short)
        duration_hours="${MC_SIM_SMOKE_HOURS:-0.25}"
        shift || true
        ;;
    soak|acceptance)
        duration_hours="${MC_SIM_SOAK_HOURS:-2}"
        shift || true
        ;;
    --*)
        duration_hours="${MC_SIM_DURATION_HOURS:-0.25}"
        ;;
    *)
        fail "Unknown Minecraft sim mode: $mode"
        info "  Use smoke, short, soak, or pass soak.sh flags directly."
        exit 2
        ;;
esac

prepend_path_if_dir "/opt/homebrew/opt/openjdk@21/bin"
prepend_path_if_dir "/opt/homebrew/Cellar/openjdk@21/21.0.11/bin"
prepend_path_if_dir "/opt/homebrew/opt/node@20/bin"
export PATH

LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
LOCAL_LLM_MODEL_BUILDING="${LOCAL_LLM_MODEL_BUILDING:-${LOCAL_LLM_MODEL:-}}"
export LOCAL_LLM_BASE_URL LOCAL_LLM_MODEL_BUILDING
MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS="${MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS:-10000}"
export MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS
MC_SIM_DISABLE_MANAGEMENT="${MC_SIM_DISABLE_MANAGEMENT:-1}"
if [ "$MC_SIM_DISABLE_MANAGEMENT" = "1" ]; then
    MINECRAFT_MANAGEMENT_REVIEW_MODE="disabled"
else
    MINECRAFT_MANAGEMENT_REVIEW_MODE="enabled"
fi
export MINECRAFT_MANAGEMENT_REVIEW_MODE
MC_SIM_INCLUDE_BRIDGE_BOT="${MC_SIM_INCLUDE_BRIDGE_BOT:-0}"
if [ -z "${SOAK_BOTS+x}" ]; then
    if [ "$MC_SIM_INCLUDE_BRIDGE_BOT" = "1" ]; then
        SOAK_BOTS="bridge alpha vera rex aurora pixel fork sentinel grok"
    else
        SOAK_BOTS="alpha vera rex aurora pixel fork sentinel grok"
    fi
fi
SOAK_BLOCK_PRIVATE_CONVERSATIONS="${SOAK_BLOCK_PRIVATE_CONVERSATIONS:-${MC_SIM_BLOCK_PRIVATE_CONVERSATIONS:-1}}"
MC_SIM_ALLOW_NEW_ACTION="${MC_SIM_ALLOW_NEW_ACTION:-0}"
if [ -z "${SOAK_BLOCK_SLOW_SIM_ACTIONS+x}" ]; then
    if [ "$MC_SIM_ALLOW_NEW_ACTION" = "1" ]; then
        SOAK_BLOCK_SLOW_SIM_ACTIONS="0"
    else
        SOAK_BLOCK_SLOW_SIM_ACTIONS="1"
    fi
fi
export SOAK_BOTS SOAK_BLOCK_PRIVATE_CONVERSATIONS SOAK_BLOCK_SLOW_SIM_ACTIONS
MC_SIM_SUPPRESS_ACTION_CHAT="${MC_SIM_SUPPRESS_ACTION_CHAT:-1}"
MINECRAFT_SUPPRESS_ACTION_CHAT="$MC_SIM_SUPPRESS_ACTION_CHAT"
MC_SIM_SAFE_TERRAIN_ACTIONS="${MC_SIM_SAFE_TERRAIN_ACTIONS:-1}"
SOAK_SAFE_TERRAIN_ACTIONS="${SOAK_SAFE_TERRAIN_ACTIONS:-$MC_SIM_SAFE_TERRAIN_ACTIONS}"
MINECRAFT_ALLOW_DESTRUCTIVE_PATHS="${MINECRAFT_ALLOW_DESTRUCTIVE_PATHS:-0}"
export MINECRAFT_SUPPRESS_ACTION_CHAT SOAK_SAFE_TERRAIN_ACTIONS MINECRAFT_ALLOW_DESTRUCTIVE_PATHS
if [ -z "${SOAK_MIN_INTENT_TO_COMMAND_RATIO+x}" ] && [ -n "${MC_SIM_MIN_INTENT_TO_COMMAND_RATIO:-}" ]; then
    SOAK_MIN_INTENT_TO_COMMAND_RATIO="$MC_SIM_MIN_INTENT_TO_COMMAND_RATIO"
fi
if [ -z "${SOAK_MIN_PARSE_SUCCESS+x}" ] && [ -n "${MC_SIM_MIN_PARSE_SUCCESS:-}" ]; then
    SOAK_MIN_PARSE_SUCCESS="$MC_SIM_MIN_PARSE_SUCCESS"
fi
if [ -z "${SOAK_MIN_EXECUTION_RATE+x}" ] && [ -n "${MC_SIM_MIN_EXECUTION_RATE:-}" ]; then
    SOAK_MIN_EXECUTION_RATE="$MC_SIM_MIN_EXECUTION_RATE"
fi
if [ -z "${SOAK_MIN_VERIFIED_SUCCESS+x}" ] && [ -n "${MC_SIM_MIN_VERIFIED_SUCCESS:-}" ]; then
    SOAK_MIN_VERIFIED_SUCCESS="$MC_SIM_MIN_VERIFIED_SUCCESS"
fi
export SOAK_MIN_INTENT_TO_COMMAND_RATIO SOAK_MIN_PARSE_SUCCESS SOAK_MIN_EXECUTION_RATE SOAK_MIN_VERIFIED_SUCCESS

MC_SIM_EASY_MODE="${MC_SIM_EASY_MODE:-1}"
if [ "$MC_SIM_EASY_MODE" = "1" ]; then
    SERVER_DIR="${SERVER_DIR:-$REPO_ROOT/minecraft-server-easy}"
    WORLD_CONFIG="${WORLD_CONFIG:-$SCRIPT_DIR/world-easy.config}"
    MC_HOST="${MC_HOST:-127.0.0.1}"
    MC_PORT="${MC_PORT:-${MC_SIM_MC_PORT:-${SERVER_PORT:-25566}}}"
    SERVER_PORT="${SERVER_PORT:-$MC_PORT}"
    WHITELIST="${WHITELIST:-false}"
    SOAK_EASY_SPAWN="${SOAK_EASY_SPAWN:-1}"
    SOAK_KEEP_MINECRAFT_RUNNING="${SOAK_KEEP_MINECRAFT_RUNNING:-${MC_SIM_KEEP_SERVER_RUNNING:-1}}"
elif [ -n "${MC_SIM_KEEP_SERVER_RUNNING+x}" ]; then
    SOAK_KEEP_MINECRAFT_RUNNING="${SOAK_KEEP_MINECRAFT_RUNNING:-$MC_SIM_KEEP_SERVER_RUNNING}"
fi
export SERVER_DIR WORLD_CONFIG MC_HOST MC_PORT SERVER_PORT WHITELIST SOAK_EASY_SPAWN SOAK_KEEP_MINECRAFT_RUNNING
SOAK_MINDSERVER_BASE_PORT="${SOAK_MINDSERVER_BASE_PORT:-${MC_SIM_MINDSERVER_BASE_PORT:-$((18080 + (RANDOM % 1000) * 10))}}"
export SOAK_MINDSERVER_BASE_PORT
if [ -n "${MC_SIM_PLAYER_NAMES:-}" ]; then
    EASY_SETUP_OBSERVERS="${EASY_SETUP_OBSERVERS:-$MC_SIM_PLAYER_NAMES}"
fi
if [ -n "${MC_SIM_OPERATOR_NAMES:-}" ]; then
    EASY_SETUP_OPERATORS="${EASY_SETUP_OPERATORS:-$MC_SIM_OPERATOR_NAMES}"
fi
if [ -n "${MC_SIM_SPECTATOR_NAMES:-}" ]; then
    EASY_SETUP_SPECTATORS="${EASY_SETUP_SPECTATORS:-$MC_SIM_SPECTATOR_NAMES}"
fi
export EASY_SETUP_OBSERVERS EASY_SETUP_OPERATORS EASY_SETUP_SPECTATORS

DEFAULT_MC_SIM_INIT_MESSAGE="You are beginning a local Minecraft reality-show smoke simulation in an easy starter meadow with nearby surface resources and a starter kit already in your inventory. Coordinate with the nearby characters using ordinary public Minecraft chat, choose roles, and visibly do useful things: inspect the meadow, pick a shared camp spot, place blocks, add torches, and start a tiny shared camp or marker build. Private bot-conversation commands are disabled in this local sim. On your first turn, send a short public chat sentence and then execute one visible command such as !placeHere(\"oak_log\") or !placeHere(\"cobblestone\"); do not wait for consensus before placing the first camp marker. Good early commands are !inventory, !nearbyBlocks, !searchForBlock(\"crafting_table\", 16), !move(\"scout_1\", \"forward\", 2), !placeHere(\"oak_log\"), !placeHere(\"cobblestone\"), and !place(\"camp-1\", \"oak_log\", {\"x\": 0, \"y\": 64, \"z\": 4}, \"up\"). After one nearby/inventory check, stop looping on gathering and place visible camp blocks. Avoid digging down, avoid underground targets, and only collect blocks that are reachable on the surface or already in the starter meadow. Keep actions safe, use public chat every few actions, and continue until the run ends."
MC_SIM_INIT_MESSAGE="${MC_SIM_INIT_MESSAGE:-$DEFAULT_MC_SIM_INIT_MESSAGE}"
SOAK_INIT_MESSAGE="${SOAK_INIT_MESSAGE:-$MC_SIM_INIT_MESSAGE}"
if [ "$SOAK_BLOCK_PRIVATE_CONVERSATIONS" = "1" ]; then
    case "$SOAK_INIT_MESSAGE" in
        *"Private bot-conversation commands are disabled"*|*"ordinary public Minecraft chat"*) ;;
        *)
            SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE Use ordinary public Minecraft chat for coordination. Private bot-conversation commands are disabled in this local sim."
            ;;
    esac
fi
if [ "$MC_SIM_EASY_MODE" = "1" ]; then
    EASY_MODE_GUIDANCE="Easy-mode rules: stay inside the glass starter meadow, use the starter kit you already have, and build something visible before doing more resource collection. On your first turn, send a short public chat sentence and then execute one visible command such as !placeHere(\"oak_log\") or !placeHere(\"cobblestone\"); do not wait for consensus before placing the first camp marker. Use ordinary public chat to announce roles, plans, progress, and requests for help. Useful building commands include !placeHere(\"oak_log\"), !placeHere(\"cobblestone\"), and !place(\"marker-1\", \"torch\", {\"x\": 2, \"y\": 64, \"z\": 2}, \"up\")."
    case "$SOAK_INIT_MESSAGE" in
        *"Easy-mode rules:"*) ;;
        *) SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE $EASY_MODE_GUIDANCE" ;;
    esac
fi
if [ "$SOAK_BLOCK_SLOW_SIM_ACTIONS" = "1" ]; then
    case "$SOAK_INIT_MESSAGE" in
        *"Use movement and inspection before collection"*|*"Use movement and exploration before collection"*) ;;
        *)
            SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE Use movement and inspection before collection: good early commands are !inventory, !nearbyBlocks, !searchForBlock(\"oak_log\", 32), !searchForBlock(\"crafting_table\", 16), !move(\"scout_1\", \"forward\", 2), !placeHere(\"oak_log\"), and !placeHere(\"cobblestone\"). Avoid digging down and avoid underground targets. Do not repeatedly collect or search for a block that was reported missing, unreachable, buried, or tool-locked."
            ;;
    esac
fi
export SOAK_INIT_MESSAGE

if [ "${LLM_PROVIDER:-}" != "lmstudio" ]; then
    fail "LLM_PROVIDER must be lmstudio for the local Minecraft sim."
    info "  Add to .env: LLM_PROVIDER=lmstudio"
    exit 1
fi
if [ "${CONVERSATION_MODE:-}" != "embodied" ]; then
    fail "CONVERSATION_MODE must be embodied for the Minecraft sim."
    info "  Add to .env: CONVERSATION_MODE=embodied"
    exit 1
fi
if [ -z "${LOCAL_LLM_MODEL:-}" ]; then
    fail "LOCAL_LLM_MODEL is missing."
    info "  Run: pnpm llm:local --list-only"
    info "  Then add a listed model id to .env."
    exit 1
fi
if [ -z "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
    fail "MINECRAFT_BRIDGE_TOKEN is missing."
    info "  Add one generated value to .env with: openssl rand -hex 32"
    exit 1
fi

log_dir="${MC_SIM_LOG_DIR:-$REPO_ROOT/logs/soak}"
cmd=("$SCRIPT_DIR/soak.sh")
if ! has_arg "--duration-hours" "$@"; then
    cmd+=("--duration-hours" "$duration_hours")
fi
if ! has_arg "--log-dir" "$@"; then
    cmd+=("--log-dir" "$log_dir")
fi
cmd+=("$@")

display_duration="$(arg_value_after "--duration-hours" "$@" || true)"
if [ -z "$display_duration" ]; then
    display_duration="$duration_hours"
fi
display_log_dir="$(arg_value_after "--log-dir" "$@" || true)"
if [ -z "$display_log_dir" ]; then
    display_log_dir="$log_dir"
fi

ok "Launching local Minecraft sim from $ENV_FILE"
info "mode: ${mode}"
info "duration: ${display_duration}h"
info "model: ${LOCAL_LLM_MODEL}"
info "build model: ${LOCAL_LLM_MODEL_BUILDING}"
info "management review: ${MINECRAFT_MANAGEMENT_REVIEW_MODE:-enabled}"
info "sim bots: ${SOAK_BOTS}"
info "private bot conversations: ${SOAK_BLOCK_PRIVATE_CONVERSATIONS}"
info "slow sim actions: ${SOAK_BLOCK_SLOW_SIM_ACTIONS}"
info "suppress action chat: ${MINECRAFT_SUPPRESS_ACTION_CHAT}"
info "safe terrain actions: ${SOAK_SAFE_TERRAIN_ACTIONS}"
info "easy mode: ${MC_SIM_EASY_MODE}"
info "keep MC server running: ${SOAK_KEEP_MINECRAFT_RUNNING:-0}"
info "minecraft: ${MC_HOST:-127.0.0.1}:${MC_PORT:-25565}"
info "server dir: ${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
info "world config: ${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
info "MindServer base port: ${SOAK_MINDSERVER_BASE_PORT}"
info "reliability thresholds: intent>=${SOAK_MIN_INTENT_TO_COMMAND_RATIO:-0.6} parse>=${SOAK_MIN_PARSE_SUCCESS:-0.8} execution>=${SOAK_MIN_EXECUTION_RATE:-0.7} verified>=${SOAK_MIN_VERIFIED_SUCCESS:-0.5}"
info "timeline artifacts: timeline.ndjson, timeline-totals.json"
if [ -n "${EASY_SETUP_OBSERVERS:-}${EASY_SETUP_OPERATORS:-}${EASY_SETUP_SPECTATORS:-}" ]; then
    info "human observers: players='${EASY_SETUP_OBSERVERS:-}' ops='${EASY_SETUP_OPERATORS:-}' spectators='${EASY_SETUP_SPECTATORS:-}'"
fi
info "init prompt: ${SOAK_INIT_MESSAGE}"
info "logs: ${display_log_dir}"

exec "${cmd[@]}"
