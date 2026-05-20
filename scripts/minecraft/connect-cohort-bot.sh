#!/usr/bin/env bash
# Shared launcher for E8 verbal cohort bots.
#
# This file is intentionally called through connect-vera-bot.sh or
# connect-rex-bot.sh so each agent keeps a fixed username/profile while the
# staged bridge/action/runtime-shim mechanics stay identical.
#
# Usage:
#   scripts/minecraft/connect-vera-bot.sh            # stage + launch Vera
#   scripts/minecraft/connect-vera-bot.sh --dry-run  # print resolved plan; no clone/network/launch
#   scripts/minecraft/connect-vera-bot.sh --verify   # static asset checks only (CI/network-safe)
#   scripts/minecraft/connect-vera-bot.sh --help
#
# Configuration (environment variables):
#   MINECRAFT_BRIDGE_TOKEN  Shared bearer secret (REQUIRED for a real run; must
#                           match the server's MINECRAFT_BRIDGE_TOKEN).
#   MINECRAFT_BRIDGE_URL    Bridge WebSocket URL
#                           (default: ws://127.0.0.1:8010/api/minecraft/bridge/ws)
#   MINDCRAFT_DIR           Where the pinned clone lives  (default: ./mindcraft)
#   MC_HOST                 E2 server host                (default: 127.0.0.1)
#   MC_PORT                 E2 server port                (default: 25565)
#   MINDCRAFT_PROFILE       Profile path inside the clone
#                           (default: ./profiles/<agent>-bot.json)
#   LOCAL_LLM_BASE_URL      LM Studio URL for operator pre-flight checks
#                           (default: http://localhost:1234/v1)
#   LOCAL_LLM_MODEL         LM Studio model id for the conversation tier (REQUIRED for a real run)
#   LOCAL_LLM_MODEL_BUILDING  LM Studio model id for the building/code tier (default: = LOCAL_LLM_MODEL)
#
# A real run requires the E2 server running, the pinned fork installed, LM
# Studio reachable, and the FastAPI bridge endpoint up with a matching bearer
# token. With the E2 default white-list=true you must whitelist the fixed bot
# username printed by the script.
set -euo pipefail

: "${COHORT_BOT_ID:?COHORT_BOT_ID is required; use connect-vera-bot.sh or connect-rex-bot.sh}"
: "${COHORT_BOT_NAME:?COHORT_BOT_NAME is required; use connect-vera-bot.sh or connect-rex-bot.sh}"
: "${COHORT_SETTINGS_TEMPLATE:?COHORT_SETTINGS_TEMPLATE is required}"
: "${COHORT_PROFILE_TEMPLATE:?COHORT_PROFILE_TEMPLATE is required}"
: "${COHORT_PROFILE_DEFAULT:?COHORT_PROFILE_DEFAULT is required}"

LAUNCH_NAME="${COHORT_LAUNCH_NAME:-connect-cohort-bot.sh}"
MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
REQUIRED_NODE_MAJOR="20"
MC_VERSION="1.21.6"
MC_HOST="${MC_HOST:-127.0.0.1}"
MC_PORT="${MC_PORT:-25565}"
MC_AUTH="offline"
MINDCRAFT_PROFILE="${MINDCRAFT_PROFILE:-$COHORT_PROFILE_DEFAULT}"
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
MINDCRAFT_LLM_URL="http://localhost:1234/v1"

MINECRAFT_BRIDGE_URL="${MINECRAFT_BRIDGE_URL:-ws://127.0.0.1:8010/api/minecraft/bridge/ws}"

MCDATA_REL="src/utils/mcdata.js"
MCDATA_VERSION_PATCH_MARKER="LTAG E3-2 runtime version refresh"
ACTIONS_REL="src/agent/commands/actions.js"
ACTIONS_PATCH_MARKER="LTAG E4-4 bridge ping action"
ACTIONS_MOVE_PATCH_MARKER="LTAG E6-2 move action"
ACTIONS_NAVIGATE_PATCH_MARKER="LTAG E6-2 navigate action"
ACTIONS_PLACE_PATCH_MARKER="LTAG E6-3 place action"
ACTIONS_BREAK_PATCH_MARKER="LTAG E6-3 break action"
ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER="LTAG E6-4 build-from-plan action"
ACTIONS_EXECUTE_CODE_PATCH_MARKER="LTAG E6-5 execute-code action"
ACTIONS_OBSERVE_PATCH_MARKER="LTAG E6-6 observe action"
AGENT_MANAGEMENT_PATCH_MARKER="LTAG E8-7 management chat gate"

