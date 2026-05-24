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
#   scripts/minecraft/run-local-sim.sh smoke-director
#   scripts/minecraft/run-local-sim.sh short
#   scripts/minecraft/run-local-sim.sh soak
#   scripts/minecraft/run-local-sim.sh soak-director
#   scripts/minecraft/run-local-sim.sh --duration-hours 0.5 --log-dir logs/soak
#   scripts/minecraft/run-local-sim.sh --help
#
# Modes:
#   smoke           0.25h embodied first live check (default)
#   short           0.25h embodied first live check
#   soak            2h embodied soak
#   smoke-director  0.25h Director V2 acceptance smoke
#   soak-director   2h Director V2 acceptance soak
#
# Required in .env:
#   LLM_PROVIDER=lmstudio
#   LOCAL_LLM_BASE_URL=http://localhost:1234/v1
#   LOCAL_LLM_MODEL=<model-id-from-LM-Studio>
#   LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id-if-available>
#   EMBEDDING_PROVIDER=deterministic
#   CONVERSATION_MODE=embodied          # or director_v2 for Director V2 prompt gating
#   MINECRAFT_BRIDGE_TOKEN=<same secret the backend reads>
#
# Optional in .env:
#   MC_SIM_DISABLE_MANAGEMENT=1
#   MC_SIM_INCLUDE_BRIDGE_BOT=0
#   MC_SIM_BLOCK_PRIVATE_CONVERSATIONS=1
#   MC_SIM_BUILD_MODE=single          # set to plan for !planAndBuild mode
#   MC_SIM_BUILDER_PROVIDER=local     # local or openrouter; plan generation only
#                                      # optional OpenRouter-builder mode is scoped
#                                      # to !planAndBuild; chat remains local.
#   MC_SIM_BUILDER_OPENROUTER_API_KEY=<key>  # defaults to OPENROUTER_API_KEY
#   MC_SIM_BUILDER_OPENROUTER_MODEL=<openrouter-model-id>
#   MC_SIM_BUILDER_FALLBACK=fail      # fail or local if OpenRouter is missing/fails
#   MC_SIM_BUILDER_MAX_CALLS_PER_RUN=12
#   MC_SIM_BUILDER_MAX_CALLS_PER_AGENT=3
#   MC_SIM_BUILDER_MAX_USD_PER_RUN=
#   MC_SIM_BUILDER_USD_PER_1K_INPUT=
#   MC_SIM_BUILDER_USD_PER_1K_OUTPUT=
#   MC_SIM_BUILD_MAX_PER_AGENT=6
#   MC_SIM_BUILD_COOLDOWN_SEC=300
#   MC_SIM_BUILD_ZONE_STRIDE=12
#   MC_SIM_BUILD_CACHE_TTL_SEC=3600
#   MC_SIM_ALLOW_NEW_ACTION=0
#   MC_SIM_BLOCK_EXECUTE_CODE_ACTIONS=1
#   MC_SIM_SUPPRESS_ACTION_CHAT=1
#   MC_SIM_SAFE_TERRAIN_ACTIONS=1
#   MC_SIM_HEARTBEAT_ENABLED=1
#   MC_SIM_HEARTBEAT_TICK_SEC=5
#   MC_SIM_HEARTBEAT_IDLE_SEC=90
#   MC_SIM_HEARTBEAT_COOLDOWN_SEC=45
#   MC_SIM_HEARTBEAT_STALE_ACTION_SEC=180
#   MC_SIM_HEARTBEAT_MAX_NO_COMMAND=3
#   MC_SIM_MEMORY_CONTEXT_ENABLED=1
#   MC_SIM_MEMORY_RECALL_LIMIT=3
#   MC_SIM_MEMORY_CORE_MAX_CHARS=1500
#   MC_SIM_MEMORY_RECALL_MAX_CHARS=1200
#   MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS=management,alpha
#   MC_SIM_AUTO_SETUP_MINDCRAFT=1
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
#   logs/soak/<UTC timestamp>/monitor.html
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

