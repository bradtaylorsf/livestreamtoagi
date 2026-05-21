#!/usr/bin/env bash
# Run the E8-8 multi-agent Minecraft stability soak.
#
# This is a thin ops orchestrator around the existing single-bot launchers. A
# real run expects the backend bridge, Docker services, LM Studio, and the
# pinned Mindcraft checkout to already be up. If Paper is down locally, it
# starts the portable Minecraft supervisor before launching BridgeBot plus
# Alpha, Vera, Rex, Aurora, Pixel, Fork, Sentinel, and Grok. Evidence lands
# under logs/soak/<UTC timestamp>/.
#
# Usage:
#   scripts/minecraft/soak.sh
#   scripts/minecraft/soak.sh --duration-hours 2
#   scripts/minecraft/soak.sh --log-dir /tmp/e8-8-soak
#   scripts/minecraft/soak.sh --dry-run
#   scripts/minecraft/soak.sh --verify
#   scripts/minecraft/soak.sh --verify-behavior <run-dir>
#   scripts/minecraft/soak.sh --help
#
# Required for a real run:
#   MINECRAFT_BRIDGE_TOKEN      Shared bearer token used by FastAPI bridge.
#   LOCAL_LLM_MODEL             LM Studio conversation-tier model id.
#
# Optional:
#   LOCAL_LLM_MODEL_BUILDING    LM Studio building/code-tier model id.
#   LOCAL_LLM_BASE_URL          Must be http://localhost:1234/v1 for Mindcraft
#                               string-form lmstudio profiles at the pinned
#                               commit. Default: http://localhost:1234/v1.
#   SOAK_DURATION_HOURS         Default: 2.
#   SOAK_AGENT_HOURLY_CAP_USD   Per-agent hourly cap assertion. Default: 0.01.
#   SOAK_MIN_MOVEMENT_PER_AGENT Minimum movement actions per tracked agent.
#                               Default: 5.
#   SOAK_MAX_DEATHS_PER_AGENT   Maximum death/respawn lines per tracked agent.
#                               Default: 2.
#   SOAK_MAX_STUCK_PER_AGENT    Maximum stuck/path-failure lines per tracked
#                               agent. Default: 5.
#   SOAK_MIN_PUBLIC_CHAT_COHORT Minimum public chat lines across the cohort.
#                               Default: 10.
#   SOAK_MIN_GATHER_OR_BUILD_COHORT
#                               Minimum gather+build actions across the cohort.
#                               Default: 3.
#   SOAK_MIN_SHARED_ARTIFACTS   Minimum shared work artifacts inferred from
#                               logs. Default: 1.
#   SOAK_REQUIRE_BEHAVIOR_GATE  Exit nonzero when behavioral acceptance fails.
#                               Default: 1.
#   SOAK_LOG_ROOT               Default: ./logs/soak.
#   SOAK_WORK_ROOT              Temp directory for isolated Mindcraft clones.
#                               Default: system temp/livestreamtoagi-soak-worktrees/<run id>.
#   SOAK_KEEP_WORKTREES         Keep temp Mindcraft clones after cleanup for
#                               debugging. Default: 0.
#   SOAK_LAUNCH_STAGGER_SECONDS Default: 3.
#   SOAK_START_MINECRAFT_IF_DOWN Start supervise.sh when health is down.
#                               Default: 1.
#   SOAK_KEEP_MINECRAFT_RUNNING Keep an auto-started Paper server running after
#                               the timed sim ends. Default: 0.
#   SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS
#                               Seconds to wait for health after auto-start.
#                               Default: 180.
#   SOAK_INIT_MESSAGE           Optional initial objective sent to each
#                               Mindcraft bot through settings.init_message.
#   SOAK_BLOCK_PRIVATE_CONVERSATIONS
#                               Set to 1 to disable Mindcraft's private
#                               bot-to-bot conversation commands and force
#                               normal public Minecraft chat/action routing.
#                               Default: 0.
#   SOAK_BLOCK_SLOW_SIM_ACTIONS Set to 1 to disable slow/noisy actions such as
#                               !newAction, !observe, !navigate, generated
#                               plan building, and code execution. Basic
#                               !place/!break stay available for quick builds.
#                               Default: 0.
#   SOAK_SAFE_TERRAIN_ACTIONS   Set to 1 to stage local-sim terrain guards:
#                               disable auto elbow-room/item pickup/torch modes
#                               and refuse destructive pathfinding.
#                               Default: 0.
#   SOAK_EASY_SPAWN             Set to 1 to use the local easy-mode spawn
#                               bootstrap: a side Paper server, peaceful rules,
#                               a flat grass starter meadow, resource piles,
#                               and starter tools/materials. Default: 0.
#   SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS
#                               Seconds to wait after bot launch before giving
#                               the online starter kit. Default: 5.
#   SOAK_MIN_INTENT_TO_COMMAND_RATIO
#                               Minimum commands emitted per intended action
#                               utterance before the reliability gate fails.
#                               Default: 0.6.
#   SOAK_MIN_PARSE_SUCCESS      Minimum command parse success rate. Default: 0.8.
#   SOAK_MIN_EXECUTION_RATE     Minimum emitted-command execution rate.
#                               Default: 0.7.
#   SOAK_MIN_VERIFIED_SUCCESS   Minimum execution-success entries corroborated
#                               by world-state evidence. Default: 0.5.
#   SOAK_RELIABILITY_MIN_INTENTS
#                               Only enforce reliability thresholds for agents
#                               with at least this many intended action events.
#                               Default: 5.
#   SOAK_RELIABILITY_FAIL_ON_VIOLATION
#                               Exit nonzero when the reliability gate reports
#                               threshold violations. Default: 1.
#   timeline.ndjson             Structured run timeline emitted under the
#                               evidence directory, with timeline-totals.json
#                               and a Timeline block in summary.txt.
#   monitor.html                Self-contained cohort monitor rendered under
#                               the evidence directory from timeline.ndjson.
#   SOAK_MONITOR_STALL_SECONDS  Idle seconds before a monitor stalled badge.
#                               Default: 120.
#   SOAK_MONITOR_LLM_IDLE_SECONDS
#                               Seconds before a monitor no-recent-LLM badge.
#                               Default: 120.
#   SOAK_BOTS                   Space-separated bot ids to launch. Default:
#                               bridge alpha vera rex aurora pixel fork
#                               sentinel grok.
#   SOAK_MINDSERVER_BASE_PORT    First local MindServer UI/control port.
#                               Each bot gets a unique incrementing port.
#                               Default: 8080.
#   MINDCRAFT_DIR               Pinned setup-mindcraft.sh checkout. Default:
#                               ./mindcraft.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
MINECRAFT_BRIDGE_URL="${MINECRAFT_BRIDGE_URL:-ws://127.0.0.1:8010/api/minecraft/bridge/ws}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://127.0.0.1:8010/api/health}"
SOAK_DURATION_HOURS="${SOAK_DURATION_HOURS:-2}"
SOAK_AGENT_HOURLY_CAP_USD="${SOAK_AGENT_HOURLY_CAP_USD:-0.01}"
SOAK_MIN_MOVEMENT_PER_AGENT="${SOAK_MIN_MOVEMENT_PER_AGENT:-5}"
SOAK_MAX_DEATHS_PER_AGENT="${SOAK_MAX_DEATHS_PER_AGENT:-2}"
SOAK_MAX_STUCK_PER_AGENT="${SOAK_MAX_STUCK_PER_AGENT:-5}"
SOAK_MIN_PUBLIC_CHAT_COHORT="${SOAK_MIN_PUBLIC_CHAT_COHORT:-10}"
SOAK_MIN_GATHER_OR_BUILD_COHORT="${SOAK_MIN_GATHER_OR_BUILD_COHORT:-3}"
SOAK_MIN_SHARED_ARTIFACTS="${SOAK_MIN_SHARED_ARTIFACTS:-1}"
SOAK_REQUIRE_BEHAVIOR_GATE="${SOAK_REQUIRE_BEHAVIOR_GATE:-1}"
SOAK_LOG_ROOT="${SOAK_LOG_ROOT:-$REPO_ROOT/logs/soak}"
SOAK_KEEP_WORKTREES="${SOAK_KEEP_WORKTREES:-0}"
SOAK_LAUNCH_STAGGER_SECONDS="${SOAK_LAUNCH_STAGGER_SECONDS:-3}"
SOAK_MAX_LOG_LINES_PER_BOT="${SOAK_MAX_LOG_LINES_PER_BOT:-200000}"
SOAK_START_MINECRAFT_IF_DOWN="${SOAK_START_MINECRAFT_IF_DOWN:-1}"
SOAK_KEEP_MINECRAFT_RUNNING="${SOAK_KEEP_MINECRAFT_RUNNING:-0}"
SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS="${SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS:-180}"
SOAK_INIT_MESSAGE="${SOAK_INIT_MESSAGE:-}"
SOAK_BLOCK_PRIVATE_CONVERSATIONS="${SOAK_BLOCK_PRIVATE_CONVERSATIONS:-0}"
SOAK_BLOCK_SLOW_SIM_ACTIONS="${SOAK_BLOCK_SLOW_SIM_ACTIONS:-0}"
SOAK_SAFE_TERRAIN_ACTIONS="${SOAK_SAFE_TERRAIN_ACTIONS:-0}"
SOAK_EASY_SPAWN="${SOAK_EASY_SPAWN:-0}"
SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS="${SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS:-5}"
SOAK_MIN_INTENT_TO_COMMAND_RATIO="${SOAK_MIN_INTENT_TO_COMMAND_RATIO:-0.6}"
SOAK_MIN_PARSE_SUCCESS="${SOAK_MIN_PARSE_SUCCESS:-0.8}"
SOAK_MIN_EXECUTION_RATE="${SOAK_MIN_EXECUTION_RATE:-0.7}"
SOAK_MIN_VERIFIED_SUCCESS="${SOAK_MIN_VERIFIED_SUCCESS:-0.5}"
SOAK_RELIABILITY_MIN_INTENTS="${SOAK_RELIABILITY_MIN_INTENTS:-5}"
SOAK_RELIABILITY_FAIL_ON_VIOLATION="${SOAK_RELIABILITY_FAIL_ON_VIOLATION:-1}"
SOAK_MONITOR_STALL_SECONDS="${SOAK_MONITOR_STALL_SECONDS:-120}"
SOAK_MONITOR_LLM_IDLE_SECONDS="${SOAK_MONITOR_LLM_IDLE_SECONDS:-120}"
MINECRAFT_ALLOW_DESTRUCTIVE_PATHS="${MINECRAFT_ALLOW_DESTRUCTIVE_PATHS:-1}"
SOAK_MINDSERVER_BASE_PORT="${SOAK_MINDSERVER_BASE_PORT:-8080}"
REQUIRED_NODE_MAJOR="20"

