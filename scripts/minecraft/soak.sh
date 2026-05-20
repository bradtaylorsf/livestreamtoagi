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
#   SOAK_LOG_ROOT               Default: ./logs/soak.
#   SOAK_LAUNCH_STAGGER_SECONDS Default: 3.
#   SOAK_START_MINECRAFT_IF_DOWN Start supervise.sh when health is down.
#                               Default: 1.
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
#   SOAK_BLOCK_SLOW_SIM_ACTIONS Set to 1 to disable slow code-generation
#                               actions such as !newAction for quick sims.
#                               Default: 0.
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
SOAK_LOG_ROOT="${SOAK_LOG_ROOT:-$REPO_ROOT/logs/soak}"
SOAK_LAUNCH_STAGGER_SECONDS="${SOAK_LAUNCH_STAGGER_SECONDS:-3}"
SOAK_MAX_LOG_LINES_PER_BOT="${SOAK_MAX_LOG_LINES_PER_BOT:-200000}"
SOAK_START_MINECRAFT_IF_DOWN="${SOAK_START_MINECRAFT_IF_DOWN:-1}"
SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS="${SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS:-180}"
SOAK_INIT_MESSAGE="${SOAK_INIT_MESSAGE:-}"
SOAK_BLOCK_PRIVATE_CONVERSATIONS="${SOAK_BLOCK_PRIVATE_CONVERSATIONS:-0}"
SOAK_BLOCK_SLOW_SIM_ACTIONS="${SOAK_BLOCK_SLOW_SIM_ACTIONS:-0}"
SOAK_MINDSERVER_BASE_PORT="${SOAK_MINDSERVER_BASE_PORT:-8080}"
REQUIRED_NODE_MAJOR="20"

MODE="run"
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

    grep -q 'CHECK_MINECRAFT=1 bash scripts/check-services.sh' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document the Minecraft service gate"
        problems=1
    }
    grep -q 'pnpm llm:local --list-only' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document LM Studio validation"
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
    info "bridge:         $MINECRAFT_BRIDGE_URL"
    info "backend health: $BACKEND_HEALTH_URL"
    info "LM Studio:      $LOCAL_LLM_BASE_URL"
    info "chat model:     ${LOCAL_LLM_MODEL:-<unset>}"
    info "build model:    ${LOCAL_LLM_MODEL_BUILDING:-${LOCAL_LLM_MODEL:-<unset>}}"
    info "hourly cap:     \$${SOAK_AGENT_HOURLY_CAP_USD} per agent"
    info "auto-start MC:  $SOAK_START_MINECRAFT_IF_DOWN"
    info "MC boot wait:   ${SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS}s"
    info "MindServer:     ${SOAK_MINDSERVER_BASE_PORT}+ per bot"
    if [ "$SOAK_BLOCK_PRIVATE_CONVERSATIONS" = "1" ]; then
        info "private conv:   blocked (!startConversation/!endConversation)"
    else
        info "private conv:   allowed"
    fi
    if [ "$SOAK_BLOCK_SLOW_SIM_ACTIONS" = "1" ]; then
        info "slow actions:   blocked (!newAction)"
    else
        info "slow actions:   allowed"
    fi
    if [ -n "$SOAK_INIT_MESSAGE" ]; then
        info "init prompt:    set (${#SOAK_INIT_MESSAGE} chars)"
    else
        info "init prompt:    <none>"
    fi
    info "bots:           $SOAK_BOTS"
    info "cost agents:    $SOAK_COST_AGENTS"
    info "Mindcraft base: $MINDCRAFT_DIR"
    info "isolation:      shared local clones with node_modules symlink"
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
}

if (process.env.SOAK_BLOCK_SLOW_SIM_ACTIONS === '1') {
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [...baseBlockedActions];
    if (!blocked.includes('!newAction')) blocked.push('!newAction');
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

if [ "$MODE" = "verify" ]; then
    verify_static
    exit $?
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
mkdir -p "$RUN_DIR"/{bots,preflight,logs,worktrees}
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
        echo "start_minecraft_if_down=$SOAK_START_MINECRAFT_IF_DOWN"
        echo "minecraft_boot_timeout_seconds=$SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS"
        echo "block_private_conversations=$SOAK_BLOCK_PRIVATE_CONVERSATIONS"
        echo "block_slow_sim_actions=$SOAK_BLOCK_SLOW_SIM_ACTIONS"
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
    dest="$RUN_DIR/worktrees/mindcraft-$bot"
    git clone --shared --quiet "$MINDCRAFT_BASE_ABS" "$dest"
    git -C "$dest" checkout --quiet --detach "$MINDCRAFT_COMMIT"
    ln -s "$MINDCRAFT_BASE_ABS/node_modules" "$dest/node_modules"
    if [ -f "$MINDCRAFT_BASE_ABS/keys.json" ]; then
        ln -s "$MINDCRAFT_BASE_ABS/keys.json" "$dest/keys.json"
    fi
    printf '%s\n' "$dest"
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

stop_bots() {
    local bot pid rest
    [ -f "$PID_FILE" ] || return 0
    while IFS="$(printf '\t')" read -r bot pid rest; do
        [ -n "${pid:-}" ] || continue
        kill "$pid" 2> /dev/null || true
    done < "$PID_FILE"
    sleep 5
    while IFS="$(printf '\t')" read -r bot pid rest; do
        [ -n "${pid:-}" ] || continue
        kill -KILL "$pid" 2> /dev/null || true
    done < "$PID_FILE"
}

stop_minecraft_supervisor() {
    local pid
    [ -f "$RUN_DIR/minecraft-supervisor.pid" ] || return 0
    pid="$(cat "$RUN_DIR/minecraft-supervisor.pid" 2> /dev/null || true)"
    [ -n "$pid" ] || return 0
    kill "$pid" 2> /dev/null || true
}

cleanup() {
    local status=$?
    stop_bots
    stop_minecraft_supervisor
    stop_process_file "$TAIL_PID_FILE"
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

print_plan
write_metadata

run_checked "docker services" "$RUN_DIR/preflight/check-services.txt" bash "$REPO_ROOT/scripts/check-services.sh"
run_checked "LM Studio models" "$RUN_DIR/preflight/llm-local.txt" pnpm llm:local --list-only
ensure_minecraft_server
run_checked "Minecraft health" "$RUN_DIR/preflight/minecraft-health.json" "$SCRIPT_DIR/health.sh" --json
run_checked "backend health" "$RUN_DIR/preflight/backend-health.json" curl -fsS "$BACKEND_HEALTH_URL"

start_log_capture

BOT_INDEX=0
for bot in $SOAK_BOTS; do
    launch_bot "$bot" "$BOT_INDEX"
    BOT_INDEX=$((BOT_INDEX + 1))
done

MONITOR_STATUS=0
monitor_bots || MONITOR_STATUS=$?

SOAK_END_ISO="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
run_cost_query "$SOAK_END_ISO"
write_summary "$SOAK_END_ISO"

EXCEEDED="$(cat "$RUN_DIR/cost-cap-exceeded.count" 2> /dev/null || echo 1)"
if [ "$MONITOR_STATUS" -ne 0 ]; then
    fail "Soak failed: at least one bot exited before the planned end. See $EARLY_EXIT_FILE"
    exit 1
fi
if [ "$EXCEEDED" != "0" ]; then
    fail "Soak failed: at least one agent exceeded the hourly cap. See $RUN_DIR/cost-ledger.tsv"
    exit 1
fi

ok "Soak completed without unrecovered bot exits and within hourly cap"
info "evidence: $RUN_DIR"