seconds_to_ms() {
    awk -v seconds="$1" 'BEGIN {
        if (seconds !~ /^[0-9]+([.][0-9]+)?$/) exit 1;
        printf "%d\n", seconds * 1000;
    }'
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
soak_profile_args=()
case "$mode" in
    smoke|short)
        duration_hours="${MC_SIM_SMOKE_HOURS:-0.25}"
        shift || true
        ;;
    soak|acceptance)
        duration_hours="${MC_SIM_SOAK_HOURS:-2}"
        shift || true
        ;;
    smoke-director|director-smoke)
        duration_hours="${MC_SIM_SMOKE_HOURS:-0.25}"
        CONVERSATION_MODE="director_v2"
        DIRECTOR_V2_GATE="1"
        SOAK_PROFILE="director_v2"
        soak_profile_args=("--profile" "director_v2")
        shift || true
        ;;
    soak-director|director-soak|acceptance-director)
        duration_hours="${MC_SIM_SOAK_HOURS:-2}"
        CONVERSATION_MODE="director_v2"
        DIRECTOR_V2_GATE="1"
        SOAK_PROFILE="director_v2"
        soak_profile_args=("--profile" "director_v2")
        shift || true
        ;;
    --*)
        duration_hours="${MC_SIM_DURATION_HOURS:-0.25}"
        ;;
    *)
        fail "Unknown Minecraft sim mode: $mode"
        info "  Use smoke, short, soak, smoke-director, soak-director, or pass soak.sh flags directly."
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
MC_SIM_BUILD_MODE="${MC_SIM_BUILD_MODE:-single}"
MC_SIM_BUILDER_PROVIDER="${MC_SIM_BUILDER_PROVIDER:-local}"
MC_SIM_BUILDER_FALLBACK="${MC_SIM_BUILDER_FALLBACK:-fail}"
MC_SIM_BUILDER_OPENROUTER_API_KEY="${MC_SIM_BUILDER_OPENROUTER_API_KEY:-${OPENROUTER_API_KEY:-}}"
MC_SIM_BUILDER_OPENROUTER_MODEL="${MC_SIM_BUILDER_OPENROUTER_MODEL:-}"
MC_SIM_BUILDER_MAX_CALLS_PER_RUN="${MC_SIM_BUILDER_MAX_CALLS_PER_RUN:-12}"
MC_SIM_BUILDER_MAX_CALLS_PER_AGENT="${MC_SIM_BUILDER_MAX_CALLS_PER_AGENT:-3}"
MC_SIM_BUILDER_MAX_USD_PER_RUN="${MC_SIM_BUILDER_MAX_USD_PER_RUN:-}"
MC_SIM_BUILDER_USD_PER_1K_INPUT="${MC_SIM_BUILDER_USD_PER_1K_INPUT:-}"
MC_SIM_BUILDER_USD_PER_1K_OUTPUT="${MC_SIM_BUILDER_USD_PER_1K_OUTPUT:-}"
MC_SIM_BUILD_MAX_PER_AGENT="${MC_SIM_BUILD_MAX_PER_AGENT:-6}"
MC_SIM_BUILD_COOLDOWN_SEC="${MC_SIM_BUILD_COOLDOWN_SEC:-300}"
MC_SIM_BUILD_ZONE_STRIDE="${MC_SIM_BUILD_ZONE_STRIDE:-12}"
MC_SIM_BUILD_CACHE_TTL_SEC="${MC_SIM_BUILD_CACHE_TTL_SEC:-3600}"
case "$MC_SIM_BUILDER_PROVIDER" in
    local|openrouter) ;;
    *)
        fail "MC_SIM_BUILDER_PROVIDER must be local or openrouter."
        exit 2
        ;;
esac
case "$MC_SIM_BUILDER_FALLBACK" in
    fail|local) ;;
    *)
        fail "MC_SIM_BUILDER_FALLBACK must be fail or local."
        exit 2
        ;;
esac
if [ "$MC_SIM_BUILDER_PROVIDER" = "openrouter" ] \
   && [ "$MC_SIM_BUILDER_FALLBACK" != "local" ] \
   && { [ -z "$MC_SIM_BUILDER_OPENROUTER_API_KEY" ] || [ -z "$MC_SIM_BUILDER_OPENROUTER_MODEL" ]; }; then
    fail "OpenRouter builder routing requires MC_SIM_BUILDER_OPENROUTER_API_KEY and MC_SIM_BUILDER_OPENROUTER_MODEL."
    info "  Set MC_SIM_BUILDER_FALLBACK=local to keep plan generation local when OpenRouter is not configured."
    exit 1