AGENT_REL="src/agent/agent.js"
BRIDGE_CLIENT_REL="src/agent/bridge/python_bridge.js"
MANAGEMENT_REVIEW_REL="src/agent/bridge/management_review.js"
BRIDGE_ACTION_REL="src/agent/commands/bridge_ping_action.js"
MOVE_ACTION_REL="src/agent/commands/move_action.js"
NAVIGATE_ACTION_REL="src/agent/commands/navigate_action.js"
PLACE_ACTION_REL="src/agent/commands/place_action.js"
BREAK_ACTION_REL="src/agent/commands/break_action.js"
BUILD_FROM_PLAN_ACTION_REL="src/agent/commands/build_from_plan_action.js"
EXECUTE_CODE_ACTION_REL="src/agent/commands/execute_code_action.js"
OBSERVE_ACTION_REL="src/agent/commands/observe_action.js"
MOVEMENT_SKILL_REL="src/agent/skills/movement.js"
BUILDING_SKILL_REL="src/agent/skills/building.js"
BUILD_PLAN_SKILL_REL="src/agent/skills/build_plan.js"
PERCEPTION_SKILL_REL="src/agent/skills/perception.js"
SAFE_FAIL_SKILL_REL="src/agent/skills/safe_fail.js"

MINDCRAFT_DIR_ABS=""
MCDATA_BACKUP=""
MCDATA_PATH=""
ACTIONS_BACKUP=""
ACTIONS_PATH=""
AGENT_BACKUP=""
AGENT_PATH=""
STAGED_DESTS=()

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FORK_SRC_DIR="$SCRIPT_DIR/fork-src"
BRIDGE_CLIENT_SRC="$FORK_SRC_DIR/agent/bridge/python_bridge.js"
MANAGEMENT_REVIEW_SRC="$FORK_SRC_DIR/agent/bridge/management_review.js"
BRIDGE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/bridge_ping_action.js"
MOVE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/move_action.js"
NAVIGATE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/navigate_action.js"
PLACE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/place_action.js"
BREAK_ACTION_SRC="$FORK_SRC_DIR/agent/commands/break_action.js"
BUILD_FROM_PLAN_ACTION_SRC="$FORK_SRC_DIR/agent/commands/build_from_plan_action.js"
EXECUTE_CODE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/execute_code_action.js"
OBSERVE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/observe_action.js"
MOVEMENT_SKILL_SRC="$FORK_SRC_DIR/agent/skills/movement.js"
BUILDING_SKILL_SRC="$FORK_SRC_DIR/agent/skills/building.js"
BUILD_PLAN_SKILL_SRC="$FORK_SRC_DIR/agent/skills/build_plan.js"
PERCEPTION_SKILL_SRC="$FORK_SRC_DIR/agent/skills/perception.js"
SAFE_FAIL_SKILL_SRC="$FORK_SRC_DIR/agent/skills/safe_fail.js"

print_help() {
    cat <<EOF
Launch ${COHORT_BOT_NAME} as a verbal Mindcraft bot wired to the Python bridge.

Usage:
  scripts/minecraft/${LAUNCH_NAME}            # stage + launch ${COHORT_BOT_NAME}
  scripts/minecraft/${LAUNCH_NAME} --dry-run  # print resolved plan; no clone/network/launch
  scripts/minecraft/${LAUNCH_NAME} --verify   # static asset checks only (CI/network-safe)
  scripts/minecraft/${LAUNCH_NAME} --help

Configuration:
  MINECRAFT_BRIDGE_TOKEN    Shared bearer secret for the FastAPI bridge.
  MINECRAFT_BRIDGE_URL      Bridge WebSocket URL.
  MINDCRAFT_DIR             Pinned Mindcraft clone (default: ./mindcraft).
  MC_HOST / MC_PORT         E2 server target (defaults: 127.0.0.1 / 25565).
  MINDCRAFT_PROFILE         Profile path inside the clone (default: ${COHORT_PROFILE_DEFAULT}).
  LOCAL_LLM_MODEL           LM Studio chat-tier model id.
  LOCAL_LLM_MODEL_BUILDING  LM Studio building/code-tier model id.
EOF
}

MODE="run"
case "${1:-}" in
    --dry-run) MODE="dry-run" ;;
    --verify)  MODE="verify" ;;
    --help|-h)
        print_help
        exit 0
        ;;
    "") ;;
    *)
        echo "x Unknown argument: $1 (try --help)" >&2
        exit 2
        ;;
esac

ok()   { echo "ok $*"; }
info() { echo "  $*"; }
fail() { echo "x $*" >&2; }

