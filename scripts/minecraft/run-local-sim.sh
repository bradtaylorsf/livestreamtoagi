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
#   MC_SIM_INIT_MESSAGE=<initial objective for the character bots>
#   MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS=10000
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

        if [ -z "${!key+x}" ]; then
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
fi
export MINECRAFT_MANAGEMENT_REVIEW_MODE

DEFAULT_MC_SIM_INIT_MESSAGE="You are beginning a local Minecraft reality-show smoke simulation. Talk with the nearby characters, choose roles, and visibly do useful things: gather wood or stone, explore nearby terrain, and start a tiny shared camp or marker build. Keep actions safe, narrate briefly in character, and continue until the run ends."
MC_SIM_INIT_MESSAGE="${MC_SIM_INIT_MESSAGE:-$DEFAULT_MC_SIM_INIT_MESSAGE}"
SOAK_INIT_MESSAGE="${SOAK_INIT_MESSAGE:-$MC_SIM_INIT_MESSAGE}"
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

ok "Launching local Minecraft sim from $ENV_FILE"
info "mode: ${mode}"
info "duration: ${duration_hours}h"
info "model: ${LOCAL_LLM_MODEL}"
info "build model: ${LOCAL_LLM_MODEL_BUILDING}"
info "management review: ${MINECRAFT_MANAGEMENT_REVIEW_MODE:-enabled}"
info "init prompt: ${SOAK_INIT_MESSAGE}"
info "logs: ${log_dir}"

exec "${cmd[@]}"