if [ "$SOAK_EASY_SPAWN" = "1" ]; then
    SERVER_DIR="${SERVER_DIR:-$REPO_ROOT/minecraft-server-easy}"
    WORLD_CONFIG="${WORLD_CONFIG:-$SCRIPT_DIR/world-easy.config}"
    MC_HOST="${MC_HOST:-127.0.0.1}"
    MC_PORT="${MC_PORT:-${SERVER_PORT:-25566}}"
    SERVER_PORT="${SERVER_PORT:-$MC_PORT}"
    WHITELIST="${WHITELIST:-false}"
    export SERVER_DIR WORLD_CONFIG MC_HOST MC_PORT SERVER_PORT WHITELIST
fi

MODE="run"
BEHAVIOR_RUN_DIR=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --duration-hours)
            [ "$#" -ge 2 ] || { echo "x --duration-hours needs a value" >&2; exit 2; }
            SOAK_DURATION_HOURS="$2"
            shift 2
            ;;
        --log-dir)
            [ "$#" -ge 2 ] || { echo "x --log-dir needs a value" >&2; exit 2; }
            SOAK_LOG_ROOT="$2"
            shift 2
            ;;
        --dry-run)
            MODE="dry-run"
            shift
            ;;
        --verify)
            MODE="verify"
            shift
            ;;
        --verify-behavior)
            [ "$#" -ge 2 ] || { echo "x --verify-behavior needs a run directory" >&2; exit 2; }
            MODE="verify-behavior"
            BEHAVIOR_RUN_DIR="$2"
            shift 2
            ;;
        --help|-h)
            awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next}{exit}' "$0"
            exit 0
            ;;
        *)
            echo "x Unknown argument: $1 (try --help)" >&2
            exit 2
            ;;
    esac
done

cd "$REPO_ROOT"

ok() { echo "ok $*"; }
info() { echo "  $*"; }
fail() { echo "x $*" >&2; }

DEFAULT_SOAK_BOTS="bridge alpha vera rex aurora pixel fork sentinel grok"
DEFAULT_SOAK_COST_AGENTS="alpha vera rex aurora pixel fork sentinel grok"
SOAK_BOTS="${SOAK_BOTS:-$DEFAULT_SOAK_BOTS}"
SOAK_COST_AGENTS="${SOAK_COST_AGENTS:-$DEFAULT_SOAK_COST_AGENTS}"

script_for_bot() {
    case "$1" in
        bridge) printf '%s\n' "$SCRIPT_DIR/connect-bridge-bot.sh" ;;
        alpha) printf '%s\n' "$SCRIPT_DIR/connect-alpha-bot.sh" ;;
        vera) printf '%s\n' "$SCRIPT_DIR/connect-vera-bot.sh" ;;
        rex) printf '%s\n' "$SCRIPT_DIR/connect-rex-bot.sh" ;;
        aurora) printf '%s\n' "$SCRIPT_DIR/connect-aurora-bot.sh" ;;
        pixel) printf '%s\n' "$SCRIPT_DIR/connect-pixel-bot.sh" ;;
        fork) printf '%s\n' "$SCRIPT_DIR/connect-fork-bot.sh" ;;
        sentinel) printf '%s\n' "$SCRIPT_DIR/connect-sentinel-bot.sh" ;;
        grok) printf '%s\n' "$SCRIPT_DIR/connect-grok-bot.sh" ;;
        *) return 1 ;;
    esac
}

node_major() {
    command -v node > /dev/null 2>&1 || return 1
    node -v 2>&1 | sed -nE 's/^v?([0-9]+).*/\1/p'
}

mindserver_port_is_free() {
    local port="$1"
    PORT="$port" node --input-type=module <<'NODE'
import net from 'node:net';

const port = Number(process.env.PORT);
const server = net.createServer();
server.once('error', () => process.exit(1));
server.once('listening', () => server.close(() => process.exit(0)));
server.listen(port, '127.0.0.1');
NODE
}

check_mindserver_ports_available() {
    local bot bot_index=0 port problems=0
    for bot in $SOAK_BOTS; do
        port=$((SOAK_MINDSERVER_BASE_PORT + bot_index))
        if ! mindserver_port_is_free "$port"; then
            fail "MindServer port $port for $bot is already in use."
            problems=1
        fi
        bot_index=$((bot_index + 1))
    done
    if [ "$problems" -ne 0 ]; then
        info "  Set SOAK_MINDSERVER_BASE_PORT to a free range, or stop stale Mindcraft/MindServer processes."
        return 1
    fi
}

duration_seconds() {
    awk -v hours="$SOAK_DURATION_HOURS" 'BEGIN {
        if (hours !~ /^[0-9]+([.][0-9]+)?$/ || hours <= 0) exit 1;
        printf "%d\n", hours * 3600;
    }'
}

iso_from_epoch() {
    local epoch="$1"
    date -u -r "$epoch" '+%Y-%m-%dT%H:%M:%SZ' 2> /dev/null \
        || date -u -d "@$epoch" '+%Y-%m-%dT%H:%M:%SZ'
}

verify_static() {
    local problems=0 bot script profile

    [ -d "$SCRIPT_DIR" ] || { fail "missing scripts dir: $SCRIPT_DIR"; problems=1; }

    for bot in $SOAK_BOTS; do
        script="$(script_for_bot "$bot")" || { fail "unknown bot: $bot"; problems=1; continue; }
        if [ ! -x "$script" ]; then
            fail "launcher missing or not executable: $script"
            problems=1
        fi
    done

    for profile in bridge alpha vera rex aurora pixel fork sentinel grok; do
        if [ ! -s "$SCRIPT_DIR/profiles/${profile}-bot.json" ]; then
            fail "profile missing or empty: $SCRIPT_DIR/profiles/${profile}-bot.json"
            problems=1
        elif grep -qi 'openrouter' "$SCRIPT_DIR/profiles/${profile}-bot.json"; then
            fail "profile is not local-only: $SCRIPT_DIR/profiles/${profile}-bot.json"
            problems=1
        fi
    done

    [ -x "$SCRIPT_DIR/supervise.sh" ] || { fail "missing executable: $SCRIPT_DIR/supervise.sh"; problems=1; }
    [ -x "$SCRIPT_DIR/start-server.sh" ] || { fail "missing executable: $SCRIPT_DIR/start-server.sh"; problems=1; }
    [ -x "$SCRIPT_DIR/setup-easy-spawn.mjs" ] || { fail "missing executable: $SCRIPT_DIR/setup-easy-spawn.mjs"; problems=1; }
    [ -x "$SCRIPT_DIR/analyze_action_reliability.py" ] || { fail "missing executable: $SCRIPT_DIR/analyze_action_reliability.py"; problems=1; }
    [ -x "$SCRIPT_DIR/build_timeline.py" ] || { fail "missing executable: $SCRIPT_DIR/build_timeline.py"; problems=1; }
    [ -x "$SCRIPT_DIR/build_monitor.py" ] || { fail "missing executable: $SCRIPT_DIR/build_monitor.py"; problems=1; }
    [ -x "$SCRIPT_DIR/serve_monitor.py" ] || { fail "missing executable: $SCRIPT_DIR/serve_monitor.py"; problems=1; }
    [ -s "$SCRIPT_DIR/world-easy.config" ] || { fail "missing easy world config: $SCRIPT_DIR/world-easy.config"; problems=1; }

    grep -q 'CHECK_MINECRAFT=1 bash scripts/check-services.sh' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document the Minecraft service gate"
        problems=1
    }
    grep -q 'pnpm llm:local --list-only' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document LM Studio validation"
        problems=1
    }
    grep -q 'Action-Command Reliability Gate' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document the action-command reliability gate"
        problems=1
    }
    grep -qi 'behavioral acceptance gate' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document the behavioral acceptance gate"
        problems=1
    }
    grep -q 'behavior.tsv' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document behavior.tsv"
        problems=1
    }
    grep -q 'timeline.ndjson' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document timeline.ndjson"
        problems=1
    }
    grep -q 'monitor.html' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document monitor.html"
        problems=1
    }
    [ -s "$REPO_ROOT/docs/minecraft/timeline-schema.md" ] || {
        fail "timeline schema doc is missing"
        problems=1
    }
    [ -s "$REPO_ROOT/docs/minecraft/cohort-monitor.md" ] || {
        fail "cohort monitor doc is missing"
        problems=1
    }
    grep -q 'llm.request' "$REPO_ROOT/docs/minecraft/timeline-schema.md" 2> /dev/null || {
        fail "timeline schema doc must document LLM events"
        problems=1
    }
    grep -q 'Intent Detection' "$REPO_ROOT/docs/minecraft/action-command-reliability.md" 2> /dev/null || {
        fail "action-command reliability methodology doc is missing"
        problems=1
    }
    grep -q 'Behavior Acceptance Table' "$REPO_ROOT/docs/minecraft/cohort-report.md" 2> /dev/null || {
        fail "cohort report must carry the per-agent behavior table heading"
        problems=1
    }

    if [ "$problems" -eq 0 ]; then
        ok "Static soak verify passed: all launchers/profiles/docs are present"
    fi
    return "$problems"
}