restore_clone_patches() {
    if [ -n "${MCDATA_BACKUP:-}" ] && [ -f "$MCDATA_BACKUP" ] && [ -n "${MCDATA_PATH:-}" ]; then
        cp "$MCDATA_BACKUP" "$MCDATA_PATH" 2> /dev/null || true
        rm -f "$MCDATA_BACKUP"
    fi
    if [ -n "${ACTIONS_BACKUP:-}" ] && [ -f "$ACTIONS_BACKUP" ] && [ -n "${ACTIONS_PATH:-}" ]; then
        cp "$ACTIONS_BACKUP" "$ACTIONS_PATH" 2> /dev/null || true
        rm -f "$ACTIONS_BACKUP"
    fi
    if [ -n "${AGENT_BACKUP:-}" ] && [ -f "$AGENT_BACKUP" ] && [ -n "${AGENT_PATH:-}" ]; then
        cp "$AGENT_BACKUP" "$AGENT_PATH" 2> /dev/null || true
        rm -f "$AGENT_BACKUP"
    fi
    local staged
    for staged in "${STAGED_DESTS[@]:-}"; do
        [ -n "$staged" ] && rm -f "$staged" 2> /dev/null || true
    done
}

node_major() {
    command -v node > /dev/null 2>&1 || return 1
    local out major
    out="$(node -v 2>&1)" || return 1
    major="$(printf '%s\n' "$out" | sed -nE 's/^v?([0-9]+).*/\1/p')"
    [ -n "$major" ] || return 1
    printf '%s\n' "$major"
}

check_node() {
    local node_m
    node_m="$(node_major || true)"
    if [ -z "${node_m:-}" ]; then
        fail "Node.js not found on PATH. Install Node ${REQUIRED_NODE_MAJOR} LTS."
        return 1
    fi
    if [ "$node_m" != "$REQUIRED_NODE_MAJOR" ]; then
        fail "Node ${node_m} found, but the pinned Mindcraft needs Node ${REQUIRED_NODE_MAJOR} LTS."
        return 1
    fi
    if ! command -v npm > /dev/null 2>&1; then
        fail "npm not found on PATH (it ships with Node ${REQUIRED_NODE_MAJOR})."
        return 1
    fi
    ok "Node ${node_m} + npm $(npm -v) detected (need Node ${REQUIRED_NODE_MAJOR})"
}

verify_committed_assets() {
    local problems=0

    if [ ! -s "$COHORT_SETTINGS_TEMPLATE" ]; then
        fail "${COHORT_BOT_NAME} settings template missing or empty: $COHORT_SETTINGS_TEMPLATE"; problems=1
    else
        grep -q '"host": "127.0.0.1"' "$COHORT_SETTINGS_TEMPLATE" || { fail "template host is not 127.0.0.1"; problems=1; }
        grep -q '"port": 25565' "$COHORT_SETTINGS_TEMPLATE" || { fail "template port is not 25565"; problems=1; }
        grep -q '"auth": "offline"' "$COHORT_SETTINGS_TEMPLATE" || { fail "template auth is not offline"; problems=1; }
        grep -q '"minecraft_version": "1.21.6"' "$COHORT_SETTINGS_TEMPLATE" || { fail "template minecraft_version is not 1.21.6"; problems=1; }
        grep -q "\"./profiles/${COHORT_BOT_ID}-bot.json\"" "$COHORT_SETTINGS_TEMPLATE" || { fail "template does not select ${COHORT_BOT_ID}-bot"; problems=1; }
        grep -q '"auto_open_ui": false' "$COHORT_SETTINGS_TEMPLATE" || { fail "auto_open_ui is not false"; problems=1; }
        grep -q '"chat_ingame": true,' "$COHORT_SETTINGS_TEMPLATE" || { fail "chat_ingame is not true"; problems=1; }
        grep -q '"narrate_behavior": true,' "$COHORT_SETTINGS_TEMPLATE" || { fail "narrate_behavior is not true"; problems=1; }
        grep -q '"chat_bot_messages": true,' "$COHORT_SETTINGS_TEMPLATE" || { fail "chat_bot_messages is not true"; problems=1; }
        grep -q '"init_message": ""' "$COHORT_SETTINGS_TEMPLATE" || { fail "init_message is not empty"; problems=1; }
        grep -q '"speak": false,' "$COHORT_SETTINGS_TEMPLATE" || { fail "speak is not false"; problems=1; }
        grep -q '"only_chat_with": \[\]' "$COHORT_SETTINGS_TEMPLATE" || { fail "only_chat_with is not []"; problems=1; }
    fi

    if [ ! -s "$COHORT_PROFILE_TEMPLATE" ]; then
        fail "${COHORT_BOT_NAME} profile missing or empty: $COHORT_PROFILE_TEMPLATE"; problems=1
    else
        grep -q "\"name\": \"${COHORT_BOT_NAME}\"" "$COHORT_PROFILE_TEMPLATE" || { fail "profile name is not ${COHORT_BOT_NAME}"; problems=1; }
        grep -q '"model": "lmstudio/__LOCAL_LLM_MODEL__"' "$COHORT_PROFILE_TEMPLATE" || { fail "profile model placeholder drifted"; problems=1; }
        grep -q '"code_model": "lmstudio/__LOCAL_LLM_MODEL_BUILDING__"' "$COHORT_PROFILE_TEMPLATE" || { fail "profile code_model placeholder drifted"; problems=1; }
        if grep -q 'openrouter' "$COHORT_PROFILE_TEMPLATE"; then
            fail "profile must be local-only"; problems=1
        fi
    fi

    for required in \
        "$BRIDGE_CLIENT_SRC" "$MANAGEMENT_REVIEW_SRC" "$BRIDGE_ACTION_SRC" \
        "$MOVE_ACTION_SRC" "$NAVIGATE_ACTION_SRC" \
        "$PLACE_ACTION_SRC" "$BREAK_ACTION_SRC" "$BUILD_FROM_PLAN_ACTION_SRC" \
        "$EXECUTE_CODE_ACTION_SRC" "$OBSERVE_ACTION_SRC" \
        "$MOVEMENT_SKILL_SRC" "$BUILDING_SKILL_SRC" "$BUILD_PLAN_SKILL_SRC" \
        "$PERCEPTION_SKILL_SRC" "$SAFE_FAIL_SKILL_SRC"
    do
        if [ ! -s "$required" ]; then
            fail "Committed bridge asset missing or empty: $required"; problems=1
        fi
    done

    return $problems
}