fi
export MC_SIM_BUILD_MODE
export MC_SIM_BUILDER_PROVIDER MC_SIM_BUILDER_FALLBACK
export MC_SIM_BUILDER_OPENROUTER_API_KEY MC_SIM_BUILDER_OPENROUTER_MODEL
export MC_SIM_BUILDER_MAX_CALLS_PER_RUN MC_SIM_BUILDER_MAX_CALLS_PER_AGENT
export MC_SIM_BUILDER_MAX_USD_PER_RUN MC_SIM_BUILDER_USD_PER_1K_INPUT MC_SIM_BUILDER_USD_PER_1K_OUTPUT
export MC_SIM_BUILD_MAX_PER_AGENT MC_SIM_BUILD_COOLDOWN_SEC MC_SIM_BUILD_ZONE_STRIDE MC_SIM_BUILD_CACHE_TTL_SEC
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
    if [ "$MC_SIM_BUILD_MODE" = "plan" ]; then
        SOAK_BLOCK_SLOW_SIM_ACTIONS="0"
    elif [ "$MC_SIM_ALLOW_NEW_ACTION" = "1" ]; then
        SOAK_BLOCK_SLOW_SIM_ACTIONS="0"
    else
        SOAK_BLOCK_SLOW_SIM_ACTIONS="1"
    fi
fi
SOAK_BLOCK_EXECUTE_CODE_ACTIONS="${SOAK_BLOCK_EXECUTE_CODE_ACTIONS:-${MC_SIM_BLOCK_EXECUTE_CODE_ACTIONS:-1}}"
export SOAK_BOTS SOAK_BLOCK_PRIVATE_CONVERSATIONS SOAK_BLOCK_SLOW_SIM_ACTIONS SOAK_BLOCK_EXECUTE_CODE_ACTIONS
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

MC_SIM_HEARTBEAT_ENABLED="${MC_SIM_HEARTBEAT_ENABLED:-1}"
MC_SIM_HEARTBEAT_TICK_SEC="${MC_SIM_HEARTBEAT_TICK_SEC:-5}"
MC_SIM_HEARTBEAT_IDLE_SEC="${MC_SIM_HEARTBEAT_IDLE_SEC:-90}"
MC_SIM_HEARTBEAT_COOLDOWN_SEC="${MC_SIM_HEARTBEAT_COOLDOWN_SEC:-45}"
MC_SIM_HEARTBEAT_STALE_ACTION_SEC="${MC_SIM_HEARTBEAT_STALE_ACTION_SEC:-180}"
MC_SIM_HEARTBEAT_MAX_NO_COMMAND="${MC_SIM_HEARTBEAT_MAX_NO_COMMAND:-3}"
MC_HEARTBEAT_ENABLED="$MC_SIM_HEARTBEAT_ENABLED"
MC_HEARTBEAT_TICK_MS="$(seconds_to_ms "$MC_SIM_HEARTBEAT_TICK_SEC" 2> /dev/null || true)"
MC_HEARTBEAT_IDLE_MS="$(seconds_to_ms "$MC_SIM_HEARTBEAT_IDLE_SEC" 2> /dev/null || true)"
MC_HEARTBEAT_COOLDOWN_MS="$(seconds_to_ms "$MC_SIM_HEARTBEAT_COOLDOWN_SEC" 2> /dev/null || true)"
MC_HEARTBEAT_STALE_ACTION_MS="$(seconds_to_ms "$MC_SIM_HEARTBEAT_STALE_ACTION_SEC" 2> /dev/null || true)"
if [ -z "$MC_HEARTBEAT_TICK_MS" ] || [ -z "$MC_HEARTBEAT_IDLE_MS" ] || \
   [ -z "$MC_HEARTBEAT_COOLDOWN_MS" ] || [ -z "$MC_HEARTBEAT_STALE_ACTION_MS" ]; then
    fail "MC_SIM_HEARTBEAT_*_SEC values must be positive numbers."
    exit 2
fi
MC_HEARTBEAT_MAX_NO_COMMAND="$MC_SIM_HEARTBEAT_MAX_NO_COMMAND"
export MC_HEARTBEAT_ENABLED MC_HEARTBEAT_TICK_MS MC_HEARTBEAT_IDLE_MS
export MC_HEARTBEAT_COOLDOWN_MS MC_HEARTBEAT_STALE_ACTION_MS MC_HEARTBEAT_MAX_NO_COMMAND
MC_SIM_MEMORY_CONTEXT_ENABLED="${MC_SIM_MEMORY_CONTEXT_ENABLED:-1}"
MC_SIM_MEMORY_RECALL_LIMIT="${MC_SIM_MEMORY_RECALL_LIMIT:-3}"
MC_SIM_MEMORY_CORE_MAX_CHARS="${MC_SIM_MEMORY_CORE_MAX_CHARS:-1500}"
MC_SIM_MEMORY_RECALL_MAX_CHARS="${MC_SIM_MEMORY_RECALL_MAX_CHARS:-1200}"
export MC_SIM_MEMORY_CONTEXT_ENABLED MC_SIM_MEMORY_RECALL_LIMIT
export MC_SIM_MEMORY_CORE_MAX_CHARS MC_SIM_MEMORY_RECALL_MAX_CHARS
if [ -n "${MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS:-}" ]; then
    export MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS
fi
SOAK_AUTO_SETUP_MINDCRAFT="${SOAK_AUTO_SETUP_MINDCRAFT:-${MC_SIM_AUTO_SETUP_MINDCRAFT:-1}}"
export SOAK_AUTO_SETUP_MINDCRAFT

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

DEFAULT_MC_SIM_INIT_MESSAGE="You are beginning a local Minecraft reality-show smoke simulation in an easy starter meadow with nearby surface resources and a starter kit already in your inventory. Coordinate with the nearby characters using ordinary public Minecraft chat, choose roles, and visibly do useful things: inspect the meadow, pick a shared camp spot, place blocks, add torches, and start a tiny shared camp or marker build. Private bot-conversation commands are disabled in this local sim. On your first turn, send a short public chat sentence and then execute one visible command such as !placeHere(\"oak_log\") or !placeHere(\"cobblestone\"); do not wait for consensus before placing the first camp marker. Good early commands are !inventory, !nearbyBlocks, !searchForBlock(\"crafting_table\", 16), !move(\"scout_1\", \"forward\", 2), !placeHere(\"oak_log\"), and !placeHere(\"cobblestone\"). After one nearby/inventory check, stop looping on gathering and place visible camp blocks. Do not use !place, !break, !observe, or JSON/object command arguments in this local smoke. Avoid digging down, avoid underground targets, and only collect blocks that are reachable on the surface or already in the starter meadow. Keep actions safe, use public chat every few actions, and continue until the run ends."
if [ "$MC_SIM_BUILD_MODE" = "plan" ]; then
    DEFAULT_MC_SIM_INIT_MESSAGE="You are beginning a local Minecraft plan-build simulation in an easy starter meadow. Coordinate in ordinary public chat, choose one compact shared structure, and use !planAndBuild(\"small shared cabin\") or another concise !planAndBuild request to generate a bounded JSON plan with the builder model and execute it through !buildFromPlan. Good starter requests are \"marker camp\", \"3x3 hut\", \"simple wall\", and \"torch-lit storage corner\". Keep arbitrary code execution out of the run; !executeCode remains blocked. After a plan starts, let the build finish before issuing another embodied action."
fi
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
    if [ "$MC_SIM_BUILD_MODE" = "plan" ]; then
        EASY_MODE_GUIDANCE="Easy-mode rules: stay inside the glass starter meadow, use the starter kit you already have, and build one coherent shared structure before doing more resource collection. Only the build owner should place blocks through !planAndBuild; support agents should coordinate in ordinary public Minecraft chat, check inventory or nearby resources when useful, and avoid standalone block placement unless the owner asks for help. Do not use !place, !placeHere, !break, !observe, or JSON/object command arguments in this local smoke."
    else
        EASY_MODE_GUIDANCE="Easy-mode rules: stay inside the glass starter meadow, use the starter kit you already have, and build something visible before doing more resource collection. On your first turn, send a short public chat sentence and then execute one visible command such as !placeHere(\"oak_log\") or !placeHere(\"cobblestone\"); do not wait for consensus before placing the first camp marker. Use ordinary public chat to announce roles, plans, progress, and requests for help. Useful building commands include !placeHere(\"oak_log\") and !placeHere(\"cobblestone\"). Do not use !place, !break, !observe, or JSON/object command arguments in this local smoke."
    fi
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
if [ "$MC_SIM_BUILD_MODE" = "plan" ]; then
    case "$SOAK_INIT_MESSAGE" in
        *"!planAndBuild"*|*"plan-build simulation"*) ;;
        *)
            SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE Build mode is plan: prefer !planAndBuild(\"small shared cabin\") and let buildFromPlan finish before issuing another embodied action."
            ;;
    esac
fi
export SOAK_INIT_MESSAGE

if [ "${LLM_PROVIDER:-}" != "lmstudio" ]; then
    fail "LLM_PROVIDER must be lmstudio for the local Minecraft sim."
    info "  Add to .env: LLM_PROVIDER=lmstudio"
    exit 1
fi
case "${CONVERSATION_MODE:-}" in
    embodied|director_v2) ;;
    *)
        fail "CONVERSATION_MODE must be embodied or director_v2 for the Minecraft sim."
        info "  Add to .env: CONVERSATION_MODE=embodied"
        info "  Or use Director V2 prompt gating: CONVERSATION_MODE=director_v2"
        exit 1
        ;;