print_plan() {
    local seconds
    seconds="$(duration_seconds 2> /dev/null || true)"

    ok "E8-8 multi-agent soak plan"
    info "duration:       ${SOAK_DURATION_HOURS}h (${seconds:-invalid} seconds)"
    info "log root:       $SOAK_LOG_ROOT"
    info "work root:      ${SOAK_WORK_ROOT:-<per-run temp>}"
    info "bridge:         $MINECRAFT_BRIDGE_URL"
    info "backend health: $BACKEND_HEALTH_URL"
    info "LM Studio:      $LOCAL_LLM_BASE_URL"
    info "chat model:     ${LOCAL_LLM_MODEL:-<unset>}"
    info "build model:    ${LOCAL_LLM_MODEL_BUILDING:-${LOCAL_LLM_MODEL:-<unset>}}"
    info "hourly cap:     \$${SOAK_AGENT_HOURLY_CAP_USD} per agent"
    info "auto-start MC:  $SOAK_START_MINECRAFT_IF_DOWN"
    info "keep MC alive:  $SOAK_KEEP_MINECRAFT_RUNNING"
    info "MC boot wait:   ${SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS}s"
    info "MC target:      ${MC_HOST:-127.0.0.1}:${MC_PORT:-${SERVER_PORT:-25565}}"
    info "server dir:     ${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
    info "world config:   ${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
    info "MindServer:     ${SOAK_MINDSERVER_BASE_PORT}+ per bot"
    info "behavior:       require=${SOAK_REQUIRE_BEHAVIOR_GATE}; movement>=${SOAK_MIN_MOVEMENT_PER_AGENT}/agent; deaths<=${SOAK_MAX_DEATHS_PER_AGENT}/agent; stuck<=${SOAK_MAX_STUCK_PER_AGENT}/agent; chat>=${SOAK_MIN_PUBLIC_CHAT_COHORT}; gather+build>=${SOAK_MIN_GATHER_OR_BUILD_COHORT}; shared>=${SOAK_MIN_SHARED_ARTIFACTS}"
    info "reliability:    intent>=${SOAK_MIN_INTENT_TO_COMMAND_RATIO} parse>=${SOAK_MIN_PARSE_SUCCESS} exec>=${SOAK_MIN_EXECUTION_RATE} verified>=${SOAK_MIN_VERIFIED_SUCCESS} min_intents=${SOAK_RELIABILITY_MIN_INTENTS} fail=${SOAK_RELIABILITY_FAIL_ON_VIOLATION}"
    info "timeline:       timeline.ndjson + timeline-totals.json"
    info "monitor:        monitor.html (stall>${SOAK_MONITOR_STALL_SECONDS}s llm_idle>${SOAK_MONITOR_LLM_IDLE_SECONDS}s)"
    if [ "$SOAK_BLOCK_PRIVATE_CONVERSATIONS" = "1" ]; then
        info "private conv:   blocked (!startConversation/!endConversation)"
    else
        info "private conv:   allowed"
    fi
    if [ "$SOAK_BLOCK_SLOW_SIM_ACTIONS" = "1" ]; then
        info "slow actions:   blocked (!newAction/!observe/!navigate/plan/code)"
    else
        info "slow actions:   allowed"
    fi
    if [ "$SOAK_SAFE_TERRAIN_ACTIONS" = "1" ]; then
        info "safe terrain:   enabled (no auto elbow-room/pickup/torch modes; no destructive pathing)"
    else
        info "safe terrain:   disabled"
    fi
    if [ "$SOAK_EASY_SPAWN" = "1" ]; then
        info "easy spawn:     enabled (peaceful starter meadow + online starter kit)"
    else
        info "easy spawn:     disabled"
    fi
    if [ -n "$SOAK_INIT_MESSAGE" ]; then
        info "init prompt:    set (${#SOAK_INIT_MESSAGE} chars)"
    else
        info "init prompt:    <none>"
    fi
    info "bots:           $SOAK_BOTS"
    info "cost agents:    $SOAK_COST_AGENTS"
    info "Mindcraft base: $MINDCRAFT_DIR"
    info "isolation:      temp local clones with node_modules symlink"
}

build_settings_json() {
    if [ -z "$SOAK_INIT_MESSAGE" ] \
        && [ "$SOAK_BLOCK_PRIVATE_CONVERSATIONS" != "1" ] \
        && [ "$SOAK_BLOCK_SLOW_SIM_ACTIONS" != "1" ]; then
        return 0
    fi
    SETTINGS_JSON="$(
        SETTINGS_JSON_CURRENT="${SETTINGS_JSON:-}" \
        SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE" \
        SOAK_BLOCK_PRIVATE_CONVERSATIONS="$SOAK_BLOCK_PRIVATE_CONVERSATIONS" \
        SOAK_BLOCK_SLOW_SIM_ACTIONS="$SOAK_BLOCK_SLOW_SIM_ACTIONS" \
        node --input-type=module <<'NODE'
const baseBlockedActions = [
    '!checkBlueprint',
    '!checkBlueprintLevel',
    '!getBlueprint',
    '!getBlueprintLevel',
];

let settings = {};
const existing = process.env.SETTINGS_JSON_CURRENT || '';
if (existing.trim().length > 0) {
    settings = JSON.parse(existing);
}

if (process.env.SOAK_INIT_MESSAGE && !Object.hasOwn(settings, 'init_message')) {
    settings.init_message = process.env.SOAK_INIT_MESSAGE;
}

if (process.env.SOAK_BLOCK_PRIVATE_CONVERSATIONS === '1') {
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [...baseBlockedActions];
    for (const command of ['!startConversation', '!endConversation']) {
        if (!blocked.includes(command)) blocked.push(command);
    }
    settings.blocked_actions = blocked;
    if (!Object.hasOwn(settings, 'num_examples')) settings.num_examples = 0;
    if (!Object.hasOwn(settings, 'show_command_syntax')) settings.show_command_syntax = 'none';
}

if (process.env.SOAK_BLOCK_SLOW_SIM_ACTIONS === '1') {
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [...baseBlockedActions];
    for (const command of [
        '!newAction',
        '!observe',
        '!navigate',
        '!buildFromPlan',
        '!executeCode',
    ]) {
        if (!blocked.includes(command)) blocked.push(command);
    }
    settings.blocked_actions = blocked;
}

process.stdout.write(JSON.stringify(settings));
NODE
    )"
    export SETTINGS_JSON
}

settings_json_for_bot() {
    local bot="$1"
    [ -n "${SETTINGS_JSON:-}" ] || return 1
    SETTINGS_JSON_INPUT="$SETTINGS_JSON" BOT_ID="$bot" SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE" \
        node --input-type=module <<'NODE'
const settings = JSON.parse(process.env.SETTINGS_JSON_INPUT);
if (process.env.BOT_ID === 'bridge' && process.env.SOAK_INIT_MESSAGE) {
    settings.init_message = '';
}
process.stdout.write(JSON.stringify(settings));
NODE
}