ok "${COHORT_BOT_NAME} Mindcraft bot -> E2 server + Python bridge"
info "bot name:  $COHORT_BOT_NAME  (fixed; whitelist this exact name)"
info "agent id:  $COHORT_BOT_ID"
info "server:    ${MC_HOST}:${MC_PORT}  auth=${MC_AUTH}  minecraft=${MC_VERSION}"
info "bridge:    ${MINECRAFT_BRIDGE_URL}  (bearer token via MINECRAFT_BRIDGE_TOKEN)"
info "clone:     $MINDCRAFT_DIR  (pinned $MINDCRAFT_COMMIT)"
info "profile:   $MINDCRAFT_PROFILE  (staged from $COHORT_PROFILE_TEMPLATE)"
info "settings:  verbal cohort template (chat_ingame=true, narrate_behavior=true,"
info "           chat_bot_messages=true, init_message empty, speak=false)"
info "LM Studio: bot connects to ${MINDCRAFT_LLM_URL}  (local only, decision 0003)"

if [ "$MODE" = "verify" ]; then
    if verify_committed_assets; then
        ok "Static verify passed: ${COHORT_BOT_NAME} profile is lmstudio-local, settings target"
        info "E2 ${MC_HOST}:${MC_PORT} auth=${MC_AUTH} minecraft=${MC_VERSION},"
        info "profiles=[${COHORT_PROFILE_DEFAULT}], chat_ingame=true,"
        info "narrate_behavior=true, chat_bot_messages=true, init_message='',"
        info "speak=false, only_chat_with=[], and bridge action assets are present."
        info "Action smoke: ${COHORT_BOT_NAME} !observe(6, \"all\", false)"
        info "Action smoke: ${COHORT_BOT_NAME} !place(\"stone\", {\"x\":0,\"y\":64,\"z\":1}, \"up\")"
        info "(No clone, no network, no Node, no launch - drop --verify to connect.)"
        exit 0
    fi
    fail "Static verify FAILED - see messages above."
    exit 1
fi

LLM_MODEL="${LOCAL_LLM_MODEL:-}"
LLM_MODEL_BUILDING="${LOCAL_LLM_MODEL_BUILDING:-$LLM_MODEL}"