esac
if [ "${CONVERSATION_MODE:-}" = "director_v2" ]; then
    DIRECTOR_V2_GATE=1
    SOAK_PROFILE="${SOAK_PROFILE:-director_v2}"
fi
DIRECTOR_V2_GATE="${DIRECTOR_V2_GATE:-0}"
SOAK_PROFILE="${SOAK_PROFILE:-default}"
export CONVERSATION_MODE DIRECTOR_V2_GATE SOAK_PROFILE
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
if [ "${#soak_profile_args[@]}" -gt 0 ] && ! has_arg "--profile" "$@"; then
    cmd+=("${soak_profile_args[@]}")
fi
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
info "conversation mode: ${CONVERSATION_MODE}"
info "Director V2 gate: ${DIRECTOR_V2_GATE}"
info "soak profile: ${SOAK_PROFILE}"
info "builder route: provider=${MC_SIM_BUILDER_PROVIDER} fallback=${MC_SIM_BUILDER_FALLBACK} openrouter_model=${MC_SIM_BUILDER_OPENROUTER_MODEL:-<unset>} caps run=${MC_SIM_BUILDER_MAX_CALLS_PER_RUN} agent=${MC_SIM_BUILDER_MAX_CALLS_PER_AGENT} usd=${MC_SIM_BUILDER_MAX_USD_PER_RUN:-<unset>}"
info "build governor: max_per_agent=${MC_SIM_BUILD_MAX_PER_AGENT} cooldown=${MC_SIM_BUILD_COOLDOWN_SEC}s zone_stride=${MC_SIM_BUILD_ZONE_STRIDE} cache_ttl=${MC_SIM_BUILD_CACHE_TTL_SEC}s"
info "management review: ${MINECRAFT_MANAGEMENT_REVIEW_MODE:-enabled}"
info "build mode: ${MC_SIM_BUILD_MODE}"
info "sim bots: ${SOAK_BOTS}"
info "private bot conversations: ${SOAK_BLOCK_PRIVATE_CONVERSATIONS}"
info "slow sim actions: ${SOAK_BLOCK_SLOW_SIM_ACTIONS}"
info "execute code actions: ${SOAK_BLOCK_EXECUTE_CODE_ACTIONS}"
info "suppress action chat: ${MINECRAFT_SUPPRESS_ACTION_CHAT}"
info "safe terrain actions: ${SOAK_SAFE_TERRAIN_ACTIONS}"
info "heartbeat: enabled=${MC_HEARTBEAT_ENABLED} idle=${MC_SIM_HEARTBEAT_IDLE_SEC}s cooldown=${MC_SIM_HEARTBEAT_COOLDOWN_SEC}s stale_action=${MC_SIM_HEARTBEAT_STALE_ACTION_SEC}s max_no_command=${MC_HEARTBEAT_MAX_NO_COMMAND}"
info "memory context: enabled=${MC_SIM_MEMORY_CONTEXT_ENABLED} recall_limit=${MC_SIM_MEMORY_RECALL_LIMIT} core_max=${MC_SIM_MEMORY_CORE_MAX_CHARS} recall_max=${MC_SIM_MEMORY_RECALL_MAX_CHARS} exclude=${MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS:-management,alpha}"
info "Mindcraft setup: auto=${SOAK_AUTO_SETUP_MINDCRAFT}"
info "easy mode: ${MC_SIM_EASY_MODE}"
info "keep MC server running: ${SOAK_KEEP_MINECRAFT_RUNNING:-0}"
info "minecraft: ${MC_HOST:-127.0.0.1}:${MC_PORT:-25565}"
info "server dir: ${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
info "world config: ${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
info "MindServer base port: ${SOAK_MINDSERVER_BASE_PORT}"
info "reliability thresholds: intent>=${SOAK_MIN_INTENT_TO_COMMAND_RATIO:-0.6} parse>=${SOAK_MIN_PARSE_SUCCESS:-0.8} execution>=${SOAK_MIN_EXECUTION_RATE:-0.7} verified>=${SOAK_MIN_VERIFIED_SUCCESS:-0.5}"
info "timeline artifacts: timeline.ndjson, timeline-totals.json, monitor.html"
if [ -n "${EASY_SETUP_OBSERVERS:-}${EASY_SETUP_OPERATORS:-}${EASY_SETUP_SPECTATORS:-}" ]; then
    info "human observers: players='${EASY_SETUP_OBSERVERS:-}' ops='${EASY_SETUP_OPERATORS:-}' spectators='${EASY_SETUP_SPECTATORS:-}'"
fi
info "init prompt: ${SOAK_INIT_MESSAGE}"
info "logs: ${display_log_dir}"

exec "${cmd[@]}"