compute_behavior_table() {
    local run_dir="${1:-$RUN_DIR}"
    mkdir -p "$run_dir"
    "${PYTHON:-python3}" - "$run_dir" <<'PY'
import math
import os
import re
import sys
from pathlib import Path


DEFAULT_AGENTS = "alpha vera rex aurora pixel fork sentinel grok"


def int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc


run_dir = Path(sys.argv[1])
agents = [
    agent.strip().lower()
    for agent in os.environ.get("SOAK_COST_AGENTS", DEFAULT_AGENTS).split()
    if agent.strip()
]
agent_set = set(agents)

min_movement = int_env("SOAK_MIN_MOVEMENT_PER_AGENT", 5)
max_deaths = int_env("SOAK_MAX_DEATHS_PER_AGENT", 2)
max_stuck = int_env("SOAK_MAX_STUCK_PER_AGENT", 5)
min_public_chat = int_env("SOAK_MIN_PUBLIC_CHAT_COHORT", 10)
min_gather_or_build = int_env("SOAK_MIN_GATHER_OR_BUILD_COHORT", 3)
min_shared_artifacts = int_env("SOAK_MIN_SHARED_ARTIFACTS", 1)

movement_re = re.compile(r"!(move|goToPlayer|goToCoordinates|searchForBlock|searchForEntity|navigate)\b", re.IGNORECASE)
death_re = re.compile(r"(died|death|respawn(ed)?)", re.IGNORECASE)
drowning_re = re.compile(r"drown(ed|ing)?", re.IGNORECASE)
stuck_re = re.compile(r"\b(stuck|cannot reach|path.*failed|unable to (move|reach))\b", re.IGNORECASE)
dig_hole_re = re.compile(r"(dig.?hole|stuck in (a )?hole|trapped)", re.IGNORECASE)
gather_re = re.compile(r"!(collectBlocks|collectAllBlocks|consume|equip|smeltItem)\b", re.IGNORECASE)
build_re = re.compile(r"!(place|placeHere|placeBlock|build|buildFromPlan)\b", re.IGNORECASE)
shared_text_re = re.compile(r"(shared|cohort|together).*(camp|marker|wall|chest|shelter|fire)", re.IGNORECASE)
spawn_re = re.compile(r"(Spawned at|\bspawn(ed)?\b|joined the game|logged in)", re.IGNORECASE)
coord_re = re.compile(
    r"x['\"]?\s*[:=]\s*(-?\d+(?:\.\d+)?).*?"
    r"y['\"]?\s*[:=]\s*(-?\d+(?:\.\d+)?).*?"
    r"z['\"]?\s*[:=]\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def agent_in_line(line: str, agent: str) -> bool:
    return re.search(rf"\b{re.escape(agent)}\b", line, re.IGNORECASE) is not None


global_lines: list[str] = []
for log_path in sorted((run_dir / "logs").glob("*.log")):
    global_lines.extend(read_lines(log_path))

all_lines: list[tuple[str, str]] = []
for agent in agents:
    for line in read_lines(run_dir / "bots" / f"{agent}.log"):
        all_lines.append((agent, line))
for line in global_lines:
    for agent in agents:
        if agent_in_line(line, agent):
            all_lines.append((agent, line))


def is_command_chat(line: str) -> bool:
    if re.search(r"(<[^>]+>|\b[a-z][\w-]*\s*:)\s*!", line, re.IGNORECASE):
        return True
    if re.search(r"\bmsg\s*=\s*['\"]?!", line, re.IGNORECASE):
        return True
    return False


def is_public_chat(line: str, agent: str, own_log: bool) -> bool:
    lowered = line.lower()
    if "[action]" in lowered or "management_review_event" in lowered:
        return False
    if is_command_chat(line):
        return False
    if re.search(rf"<\s*{re.escape(agent)}\s*>", line, re.IGNORECASE):
        return True
    if re.search(rf"\b{re.escape(agent)}\s*:\s+\S", line, re.IGNORECASE):
        return True
    if re.search(r"\bchat\b.*\bmsg\s*=", line, re.IGNORECASE):
        return own_log or agent_in_line(line, agent)
    return False


def count_regex(lines: list[str], pattern: re.Pattern[str]) -> int:
    return sum(1 for line in lines if pattern.search(line))


def spawn_safe(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if spawn_re.search(line):
            window = lines[index : index + 30]
            return 0 if any(death_re.search(candidate) or drowning_re.search(candidate) for candidate in window) else 1
    return 0


rows: list[dict[str, int | str]] = []
unmet: list[str] = []
totals = {
    "total_movement": 0,
    "total_public_chat": 0,
    "total_inter_agent_chat": 0,
    "total_gather": 0,
    "total_build": 0,
    "total_deaths": 0,
    "total_drownings": 0,
    "total_stuck": 0,
    "total_dig_holes": 0,
}

for agent in agents:
    own_lines = read_lines(run_dir / "bots" / f"{agent}.log")
    agent_global_lines = [line for line in global_lines if agent_in_line(line, agent)]
    counter_lines = own_lines + agent_global_lines
    own_public_chat = [line for line in own_lines if is_public_chat(line, agent, own_log=True)]
    global_public_chat = [line for line in agent_global_lines if is_public_chat(line, agent, own_log=False)]
    public_chat_lines = own_public_chat + global_public_chat

    movement = count_regex(counter_lines, movement_re)
    gather = count_regex(counter_lines, gather_re)
    build = count_regex(counter_lines, build_re)
    deaths = count_regex(counter_lines, death_re)
    drownings = count_regex(counter_lines, drowning_re)
    stuck = count_regex(counter_lines, stuck_re)
    dig_holes = count_regex(counter_lines, dig_hole_re)
    inter_agent_chat = sum(
        1
        for line in public_chat_lines
        if any(other != agent and agent_in_line(line, other) for other in agent_set)
    )
    safe_spawn = spawn_safe(counter_lines)

    agent_unmet: list[str] = []
    if safe_spawn != 1:
        agent_unmet.append(f"agent {agent} safe spawn expected 1 got {safe_spawn}")
    if movement < min_movement:
        agent_unmet.append(f"agent {agent} movement expected >= {min_movement} got {movement}")
    if deaths > max_deaths:
        agent_unmet.append(f"agent {agent} deaths expected <= {max_deaths} got {deaths}")
    if stuck > max_stuck:
        agent_unmet.append(f"agent {agent} stuck expected <= {max_stuck} got {stuck}")
    unmet.extend(agent_unmet)

    row = {
        "agent": agent,
        "spawn_safe": safe_spawn,
        "movement": movement,
        "public_chat": len(public_chat_lines),
        "inter_agent_chat": inter_agent_chat,
        "gather": gather,
        "build": build,
        "deaths": deaths,
        "drownings": drownings,
        "stuck": stuck,
        "dig_holes": dig_holes,
        "behavior_status": "fail" if agent_unmet else "pass",
    }
    rows.append(row)

    totals["total_movement"] += movement
    totals["total_public_chat"] += len(public_chat_lines)
    totals["total_inter_agent_chat"] += inter_agent_chat
    totals["total_gather"] += gather
    totals["total_build"] += build
    totals["total_deaths"] += deaths
    totals["total_drownings"] += drownings
    totals["total_stuck"] += stuck
    totals["total_dig_holes"] += dig_holes


place_agents: set[str] = set()
place_coords: list[tuple[str, tuple[float, float, float]]] = []
shared_text_count = 0
for agent, line in all_lines:
    if shared_text_re.search(line):
        shared_text_count += 1
    if build_re.search(line):
        place_agents.add(agent)
        coord_match = coord_re.search(line)
        if coord_match:
            place_coords.append((agent, tuple(float(part) for part in coord_match.groups())))

nearby_place_pairs = 0
for index, (agent, coord) in enumerate(place_coords):
    for other_agent, other_coord in place_coords[:index]:
        if other_agent == agent:
            continue
        if math.dist(coord, other_coord) <= 10:
            nearby_place_pairs += 1

shared_artifact_count = max(shared_text_count, nearby_place_pairs, 1 if len(place_agents) >= 2 else 0)
totals["total_gather_or_build"] = totals["total_gather"] + totals["total_build"]
totals["shared_artifact_count"] = shared_artifact_count

if totals["total_public_chat"] < min_public_chat:
    unmet.append(f"cohort public chat expected >= {min_public_chat} got {totals['total_public_chat']}")
if totals["total_gather_or_build"] < min_gather_or_build:
    unmet.append(
        f"cohort gather+build expected >= {min_gather_or_build} got {totals['total_gather_or_build']}"
    )
if shared_artifact_count < min_shared_artifacts:
    unmet.append(f"cohort shared artifacts expected >= {min_shared_artifacts} got {shared_artifact_count}")

status = "fail" if unmet else "pass"

header = [
    "agent",
    "spawn_safe",
    "movement",
    "public_chat",
    "inter_agent_chat",
    "gather",
    "build",
    "deaths",
    "drownings",
    "stuck",
    "dig_holes",
    "behavior_status",
]
with (run_dir / "behavior.tsv").open("w", encoding="utf-8") as handle:
    handle.write("\t".join(header) + "\n")
    for row in rows:
        handle.write("\t".join(str(row[column]) for column in header) + "\n")

with (run_dir / "behavior-totals.env").open("w", encoding="utf-8") as handle:
    for key in sorted(totals):
        handle.write(f"{key}={totals[key]}\n")
    handle.write(f"behavior_gate_status={status}\n")
    handle.write(f"behavior_gate_required={os.environ.get('SOAK_REQUIRE_BEHAVIOR_GATE', '1')}\n")

with (run_dir / "behavior-unmet-thresholds.txt").open("w", encoding="utf-8") as handle:
    for item in unmet:
        handle.write(item + "\n")

with (run_dir / "behavior-gate-status.txt").open("w", encoding="utf-8") as handle:
    handle.write(status + "\n")
PY
}

behavior_metric() {
    local run_dir="${1:-$RUN_DIR}" key="$2"
    awk -F= -v key="$key" '$1 == key {print $2}' "$run_dir/behavior-totals.env" 2> /dev/null
}

append_behavior_summary() {
    local run_dir="${1:-$RUN_DIR}"
    {
        echo
        echo "Behavioral acceptance"
        echo "behavior.tsv: $run_dir/behavior.tsv"
        echo
        echo "Per-agent behavior table"
        cat "$run_dir/behavior.tsv"
        echo
        echo "Cohort behavior totals"
        echo "total_movement: $(behavior_metric "$run_dir" total_movement)"
        echo "total_public_chat: $(behavior_metric "$run_dir" total_public_chat)"
        echo "total_inter_agent_chat: $(behavior_metric "$run_dir" total_inter_agent_chat)"
        echo "total_gather: $(behavior_metric "$run_dir" total_gather)"
        echo "total_build: $(behavior_metric "$run_dir" total_build)"
        echo "total_gather_or_build: $(behavior_metric "$run_dir" total_gather_or_build)"
        echo "total_deaths: $(behavior_metric "$run_dir" total_deaths)"
        echo "total_drownings: $(behavior_metric "$run_dir" total_drownings)"
        echo "total_stuck: $(behavior_metric "$run_dir" total_stuck)"
        echo "total_dig_holes: $(behavior_metric "$run_dir" total_dig_holes)"
        echo "shared_artifact_count: $(behavior_metric "$run_dir" shared_artifact_count)"
        echo
        echo "behavior_gate_status=$(behavior_metric "$run_dir" behavior_gate_status)"
        echo "behavior_gate_required=$(behavior_metric "$run_dir" behavior_gate_required)"
        echo "unmet_thresholds:"
        if [ -s "$run_dir/behavior-unmet-thresholds.txt" ]; then
            sed 's/^/- /' "$run_dir/behavior-unmet-thresholds.txt"
        else
            echo "none"
        fi
    } >> "$run_dir/summary.txt"
}

run_behavior_gate() {
    local run_dir="${1:-$RUN_DIR}"
    compute_behavior_table "$run_dir"
    append_behavior_summary "$run_dir"
}

if [ "$MODE" = "verify" ]; then
    verify_static
    exit $?
fi

if [ "$MODE" = "verify-behavior" ]; then
    verify_static || true
    mkdir -p "$BEHAVIOR_RUN_DIR"
    : > "$BEHAVIOR_RUN_DIR/summary.txt"
    run_behavior_gate "$BEHAVIOR_RUN_DIR"
    BEHAVIOR_GATE_STATUS="$(cat "$BEHAVIOR_RUN_DIR/behavior-gate-status.txt" 2> /dev/null || echo fail)"
    if [ "$SOAK_REQUIRE_BEHAVIOR_GATE" = "1" ] && [ "$BEHAVIOR_GATE_STATUS" != "pass" ]; then
        fail "Behavioral acceptance gate failed: $(paste -sd '; ' "$BEHAVIOR_RUN_DIR/behavior-unmet-thresholds.txt" 2> /dev/null || echo 'see behavior.tsv')"
        exit 1
    fi
    ok "Behavioral acceptance gate $BEHAVIOR_GATE_STATUS for $BEHAVIOR_RUN_DIR"
    exit 0
fi

if [ "$MODE" = "dry-run" ]; then
    verify_static || true
    print_plan
    echo
    ok "Dry run complete - no services checked, no bots launched"
    exit 0
fi

verify_static || { fail "Refusing to run with invalid committed soak assets."; exit 1; }

DURATION_SECONDS="$(duration_seconds 2> /dev/null || true)"
if [ -z "$DURATION_SECONDS" ]; then
    fail "Invalid SOAK_DURATION_HOURS: $SOAK_DURATION_HOURS"
    exit 2
fi

if [ "$LOCAL_LLM_BASE_URL" != "http://localhost:1234/v1" ]; then
    fail "LOCAL_LLM_BASE_URL must be http://localhost:1234/v1 for pinned Mindcraft lmstudio profiles."
    info "  The connect scripts only use LOCAL_LLM_BASE_URL for pre-flight checks;"
    info "  Mindcraft string-form lmstudio/<model> connects to localhost:1234."
    exit 1
fi

if [ -z "${LOCAL_LLM_MODEL:-}" ]; then
    fail "LOCAL_LLM_MODEL is not set. List local ids with: pnpm llm:local --list-only"
    exit 1
fi
export LOCAL_LLM_MODEL_BUILDING="${LOCAL_LLM_MODEL_BUILDING:-$LOCAL_LLM_MODEL}"

if [ -z "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
    fail "MINECRAFT_BRIDGE_TOKEN is not set; bridge auth is fail-closed."
    exit 1
fi

NODE_MAJOR="$(node_major || true)"
if [ "$NODE_MAJOR" != "$REQUIRED_NODE_MAJOR" ]; then
    fail "Node ${NODE_MAJOR:-<missing>} found, but Mindcraft soak requires Node $REQUIRED_NODE_MAJOR LTS."
    exit 1
fi
build_settings_json
case "$SOAK_MINDSERVER_BASE_PORT" in
    ""|*[!0-9]*)
        fail "SOAK_MINDSERVER_BASE_PORT must be a numeric TCP port."
        exit 2
        ;;
esac
check_mindserver_ports_available || exit 1

if MINDCRAFT_BASE_ABS="$(cd -- "$MINDCRAFT_DIR" 2> /dev/null && pwd)"; then
    :
else
    MINDCRAFT_BASE_ABS=""
fi
if [ -z "$MINDCRAFT_BASE_ABS" ] || [ ! -d "$MINDCRAFT_BASE_ABS/.git" ]; then
    fail "No pinned Mindcraft clone at $MINDCRAFT_DIR. Run scripts/minecraft/setup-mindcraft.sh first."
    exit 1
fi
HEAD_SHA="$(git -C "$MINDCRAFT_BASE_ABS" rev-parse HEAD 2> /dev/null || true)"
if [ "$HEAD_SHA" != "$MINDCRAFT_COMMIT" ]; then
    fail "Mindcraft clone is not at pinned commit $MINDCRAFT_COMMIT"
    info "  HEAD is ${HEAD_SHA:-<unknown>}"
    exit 1
fi
if [ ! -d "$MINDCRAFT_BASE_ABS/node_modules" ]; then
    fail "$MINDCRAFT_BASE_ABS/node_modules missing. Run scripts/minecraft/setup-mindcraft.sh first."
    exit 1
fi

RUN_ID="$(date -u '+%Y%m%dT%H%M%SZ')"
RUN_DIR="$SOAK_LOG_ROOT/$RUN_ID"
SOAK_WORK_ROOT="${SOAK_WORK_ROOT:-${TMPDIR:-/tmp}/livestreamtoagi-soak-worktrees/$RUN_ID}"
mkdir -p "$SOAK_WORK_ROOT"
SOAK_WORK_ROOT="$(cd -- "$SOAK_WORK_ROOT" && pwd)"
mkdir -p "$RUN_DIR"/{bots,preflight,logs,timeline-raw}
printf '%s\n' "$SOAK_WORK_ROOT" > "$RUN_DIR/worktrees.path"
PID_FILE="$RUN_DIR/pids.tsv"
TAIL_PID_FILE="$RUN_DIR/tail-pids.txt"
EARLY_EXIT_FILE="$RUN_DIR/early-exits.tsv"
: > "$PID_FILE"
: > "$TAIL_PID_FILE"
: > "$EARLY_EXIT_FILE"

SOAK_START_ISO="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
SOAK_START_EPOCH="$(date '+%s')"
SOAK_END_EPOCH=$((SOAK_START_EPOCH + DURATION_SECONDS))
SOAK_PLANNED_END_ISO="$(iso_from_epoch "$SOAK_END_EPOCH")"

run_checked() {
    local label="$1" output="$2"
    shift 2
    info "preflight: $label"
    if "$@" > "$output" 2>&1; then
        ok "$label"
    else
        fail "$label failed; see $output"
        return 1
    fi
}

write_metadata() {
    {
        echo "run_id=$RUN_ID"
        echo "start_utc=$SOAK_START_ISO"
        echo "planned_end_utc=$SOAK_PLANNED_END_ISO"
        echo "duration_hours=$SOAK_DURATION_HOURS"
        echo "duration_seconds=$DURATION_SECONDS"
        echo "repo_root=$REPO_ROOT"
        echo "git_head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
        echo "git_branch=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || true)"
        echo "host=$(hostname 2>/dev/null || true)"
        echo "uname=$(uname -a 2>/dev/null || true)"
        echo "node=$(node -v 2>/dev/null || true)"
        echo "npm=$(npm -v 2>/dev/null || true)"
        echo "java=$(java -version 2>&1 | head -n1 || true)"
        echo "local_llm_base_url=$LOCAL_LLM_BASE_URL"
        echo "local_llm_model=$LOCAL_LLM_MODEL"
        echo "local_llm_model_building=$LOCAL_LLM_MODEL_BUILDING"
        echo "bridge_url=$MINECRAFT_BRIDGE_URL"
        echo "bridge_token_set=yes"
        echo "agent_hourly_cap_usd=$SOAK_AGENT_HOURLY_CAP_USD"
        echo "min_movement_per_agent=$SOAK_MIN_MOVEMENT_PER_AGENT"
        echo "max_deaths_per_agent=$SOAK_MAX_DEATHS_PER_AGENT"
        echo "max_stuck_per_agent=$SOAK_MAX_STUCK_PER_AGENT"
        echo "min_public_chat_cohort=$SOAK_MIN_PUBLIC_CHAT_COHORT"
        echo "min_gather_or_build_cohort=$SOAK_MIN_GATHER_OR_BUILD_COHORT"
        echo "min_shared_artifacts=$SOAK_MIN_SHARED_ARTIFACTS"
        echo "require_behavior_gate=$SOAK_REQUIRE_BEHAVIOR_GATE"
        echo "work_root=$SOAK_WORK_ROOT"
        echo "keep_worktrees=$SOAK_KEEP_WORKTREES"
        echo "start_minecraft_if_down=$SOAK_START_MINECRAFT_IF_DOWN"
        echo "keep_minecraft_running=$SOAK_KEEP_MINECRAFT_RUNNING"
        echo "minecraft_boot_timeout_seconds=$SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS"
        echo "block_private_conversations=$SOAK_BLOCK_PRIVATE_CONVERSATIONS"
        echo "block_slow_sim_actions=$SOAK_BLOCK_SLOW_SIM_ACTIONS"
        echo "safe_terrain_actions=$SOAK_SAFE_TERRAIN_ACTIONS"
        echo "easy_spawn=$SOAK_EASY_SPAWN"
        echo "easy_spawn_online_delay_seconds=$SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS"
        echo "min_intent_to_command_ratio=$SOAK_MIN_INTENT_TO_COMMAND_RATIO"
        echo "min_parse_success=$SOAK_MIN_PARSE_SUCCESS"
        echo "min_execution_rate=$SOAK_MIN_EXECUTION_RATE"
        echo "min_verified_success=$SOAK_MIN_VERIFIED_SUCCESS"
        echo "reliability_min_intents=$SOAK_RELIABILITY_MIN_INTENTS"
        echo "reliability_fail_on_violation=$SOAK_RELIABILITY_FAIL_ON_VIOLATION"
        echo "monitor_stall_seconds=$SOAK_MONITOR_STALL_SECONDS"
        echo "monitor_llm_idle_seconds=$SOAK_MONITOR_LLM_IDLE_SECONDS"
        echo "allow_destructive_paths=$MINECRAFT_ALLOW_DESTRUCTIVE_PATHS"
        echo "minecraft_host=${MC_HOST:-127.0.0.1}"
        echo "minecraft_port=${MC_PORT:-${SERVER_PORT:-25565}}"
        echo "server_dir=${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
        echo "world_config=${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
        if [ -n "$SOAK_INIT_MESSAGE" ]; then
            echo "init_message_set=yes"
            echo "init_message_chars=${#SOAK_INIT_MESSAGE}"
        else
            echo "init_message_set=no"
            echo "init_message_chars=0"
        fi
        echo "mindserver_base_port=$SOAK_MINDSERVER_BASE_PORT"
        echo "bots=$SOAK_BOTS"
        echo "cost_agents=$SOAK_COST_AGENTS"
    } > "$RUN_DIR/metadata.env"
}

start_tail_if_present() {
    local source="$1" dest="$2" label="$3"
    if [ -f "$source" ]; then
        tail -n 0 -F "$source" > "$dest" 2>&1 &
        echo "$!" >> "$TAIL_PID_FILE"
        ok "capturing $label -> $dest"
    else
        echo "$label not present: $source" > "$dest"
        info "$label not present; wrote note to $dest"
    fi
}

start_log_capture() {
    if command -v journalctl > /dev/null 2>&1; then
        journalctl -u minecraft -f -o short-iso > "$RUN_DIR/logs/journalctl-minecraft.log" 2>&1 &
        echo "$!" >> "$TAIL_PID_FILE"
        ok "capturing journalctl -u minecraft"
    else
        echo "journalctl not available on this host" > "$RUN_DIR/logs/journalctl-minecraft.log"
    fi

    local server_dir="${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
    start_tail_if_present "$server_dir/logs/supervisor.log" "$RUN_DIR/logs/supervisor.log" "supervisor log"
    start_tail_if_present "$server_dir/logs/latest.log" "$RUN_DIR/logs/paper-latest.log" "Paper latest.log"

    if [ -n "${BRIDGE_LOG_FILE:-}" ]; then
        start_tail_if_present "$BRIDGE_LOG_FILE" "$RUN_DIR/logs/bridge.log" "bridge log"
    else
        echo "BRIDGE_LOG_FILE not set; backend stdout is not capturable by soak.sh" > "$RUN_DIR/logs/bridge.log"
    fi

    if [ -n "${MANAGEMENT_LOG_FILE:-}" ]; then
        start_tail_if_present "$MANAGEMENT_LOG_FILE" "$RUN_DIR/logs/management.log" "Management log"
    else
        echo "MANAGEMENT_LOG_FILE not set; Management interventions are queried from DB when possible" > "$RUN_DIR/logs/management.log"
    fi
}

ensure_minecraft_server() {
    if "$SCRIPT_DIR/health.sh" --quiet; then
        ok "Minecraft server already up"
        return 0
    fi

    if [ "$SOAK_START_MINECRAFT_IF_DOWN" != "1" ]; then
        fail "Minecraft server is down and SOAK_START_MINECRAFT_IF_DOWN is not 1."
        info "  Start it with scripts/minecraft/start-server.sh or enable auto-start."
        return 1
    fi

    info "Minecraft server down; starting portable supervisor for the soak"
    SERVER_DIR="${SERVER_DIR:-$REPO_ROOT/minecraft-server}" \
        "$SCRIPT_DIR/supervise.sh" > "$RUN_DIR/logs/minecraft-supervisor-stdout.log" 2>&1 &
    local supervisor_pid="$!"
    echo "$supervisor_pid" > "$RUN_DIR/minecraft-supervisor.pid"

    local waited=0
    while [ "$waited" -lt "$SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS" ]; do
        if "$SCRIPT_DIR/health.sh" --quiet; then
            ok "Minecraft server became healthy after ${waited}s"
            return 0
        fi
        if ! kill -0 "$supervisor_pid" 2> /dev/null; then
            fail "Minecraft supervisor exited before the server became healthy."
            tail -40 "$RUN_DIR/logs/minecraft-supervisor-stdout.log" >&2 || true
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done

    fail "Minecraft server did not become healthy within ${SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS}s."
    tail -40 "$RUN_DIR/logs/minecraft-supervisor-stdout.log" >&2 || true
    return 1
}

prepare_mindcraft_clone() {
    local bot="$1" dest
    dest="$SOAK_WORK_ROOT/mindcraft-$bot"
    git clone --shared --quiet "$MINDCRAFT_BASE_ABS" "$dest"
    git -C "$dest" checkout --quiet --detach "$MINDCRAFT_COMMIT"
    ln -s "$MINDCRAFT_BASE_ABS/node_modules" "$dest/node_modules"
    if [ -f "$MINDCRAFT_BASE_ABS/keys.json" ]; then
        ln -s "$MINDCRAFT_BASE_ABS/keys.json" "$dest/keys.json"
    fi
    apply_safe_terrain_patch "$dest"
    printf '%s\n' "$dest"
}

apply_safe_terrain_patch() {
    local dest="$1" profile skills
    [ "$SOAK_SAFE_TERRAIN_ACTIONS" = "1" ] || return 0
    profile="$dest/profiles/defaults/assistant.json"
    skills="$dest/src/agent/library/skills.js"
    if [ ! -f "$profile" ] || [ ! -f "$skills" ]; then
        fail "Safe terrain patch could not find Mindcraft profile/skills files in $dest"
        return 1
    fi
    SAFE_TERRAIN_PROFILE="$profile" SAFE_TERRAIN_SKILLS="$skills" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const profilePath = process.env.SAFE_TERRAIN_PROFILE;
const skillsPath = process.env.SAFE_TERRAIN_SKILLS;
const marker = 'LTAG safe terrain local sim';

const profile = JSON.parse(readFileSync(profilePath, 'utf8'));
profile.modes = {
    ...(profile.modes || {}),
    self_preservation: true,
    unstuck: true,
    cowardice: false,
    self_defense: true,
    hunting: false,
    item_collecting: false,
    torch_placing: false,
    elbow_room: false,
    idle_staring: true,
    cheat: false,
};
writeFileSync(profilePath, `${JSON.stringify(profile, null, 4)}\n`);

let source = readFileSync(skillsPath, 'utf8');
if (!source.includes(marker)) {
    const movementNeedle = `    const nonDestructiveMovements = new pf.Movements(bot);
    const dontBreakBlocks = ['glass', 'glass_pane'];
`;
    const movementPatch = `    const nonDestructiveMovements = new pf.Movements(bot);
    const allowDestructivePaths = !['0', 'false', 'no', 'off'].includes(String(process.env.MINECRAFT_ALLOW_DESTRUCTIVE_PATHS || '1').trim().toLowerCase()); // ${marker}
    if (!allowDestructivePaths) {
        nonDestructiveMovements.canDig = false;
        nonDestructiveMovements.allow1by1towers = false;
    }
    const dontBreakBlocks = ['glass', 'glass_pane'];
`;
    if (!source.includes(movementNeedle)) {
        throw new Error('goToGoal movement initialization shape changed');
    }
    source = source.replace(movementNeedle, movementPatch);

    source = source.replace(
        `    const destructiveMovements = new pf.Movements(bot);

    let final_movements = destructiveMovements;
`,
        `    const destructiveMovements = new pf.Movements(bot);

    let final_movements = allowDestructivePaths ? destructiveMovements : nonDestructiveMovements;
`,
    );

    const fallbackNeedle = `    else if (await bot.pathfinder.getPathTo(destructiveMovements, goal, pathfind_timeout).status === 'success') {
        log(bot, \`Found destructive path.\`);
    }
    else {
        log(bot, \`Path not found, but attempting to navigate anyway using destructive movements.\`);
    }
`;
    const fallbackPatch = `    else if (allowDestructivePaths && await bot.pathfinder.getPathTo(destructiveMovements, goal, pathfind_timeout).status === 'success') {
        log(bot, \`Found destructive path.\`);
    }
    else if (allowDestructivePaths) {
        log(bot, \`Path not found, but attempting to navigate anyway using destructive movements.\`);
    }
    else {
        log(bot, \`Path not found without terrain digging; refusing destructive navigation.\`);
        return false;
    }
`;
    if (!source.includes(fallbackNeedle)) {
        throw new Error('goToGoal destructive fallback shape changed');
    }
    source = source.replace(fallbackNeedle, fallbackPatch);
    writeFileSync(skillsPath, source);
}
NODE
}

launch_bot() {
    local bot="$1" bot_index="$2" script worktree log pid mindserver_port bot_settings_json
    script="$(script_for_bot "$bot")"
    worktree="$(prepare_mindcraft_clone "$bot")"
    mindserver_port=$((SOAK_MINDSERVER_BASE_PORT + bot_index))
    log="$RUN_DIR/bots/$bot.log"
    info "launching $bot with isolated Mindcraft clone $worktree (MindServer :$mindserver_port)"
    (
        cd "$REPO_ROOT"
        export MINDCRAFT_DIR="$worktree"
        export MINDSERVER_PORT="$mindserver_port"
        export LOCAL_LLM_MODEL LOCAL_LLM_MODEL_BUILDING LOCAL_LLM_BASE_URL
        export MINECRAFT_BRIDGE_URL MINECRAFT_BRIDGE_TOKEN
        export MC_RUN_DIR="$RUN_DIR"
        export MC_TIMELINE_NDJSON="$RUN_DIR/timeline-raw/$bot.ndjson"
        export MC_HOST MC_PORT
        export LTAG_RUN_ID="$RUN_ID"
        export MINECRAFT_ALLOW_DESTRUCTIVE_PATHS
        export MINECRAFT_MANAGEMENT_REVIEW_MODE MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS
        bot_settings_json="$(settings_json_for_bot "$bot" || true)"
        if [ -n "$bot_settings_json" ]; then
            exec env SETTINGS_JSON="$bot_settings_json" "$script"
        else
            exec "$script"
        fi
    ) > "$log" 2>&1 &
    pid="$!"
    printf '%s\t%s\t%s\t%s\t%s\n' "$bot" "$pid" "$script" "$worktree" "$log" >> "$PID_FILE"
    sleep "$SOAK_LAUNCH_STAGGER_SECONDS"
}

stop_process_file() {
    local file="$1" pid
    [ -f "$file" ] || return 0
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        kill "$pid" 2> /dev/null || true
    done < "$file"
}

signal_process_tree() {
    local pid="$1" signal="$2" child
    for child in $(pgrep -P "$pid" 2> /dev/null || true); do
        signal_process_tree "$child" "$signal"
    done
    kill "-$signal" "$pid" 2> /dev/null || true
}

stop_bots() {
    local bot pid rest
    [ -f "$PID_FILE" ] || return 0
    while IFS="$(printf '\t')" read -r bot pid rest; do
        [ -n "${pid:-}" ] || continue
        signal_process_tree "$pid" TERM
    done < "$PID_FILE"
    sleep 5
    while IFS="$(printf '\t')" read -r bot pid rest; do
        [ -n "${pid:-}" ] || continue
        if kill -0 "$pid" 2> /dev/null; then
            signal_process_tree "$pid" KILL
        fi
        wait "$pid" 2> /dev/null || true
    done < "$PID_FILE"
}

stop_minecraft_supervisor() {
    local pid
    [ -f "$RUN_DIR/minecraft-supervisor.pid" ] || return 0
    if [ "$SOAK_KEEP_MINECRAFT_RUNNING" = "1" ]; then
        info "leaving auto-started Minecraft supervisor running"
        return 0
    fi
    pid="$(cat "$RUN_DIR/minecraft-supervisor.pid" 2> /dev/null || true)"
    [ -n "$pid" ] || return 0
    kill "$pid" 2> /dev/null || true
    wait "$pid" 2> /dev/null || true
}

cleanup_worktrees() {
    [ -n "${SOAK_WORK_ROOT:-}" ] || return 0
    if [ "$SOAK_KEEP_WORKTREES" = "1" ]; then
        info "keeping temp Mindcraft clones at $SOAK_WORK_ROOT"
        return 0
    fi
    case "$SOAK_WORK_ROOT" in
        ""|"/"|"$REPO_ROOT"|"$REPO_ROOT"/*)
            info "not auto-removing work root at $SOAK_WORK_ROOT"
            return 0
            ;;
    esac
    rm -rf "$SOAK_WORK_ROOT"
}

cleanup() {
    local status=$?
    stop_bots
    stop_minecraft_supervisor
    stop_process_file "$TAIL_PID_FILE"
    cleanup_worktrees
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

monitor_bots() {
    local had_early_exit=0 now bot pid script worktree log
    while :; do
        now="$(date '+%s')"
        [ "$now" -lt "$SOAK_END_EPOCH" ] || break
        while IFS="$(printf '\t')" read -r bot pid script worktree log; do
            [ -n "${pid:-}" ] || continue
            if ! kill -0 "$pid" 2> /dev/null; then
                if ! grep -q "^${bot}[[:space:]]" "$EARLY_EXIT_FILE" 2> /dev/null; then
                    printf '%s\t%s\t%s\n' "$bot" "$pid" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$EARLY_EXIT_FILE"
                    fail "$bot exited before planned soak end"
                    had_early_exit=1
                fi
            fi
        done < "$PID_FILE"
        sleep 5
    done
    return "$had_early_exit"
}

run_cost_query() {
    local end_iso="$1" report="$RUN_DIR/cost-ledger.tsv" exceeded="$RUN_DIR/cost-cap-exceeded.count"
    local -a psql_base
    psql_base=(docker compose exec -T postgres psql -U "${POSTGRES_USER:-agi}" -d "${POSTGRES_DB:-livestream_agi}" -v ON_ERROR_STOP=1 -X)

    "${psql_base[@]}" \
        -v start_ts="$SOAK_START_ISO" \
        -v end_ts="$end_iso" \
        -v hourly_cap="$SOAK_AGENT_HOURLY_CAP_USD" \
        -P footer=off \
        > "$report" <<'SQL'
WITH tracked(agent_id) AS (
    VALUES
        ('alpha'), ('vera'), ('rex'), ('aurora'), ('pixel'), ('fork'), ('sentinel'), ('grok')
),
hourly AS (
    SELECT
        lower(agent_id) AS agent_id,
        date_trunc('hour', created_at) AS hour_utc,
        COALESCE(SUM(amount), 0) AS usd,
        COALESCE(SUM(
            COALESCE((details->>'input_tokens')::int, 0)
          + COALESCE((details->>'output_tokens')::int, 0)
        ), 0) AS tokens
    FROM cost_events
    WHERE created_at >= :'start_ts'::timestamptz
      AND created_at <= :'end_ts'::timestamptz
      AND lower(COALESCE(agent_id, '')) IN (SELECT agent_id FROM tracked)
    GROUP BY lower(agent_id), date_trunc('hour', created_at)
),
totals AS (
    SELECT agent_id, SUM(usd) AS total_usd, SUM(tokens) AS total_tokens
    FROM hourly
    GROUP BY agent_id
),
max_hour AS (
    SELECT agent_id, MAX(usd) AS max_hour_usd
    FROM hourly
    GROUP BY agent_id
)
SELECT
    tracked.agent_id,
    COALESCE(totals.total_tokens, 0) AS total_tokens,
    COALESCE(totals.total_usd, 0)::numeric(10,4) AS total_usd,
    COALESCE(max_hour.max_hour_usd, 0)::numeric(10,4) AS max_hour_usd,
    :'hourly_cap'::numeric(10,4) AS hourly_cap_usd,
    CASE
        WHEN COALESCE(max_hour.max_hour_usd, 0) <= :'hourly_cap'::numeric THEN 'pass'
        ELSE 'fail'
    END AS cap_status
FROM tracked
LEFT JOIN totals USING (agent_id)
LEFT JOIN max_hour USING (agent_id)
ORDER BY tracked.agent_id;
SQL

    "${psql_base[@]}" \
        -v start_ts="$SOAK_START_ISO" \
        -v end_ts="$end_iso" \
        -v hourly_cap="$SOAK_AGENT_HOURLY_CAP_USD" \
        -At \
        > "$exceeded" <<'SQL'
WITH tracked(agent_id) AS (
    VALUES
        ('alpha'), ('vera'), ('rex'), ('aurora'), ('pixel'), ('fork'), ('sentinel'), ('grok')
),
hourly AS (
    SELECT lower(agent_id) AS agent_id, date_trunc('hour', created_at) AS hour_utc, SUM(amount) AS usd
    FROM cost_events
    WHERE created_at >= :'start_ts'::timestamptz
      AND created_at <= :'end_ts'::timestamptz
      AND lower(COALESCE(agent_id, '')) IN (SELECT agent_id FROM tracked)
    GROUP BY lower(agent_id), date_trunc('hour', created_at)
)
SELECT COUNT(*)
FROM (
    SELECT tracked.agent_id, COALESCE(MAX(hourly.usd), 0) AS max_hour_usd
    FROM tracked
    LEFT JOIN hourly USING (agent_id)
    GROUP BY tracked.agent_id
) cap_check
WHERE max_hour_usd > :'hourly_cap'::numeric;
SQL
}

count_matches() {
    local pattern="$1"
    shift
    # grep -c returns 1 when nothing matches, which would trip pipefail in
    # the success path. Swallow that so the summary always renders.
    { grep -Eihc "$pattern" "$@" 2> /dev/null || true; } | awk '{sum += $1} END {print sum + 0}'
}

write_summary() {
    local end_iso="$1" early_count bridge_drops management_events crash_lines runaway_lines
    early_count="$(wc -l < "$EARLY_EXIT_FILE" | tr -d ' ')"
    bridge_drops="$(count_matches 'bridge[-_ ]down|bridge_(connect_failed|send_failed)|bridge unavailable|WebSocket.*(closed|disconnect)|ECONN' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log)"
    management_events="$(count_matches 'management_review_event|Management|intervene|shadow' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log)"
    crash_lines="$(count_matches 'uncaught|unhandled|fatal|segmentation|crash|exception' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log)"
    runaway_lines="$(find "$RUN_DIR/bots" -name '*.log' -type f -exec wc -l {} \; | awk -v max="$SOAK_MAX_LOG_LINES_PER_BOT" '$1 > max {print $0}')"
    {
        echo "E8-8 multi-agent soak summary"
        echo "run_id: $RUN_ID"
        echo "start_utc: $SOAK_START_ISO"
        echo "end_utc: $end_iso"
        echo "planned_duration_hours: $SOAK_DURATION_HOURS"
        echo "bots: $SOAK_BOTS"
        echo
        echo "Counters"
        echo "early_bot_exits: $early_count"
        echo "bridge_drop_lines: $bridge_drops"
        echo "management_event_lines: $management_events"
        echo "crash_candidate_lines: $crash_lines"
        echo
        echo "Respond/ignore rough count from bot logs"
        echo "respond: $(count_matches '\brespond\b' "$RUN_DIR"/bots/*.log)"
        echo "ignore: $(count_matches '\bignore\b' "$RUN_DIR"/bots/*.log)"
        echo
        echo "Runaway log-line check (limit $SOAK_MAX_LOG_LINES_PER_BOT per bot log)"
        if [ -n "$runaway_lines" ]; then
            printf '%s\n' "$runaway_lines"
        else
            echo "none"
        fi
        echo
        echo "Early exits"
        if [ -s "$EARLY_EXIT_FILE" ]; then
            cat "$EARLY_EXIT_FILE"
        else
            echo "none"
        fi
        echo
        echo "Cost ledger"
        if [ -s "$RUN_DIR/cost-ledger.tsv" ]; then
            cat "$RUN_DIR/cost-ledger.tsv"
        else
            echo "not available"
        fi
    } > "$RUN_DIR/summary.txt"
}

run_action_reliability() {
    "${PYTHON:-python3}" "$SCRIPT_DIR/analyze_action_reliability.py" \
        --run-dir "$RUN_DIR" \
        --min-intent-to-command "$SOAK_MIN_INTENT_TO_COMMAND_RATIO" \
        --min-parse-success "$SOAK_MIN_PARSE_SUCCESS" \
        --min-execution-rate "$SOAK_MIN_EXECUTION_RATE" \
        --min-verified-success "$SOAK_MIN_VERIFIED_SUCCESS" \
        --min-intents "$SOAK_RELIABILITY_MIN_INTENTS"
}

append_action_reliability_summary() {
    local status="$1" status_label
    if [ "$status" -eq 0 ]; then
        status_label="pass"
    else
        status_label="not acceptable"
    fi

    {
        echo
        echo "Action-command reliability"
        echo "status: $status_label"
        echo "report: $RUN_DIR/action-reliability.md"
        if [ -s "$RUN_DIR/action-reliability.json" ]; then
            ACTION_RELIABILITY_JSON="$RUN_DIR/action-reliability.json" "${PYTHON:-python3}" <<'PY' || echo "unable to render action reliability JSON"
import json
import os

path = os.environ["ACTION_RELIABILITY_JSON"]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

print(f"acceptable: {'yes' if data.get('acceptable') else 'no'}")
print("agent\tintents\tcommands\tintent_to_command\tparse\texecution\tverified\tviolations")
for agent, stats in sorted(data.get("agents", {}).items()):
    counts = stats.get("counts", {})
    metrics = stats.get("metrics", {})
    violations = len(stats.get("threshold_violations", []))
    print(
        "\t".join(
            [
                agent,
                str(counts.get("intended_action_events", 0)),
                str(counts.get("emitted_commands", 0)),
                str(metrics.get("intent_to_command_ratio", "n/a")),
                str(metrics.get("parse_success_rate", "n/a")),
                str(metrics.get("command_execution_rate", "n/a")),
                str(metrics.get("verified_success_rate", "n/a")),
                str(violations),
            ]
        )
    )

violations = data.get("threshold_violations", [])
if violations:
    print("violations:")
    for item in violations[:10]:
        print(
            f"- {item['agent']} {item['metric']}={item['observed']} "
            f"< {item['required']} (intents={item['intended_action_events']})"
        )
else:
    print("violations: none")
PY
        else
            echo "not available"
        fi
    } >> "$RUN_DIR/summary.txt"
}

run_timeline_export() {
    "${PYTHON:-python3}" "$SCRIPT_DIR/build_timeline.py" --run-dir "$RUN_DIR"
}

run_monitor_render() {
    SOAK_MONITOR_STALL_SECONDS="$SOAK_MONITOR_STALL_SECONDS" \
        SOAK_MONITOR_LLM_IDLE_SECONDS="$SOAK_MONITOR_LLM_IDLE_SECONDS" \
        "${PYTHON:-python3}" "$SCRIPT_DIR/build_monitor.py" --run-dir "$RUN_DIR"
}

append_timeline_summary() {
    {
        echo
        echo "Timeline"
        echo "timeline: $RUN_DIR/timeline.ndjson"
        echo "totals: $RUN_DIR/timeline-totals.json"
        if [ -s "$RUN_DIR/timeline-totals.json" ]; then
            TIMELINE_TOTALS_JSON="$RUN_DIR/timeline-totals.json" "${PYTHON:-python3}" <<'PY' || echo "unable to render timeline totals"
import json
import os

path = os.environ["TIMELINE_TOTALS_JSON"]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

print(f"events_total: {data.get('event_count', 0)}")
print("events_by_type:")
for key, value in sorted(data.get("counts_by_event_type", {}).items()):
    print(f"- {key}: {value}")

print("events_by_agent:")
for key, value in sorted(data.get("counts_by_agent", {}).items()):
    print(f"- {key}: {value}")

print("events_by_model:")
models = data.get("counts_by_model", {})
if models:
    for key, value in sorted(models.items()):
        print(f"- {key}: {value}")
else:
    print("- none")

tokens = data.get("token_totals", {})
print("token_totals:")
print(f"- requests: {tokens.get('requests', 0)}")
print(f"- prompt_tokens: {tokens.get('prompt_tokens', 0)}")
print(f"- completion_tokens: {tokens.get('completion_tokens', 0)}")
print(f"- total_tokens: {tokens.get('total_tokens', 0)}")
reported = tokens.get("provider_reported", {})
estimated = tokens.get("estimated", {})
print(f"- provider_reported_requests: {reported.get('requests', 0)}")
print(f"- estimated_requests: {estimated.get('requests', 0)}")
PY
        else
            echo "not available"
        fi
    } >> "$RUN_DIR/summary.txt"
}

append_monitor_summary() {
    local status="$1"
    {
        echo
        echo "Cohort monitor"
        if [ "$status" = "available" ]; then
            echo "monitor: $RUN_DIR/monitor.html"
            echo "live_server: python3 scripts/minecraft/serve_monitor.py --run-dir $RUN_DIR"
        else
            echo "monitor: not available"
            echo "live_server: python3 scripts/minecraft/serve_monitor.py --run-dir $RUN_DIR"
        fi
        echo "stall_seconds: $SOAK_MONITOR_STALL_SECONDS"
        echo "llm_idle_seconds: $SOAK_MONITOR_LLM_IDLE_SECONDS"
    } >> "$RUN_DIR/summary.txt"
}

print_plan
write_metadata

run_checked "docker services" "$RUN_DIR/preflight/check-services.txt" bash "$REPO_ROOT/scripts/check-services.sh"
run_checked "LM Studio models" "$RUN_DIR/preflight/llm-local.txt" pnpm llm:local --list-only
if [ "$SOAK_EASY_SPAWN" = "1" ]; then
    run_checked "easy spawn access files" "$RUN_DIR/preflight/easy-spawn-access.txt" \
        node "$SCRIPT_DIR/setup-easy-spawn.mjs" --write-access-only
fi
ensure_minecraft_server
run_checked "Minecraft health" "$RUN_DIR/preflight/minecraft-health.json" "$SCRIPT_DIR/health.sh" --json
if [ "$SOAK_EASY_SPAWN" = "1" ]; then
    run_checked "easy spawn terrain" "$RUN_DIR/preflight/easy-spawn-terrain.txt" \
        node "$SCRIPT_DIR/setup-easy-spawn.mjs" --terrain-only
fi
run_checked "backend health" "$RUN_DIR/preflight/backend-health.json" curl -fsS "$BACKEND_HEALTH_URL"

start_log_capture

BOT_INDEX=0
for bot in $SOAK_BOTS; do
    launch_bot "$bot" "$BOT_INDEX"
    BOT_INDEX=$((BOT_INDEX + 1))
done

if [ "$SOAK_EASY_SPAWN" = "1" ]; then
    sleep "$SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS"
    run_checked "easy spawn starter kit" "$RUN_DIR/preflight/easy-spawn-kit.txt" \
        node "$SCRIPT_DIR/setup-easy-spawn.mjs"
fi

MONITOR_STATUS=0
monitor_bots || MONITOR_STATUS=$?

SOAK_END_ISO="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
run_cost_query "$SOAK_END_ISO"
write_summary "$SOAK_END_ISO"
RELIABILITY_STATUS=0
run_action_reliability || RELIABILITY_STATUS=$?
append_action_reliability_summary "$RELIABILITY_STATUS"
run_behavior_gate "$RUN_DIR"
run_timeline_export
append_timeline_summary
if run_monitor_render; then
    append_monitor_summary "available"
else
    fail "Monitor render failed; continuing. Re-run with: python3 scripts/minecraft/build_monitor.py --run-dir $RUN_DIR"
    append_monitor_summary "unavailable"
fi

EXCEEDED="$(cat "$RUN_DIR/cost-cap-exceeded.count" 2> /dev/null || echo 1)"
BEHAVIOR_GATE_STATUS="$(cat "$RUN_DIR/behavior-gate-status.txt" 2> /dev/null || echo fail)"
if [ "$MONITOR_STATUS" -ne 0 ]; then
    fail "Soak failed: at least one bot exited before the planned end. See $EARLY_EXIT_FILE"
    exit 1
fi
if [ "$EXCEEDED" != "0" ]; then
    fail "Soak failed: at least one agent exceeded the hourly cap. See $RUN_DIR/cost-ledger.tsv"
    exit 1
fi
if [ "$SOAK_RELIABILITY_FAIL_ON_VIOLATION" = "1" ] && [ "$RELIABILITY_STATUS" -ne 0 ]; then
    fail "Soak failed: action-command reliability below threshold. See $RUN_DIR/action-reliability.md"
    exit 1
fi
if [ "$SOAK_REQUIRE_BEHAVIOR_GATE" = "1" ] && [ "$BEHAVIOR_GATE_STATUS" != "pass" ]; then
    fail "Behavioral acceptance gate failed: $(paste -sd '; ' "$RUN_DIR/behavior-unmet-thresholds.txt" 2> /dev/null || echo 'see behavior.tsv')"
    exit 1
fi
if [ "$BEHAVIOR_GATE_STATUS" != "pass" ]; then
    info "behavior gate failed but SOAK_REQUIRE_BEHAVIOR_GATE=$SOAK_REQUIRE_BEHAVIOR_GATE; document the deviation in docs/minecraft/cohort-report.md"
fi

ok "Soak completed without unrecovered bot exits, within hourly cap, with acceptable action-command reliability, and behavior_gate_status=$BEHAVIOR_GATE_STATUS"
info "evidence: $RUN_DIR"