if [ "$MODE" = "dry-run" ]; then
    check_node || true
    verify_committed_assets || true
    echo
    ok "Dry run complete - no clone, no network, nothing launched."
    info "host:        $MC_HOST"
    info "port:        $MC_PORT"
    info "auth:        $MC_AUTH"
    info "minecraft:   $MC_VERSION"
    info "bridge url:  $MINECRAFT_BRIDGE_URL"
    if [ -n "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
        info "bridge token: set (value hidden)"
    else
        info "bridge token: (MINECRAFT_BRIDGE_TOKEN unset - REQUIRED for a real run)"
    fi
    info "profile:     $MINDCRAFT_PROFILE  (bot name $COHORT_BOT_NAME)"
    if [ -n "$LLM_MODEL" ]; then
        info "model:       lmstudio/$LLM_MODEL  (conversation tier)"
        info "code_model:  lmstudio/$LLM_MODEL_BUILDING  (building tier)"
    else
        info "model:       (LOCAL_LLM_MODEL unset - REQUIRED for a real run;"
        info "             list ids with: pnpm llm:local --list-only)"
    fi
    info "verbal:      chat_ingame=true, narrate_behavior=true,"
    info "             chat_bot_messages=true, init_message='', speak=false,"
    info "             only_chat_with=[]"
    info "Would assert: $MINDCRAFT_DIR HEAD == $MINDCRAFT_COMMIT"
    info "Would stage:  $COHORT_SETTINGS_TEMPLATE -> $MINDCRAFT_DIR/settings.js"
    info "Would stage:  $COHORT_PROFILE_TEMPLATE  -> $MINDCRAFT_DIR/${MINDCRAFT_PROFILE#./}"
    info "Would copy:   fork-src/ bridge client, action handlers, and helper skills"
    info "Would patch:  inject bridge/action commands into $MINDCRAFT_DIR/$ACTIONS_REL"
    info "Would stage:  runtime-version shim in $MINDCRAFT_DIR/$MCDATA_REL"
    info "Would launch: (cd $MINDCRAFT_DIR && node main.js --profiles $MINDCRAFT_PROFILE)"
    exit 0
fi

verify_committed_assets || { fail "Refusing to launch with bad committed assets."; exit 1; }
check_node || exit 1
command -v git > /dev/null 2>&1 || { fail "git not found on PATH."; exit 1; }

if [ -z "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
    fail "MINECRAFT_BRIDGE_TOKEN is not set - the bridge has NO unauthenticated path."
    info "  Export the SAME shared secret the FastAPI bridge server uses:"
    info "    export MINECRAFT_BRIDGE_TOKEN=<the-server-secret>"
    exit 1
fi

if [ -z "$LLM_MODEL" ]; then
    fail "LOCAL_LLM_MODEL is not set - ${COHORT_BOT_NAME} needs a local LM Studio model id."
    info "  List the models LM Studio is serving, then export one:"
    info "    pnpm llm:local --list-only"
    info "    export LOCAL_LLM_MODEL=<model-id-from-the-list>"
    exit 1
fi

if [ ! -d "$MINDCRAFT_DIR/.git" ]; then
    fail "No Mindcraft clone at $MINDCRAFT_DIR."
    info "  Install the pinned fork first:  scripts/minecraft/setup-mindcraft.sh"
    exit 1
fi
HEAD_SHA="$(git -C "$MINDCRAFT_DIR" rev-parse HEAD 2>/dev/null || true)"
if [ "$HEAD_SHA" != "$MINDCRAFT_COMMIT" ]; then
    fail "Clone is not at the pinned commit - refusing to launch an unpinned tree."
    info "  HEAD is     ${HEAD_SHA:-<unknown>}"
    info "  expected    $MINDCRAFT_COMMIT"
    info "  Re-pin with: scripts/minecraft/setup-mindcraft.sh"
    exit 1
fi
ok "Clone is at the pinned commit $MINDCRAFT_COMMIT"
MINDCRAFT_DIR_ABS="$(cd -- "$MINDCRAFT_DIR" && pwd)"

DEST_SETTINGS="$MINDCRAFT_DIR_ABS/settings.js"
if ! sed -E \
    -e "s|^([[:space:]]*\"host\":[[:space:]]*\")[^\"]*(\".*)$|\1${MC_HOST}\2|" \
    -e "s|^([[:space:]]*\"port\":[[:space:]]*)[0-9]+(,.*)$|\1${MC_PORT}\2|" \
    -e "s|\"\\./profiles/${COHORT_BOT_ID}-bot\\.json\"|\"${MINDCRAFT_PROFILE}\"|" \
    "$COHORT_SETTINGS_TEMPLATE" > "$DEST_SETTINGS"; then
    fail "Failed to stage settings.js -> $DEST_SETTINGS"
    exit 1
fi
ok "Staged settings.js -> $DEST_SETTINGS (host=${MC_HOST} port=${MC_PORT} profile=${MINDCRAFT_PROFILE})"

DEST_PROFILE="$MINDCRAFT_DIR_ABS/${MINDCRAFT_PROFILE#./}"
mkdir -p "$(dirname -- "$DEST_PROFILE")"
if ! TEMPLATE_PATH="$COHORT_PROFILE_TEMPLATE" DEST_PATH="$DEST_PROFILE" CHAT_MODEL="$LLM_MODEL" CODE_MODEL="$LLM_MODEL_BUILDING" BOT_NAME="$COHORT_BOT_NAME" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const templatePath = process.env.TEMPLATE_PATH;
const destPath = process.env.DEST_PATH;
const chatModel = process.env.CHAT_MODEL;
const codeModel = process.env.CODE_MODEL;
const botName = process.env.BOT_NAME;
const profile = JSON.parse(readFileSync(templatePath, 'utf8'));

if (
    profile.name !== botName ||
    profile.model !== 'lmstudio/__LOCAL_LLM_MODEL__' ||
    profile.code_model !== 'lmstudio/__LOCAL_LLM_MODEL_BUILDING__'
) {
    throw new Error(`${botName} profile template lost its local model placeholders`);
}

profile.model = `lmstudio/${chatModel}`;
profile.code_model = `lmstudio/${codeModel}`;
writeFileSync(destPath, `${JSON.stringify(profile, null, 4)}\n`);
NODE
then
    fail "Failed to stage profile -> $DEST_PROFILE"
    exit 1
fi
ok "Staged profile -> $DEST_PROFILE"
info "  model:      lmstudio/${LLM_MODEL}"
info "  code_model: lmstudio/${LLM_MODEL_BUILDING}"

stage_file() {
    local src="$1"
    local rel="$2"
    local dest="$MINDCRAFT_DIR_ABS/$rel"
    mkdir -p "$(dirname -- "$dest")"
    cp "$src" "$dest"
    STAGED_DESTS+=("$dest")
}

trap restore_clone_patches EXIT
trap 'restore_clone_patches; exit 130' INT
trap 'restore_clone_patches; exit 143' TERM

stage_file "$BRIDGE_CLIENT_SRC" "$BRIDGE_CLIENT_REL"
stage_file "$MANAGEMENT_REVIEW_SRC" "$MANAGEMENT_REVIEW_REL"
stage_file "$BRIDGE_ACTION_SRC" "$BRIDGE_ACTION_REL"
stage_file "$MOVE_ACTION_SRC" "$MOVE_ACTION_REL"
stage_file "$NAVIGATE_ACTION_SRC" "$NAVIGATE_ACTION_REL"
stage_file "$PLACE_ACTION_SRC" "$PLACE_ACTION_REL"
stage_file "$BREAK_ACTION_SRC" "$BREAK_ACTION_REL"
stage_file "$BUILD_FROM_PLAN_ACTION_SRC" "$BUILD_FROM_PLAN_ACTION_REL"
stage_file "$EXECUTE_CODE_ACTION_SRC" "$EXECUTE_CODE_ACTION_REL"
stage_file "$OBSERVE_ACTION_SRC" "$OBSERVE_ACTION_REL"
stage_file "$MOVEMENT_SKILL_SRC" "$MOVEMENT_SKILL_REL"
stage_file "$BUILDING_SKILL_SRC" "$BUILDING_SKILL_REL"
stage_file "$BUILD_PLAN_SKILL_SRC" "$BUILD_PLAN_SKILL_REL"
stage_file "$PERCEPTION_SKILL_SRC" "$PERCEPTION_SKILL_REL"
stage_file "$SAFE_FAIL_SKILL_SRC" "$SAFE_FAIL_SKILL_REL"
ok "Copied bridge client, action handlers, and helper skills from fork-src"

AGENT_PATH="$MINDCRAFT_DIR_ABS/$AGENT_REL"
if [ ! -f "$AGENT_PATH" ]; then
    fail "Mindcraft source file missing: $AGENT_PATH"
    exit 1
fi
if grep -q "$AGENT_MANAGEMENT_PATCH_MARKER" "$AGENT_PATH"; then
    info "Found a previous Management chat gate in $AGENT_REL; restoring pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$AGENT_REL" > "$AGENT_PATH"; then
        fail "Could not restore pinned $AGENT_REL before patching."
        exit 1
    fi
fi
AGENT_BACKUP="$(mktemp -t mindcraft-agent.XXXXXX)"
cp "$AGENT_PATH" "$AGENT_BACKUP"
if ! AGENT_PATH="$AGENT_PATH" \
    AGENT_MANAGEMENT_PATCH_MARKER="$AGENT_MANAGEMENT_PATCH_MARKER" \
    node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.AGENT_PATH;
const marker = process.env.AGENT_MANAGEMENT_PATCH_MARKER;
let source = readFileSync(path, 'utf8');

const importAnchor = "import { speak } from './speak.js';\n";
const importLine = `import { reviewChat } from './bridge/management_review.js'; // ${marker}\n`;
if (!source.includes(importLine)) {
    if (!source.includes(importAnchor)) {
        throw new Error('speak import anchor not found while applying Management chat gate');
    }
    source = source.replace(importAnchor, importAnchor + importLine);
}

let methodStart = source.indexOf('    async openChat(message) {');
if (methodStart === -1) methodStart = source.indexOf('        async openChat(message) {');
let methodEnd = source.indexOf('\n    startEvents() {', methodStart);
if (methodEnd === -1) methodEnd = source.indexOf('\n        startEvents() {', methodStart);
if (methodStart === -1 || methodEnd === -1) {
    throw new Error('openChat method shape changed while applying Management chat gate');
}

const replacement = `    async openChat(message) { // ${marker}
        let to_translate = message;
        let remaining = '';
        let command_name = containsCommand(message);
        let translate_up_to = command_name ? message.indexOf(command_name) : -1;
        if (translate_up_to != -1) { // don't translate the command
            to_translate = to_translate.substring(0, translate_up_to);
            remaining = message.substring(translate_up_to);
        }
        message = (await handleTranslation(to_translate)).trim() + " " + remaining;
        // newlines are interpreted as separate chats, which triggers spam filters. replace them with spaces
        message = message.replaceAll('\\n', ' ');

        const review = await reviewChat({ agentId: this.name, text: message });
        if (!review.allow) return;
        if (review.sanitized) {
            message = review.sanitized.replaceAll('\\n', ' ');
            to_translate = review.sanitized;
        }

        if (settings.only_chat_with.length > 0) {
            for (let username of settings.only_chat_with) {
                this.bot.whisper(username, message);
            }
        }
        else {
            if (settings.speak) {
                speak(to_translate, this.prompter.profile.speak_model);
            }
            if (settings.chat_ingame) {this.bot.chat(message);}
            sendOutputToServer(this.name, message);
        }
    }
`;
source = source.slice(0, methodStart) + replacement + source.slice(methodEnd);
writeFileSync(path, source);
NODE
then
    fail "Failed to apply Management chat gate to $AGENT_REL"
    exit 1
fi
ok "Applied Management chat gate to $AGENT_REL"

ACTIONS_PATH="$MINDCRAFT_DIR_ABS/$ACTIONS_REL"
if [ ! -f "$ACTIONS_PATH" ]; then
    fail "Mindcraft source file missing: $ACTIONS_PATH"
    exit 1
fi
if grep -q "$ACTIONS_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_MOVE_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_NAVIGATE_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_PLACE_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_BREAK_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_EXECUTE_CODE_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_OBSERVE_PATCH_MARKER" "$ACTIONS_PATH"; then
    info "Found a previous bridge-action patch in $ACTIONS_REL; restoring pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$ACTIONS_REL" > "$ACTIONS_PATH"; then
        fail "Could not restore pinned $ACTIONS_REL before patching."
        exit 1
    fi
fi
ACTIONS_BACKUP="$(mktemp -t mindcraft-actions.XXXXXX)"
cp "$ACTIONS_PATH" "$ACTIONS_BACKUP"
if ! ACTIONS_PATH="$ACTIONS_PATH" \
    ACTIONS_PATCH_MARKER="$ACTIONS_PATCH_MARKER" \
    ACTIONS_MOVE_PATCH_MARKER="$ACTIONS_MOVE_PATCH_MARKER" \
    ACTIONS_NAVIGATE_PATCH_MARKER="$ACTIONS_NAVIGATE_PATCH_MARKER" \
    ACTIONS_PLACE_PATCH_MARKER="$ACTIONS_PLACE_PATCH_MARKER" \
    ACTIONS_BREAK_PATCH_MARKER="$ACTIONS_BREAK_PATCH_MARKER" \
    ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER="$ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER" \
    ACTIONS_EXECUTE_CODE_PATCH_MARKER="$ACTIONS_EXECUTE_CODE_PATCH_MARKER" \
    ACTIONS_OBSERVE_PATCH_MARKER="$ACTIONS_OBSERVE_PATCH_MARKER" \
    node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.ACTIONS_PATH;
let source = readFileSync(path, 'utf8');
const anchor = 'export const actionsList = [';
if (!source.includes(anchor)) {
    throw new Error('actionsList anchor not found');
}

const actions = [
    ['bridgePingAction', './bridge_ping_action.js', process.env.ACTIONS_PATCH_MARKER],
    ['moveAction', './move_action.js', process.env.ACTIONS_MOVE_PATCH_MARKER],
    ['navigateAction', './navigate_action.js', process.env.ACTIONS_NAVIGATE_PATCH_MARKER],
    ['placeAction', './place_action.js', process.env.ACTIONS_PLACE_PATCH_MARKER],
    ['breakAction', './break_action.js', process.env.ACTIONS_BREAK_PATCH_MARKER],
    ['buildFromPlanAction', './build_from_plan_action.js', process.env.ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER],
    ['executeCodeAction', './execute_code_action.js', process.env.ACTIONS_EXECUTE_CODE_PATCH_MARKER],
    ['observeAction', './observe_action.js', process.env.ACTIONS_OBSERVE_PATCH_MARKER],
];
const missing = actions.filter(([, , marker]) => !source.includes(marker));
if (missing.length > 0) {
    source = missing
        .map(([name, modulePath, marker]) => `import { ${name} } from '${modulePath}'; // ${marker}\n`)
        .join('') + source;
    source = source.replace(
        anchor,
        `${anchor}\n${missing.map(([name, , marker]) => `    ${name}, // ${marker}`).join('\n')}`
    );
    writeFileSync(path, source);
}
NODE
then
    fail "Failed to inject bridge action commands into $ACTIONS_REL"
    exit 1
fi
ok "Injected bridge action commands into $ACTIONS_REL"

MCDATA_PATH="$MINDCRAFT_DIR_ABS/$MCDATA_REL"
if [ ! -f "$MCDATA_PATH" ]; then
    fail "Mindcraft source file missing: $MCDATA_PATH"
    exit 1
fi
if grep -q "$MCDATA_VERSION_PATCH_MARKER" "$MCDATA_PATH"; then
    info "Found a previous runtime-version shim in $MCDATA_REL; restoring pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$MCDATA_REL" > "$MCDATA_PATH"; then
        fail "Could not restore pinned $MCDATA_REL before applying runtime-version shim."
        exit 1
    fi
fi
if ! grep -q 'let mc_version = settings.minecraft_version;' "$MCDATA_PATH"; then
    fail "Mindcraft source shape changed; cannot apply runtime-version shim."
    exit 1
fi
MCDATA_BACKUP="$(mktemp -t mindcraft-mcdata.XXXXXX)"
cp "$MCDATA_PATH" "$MCDATA_BACKUP"
MCDATA_PATH="$MCDATA_PATH" MCDATA_VERSION_PATCH_MARKER="$MCDATA_VERSION_PATCH_MARKER" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.MCDATA_PATH;
const marker = process.env.MCDATA_VERSION_PATCH_MARKER;
let source = readFileSync(path, 'utf8');

source = source.replace(
    'let mc_version = settings.minecraft_version;',
    `let mc_version = null; // ${marker}: settings arrive after module import`
);
const initNeedle = 'export function initBot(username) {\n';
const initPatch = `export function initBot(username) {\n    mc_version = settings.minecraft_version; // ${marker}\n`;
if (!source.includes(initPatch)) {
    if (!source.includes(initNeedle)) {
        throw new Error('initBot signature not found while applying runtime-version shim');
    }
    source = source.replace(initNeedle, initPatch);
}
writeFileSync(path, source);
NODE
ok "Staged Mindcraft runtime-version shim -> $MCDATA_PATH"

echo
info "-- Whitelist (E2 server defaults to white-list=true) --"
info "In the E2 server console, run exactly:"
info "    whitelist add ${COHORT_BOT_NAME}"
info "Skipping this -> ${COHORT_BOT_NAME} connects then is kicked with 'not whitelisted'."
echo

export LTAG_AGENT_ID="$COHORT_BOT_ID"

ok "Launching ${COHORT_BOT_NAME} -> ${MC_HOST}:${MC_PORT} ... (Ctrl+C to stop)"
info "${COHORT_BOT_NAME} is verbal: chat_ingame=true, narrate_behavior=true, chat_bot_messages=true."
info "Action smoke: ${COHORT_BOT_NAME} !observe(6, \"all\", false)"
info "Action smoke: ${COHORT_BOT_NAME} !place(\"stone\", {\"x\":0,\"y\":64,\"z\":1}, \"up\")"
cd "$MINDCRAFT_DIR_ABS"
node main.js --profiles "$MINDCRAFT_PROFILE"
