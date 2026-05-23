#!/usr/bin/env bash
# Launch ONE Mindcraft bot wired to the Python bridge (E4-4 / #543 spike).
#
# This is the committed launch script referenced by
# docs/minecraft/mindcraft-bridge-client.md. It proves decision 0005's bridge
# extension point end-to-end: a Node bot opens an authenticated WebSocket to the
# E4-3 FastAPI bridge endpoint and the in-game `!bridgePing("hi")` action
# round-trips a contract envelope and logs the Python `pong`.
#
# `./mindcraft` is git-ignored, so the committed artifacts are the settings
# template, the local-only bridge profile, and the bridge client + action under
# scripts/minecraft/fork-src/. This script STAGES them into the clone — exactly
# the copy-in pattern connect-stock-bot.sh uses for settings.js / the mcdata
# shim. The pinned tree is restored on exit (the bridge files removed, the
# patched actions.js + mcdata.js reverted) so the clone stays clean.
#
# Pinned defaults come from the E1 decisions:
#   - Fork commit: 35be480b4cc0bca990278e6103a1426392559d96  (E1-R1 → docs/decisions/0001)
#   - Node:        20 LTS                                     (E1-R1 → docs/decisions/0001)
#   - Minecraft:   1.21.6                                     (E1-R1 → docs/decisions/0001)
#   - host/port:   127.0.0.1 : 25565  (E2 start-server.sh default; localhost only)
#   - auth:        offline   (E1-R2 → docs/decisions/0002 — matches online-mode=false)
#   - bridge:      ws://127.0.0.1:8010/api/minecraft/bridge/ws  (decision 0010 §1)
# Models are LOCAL ONLY (LM Studio, decision 0003): zero external spend. No
# openrouter/... here. The bridge bearer token is NEVER committed.
#
# Usage:
#   scripts/minecraft/connect-bridge-bot.sh            # stage + launch the bridge bot
#   scripts/minecraft/connect-bridge-bot.sh --dry-run  # print resolved plan; no clone/network/launch
#   scripts/minecraft/connect-bridge-bot.sh --verify   # static asset checks only (CI/network-safe)
#   scripts/minecraft/connect-bridge-bot.sh --help
#
# Configuration (environment variables):
#   MINECRAFT_BRIDGE_TOKEN  Shared bearer secret (REQUIRED for a real run; must
#                           match the server's MINECRAFT_BRIDGE_TOKEN). Never
#                           printed, never committed.
#   MINECRAFT_BRIDGE_URL    Bridge WebSocket URL
#                           (default: ws://127.0.0.1:8010/api/minecraft/bridge/ws)
#   MINDCRAFT_DIR           Where the pinned clone lives  (default: ./mindcraft)
#   MC_HOST                 E2 server host                (default: 127.0.0.1)
#   MC_PORT                 E2 server port                (default: 25565)
#   MINDCRAFT_PROFILE       Profile path inside the clone (default: ./profiles/bridge-bot.json)
#   LOCAL_LLM_BASE_URL      OpenAI-compatible local endpoint for the bot and
#                           pre-flight reachability checks.
#                           (default: http://localhost:1234/v1)
#   LOCAL_LLM_MODEL         LM Studio model id for the conversation tier (REQUIRED for a real run)
#   LOCAL_LLM_MODEL_BUILDING  LM Studio model id for the building/code tier (default: = LOCAL_LLM_MODEL)
#
# A real run requires the E2 server running, the pinned fork installed, LM
# Studio reachable, and the FastAPI bridge endpoint (E4-3) up with a matching
# MINECRAFT_BRIDGE_TOKEN. The bot username is fixed as "BridgeBot"; with the E2
# default white-list=true you must whitelist it (this script prints the command).
set -euo pipefail

# ── Pinned E1 defaults (kept in sync with docs/decisions/0001 & 0002) ──
MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
REQUIRED_NODE_MAJOR="20"
MC_VERSION="1.21.6"                       # E1-R1 / decisions 0001
MC_HOST="${MC_HOST:-127.0.0.1}"           # E1-R2 / decisions 0002 — localhost only
MC_PORT="${MC_PORT:-25565}"               # E2 start-server.sh default
MC_AUTH="offline"                         # E1-R2 / decisions 0002
MINDCRAFT_PROFILE="${MINDCRAFT_PROFILE:-./profiles/bridge-bot.json}"
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
MINDCRAFT_LLM_URL="$LOCAL_LLM_BASE_URL"        # where the bot actually connects
BRIDGE_BOT_NAME="BridgeBot"               # MUST match "name" in profiles/bridge-bot.json

# ── Bridge defaults (decision 0010 §1/§4) ──
MINECRAFT_BRIDGE_URL="${MINECRAFT_BRIDGE_URL:-ws://127.0.0.1:8010/api/minecraft/bridge/ws}"
# MINECRAFT_BRIDGE_TOKEN is intentionally NOT defaulted: fail closed if unset
# for a real run. Never echo its value.

MCDATA_REL="src/utils/mcdata.js"
MCDATA_VERSION_PATCH_MARKER="LTAG E3-2 runtime version refresh"
ACTIONS_REL="src/agent/commands/actions.js"
ACTIONS_PATCH_MARKER="LTAG E4-4 bridge ping action"
ACTIONS_MOVE_PATCH_MARKER="LTAG E6-2 move action"
ACTIONS_NAVIGATE_PATCH_MARKER="LTAG E6-2 navigate action"
ACTIONS_PLACE_PATCH_MARKER="LTAG E6-3 place action"
ACTIONS_BREAK_PATCH_MARKER="LTAG E6-3 break action"
ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER="LTAG E6-4 build-from-plan action"
ACTIONS_PLAN_AND_BUILD_PATCH_MARKER="LTAG E9-1 plan-and-build action"
ACTIONS_EXECUTE_CODE_PATCH_MARKER="LTAG E6-5 execute-code action"
ACTIONS_OBSERVE_PATCH_MARKER="LTAG E6-6 observe action"
ACTIONS_INTERRUPTION_GUARD_PATCH_MARKER="LTAG E8-14 action interruption guard"
ACTIONS_PARSE_GUARD_PATCH_MARKER="LTAG E8-16 command parse guard"
AGENT_MANAGEMENT_PATCH_MARKER="LTAG E8-7 management chat gate"
AGENT_CLEAN_EXIT_PATCH_MARKER="LTAG E8-14 clean exit chat gate"
AGENT_HEARTBEAT_PATCH_MARKER="LTAG E8-15 autonomous heartbeat"
AGENT_INBOX_PATCH_MARKER="LTAG E9-1 inbox queue"
AGENT_DIRECTOR_GATE_PATCH_MARKER="LTAG E8.5-4 director gate"
AGENT_ACTION_QUEUE_PATCH_MARKER="LTAG E9-1 action queue"
MODES_UNSTUCK_PATCH_MARKER="LTAG E8-16 unstuck no-kill"
ACTION_MANAGER_NO_KILL_PATCH_MARKER="LTAG E8-17 action stop no-kill"
AGENT_REL="src/agent/agent.js"
MODES_REL="src/agent/modes.js"
ACTION_MANAGER_REL="src/agent/action_manager.js"
BRIDGE_CLIENT_REL="src/agent/bridge/python_bridge.js"
TIMELINE_EMITTER_REL="src/agent/bridge/timeline_emitter.js"
MANAGEMENT_REVIEW_REL="src/agent/bridge/management_review.js"
BRIDGE_ACTION_REL="src/agent/commands/bridge_ping_action.js"
MOVE_ACTION_REL="src/agent/commands/move_action.js"
NAVIGATE_ACTION_REL="src/agent/commands/navigate_action.js"
PLACE_ACTION_REL="src/agent/commands/place_action.js"
BREAK_ACTION_REL="src/agent/commands/break_action.js"
BUILD_FROM_PLAN_ACTION_REL="src/agent/commands/build_from_plan_action.js"
PLAN_AND_BUILD_ACTION_REL="src/agent/commands/plan_and_build_action.js"
EXECUTE_CODE_ACTION_REL="src/agent/commands/execute_code_action.js"
OBSERVE_ACTION_REL="src/agent/commands/observe_action.js"
PLACE_HERE_GUARD_REL="src/agent/commands/place_here_guard.js"
MOVEMENT_SKILL_REL="src/agent/skills/movement.js"
BUILDING_SKILL_REL="src/agent/skills/building.js"
BUILD_PLAN_SKILL_REL="src/agent/skills/build_plan.js"
BUILDER_PROVIDER_SKILL_REL="src/agent/skills/builder_provider.js"
BUILD_PLAN_GOVERNOR_SKILL_REL="src/agent/skills/build_plan_governor.js"
PERCEPTION_SKILL_REL="src/agent/skills/perception.js"
SAFE_FAIL_SKILL_REL="src/agent/skills/safe_fail.js"
ACTION_INTERRUPTION_SKILL_REL="src/agent/skills/action_interruption.js"
LMSTUDIO_USAGE_SKILL_REL="src/agent/skills/lmstudio_usage.js"
HEARTBEAT_SKILL_REL="src/agent/skills/heartbeat.js"
INBOX_QUEUE_SKILL_REL="src/agent/skills/inbox_queue.js"
DIRECTOR_GATE_SKILL_REL="src/agent/skills/director_gate.js"
ACTION_QUEUE_SKILL_REL="src/agent/skills/action_queue.js"

MINDCRAFT_DIR_ABS=""
MCDATA_BACKUP=""
MCDATA_PATH=""
ACTIONS_BACKUP=""
ACTIONS_PATH=""
AGENT_BACKUP=""
AGENT_PATH=""
MODES_BACKUP=""
MODES_PATH=""
ACTION_MANAGER_BACKUP=""
ACTION_MANAGER_PATH=""
BRIDGE_CLIENT_DEST=""
TIMELINE_EMITTER_DEST=""
MANAGEMENT_REVIEW_DEST=""
BRIDGE_ACTION_DEST=""
MOVE_ACTION_DEST=""
NAVIGATE_ACTION_DEST=""
PLACE_ACTION_DEST=""
BREAK_ACTION_DEST=""
BUILD_FROM_PLAN_ACTION_DEST=""
PLAN_AND_BUILD_ACTION_DEST=""
EXECUTE_CODE_ACTION_DEST=""
OBSERVE_ACTION_DEST=""
PLACE_HERE_GUARD_DEST=""
MOVEMENT_SKILL_DEST=""
BUILDING_SKILL_DEST=""
BUILD_PLAN_SKILL_DEST=""
BUILDER_PROVIDER_SKILL_DEST=""
BUILD_PLAN_GOVERNOR_SKILL_DEST=""
PERCEPTION_SKILL_DEST=""
SAFE_FAIL_SKILL_DEST=""
ACTION_INTERRUPTION_SKILL_DEST=""
LMSTUDIO_USAGE_SKILL_DEST=""
HEARTBEAT_SKILL_DEST=""
INBOX_QUEUE_SKILL_DEST=""
DIRECTOR_GATE_SKILL_DEST=""
ACTION_QUEUE_SKILL_DEST=""

# Resolve the committed templates relative to THIS script (not the caller's
# cwd) so the reviewed copies are used no matter where it is invoked.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings.js"
PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/bridge-bot.json"
FORK_SRC_DIR="$SCRIPT_DIR/fork-src"
BRIDGE_CLIENT_SRC="$FORK_SRC_DIR/agent/bridge/python_bridge.js"
TIMELINE_EMITTER_SRC="$FORK_SRC_DIR/agent/bridge/timeline_emitter.js"
MANAGEMENT_REVIEW_SRC="$FORK_SRC_DIR/agent/bridge/management_review.js"
BRIDGE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/bridge_ping_action.js"
MOVE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/move_action.js"
NAVIGATE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/navigate_action.js"
PLACE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/place_action.js"
BREAK_ACTION_SRC="$FORK_SRC_DIR/agent/commands/break_action.js"
BUILD_FROM_PLAN_ACTION_SRC="$FORK_SRC_DIR/agent/commands/build_from_plan_action.js"
PLAN_AND_BUILD_ACTION_SRC="$FORK_SRC_DIR/agent/commands/plan_and_build_action.js"
EXECUTE_CODE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/execute_code_action.js"
OBSERVE_ACTION_SRC="$FORK_SRC_DIR/agent/commands/observe_action.js"
PLACE_HERE_GUARD_SRC="$FORK_SRC_DIR/agent/commands/place_here_guard.js"
MOVEMENT_SKILL_SRC="$FORK_SRC_DIR/agent/skills/movement.js"
BUILDING_SKILL_SRC="$FORK_SRC_DIR/agent/skills/building.js"
BUILD_PLAN_SKILL_SRC="$FORK_SRC_DIR/agent/skills/build_plan.js"
BUILDER_PROVIDER_SKILL_SRC="$FORK_SRC_DIR/agent/skills/builder_provider.js"
BUILD_PLAN_GOVERNOR_SKILL_SRC="$FORK_SRC_DIR/agent/skills/build_plan_governor.js"
PERCEPTION_SKILL_SRC="$FORK_SRC_DIR/agent/skills/perception.js"
SAFE_FAIL_SKILL_SRC="$FORK_SRC_DIR/agent/skills/safe_fail.js"
ACTION_INTERRUPTION_SKILL_SRC="$FORK_SRC_DIR/agent/skills/action_interruption.js"
LMSTUDIO_USAGE_SKILL_SRC="$FORK_SRC_DIR/agent/skills/lmstudio_usage.js"
HEARTBEAT_SKILL_SRC="$FORK_SRC_DIR/agent/skills/heartbeat.js"
INBOX_QUEUE_SKILL_SRC="$FORK_SRC_DIR/agent/skills/inbox_queue.js"
DIRECTOR_GATE_SKILL_SRC="$FORK_SRC_DIR/agent/skills/director_gate.js"
ACTION_QUEUE_SKILL_SRC="$FORK_SRC_DIR/agent/skills/action_queue.js"

MODE="run"
case "${1:-}" in
    --dry-run) MODE="dry-run" ;;
    --verify)  MODE="verify" ;;
    --help|-h)
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

# Restore the disposable clone: revert the patched/copied files so a re-run (or
# any other launch script) sees the pinned tree, same trap pattern as the
# mcdata shim in connect-stock-bot.sh.
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
    if [ -n "${MODES_BACKUP:-}" ] && [ -f "$MODES_BACKUP" ] && [ -n "${MODES_PATH:-}" ]; then
        cp "$MODES_BACKUP" "$MODES_PATH" 2> /dev/null || true
        rm -f "$MODES_BACKUP"
    fi
    if [ -n "${ACTION_MANAGER_BACKUP:-}" ] && [ -f "$ACTION_MANAGER_BACKUP" ] && [ -n "${ACTION_MANAGER_PATH:-}" ]; then
        cp "$ACTION_MANAGER_BACKUP" "$ACTION_MANAGER_PATH" 2> /dev/null || true
        rm -f "$ACTION_MANAGER_BACKUP"
    fi
    [ -n "${BRIDGE_CLIENT_DEST:-}" ] && rm -f "$BRIDGE_CLIENT_DEST" 2> /dev/null || true
    [ -n "${TIMELINE_EMITTER_DEST:-}" ] && rm -f "$TIMELINE_EMITTER_DEST" 2> /dev/null || true
    [ -n "${MANAGEMENT_REVIEW_DEST:-}" ] && rm -f "$MANAGEMENT_REVIEW_DEST" 2> /dev/null || true
    [ -n "${BRIDGE_ACTION_DEST:-}" ] && rm -f "$BRIDGE_ACTION_DEST" 2> /dev/null || true
    [ -n "${MOVE_ACTION_DEST:-}" ] && rm -f "$MOVE_ACTION_DEST" 2> /dev/null || true
    [ -n "${NAVIGATE_ACTION_DEST:-}" ] && rm -f "$NAVIGATE_ACTION_DEST" 2> /dev/null || true
    [ -n "${PLACE_ACTION_DEST:-}" ] && rm -f "$PLACE_ACTION_DEST" 2> /dev/null || true
    [ -n "${BREAK_ACTION_DEST:-}" ] && rm -f "$BREAK_ACTION_DEST" 2> /dev/null || true
    [ -n "${BUILD_FROM_PLAN_ACTION_DEST:-}" ] && rm -f "$BUILD_FROM_PLAN_ACTION_DEST" 2> /dev/null || true
    [ -n "${EXECUTE_CODE_ACTION_DEST:-}" ] && rm -f "$EXECUTE_CODE_ACTION_DEST" 2> /dev/null || true
    [ -n "${OBSERVE_ACTION_DEST:-}" ] && rm -f "$OBSERVE_ACTION_DEST" 2> /dev/null || true
    [ -n "${PLACE_HERE_GUARD_DEST:-}" ] && rm -f "$PLACE_HERE_GUARD_DEST" 2> /dev/null || true
    [ -n "${MOVEMENT_SKILL_DEST:-}" ] && rm -f "$MOVEMENT_SKILL_DEST" 2> /dev/null || true
    [ -n "${BUILDING_SKILL_DEST:-}" ] && rm -f "$BUILDING_SKILL_DEST" 2> /dev/null || true
    [ -n "${BUILD_PLAN_SKILL_DEST:-}" ] && rm -f "$BUILD_PLAN_SKILL_DEST" 2> /dev/null || true
    [ -n "${BUILDER_PROVIDER_SKILL_DEST:-}" ] && rm -f "$BUILDER_PROVIDER_SKILL_DEST" 2> /dev/null || true
    [ -n "${BUILD_PLAN_GOVERNOR_SKILL_DEST:-}" ] && rm -f "$BUILD_PLAN_GOVERNOR_SKILL_DEST" 2> /dev/null || true
    [ -n "${PERCEPTION_SKILL_DEST:-}" ] && rm -f "$PERCEPTION_SKILL_DEST" 2> /dev/null || true
    [ -n "${SAFE_FAIL_SKILL_DEST:-}" ] && rm -f "$SAFE_FAIL_SKILL_DEST" 2> /dev/null || true
    [ -n "${ACTION_INTERRUPTION_SKILL_DEST:-}" ] && rm -f "$ACTION_INTERRUPTION_SKILL_DEST" 2> /dev/null || true
    [ -n "${LMSTUDIO_USAGE_SKILL_DEST:-}" ] && rm -f "$LMSTUDIO_USAGE_SKILL_DEST" 2> /dev/null || true
    [ -n "${HEARTBEAT_SKILL_DEST:-}" ] && rm -f "$HEARTBEAT_SKILL_DEST" 2> /dev/null || true
}

# ── Node / npm check (identical posture to connect-stock-bot.sh) ──
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
        fail "Node.js not found on PATH. Install Node ${REQUIRED_NODE_MAJOR} LTS:"
        info "  nvm:   nvm install ${REQUIRED_NODE_MAJOR} && nvm use ${REQUIRED_NODE_MAJOR}"
        info "  See docs/minecraft/mindcraft-bridge-client.md for details."
        return 1
    fi
    if [ "$node_m" != "$REQUIRED_NODE_MAJOR" ]; then
        fail "Node ${node_m} found, but the pinned Mindcraft needs Node ${REQUIRED_NODE_MAJOR} LTS."
        info "  Mindcraft warns Node 24+ breaks native deps; we pin ${REQUIRED_NODE_MAJOR} (E1-R1)."
        info "  Install Node ${REQUIRED_NODE_MAJOR} and retry."
        return 1
    fi
    if ! command -v npm > /dev/null 2>&1; then
        fail "npm not found on PATH (it ships with Node ${REQUIRED_NODE_MAJOR})."
        return 1
    fi
    ok "Node ${node_m} + npm $(npm -v) detected (need Node ${REQUIRED_NODE_MAJOR})"
}

# ── Static assertions on the committed assets (no Node/net/git) ──
# Defense-in-depth; the strict checks live in
# tests/backend/test_bridge_node_client.py.
verify_committed_assets() {
    local problems=0

    if [ ! -s "$SETTINGS_TEMPLATE" ]; then
        fail "Settings template missing or empty: $SETTINGS_TEMPLATE"; problems=1
    else
        grep -q '"host": "127.0.0.1"'   "$SETTINGS_TEMPLATE" || { fail "template host is not 127.0.0.1"; problems=1; }
        grep -q '"port": 25565'         "$SETTINGS_TEMPLATE" || { fail "template port is not 25565"; problems=1; }
        grep -q '"auth": "offline"'     "$SETTINGS_TEMPLATE" || { fail "template auth is not offline"; problems=1; }
        grep -q '"minecraft_version": "1.21.6"' "$SETTINGS_TEMPLATE" || { fail "template minecraft_version is not 1.21.6"; problems=1; }
    fi

    if [ ! -s "$PROFILE_TEMPLATE" ]; then
        fail "Bridge profile missing or empty: $PROFILE_TEMPLATE"; problems=1
    else
        grep -q "\"name\": \"${BRIDGE_BOT_NAME}\"" "$PROFILE_TEMPLATE" || { fail "profile name is not ${BRIDGE_BOT_NAME}"; problems=1; }
        grep -q '"model": "lmstudio/'      "$PROFILE_TEMPLATE" || { fail "profile model is not an lmstudio/ id"; problems=1; }
        grep -q '"code_model": "lmstudio/' "$PROFILE_TEMPLATE" || { fail "profile code_model is not an lmstudio/ id"; problems=1; }
        if grep -q 'openrouter/' "$PROFILE_TEMPLATE"; then
            fail "profile must NOT reference openrouter/ — local validation only"; problems=1
        fi
    fi

    if [ ! -s "$BRIDGE_CLIENT_SRC" ]; then
        fail "Bridge client missing or empty: $BRIDGE_CLIENT_SRC"; problems=1
    else
        grep -q '/api/minecraft/bridge/ws' "$BRIDGE_CLIENT_SRC" || { fail "client missing the bridge endpoint path"; problems=1; }
        grep -q 'Bearer'                   "$BRIDGE_CLIENT_SRC" || { fail "client missing bearer-token auth"; problems=1; }
        grep -q 'MINECRAFT_BRIDGE_TOKEN'   "$BRIDGE_CLIENT_SRC" || { fail "client does not read MINECRAFT_BRIDGE_TOKEN"; problems=1; }
        grep -q 'request_id'               "$BRIDGE_CLIENT_SRC" || { fail "client missing request_id envelope field"; problems=1; }
        grep -q 'deadline_ms'              "$BRIDGE_CLIENT_SRC" || { fail "client missing deadline_ms envelope field"; problems=1; }
        grep -q 'cost_context'             "$BRIDGE_CLIENT_SRC" || { fail "client missing cost_context envelope field"; problems=1; }
        grep -q 'setTimeout'               "$BRIDGE_CLIENT_SRC" || { fail "client missing a local deadline timeout"; problems=1; }
        grep -q 'BridgeClientError'        "$BRIDGE_CLIENT_SRC" || { fail "client missing the structured error type"; problems=1; }
        if grep -q 'openrouter' "$BRIDGE_CLIENT_SRC"; then
            fail "bridge client must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$TIMELINE_EMITTER_SRC" ]; then
        fail "Timeline emitter missing or empty: $TIMELINE_EMITTER_SRC"; problems=1
    else
        grep -q 'MC_TIMELINE_NDJSON' "$TIMELINE_EMITTER_SRC" || { fail "timeline emitter does not read MC_TIMELINE_NDJSON"; problems=1; }
        grep -q 'MC_RUN_DIR' "$TIMELINE_EMITTER_SRC" || { fail "timeline emitter does not fall back to MC_RUN_DIR"; problems=1; }
        grep -q 'appendFileSync' "$TIMELINE_EMITTER_SRC" || { fail "timeline emitter does not write NDJSON"; problems=1; }
    fi

    if [ ! -s "$LMSTUDIO_USAGE_SKILL_SRC" ]; then
        fail "LM Studio usage shim missing or empty: $LMSTUDIO_USAGE_SKILL_SRC"; problems=1
    else
        grep -q 'llm.request' "$LMSTUDIO_USAGE_SKILL_SRC" || { fail "LM Studio shim does not emit llm.request"; problems=1; }
        grep -q 'llm.response' "$LMSTUDIO_USAGE_SKILL_SRC" || { fail "LM Studio shim does not emit llm.response"; problems=1; }
        grep -q 'deterministicTokenEstimate' "$LMSTUDIO_USAGE_SKILL_SRC" || { fail "LM Studio shim missing deterministic estimator"; problems=1; }
    fi

    if [ ! -s "$HEARTBEAT_SKILL_SRC" ]; then
        fail "Heartbeat skill missing or empty: $HEARTBEAT_SKILL_SRC"; problems=1
    else
        grep -q 'heartbeat.fired' "$HEARTBEAT_SKILL_SRC" || { fail "heartbeat skill does not emit heartbeat.fired"; problems=1; }
        grep -q 'heartbeat.outcome' "$HEARTBEAT_SKILL_SRC" || { fail "heartbeat skill does not emit heartbeat.outcome"; problems=1; }
        grep -q 'heartbeat.halted' "$HEARTBEAT_SKILL_SRC" || { fail "heartbeat skill does not emit heartbeat.halted"; problems=1; }
        grep -q 'MC_HEARTBEAT_IDLE_MS' "$HEARTBEAT_SKILL_SRC" || { fail "heartbeat skill missing idle env"; problems=1; }
    fi

    if [ ! -s "$INBOX_QUEUE_SKILL_SRC" ]; then
        fail "Inbox queue skill missing or empty: $INBOX_QUEUE_SKILL_SRC"; problems=1
    else
        grep -q 'MINECRAFT_TURN_DEBOUNCE_MS' "$INBOX_QUEUE_SKILL_SRC" || { fail "inbox queue missing debounce env"; problems=1; }
        grep -q 'inbox.queued' "$INBOX_QUEUE_SKILL_SRC" || { fail "inbox queue missing telemetry"; problems=1; }
        grep -q 'installInboxQueue' "$INBOX_QUEUE_SKILL_SRC" || { fail "inbox queue missing installer"; problems=1; }
    fi

    if [ ! -s "$DIRECTOR_GATE_SKILL_SRC" ]; then
        fail "Director gate skill missing or empty: $DIRECTOR_GATE_SKILL_SRC"; problems=1
    else
        grep -q 'director_gate.selected' "$DIRECTOR_GATE_SKILL_SRC" || { fail "director gate missing selected telemetry"; problems=1; }
        grep -q 'director_gate.suppressed' "$DIRECTOR_GATE_SKILL_SRC" || { fail "director gate missing suppressed telemetry"; problems=1; }
        grep -q "service: 'director'" "$DIRECTOR_GATE_SKILL_SRC" || { fail "director gate does not call director.gate"; problems=1; }
        grep -q 'installDirectorGate' "$DIRECTOR_GATE_SKILL_SRC" || { fail "director gate missing installer"; problems=1; }
    fi

    if [ ! -s "$ACTION_QUEUE_SKILL_SRC" ]; then
        fail "Action queue skill missing or empty: $ACTION_QUEUE_SKILL_SRC"; problems=1
    else
        grep -q 'MINECRAFT_ACTION_QUEUE_MAX' "$ACTION_QUEUE_SKILL_SRC" || { fail "action queue missing max env"; problems=1; }
        grep -q 'action.queued' "$ACTION_QUEUE_SKILL_SRC" || { fail "action queue missing queued telemetry"; problems=1; }
        grep -q 'installActionQueue' "$ACTION_QUEUE_SKILL_SRC" || { fail "action queue missing installer"; problems=1; }
    fi

    if [ ! -s "$MANAGEMENT_REVIEW_SRC" ]; then
        fail "Management review helper missing or empty: $MANAGEMENT_REVIEW_SRC"; problems=1
    else
        grep -q "service: 'management'" "$MANAGEMENT_REVIEW_SRC" || { fail "management helper does not call management.review"; problems=1; }
        grep -q "method: 'review'" "$MANAGEMENT_REVIEW_SRC" || { fail "management helper method is not review"; problems=1; }
        grep -q "DEFAULT_MANAGEMENT_REVIEW_DEADLINE_MS = 10000" "$MANAGEMENT_REVIEW_SRC" || { fail "management helper deadline default is not 10000ms"; problems=1; }
        grep -q "MINECRAFT_MANAGEMENT_REVIEW_MODE" "$MANAGEMENT_REVIEW_SRC" || { fail "management helper is missing simulation disable mode"; problems=1; }
        grep -q "agent_tier: 'filter'" "$MANAGEMENT_REVIEW_SRC" || { fail "management helper cost tier is not filter"; problems=1; }
        if grep -q 'openrouter' "$MANAGEMENT_REVIEW_SRC"; then
            fail "management helper must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$BRIDGE_ACTION_SRC" ]; then
        fail "Bridge action missing or empty: $BRIDGE_ACTION_SRC"; problems=1
    else
        grep -q "'!bridgePing'" "$BRIDGE_ACTION_SRC" || { fail "action name is not !bridgePing"; problems=1; }
        grep -q 'callBridge'    "$BRIDGE_ACTION_SRC" || { fail "action does not call callBridge"; problems=1; }
        grep -q 'try {'         "$BRIDGE_ACTION_SRC" || { fail "action is not wrapped to never crash the bot"; problems=1; }
    fi

    if [ ! -s "$MOVEMENT_SKILL_SRC" ]; then
        fail "Movement skill helpers missing or empty: $MOVEMENT_SKILL_SRC"; problems=1
    else
        grep -q 'classifyMovement' "$MOVEMENT_SKILL_SRC" || { fail "movement helpers missing classifyMovement"; problems=1; }
        grep -q 'targetFromMove'   "$MOVEMENT_SKILL_SRC" || { fail "movement helpers missing targetFromMove"; problems=1; }
        if grep -q 'callBridge' "$MOVEMENT_SKILL_SRC"; then
            fail "movement helpers must stay pure (no bridge calls)"; problems=1
        fi
    fi

    if [ ! -s "$BUILDING_SKILL_SRC" ]; then
        fail "Building skill helpers missing or empty: $BUILDING_SKILL_SRC"; problems=1
    else
        grep -q 'classifyPlace' "$BUILDING_SKILL_SRC" || { fail "building helpers missing classifyPlace"; problems=1; }
        grep -q 'classifyBreak' "$BUILDING_SKILL_SRC" || { fail "building helpers missing classifyBreak"; problems=1; }
        if grep -q 'callBridge' "$BUILDING_SKILL_SRC"; then
            fail "building helpers must stay pure (no bridge calls)"; problems=1
        fi
    fi

    if [ ! -s "$BUILD_PLAN_SKILL_SRC" ]; then
        fail "Build-plan skill helpers missing or empty: $BUILD_PLAN_SKILL_SRC"; problems=1
    else
        grep -q 'normalizePlan'      "$BUILD_PLAN_SKILL_SRC" || { fail "build-plan helpers missing normalizePlan"; problems=1; }
        grep -q 'completionMetric'  "$BUILD_PLAN_SKILL_SRC" || { fail "build-plan helpers missing completionMetric"; problems=1; }
        grep -q 'structureObservation' "$BUILD_PLAN_SKILL_SRC" || { fail "build-plan helpers missing structureObservation"; problems=1; }
        if grep -q 'callBridge' "$BUILD_PLAN_SKILL_SRC"; then
            fail "build-plan helpers must stay pure (no bridge calls)"; problems=1
        fi
    fi

    if [ ! -s "$BUILDER_PROVIDER_SKILL_SRC" ]; then
        fail "Builder-provider helper missing or empty: $BUILDER_PROVIDER_SKILL_SRC"; problems=1
    else
        grep -q 'MC_SIM_BUILDER_PROVIDER' "$BUILDER_PROVIDER_SKILL_SRC" || { fail "builder provider missing env routing"; problems=1; }
        grep -q 'plan_generation' "$BUILDER_PROVIDER_SKILL_SRC" || { fail "builder provider missing plan_generation guard"; problems=1; }
        grep -q 'OpenRouter' "$BUILDER_PROVIDER_SKILL_SRC" || { fail "builder provider missing OpenRouter routing"; problems=1; }
    fi

    if [ ! -s "$BUILD_PLAN_GOVERNOR_SKILL_SRC" ]; then
        fail "Build-plan governor helper missing or empty: $BUILD_PLAN_GOVERNOR_SKILL_SRC"; problems=1
    else
        grep -q 'active_build_exists' "$BUILD_PLAN_GOVERNOR_SKILL_SRC" || { fail "build-plan governor missing active-build guard"; problems=1; }
        grep -q 'MC_SIM_BUILD_COOLDOWN_SEC' "$BUILD_PLAN_GOVERNOR_SKILL_SRC" || { fail "build-plan governor missing cooldown env"; problems=1; }
        grep -q 'buildPlanCacheKey' "$BUILD_PLAN_GOVERNOR_SKILL_SRC" || { fail "build-plan governor missing cache key helper"; problems=1; }
    fi

    if [ ! -s "$PERCEPTION_SKILL_SRC" ]; then
        fail "Perception skill helpers missing or empty: $PERCEPTION_SKILL_SRC"; problems=1
    else
        grep -q 'perceptionObservation' "$PERCEPTION_SKILL_SRC" || { fail "perception helpers missing perceptionObservation"; problems=1; }
        grep -q 'nearbyBlocks' "$PERCEPTION_SKILL_SRC" || { fail "perception helpers missing nearbyBlocks"; problems=1; }
        grep -q 'nearbyEntities' "$PERCEPTION_SKILL_SRC" || { fail "perception helpers missing nearbyEntities"; problems=1; }
        grep -q 'inventorySnapshot' "$PERCEPTION_SKILL_SRC" || { fail "perception helpers missing inventorySnapshot"; problems=1; }
        if grep -q 'callBridge' "$PERCEPTION_SKILL_SRC"; then
            fail "perception helpers must stay pure (no bridge calls)"; problems=1
        fi
    fi

    if [ ! -s "$SAFE_FAIL_SKILL_SRC" ]; then
        fail "Safe-fail skill helpers missing or empty: $SAFE_FAIL_SKILL_SRC"; problems=1
    else
        grep -q 'decideSafeFail' "$SAFE_FAIL_SKILL_SRC" || { fail "safe-fail helpers missing decideSafeFail"; problems=1; }
        grep -q 'bridge-overloaded' "$SAFE_FAIL_SKILL_SRC" || { fail "safe-fail helpers missing bridge_overloaded normalization"; problems=1; }
        grep -q 'retry-bounded' "$SAFE_FAIL_SKILL_SRC" || { fail "safe-fail helpers missing retry-bounded policy"; problems=1; }
        if grep -q 'callBridge' "$SAFE_FAIL_SKILL_SRC"; then
            fail "safe-fail helpers must stay pure (no bridge calls)"; problems=1
        fi
    fi

    if [ ! -s "$ACTION_INTERRUPTION_SKILL_SRC" ]; then
        fail "Action interruption helpers missing or empty: $ACTION_INTERRUPTION_SKILL_SRC"; problems=1
    else
        grep -q 'classifyInterruption' "$ACTION_INTERRUPTION_SKILL_SRC" || { fail "action interruption helpers missing classifyInterruption"; problems=1; }
        grep -q 'PathStopped' "$ACTION_INTERRUPTION_SKILL_SRC" || { fail "action interruption helpers missing PathStopped classification"; problems=1; }
        if grep -q 'callBridge' "$ACTION_INTERRUPTION_SKILL_SRC"; then
            fail "action interruption helpers must stay pure (no bridge calls)"; problems=1
        fi
    fi

    if [ ! -s "$PLACE_HERE_GUARD_SRC" ]; then
        fail "Place-here guard missing or empty: $PLACE_HERE_GUARD_SRC"; problems=1
    else
        grep -q 'wrapPlaceHere' "$PLACE_HERE_GUARD_SRC" || { fail "place-here guard missing wrapPlaceHere"; problems=1; }
        grep -q 'wrapInterruptedActions' "$PLACE_HERE_GUARD_SRC" || { fail "place-here guard missing action-list wrapper"; problems=1; }
        grep -q "service: 'action'" "$PLACE_HERE_GUARD_SRC" || { fail "place-here guard does not emit action.result"; problems=1; }
        grep -q 'classifyInterruption' "$PLACE_HERE_GUARD_SRC" || { fail "place-here guard does not classify interruptions"; problems=1; }
        grep -q 'command parse guard' "$PLACE_HERE_GUARD_SRC" || { fail "place-here guard missing command parse guard"; problems=1; }
    fi

    if [ ! -s "$MOVE_ACTION_SRC" ]; then
        fail "Move action missing or empty: $MOVE_ACTION_SRC"; problems=1
    else
        grep -q "'!move'" "$MOVE_ACTION_SRC" || { fail "move action name is not !move"; problems=1; }
        grep -q "service: 'perception'" "$MOVE_ACTION_SRC" || { fail "move action does not emit perception.report"; problems=1; }
        grep -q "service: 'action'"     "$MOVE_ACTION_SRC" || { fail "move action does not emit action.result"; problems=1; }
        grep -q 'classifyMovement'      "$MOVE_ACTION_SRC" || { fail "move action does not classify observed movement"; problems=1; }
        grep -q 'safe-idling'           "$MOVE_ACTION_SRC" || { fail "move action missing bridge safe-idle path"; problems=1; }
        if grep -q 'openrouter' "$MOVE_ACTION_SRC"; then
            fail "move action must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$NAVIGATE_ACTION_SRC" ]; then
        fail "Navigate action missing or empty: $NAVIGATE_ACTION_SRC"; problems=1
    else
        grep -q "'!navigate'" "$NAVIGATE_ACTION_SRC" || { fail "navigate action name is not !navigate"; problems=1; }
        grep -q "service: 'perception'" "$NAVIGATE_ACTION_SRC" || { fail "navigate action does not emit perception.report"; problems=1; }
        grep -q "service: 'action'"     "$NAVIGATE_ACTION_SRC" || { fail "navigate action does not emit action.result"; problems=1; }
        grep -q 'classifyMovement'      "$NAVIGATE_ACTION_SRC" || { fail "navigate action does not classify observed movement"; problems=1; }
        grep -q 'safe-idling'           "$NAVIGATE_ACTION_SRC" || { fail "navigate action missing bridge safe-idle path"; problems=1; }
        if grep -q 'openrouter' "$NAVIGATE_ACTION_SRC"; then
            fail "navigate action must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$PLACE_ACTION_SRC" ]; then
        fail "Place action missing or empty: $PLACE_ACTION_SRC"; problems=1
    else
        grep -q "'!place'" "$PLACE_ACTION_SRC" || { fail "place action name is not !place"; problems=1; }
        grep -q "service: 'perception'" "$PLACE_ACTION_SRC" || { fail "place action does not emit perception.report"; problems=1; }
        grep -q "service: 'action'"     "$PLACE_ACTION_SRC" || { fail "place action does not emit action.result"; problems=1; }
        grep -q 'classifyPlace'         "$PLACE_ACTION_SRC" || { fail "place action does not classify observed placement"; problems=1; }
        grep -q 'safe-idling'           "$PLACE_ACTION_SRC" || { fail "place action missing bridge safe-idle path"; problems=1; }
        if grep -q 'openrouter' "$PLACE_ACTION_SRC"; then
            fail "place action must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$BREAK_ACTION_SRC" ]; then
        fail "Break action missing or empty: $BREAK_ACTION_SRC"; problems=1
    else
        grep -q "'!break'" "$BREAK_ACTION_SRC" || { fail "break action name is not !break"; problems=1; }
        grep -q "service: 'perception'" "$BREAK_ACTION_SRC" || { fail "break action does not emit perception.report"; problems=1; }
        grep -q "service: 'action'"     "$BREAK_ACTION_SRC" || { fail "break action does not emit action.result"; problems=1; }
        grep -q 'classifyBreak'         "$BREAK_ACTION_SRC" || { fail "break action does not classify observed break"; problems=1; }
        grep -q 'safe-idling'           "$BREAK_ACTION_SRC" || { fail "break action missing bridge safe-idle path"; problems=1; }
        if grep -q 'openrouter' "$BREAK_ACTION_SRC"; then
            fail "break action must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$BUILD_FROM_PLAN_ACTION_SRC" ]; then
        fail "Build-from-plan action missing or empty: $BUILD_FROM_PLAN_ACTION_SRC"; problems=1
    else
        grep -q "'!buildFromPlan'" "$BUILD_FROM_PLAN_ACTION_SRC" || { fail "build-from-plan action name is not !buildFromPlan"; problems=1; }
        grep -q "service: 'perception'" "$BUILD_FROM_PLAN_ACTION_SRC" || { fail "build-from-plan action does not emit perception.report"; problems=1; }
        grep -q "service: 'action'"     "$BUILD_FROM_PLAN_ACTION_SRC" || { fail "build-from-plan action does not emit action.result"; problems=1; }
        grep -q 'completionMetric'      "$BUILD_FROM_PLAN_ACTION_SRC" || { fail "build-from-plan action does not compute completion"; problems=1; }
        grep -q 'safe-idling'           "$BUILD_FROM_PLAN_ACTION_SRC" || { fail "build-from-plan action missing bridge safe-idle path"; problems=1; }
        if grep -q 'openrouter' "$BUILD_FROM_PLAN_ACTION_SRC"; then
            fail "build-from-plan action must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$PLAN_AND_BUILD_ACTION_SRC" ]; then
        fail "Plan-and-build action missing or empty: $PLAN_AND_BUILD_ACTION_SRC"; problems=1
    else
        grep -q "'!planAndBuild'" "$PLAN_AND_BUILD_ACTION_SRC" || { fail "plan-and-build action name is not !planAndBuild"; problems=1; }
        grep -q 'build_plan.generation.completed' "$PLAN_AND_BUILD_ACTION_SRC" || { fail "plan-and-build action missing plan telemetry"; problems=1; }
        grep -q 'performBuildFromPlan' "$PLAN_AND_BUILD_ACTION_SRC" || { fail "plan-and-build action does not execute buildFromPlan"; problems=1; }
    fi

    if [ ! -s "$EXECUTE_CODE_ACTION_SRC" ]; then
        fail "Execute-code action missing or empty: $EXECUTE_CODE_ACTION_SRC"; problems=1
    else
        grep -q "'!executeCode'" "$EXECUTE_CODE_ACTION_SRC" || { fail "execute-code action name is not !executeCode"; problems=1; }
        grep -q "service: 'code'" "$EXECUTE_CODE_ACTION_SRC" || { fail "execute-code action does not call code.execute"; problems=1; }
        grep -q "method: 'execute'" "$EXECUTE_CODE_ACTION_SRC" || { fail "execute-code action does not call code.execute"; problems=1; }
        grep -q 'safe-idling' "$EXECUTE_CODE_ACTION_SRC" || { fail "execute-code action missing bridge safe-idle path"; problems=1; }
        grep -q 'BridgeClientError' "$EXECUTE_CODE_ACTION_SRC" || { fail "execute-code action missing structured bridge errors"; problems=1; }
        if grep -q 'openrouter' "$EXECUTE_CODE_ACTION_SRC"; then
            fail "execute-code action must NOT reference openrouter"; problems=1
        fi
    fi

    if [ ! -s "$OBSERVE_ACTION_SRC" ]; then
        fail "Observe action missing or empty: $OBSERVE_ACTION_SRC"; problems=1
    else
        grep -q "'!observe'" "$OBSERVE_ACTION_SRC" || { fail "observe action name is not !observe"; problems=1; }
        grep -q "service: 'perception'" "$OBSERVE_ACTION_SRC" || { fail "observe action does not emit perception.report"; problems=1; }
        grep -q "method: 'report'" "$OBSERVE_ACTION_SRC" || { fail "observe action does not call perception.report"; problems=1; }
        grep -q 'perceptionObservation' "$OBSERVE_ACTION_SRC" || { fail "observe action does not build a perception snapshot"; problems=1; }
        grep -q 'safe-idling' "$OBSERVE_ACTION_SRC" || { fail "observe action missing bridge safe-idle path"; problems=1; }
        if grep -q "service: 'action'" "$OBSERVE_ACTION_SRC"; then
            fail "observe action must stay read-only and not emit action.result"; problems=1
        fi
        if grep -q 'openrouter' "$OBSERVE_ACTION_SRC"; then
            fail "observe action must NOT reference openrouter"; problems=1
        fi
    fi

    return $problems
}

# ── (b) Resolve + print config (shared by every mode) ──
ok "Bridge Mindcraft bot → E2 server + Python bridge"
info "bot name:  $BRIDGE_BOT_NAME  (fixed; whitelist this exact name)"
info "server:    ${MC_HOST}:${MC_PORT}  auth=${MC_AUTH}  minecraft=${MC_VERSION}"
info "bridge:    ${MINECRAFT_BRIDGE_URL}  (bearer token via MINECRAFT_BRIDGE_TOKEN)"
info "clone:     $MINDCRAFT_DIR  (pinned $MINDCRAFT_COMMIT)"
info "profile:   $MINDCRAFT_PROFILE  (staged from $PROFILE_TEMPLATE)"
info "client:    staged → $BRIDGE_CLIENT_REL  (from fork-src/)"
info "actions:   !bridgePing, !move, !navigate, !place, !break, !buildFromPlan,"
info "           !planAndBuild, !executeCode, !observe injected into $ACTIONS_REL"
info "LM Studio: bot connects to ${MINDCRAFT_LLM_URL}  (local only, decision 0003)"

# ── --verify: static, CI/network-safe checks only ──
if [ "$MODE" = "verify" ]; then
    if verify_committed_assets; then
        ok "Static verify passed: settings → E2 server, bridge profile is"
        info "local-only (lmstudio/), python_bridge.js carries the envelope fields,"
        info "bearer auth, bridge endpoint, a deadline timeout and a structured"
        info "error type, and !bridgePing/!move/!navigate/!place/!break/!buildFromPlan/"
        info "!planAndBuild/!executeCode/!observe are wrapped so failures never crash and embodied outcomes"
        info "or snapshots report through the E4-6 channel."
        info "Malformed command calls are reported as wrong_args/invalid_args instead of crashing."
        info "(No clone, no network, no Node, no launch — drop --verify to connect.)"
        exit 0
    fi
    fail "Static verify FAILED — see messages above."
    exit 1
fi

LLM_MODEL="${LOCAL_LLM_MODEL:-}"
LLM_MODEL_BUILDING="${LOCAL_LLM_MODEL_BUILDING:-$LLM_MODEL}"

# ── --dry-run: print the resolved plan, do NOT clone/network/launch ──
if [ "$MODE" = "dry-run" ]; then
    check_node || true
    verify_committed_assets || true
    echo
    ok "Dry run complete — no clone, no network, nothing launched."
    info "host:        $MC_HOST"
    info "port:        $MC_PORT"
    info "auth:        $MC_AUTH"
    info "minecraft:   $MC_VERSION"
    info "bridge url:  $MINECRAFT_BRIDGE_URL"
    if [ -n "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
        info "bridge token: set (value hidden)"
    else
        info "bridge token: (MINECRAFT_BRIDGE_TOKEN unset — REQUIRED for a real run)"
    fi
    info "profile:     $MINDCRAFT_PROFILE  (bot name $BRIDGE_BOT_NAME)"
    if [ -n "$LLM_MODEL" ]; then
        info "model:       lmstudio/$LLM_MODEL  (conversation tier)"
        info "code_model:  lmstudio/$LLM_MODEL_BUILDING  (building tier)"
    else
        info "model:       (LOCAL_LLM_MODEL unset — REQUIRED for a real run;"
        info "             list ids with: pnpm llm:local --list-only)"
    fi
    info "Would assert: $MINDCRAFT_DIR HEAD == $MINDCRAFT_COMMIT"
    info "Would stage:  $SETTINGS_TEMPLATE → $MINDCRAFT_DIR/settings.js"
    info "Would stage:  $PROFILE_TEMPLATE  → $MINDCRAFT_DIR/${MINDCRAFT_PROFILE#./}"
    info "Would copy:   fork-src/ → $MINDCRAFT_DIR/$BRIDGE_CLIENT_REL +"
    info "              $TIMELINE_EMITTER_REL + $LMSTUDIO_USAGE_SKILL_REL +"
    info "              $BRIDGE_ACTION_REL + $MOVE_ACTION_REL + $NAVIGATE_ACTION_REL +"
    info "              $PLACE_ACTION_REL + $BREAK_ACTION_REL + $BUILD_FROM_PLAN_ACTION_REL +"
    info "              $PLAN_AND_BUILD_ACTION_REL +"
    info "              $EXECUTE_CODE_ACTION_REL + $OBSERVE_ACTION_REL +"
    info "              $MOVEMENT_SKILL_REL + $BUILDING_SKILL_REL +"
    info "              $BUILD_PLAN_SKILL_REL + $BUILDER_PROVIDER_SKILL_REL +"
    info "              $BUILD_PLAN_GOVERNOR_SKILL_REL + $PERCEPTION_SKILL_REL +"
    info "              $SAFE_FAIL_SKILL_REL + $ACTION_INTERRUPTION_SKILL_REL +"
    info "              $PLACE_HERE_GUARD_REL + $HEARTBEAT_SKILL_REL +"
    info "              $INBOX_QUEUE_SKILL_REL + $DIRECTOR_GATE_SKILL_REL + $ACTION_QUEUE_SKILL_REL"
    info "Would patch:  inject bridgePingAction, moveAction, navigateAction,"
    info "              placeAction, breakAction, buildFromPlanAction, planAndBuildAction, executeCodeAction"
    info "              and observeAction into $MINDCRAFT_DIR/$ACTIONS_REL (restored on exit)"
    info "Would stage:  runtime-version shim in $MINDCRAFT_DIR/$MCDATA_REL (restored on exit)"
    info "Would launch: (cd $MINDCRAFT_DIR && node main.js --profiles $MINDCRAFT_PROFILE)"
    exit 0
fi

# ── Real run ──
verify_committed_assets || { fail "Refusing to launch with bad committed assets."; exit 1; }
check_node || exit 1
command -v git > /dev/null 2>&1 || { fail "git not found on PATH."; exit 1; }

# (a) The pinned fork must already be installed (E3-1 / #533).
if [ ! -d "$MINDCRAFT_DIR/.git" ]; then
    fail "No Mindcraft clone at $MINDCRAFT_DIR."
    info "  Install the pinned fork first:  scripts/minecraft/setup-mindcraft.sh"
    exit 1
fi
HEAD_SHA="$(git -C "$MINDCRAFT_DIR" rev-parse HEAD 2>/dev/null || true)"
if [ "$HEAD_SHA" != "$MINDCRAFT_COMMIT" ]; then
    fail "Clone is not at the pinned commit — refusing to launch an unpinned tree."
    info "  HEAD is     ${HEAD_SHA:-<unknown>}"
    info "  expected    $MINDCRAFT_COMMIT"
    info "  Re-pin with: scripts/minecraft/setup-mindcraft.sh"
    exit 1
fi
ok "Clone is at the pinned commit $MINDCRAFT_COMMIT"
MINDCRAFT_DIR_ABS="$(cd -- "$MINDCRAFT_DIR" && pwd)"

# (b) Fail closed on a missing bridge token (decision 0010 §4 — no anonymous
#     path). Checked BEFORE the LLM model so the security boundary is first.
if [ -z "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
    fail "MINECRAFT_BRIDGE_TOKEN is not set — the bridge has NO unauthenticated path."
    info "  Export the SAME shared secret the FastAPI bridge server uses:"
    info "    export MINECRAFT_BRIDGE_TOKEN=<the-server-secret>"
    info "  (decision 0010 §4: bearer token is the auth boundary, not agent_id)"
    exit 1
fi

# (c) The conversation model is mandatory for a real run (local LM Studio only).
if [ -z "$LLM_MODEL" ]; then
    fail "LOCAL_LLM_MODEL is not set — a real run needs a local LM Studio model id."
    info "  List the models LM Studio is serving, then export one:"
    info "    pnpm llm:local --list-only"
    info "    export LOCAL_LLM_MODEL=<model-id-from-the-list>"
    info "  This keeps validation 100% local — zero external model spend (decision 0003)."
    exit 1
fi

# (d) Stage settings.js (host/port/profile substituted; everything else the
#     reviewed template verbatim). Line-anchored so the header is untouched.
DEST_SETTINGS="$MINDCRAFT_DIR_ABS/settings.js"
if ! sed -E \
    -e "s|^([[:space:]]*\"host\":[[:space:]]*\")[^\"]*(\".*)$|\1${MC_HOST}\2|" \
    -e "s|^([[:space:]]*\"port\":[[:space:]]*)[0-9]+(,.*)$|\1${MC_PORT}\2|" \
    -e "s|^([[:space:]]*\")\\./profiles/stock-bot\\.json(\".*)$|\1${MINDCRAFT_PROFILE}\2|" \
    "$SETTINGS_TEMPLATE" > "$DEST_SETTINGS"; then
    fail "Failed to stage settings.js → $DEST_SETTINGS"
    exit 1
fi
ok "Staged settings.js → $DEST_SETTINGS (host=${MC_HOST} port=${MC_PORT} profile=${MINDCRAFT_PROFILE})"
SETTINGS_PATH="$DEST_SETTINGS" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.SETTINGS_PATH;
const importLine = "import './src/agent/skills/lmstudio_usage.js'; // LTAG E8-12 timeline telemetry\n";
let source = readFileSync(path, 'utf8');
if (!source.includes('lmstudio_usage.js')) {
    writeFileSync(path, importLine + source);
}
NODE
ok "Enabled LM Studio timeline telemetry in settings.js"

# (e) Stage the profile with the LM Studio model ids substituted in.
DEST_PROFILE="$MINDCRAFT_DIR_ABS/${MINDCRAFT_PROFILE#./}"
mkdir -p "$(dirname -- "$DEST_PROFILE")"
if ! TEMPLATE_PATH="$PROFILE_TEMPLATE" DEST_PATH="$DEST_PROFILE" CHAT_MODEL="$LLM_MODEL" CODE_MODEL="$LLM_MODEL_BUILDING" LLM_URL="$LOCAL_LLM_BASE_URL" EMBEDDING_URL="${LOCAL_LLM_UPSTREAM_URL:-$LOCAL_LLM_BASE_URL}" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const templatePath = process.env.TEMPLATE_PATH;
const destPath = process.env.DEST_PATH;
const chatModel = process.env.CHAT_MODEL;
const codeModel = process.env.CODE_MODEL;
const llmUrl = process.env.LLM_URL || 'http://localhost:1234/v1';
const embeddingUrl = process.env.EMBEDDING_URL || llmUrl;
const profile = JSON.parse(readFileSync(templatePath, 'utf8'));

if (
    profile.model !== 'lmstudio/__LOCAL_LLM_MODEL__' ||
    profile.code_model !== 'lmstudio/__LOCAL_LLM_MODEL_BUILDING__'
) {
    throw new Error('bridge-bot profile template lost its local model placeholders');
}

profile.model = { api: 'lmstudio', model: `lmstudio/${chatModel}`, url: llmUrl };
profile.code_model = { api: 'lmstudio', model: `lmstudio/${codeModel}`, url: llmUrl };
profile.embedding = {
    api: 'lmstudio',
    model: 'lmstudio/text-embedding-nomic-embed-text-v1.5',
    url: embeddingUrl,
};
writeFileSync(destPath, `${JSON.stringify(profile, null, 4)}\n`);
NODE
then
    fail "Failed to stage profile → $DEST_PROFILE"
    exit 1
fi
ok "Staged profile → $DEST_PROFILE"
info "  model:      lmstudio/${LLM_MODEL}        (conversation tier — decision 0003)"
info "  code_model: lmstudio/${LLM_MODEL_BUILDING}  (building tier — decision 0003)"
info "  url:        ${LOCAL_LLM_BASE_URL}"

# (f) Copy the committed bridge client + movement/building/code/perception actions verbatim into the
#     clone (the decision 0005 extension points). Removed again on exit.
BRIDGE_CLIENT_DEST="$MINDCRAFT_DIR_ABS/$BRIDGE_CLIENT_REL"
TIMELINE_EMITTER_DEST="$MINDCRAFT_DIR_ABS/$TIMELINE_EMITTER_REL"
MANAGEMENT_REVIEW_DEST="$MINDCRAFT_DIR_ABS/$MANAGEMENT_REVIEW_REL"
BRIDGE_ACTION_DEST="$MINDCRAFT_DIR_ABS/$BRIDGE_ACTION_REL"
MOVE_ACTION_DEST="$MINDCRAFT_DIR_ABS/$MOVE_ACTION_REL"
NAVIGATE_ACTION_DEST="$MINDCRAFT_DIR_ABS/$NAVIGATE_ACTION_REL"
PLACE_ACTION_DEST="$MINDCRAFT_DIR_ABS/$PLACE_ACTION_REL"
BREAK_ACTION_DEST="$MINDCRAFT_DIR_ABS/$BREAK_ACTION_REL"
BUILD_FROM_PLAN_ACTION_DEST="$MINDCRAFT_DIR_ABS/$BUILD_FROM_PLAN_ACTION_REL"
PLAN_AND_BUILD_ACTION_DEST="$MINDCRAFT_DIR_ABS/$PLAN_AND_BUILD_ACTION_REL"
EXECUTE_CODE_ACTION_DEST="$MINDCRAFT_DIR_ABS/$EXECUTE_CODE_ACTION_REL"
OBSERVE_ACTION_DEST="$MINDCRAFT_DIR_ABS/$OBSERVE_ACTION_REL"
PLACE_HERE_GUARD_DEST="$MINDCRAFT_DIR_ABS/$PLACE_HERE_GUARD_REL"
MOVEMENT_SKILL_DEST="$MINDCRAFT_DIR_ABS/$MOVEMENT_SKILL_REL"
BUILDING_SKILL_DEST="$MINDCRAFT_DIR_ABS/$BUILDING_SKILL_REL"
BUILD_PLAN_SKILL_DEST="$MINDCRAFT_DIR_ABS/$BUILD_PLAN_SKILL_REL"
BUILDER_PROVIDER_SKILL_DEST="$MINDCRAFT_DIR_ABS/$BUILDER_PROVIDER_SKILL_REL"
BUILD_PLAN_GOVERNOR_SKILL_DEST="$MINDCRAFT_DIR_ABS/$BUILD_PLAN_GOVERNOR_SKILL_REL"
PERCEPTION_SKILL_DEST="$MINDCRAFT_DIR_ABS/$PERCEPTION_SKILL_REL"
SAFE_FAIL_SKILL_DEST="$MINDCRAFT_DIR_ABS/$SAFE_FAIL_SKILL_REL"
ACTION_INTERRUPTION_SKILL_DEST="$MINDCRAFT_DIR_ABS/$ACTION_INTERRUPTION_SKILL_REL"
LMSTUDIO_USAGE_SKILL_DEST="$MINDCRAFT_DIR_ABS/$LMSTUDIO_USAGE_SKILL_REL"
HEARTBEAT_SKILL_DEST="$MINDCRAFT_DIR_ABS/$HEARTBEAT_SKILL_REL"
INBOX_QUEUE_SKILL_DEST="$MINDCRAFT_DIR_ABS/$INBOX_QUEUE_SKILL_REL"
DIRECTOR_GATE_SKILL_DEST="$MINDCRAFT_DIR_ABS/$DIRECTOR_GATE_SKILL_REL"
ACTION_QUEUE_SKILL_DEST="$MINDCRAFT_DIR_ABS/$ACTION_QUEUE_SKILL_REL"
mkdir -p \
    "$(dirname -- "$BRIDGE_CLIENT_DEST")" \
    "$(dirname -- "$TIMELINE_EMITTER_DEST")" \
    "$(dirname -- "$MANAGEMENT_REVIEW_DEST")" \
    "$(dirname -- "$BRIDGE_ACTION_DEST")" \
    "$(dirname -- "$MOVE_ACTION_DEST")" \
    "$(dirname -- "$NAVIGATE_ACTION_DEST")" \
    "$(dirname -- "$PLACE_ACTION_DEST")" \
    "$(dirname -- "$BREAK_ACTION_DEST")" \
    "$(dirname -- "$BUILD_FROM_PLAN_ACTION_DEST")" \
    "$(dirname -- "$PLAN_AND_BUILD_ACTION_DEST")" \
    "$(dirname -- "$EXECUTE_CODE_ACTION_DEST")" \
    "$(dirname -- "$OBSERVE_ACTION_DEST")" \
    "$(dirname -- "$PLACE_HERE_GUARD_DEST")" \
    "$(dirname -- "$MOVEMENT_SKILL_DEST")" \
    "$(dirname -- "$BUILDING_SKILL_DEST")" \
    "$(dirname -- "$BUILD_PLAN_SKILL_DEST")" \
    "$(dirname -- "$BUILDER_PROVIDER_SKILL_DEST")" \
    "$(dirname -- "$BUILD_PLAN_GOVERNOR_SKILL_DEST")" \
    "$(dirname -- "$PERCEPTION_SKILL_DEST")" \
    "$(dirname -- "$SAFE_FAIL_SKILL_DEST")" \
    "$(dirname -- "$ACTION_INTERRUPTION_SKILL_DEST")" \
    "$(dirname -- "$LMSTUDIO_USAGE_SKILL_DEST")" \
    "$(dirname -- "$HEARTBEAT_SKILL_DEST")" \
    "$(dirname -- "$INBOX_QUEUE_SKILL_DEST")" \
    "$(dirname -- "$DIRECTOR_GATE_SKILL_DEST")" \
    "$(dirname -- "$ACTION_QUEUE_SKILL_DEST")"
cp "$BRIDGE_CLIENT_SRC" "$BRIDGE_CLIENT_DEST"
cp "$TIMELINE_EMITTER_SRC" "$TIMELINE_EMITTER_DEST"
cp "$MANAGEMENT_REVIEW_SRC" "$MANAGEMENT_REVIEW_DEST"
cp "$BRIDGE_ACTION_SRC" "$BRIDGE_ACTION_DEST"
cp "$MOVE_ACTION_SRC" "$MOVE_ACTION_DEST"
cp "$NAVIGATE_ACTION_SRC" "$NAVIGATE_ACTION_DEST"
cp "$PLACE_ACTION_SRC" "$PLACE_ACTION_DEST"
cp "$BREAK_ACTION_SRC" "$BREAK_ACTION_DEST"
cp "$BUILD_FROM_PLAN_ACTION_SRC" "$BUILD_FROM_PLAN_ACTION_DEST"
cp "$PLAN_AND_BUILD_ACTION_SRC" "$PLAN_AND_BUILD_ACTION_DEST"
cp "$EXECUTE_CODE_ACTION_SRC" "$EXECUTE_CODE_ACTION_DEST"
cp "$OBSERVE_ACTION_SRC" "$OBSERVE_ACTION_DEST"
cp "$PLACE_HERE_GUARD_SRC" "$PLACE_HERE_GUARD_DEST"
cp "$MOVEMENT_SKILL_SRC" "$MOVEMENT_SKILL_DEST"
cp "$BUILDING_SKILL_SRC" "$BUILDING_SKILL_DEST"
cp "$BUILD_PLAN_SKILL_SRC" "$BUILD_PLAN_SKILL_DEST"
cp "$BUILDER_PROVIDER_SKILL_SRC" "$BUILDER_PROVIDER_SKILL_DEST"
cp "$BUILD_PLAN_GOVERNOR_SKILL_SRC" "$BUILD_PLAN_GOVERNOR_SKILL_DEST"
cp "$PERCEPTION_SKILL_SRC" "$PERCEPTION_SKILL_DEST"
cp "$SAFE_FAIL_SKILL_SRC" "$SAFE_FAIL_SKILL_DEST"
cp "$ACTION_INTERRUPTION_SKILL_SRC" "$ACTION_INTERRUPTION_SKILL_DEST"
cp "$LMSTUDIO_USAGE_SKILL_SRC" "$LMSTUDIO_USAGE_SKILL_DEST"
cp "$HEARTBEAT_SKILL_SRC" "$HEARTBEAT_SKILL_DEST"
cp "$INBOX_QUEUE_SKILL_SRC" "$INBOX_QUEUE_SKILL_DEST"
cp "$DIRECTOR_GATE_SKILL_SRC" "$DIRECTOR_GATE_SKILL_DEST"
cp "$ACTION_QUEUE_SKILL_SRC" "$ACTION_QUEUE_SKILL_DEST"
ok "Copied bridge client → $BRIDGE_CLIENT_REL"
ok "Copied timeline emitter → $TIMELINE_EMITTER_REL"
ok "Copied Management review helper → $MANAGEMENT_REVIEW_REL"
ok "Copied bridge action → $BRIDGE_ACTION_REL"
ok "Copied move action → $MOVE_ACTION_REL"
ok "Copied navigate action → $NAVIGATE_ACTION_REL"
ok "Copied place action → $PLACE_ACTION_REL"
ok "Copied break action → $BREAK_ACTION_REL"
ok "Copied build-from-plan action → $BUILD_FROM_PLAN_ACTION_REL"
ok "Copied plan-and-build action → $PLAN_AND_BUILD_ACTION_REL"
ok "Copied execute-code action → $EXECUTE_CODE_ACTION_REL"
ok "Copied observe action → $OBSERVE_ACTION_REL"
ok "Copied action interruption guard → $PLACE_HERE_GUARD_REL"
ok "Copied movement helpers → $MOVEMENT_SKILL_REL"
ok "Copied building helpers → $BUILDING_SKILL_REL"
ok "Copied build-plan helpers → $BUILD_PLAN_SKILL_REL"
ok "Copied builder-provider helpers → $BUILDER_PROVIDER_SKILL_REL"
ok "Copied build-plan governor helpers → $BUILD_PLAN_GOVERNOR_SKILL_REL"
ok "Copied perception helpers → $PERCEPTION_SKILL_REL"
ok "Copied safe-fail helpers → $SAFE_FAIL_SKILL_REL"
ok "Copied action interruption helpers → $ACTION_INTERRUPTION_SKILL_REL"
ok "Copied LM Studio usage shim → $LMSTUDIO_USAGE_SKILL_REL"
ok "Copied autonomous heartbeat skill → $HEARTBEAT_SKILL_REL"
ok "Copied inbox queue skill → $INBOX_QUEUE_SKILL_REL"
ok "Copied Director gate skill → $DIRECTOR_GATE_SKILL_REL"
ok "Copied action queue skill → $ACTION_QUEUE_SKILL_REL"

AGENT_PATH="$MINDCRAFT_DIR_ABS/$AGENT_REL"
if [ ! -f "$AGENT_PATH" ]; then
    fail "Mindcraft source file missing: $AGENT_PATH"
    exit 1
fi
if grep -q "$AGENT_MANAGEMENT_PATCH_MARKER" "$AGENT_PATH" || \
   grep -q "$AGENT_CLEAN_EXIT_PATCH_MARKER" "$AGENT_PATH" || \
   grep -q "$AGENT_HEARTBEAT_PATCH_MARKER" "$AGENT_PATH" || \
   grep -q "$AGENT_INBOX_PATCH_MARKER" "$AGENT_PATH" || \
   grep -q "$AGENT_DIRECTOR_GATE_PATCH_MARKER" "$AGENT_PATH" || \
   grep -q "$AGENT_ACTION_QUEUE_PATCH_MARKER" "$AGENT_PATH"; then
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
    AGENT_CLEAN_EXIT_PATCH_MARKER="$AGENT_CLEAN_EXIT_PATCH_MARKER" \
    AGENT_HEARTBEAT_PATCH_MARKER="$AGENT_HEARTBEAT_PATCH_MARKER" \
    AGENT_INBOX_PATCH_MARKER="$AGENT_INBOX_PATCH_MARKER" \
    AGENT_DIRECTOR_GATE_PATCH_MARKER="$AGENT_DIRECTOR_GATE_PATCH_MARKER" \
    AGENT_ACTION_QUEUE_PATCH_MARKER="$AGENT_ACTION_QUEUE_PATCH_MARKER" \
    node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.AGENT_PATH;
const marker = process.env.AGENT_MANAGEMENT_PATCH_MARKER;
const cleanExitMarker = process.env.AGENT_CLEAN_EXIT_PATCH_MARKER;
const heartbeatMarker = process.env.AGENT_HEARTBEAT_PATCH_MARKER;
const inboxMarker = process.env.AGENT_INBOX_PATCH_MARKER;
const directorGateMarker = process.env.AGENT_DIRECTOR_GATE_PATCH_MARKER;
const actionQueueMarker = process.env.AGENT_ACTION_QUEUE_PATCH_MARKER;
let source = readFileSync(path, 'utf8');

const importAnchor = "import { speak } from './speak.js';\n";
const importLine = `import { reviewChat } from './bridge/management_review.js'; // ${marker}\n`;
const heartbeatImportLine = `import { installHeartbeat } from './skills/heartbeat.js'; // ${heartbeatMarker}\n`;
const inboxImportLine = `import { installInboxQueue } from './skills/inbox_queue.js'; // ${inboxMarker}\n`;
const directorGateImportLine = `import { installDirectorGate } from './skills/director_gate.js'; // ${directorGateMarker}\n`;
const actionQueueImportLine = `import { installActionQueue } from './skills/action_queue.js'; // ${actionQueueMarker}\n`;
if (!source.includes(importLine)) {
    if (!source.includes(importAnchor)) {
        throw new Error('speak import anchor not found while applying Management chat gate');
    }
    source = source.replace(importAnchor, importAnchor + importLine);
}
if (!source.includes(heartbeatImportLine)) {
    if (!source.includes(importAnchor)) {
        throw new Error('speak import anchor not found while applying autonomous heartbeat');
    }
    source = source.replace(importAnchor, importAnchor + heartbeatImportLine);
}
for (const [line, label] of [
    [inboxImportLine, 'inbox queue'],
    [directorGateImportLine, 'director gate'],
    [actionQueueImportLine, 'action queue'],
]) {
    if (!source.includes(line)) {
        if (!source.includes(importAnchor)) {
            throw new Error(`speak import anchor not found while applying ${label}`);
        }
        source = source.replace(importAnchor, importAnchor + line);
    }
}

const actionQueueCallNeedle = `installActionQueue(this.actions); // ${actionQueueMarker}`;
if (!source.includes(actionQueueCallNeedle)) {
    const actionsNeedle = '        this.actions = new ActionManager(this);\n';
    if (!source.includes(actionsNeedle)) {
        throw new Error('ActionManager construction anchor not found while applying action queue');
    }
    source = source.replace(actionsNeedle, actionsNeedle + `        ${actionQueueCallNeedle}\n`);
}

let methodStart = source.indexOf('    async openChat(message) {');
if (methodStart === -1) methodStart = source.indexOf('        async openChat(message) {');
let methodEnd = source.indexOf('\n    startEvents() {', methodStart);
if (methodEnd === -1) methodEnd = source.indexOf('\n        startEvents() {', methodStart);
if (methodStart === -1 || methodEnd === -1) {
    throw new Error('openChat method shape changed while applying Management chat gate');
}

const replacement = `    async openChat(message) { // ${marker}
        const statusMessage = String(message || '').trim();
        if (/^(I'm stuck!|I'm free\\.|Exiting\\.|Restarting\\.)$/.test(statusMessage)) {
            console.log('[behavior-status]', this.name + ':', statusMessage);
            return;
        }
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

const cleanExitPatterns = [
    /(^[ \t]*)((?:await\s+)?this\.openChat\((['"])Exiting\.\3\);)/gm,
    /(^[ \t]*)((?:await\s+)?this\.bot\.chat\((['"])Exiting\.\3\);)/gm,
    /(^[ \t]*)((?:await\s+)?bot\.chat\((['"])Exiting\.\3\);)/gm,
];
for (const pattern of cleanExitPatterns) {
    source = source.replace(
        pattern,
        (_match, indent, statement) =>
            `${indent}if (process.env.MINECRAFT_CLEAN_EXIT === '1') ${statement} // ${cleanExitMarker}`,
    );
}
const cleanExitTernaryNeedle = "        this.bot.chat(code > 1 ? 'Restarting.': 'Exiting.');";
if (source.includes(cleanExitTernaryNeedle)) {
    source = source.replace(
        cleanExitTernaryNeedle,
        `        if (process.env.MINECRAFT_CLEAN_EXIT === '1') this.bot.chat(code > 1 ? 'Restarting.': 'Exiting.'); // ${cleanExitMarker}`,
    );
} else if (!source.includes("MINECRAFT_CLEAN_EXIT === '1') this.bot.chat(code > 1")) {
    throw new Error('cleanKill chat anchor not found');
}

const heartbeatCallNeedle = `installHeartbeat(this); // ${heartbeatMarker}`;
if (!source.includes(heartbeatCallNeedle)) {
    let startEventsNeedle = '    startEvents() {\n';
    let heartbeatCall = `        ${heartbeatCallNeedle}\n`;
    if (!source.includes(startEventsNeedle)) {
        startEventsNeedle = '        startEvents() {\n';
        heartbeatCall = `            ${heartbeatCallNeedle}\n`;
    }
    if (!source.includes(startEventsNeedle)) {
        throw new Error('startEvents method shape changed while applying autonomous heartbeat');
    }
    source = source.replace(startEventsNeedle, startEventsNeedle + heartbeatCall);
}
const inboxCallNeedle = `installInboxQueue(this); // ${inboxMarker}`;
const directorGateCallNeedle = `installDirectorGate(this); // ${directorGateMarker}`;
if (!source.includes(inboxCallNeedle)) {
    const setupNeedle = '    async _setupEventHandlers(save_data, init_message) {\n';
    if (!source.includes(setupNeedle)) {
        throw new Error('_setupEventHandlers anchor not found while applying inbox queue');
    }
    source = source.replace(
        setupNeedle,
        setupNeedle + `        ${inboxCallNeedle}\n        ${directorGateCallNeedle}\n`,
    );
} else if (!source.includes(directorGateCallNeedle)) {
    source = source.replace(inboxCallNeedle, `${inboxCallNeedle}\n        ${directorGateCallNeedle}`);
}
writeFileSync(path, source);
NODE
then
    fail "Failed to apply Management chat gate to $AGENT_REL"
    exit 1
fi
ok "Applied Management chat gate to $AGENT_REL"

MODES_PATH="$MINDCRAFT_DIR_ABS/$MODES_REL"
if [ ! -f "$MODES_PATH" ]; then
    fail "Mindcraft source file missing: $MODES_PATH"
    exit 1
fi
if grep -q "$MODES_UNSTUCK_PATCH_MARKER" "$MODES_PATH"; then
    info "Found a previous unstuck no-kill patch in $MODES_REL; restoring pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$MODES_REL" > "$MODES_PATH"; then
        fail "Could not restore pinned $MODES_REL before patching."
        exit 1
    fi
fi
MODES_BACKUP="$(mktemp -t mindcraft-modes.XXXXXX)"
cp "$MODES_PATH" "$MODES_BACKUP"
if ! MODES_PATH="$MODES_PATH" \
    MODES_UNSTUCK_PATCH_MARKER="$MODES_UNSTUCK_PATCH_MARKER" \
    node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.MODES_PATH;
const marker = process.env.MODES_UNSTUCK_PATCH_MARKER;
let source = readFileSync(path, 'utf8');
const stuckNeedle = `if (this.stuck_time > max_stuck_time) {`;
const stuckPatch = `const activeActionLabel = agent.actions?.currentActionLabel || ''; // ${marker}
            const effectiveMaxStuckTime = /action:(placeHere|place|buildFromPlan|planAndBuild|collectBlocks|followPlayer)/.test(activeActionLabel) ? max_stuck_time * 3 : max_stuck_time;
            if (this.stuck_time > effectiveMaxStuckTime) {`;
if (source.includes(stuckNeedle)) {
    source = source.replace(stuckNeedle, stuckPatch);
} else if (!source.includes('effectiveMaxStuckTime')) {
    throw new Error('unstuck stuck-time anchor not found');
}
const needle = `const crashTimeout = setTimeout(() => { agent.cleanKill("Got stuck and couldn't get unstuck") }, 10000);
                    await skills.moveAway(bot, 5);
                    clearTimeout(crashTimeout);
                    say(agent, 'I\\'m free.');`;
const patch = `let unstuckTimedOut = false; // ${marker}
                    const unstuckTimeout = new Promise((resolve) => setTimeout(() => {
                        unstuckTimedOut = true;
                        console.warn('[mode-status]', agent.name + ':', "unstuck timed out before recovery");
                        bot.output += "interrupted: unstuck-failed: timed out before recovery\\n";
                        resolve();
                    }, 10000));
                    await Promise.race([skills.moveAway(bot, 5), unstuckTimeout]);
                    if (!unstuckTimedOut) say(agent, 'I\\'m free.');
                    else agent.bot.emit('idle');`;
if (source.includes(needle)) {
    source = source.replace(needle, patch);
} else if (!source.includes(marker)) {
    throw new Error('unstuck cleanKill anchor not found');
}
writeFileSync(path, source);
NODE
then
    fail "Failed to apply unstuck no-kill patch to $MODES_REL"
    exit 1
fi
ok "Applied unstuck no-kill patch to $MODES_REL"

ACTION_MANAGER_PATH="$MINDCRAFT_DIR_ABS/$ACTION_MANAGER_REL"
if [ ! -f "$ACTION_MANAGER_PATH" ]; then
    fail "Mindcraft source file missing: $ACTION_MANAGER_PATH"
    exit 1
fi
if grep -q "$ACTION_MANAGER_NO_KILL_PATCH_MARKER" "$ACTION_MANAGER_PATH"; then
    info "Found a previous action-manager no-kill patch in $ACTION_MANAGER_REL; restoring pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$ACTION_MANAGER_REL" > "$ACTION_MANAGER_PATH"; then
        fail "Could not restore pinned $ACTION_MANAGER_REL before patching."
        exit 1
    fi
fi
ACTION_MANAGER_BACKUP="$(mktemp -t mindcraft-action-manager.XXXXXX)"
cp "$ACTION_MANAGER_PATH" "$ACTION_MANAGER_BACKUP"
if ! ACTION_MANAGER_PATH="$ACTION_MANAGER_PATH" \
    ACTION_MANAGER_NO_KILL_PATCH_MARKER="$ACTION_MANAGER_NO_KILL_PATCH_MARKER" \
    node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.ACTION_MANAGER_PATH;
const marker = process.env.ACTION_MANAGER_NO_KILL_PATCH_MARKER;
let source = readFileSync(path, 'utf8');
const needle = `const timeout = setTimeout(() => {
            this.agent.cleanKill('Code execution refused stop after 10 seconds. Killing process.');
        }, 10000);
        while (this.executing) {
            this.agent.requestInterrupt();
            console.log('waiting for code to finish executing...');
            await new Promise(resolve => setTimeout(resolve, 300));
        }
        clearTimeout(timeout);`;
const patch = `const deadline = Date.now() + 10000; // ${marker}
        while (this.executing && Date.now() < deadline) {
            this.agent.requestInterrupt();
            console.log('waiting for code to finish executing...');
            await new Promise(resolve => setTimeout(resolve, 300));
        }
        if (this.executing) {
            console.warn('[action-status]', \`action \${this.currentActionLabel || 'unknown'} refused stop; forcing idle without process exit\`);
            this.agent.bot.output = (this.agent.bot.output || '') + 'interrupted: action-stop-timeout: action refused stop before completion\\n';
            this.agent.bot.interrupt_code = true;
            this.executing = false;
            this.currentActionLabel = '';
            this.currentActionFn = null;
            this.cancelResume();
            this.agent.bot.emit('idle');
        }`;
if (source.includes(needle)) {
    source = source.replace(needle, patch);
} else if (!source.includes(marker)) {
    throw new Error('action-manager stop cleanKill anchor not found');
}
writeFileSync(path, source);
NODE
then
    fail "Failed to apply action-manager no-kill patch to $ACTION_MANAGER_REL"
    exit 1
fi
ok "Applied action-manager no-kill patch to $ACTION_MANAGER_REL"

# (g) Inject bridgePingAction/moveAction/navigateAction/placeAction/breakAction/buildFromPlanAction/executeCodeAction/observeAction into the actionsList
#     array via an anchored node-driven patch. Backed up + restored on exit
#     (the mcdata shim pattern).
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
   grep -q "$ACTIONS_PLAN_AND_BUILD_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_EXECUTE_CODE_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_OBSERVE_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_INTERRUPTION_GUARD_PATCH_MARKER" "$ACTIONS_PATH" || \
   grep -q "$ACTIONS_PARSE_GUARD_PATCH_MARKER" "$ACTIONS_PATH"; then
    info "Found a previous bridge-action patch in $ACTIONS_REL; restoring pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$ACTIONS_REL" > "$ACTIONS_PATH"; then
        fail "Could not restore pinned $ACTIONS_REL before patching."
        exit 1
    fi
fi
ACTIONS_BACKUP="$(mktemp -t mindcraft-actions.XXXXXX)"
cp "$ACTIONS_PATH" "$ACTIONS_BACKUP"
trap restore_clone_patches EXIT
trap 'restore_clone_patches; exit 130' INT
trap 'restore_clone_patches; exit 143' TERM
if ! ACTIONS_PATH="$ACTIONS_PATH" \
    ACTIONS_PATCH_MARKER="$ACTIONS_PATCH_MARKER" \
    ACTIONS_MOVE_PATCH_MARKER="$ACTIONS_MOVE_PATCH_MARKER" \
    ACTIONS_NAVIGATE_PATCH_MARKER="$ACTIONS_NAVIGATE_PATCH_MARKER" \
    ACTIONS_PLACE_PATCH_MARKER="$ACTIONS_PLACE_PATCH_MARKER" \
    ACTIONS_BREAK_PATCH_MARKER="$ACTIONS_BREAK_PATCH_MARKER" \
    ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER="$ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER" \
    ACTIONS_PLAN_AND_BUILD_PATCH_MARKER="$ACTIONS_PLAN_AND_BUILD_PATCH_MARKER" \
    ACTIONS_EXECUTE_CODE_PATCH_MARKER="$ACTIONS_EXECUTE_CODE_PATCH_MARKER" \
    ACTIONS_OBSERVE_PATCH_MARKER="$ACTIONS_OBSERVE_PATCH_MARKER" \
    ACTIONS_INTERRUPTION_GUARD_PATCH_MARKER="$ACTIONS_INTERRUPTION_GUARD_PATCH_MARKER" \
    ACTIONS_PARSE_GUARD_PATCH_MARKER="$ACTIONS_PARSE_GUARD_PATCH_MARKER" \
    node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.ACTIONS_PATH;
const bridgeMarker = process.env.ACTIONS_PATCH_MARKER;
const moveMarker = process.env.ACTIONS_MOVE_PATCH_MARKER;
const navigateMarker = process.env.ACTIONS_NAVIGATE_PATCH_MARKER;
const placeMarker = process.env.ACTIONS_PLACE_PATCH_MARKER;
const breakMarker = process.env.ACTIONS_BREAK_PATCH_MARKER;
const buildFromPlanMarker = process.env.ACTIONS_BUILD_FROM_PLAN_PATCH_MARKER;
const planAndBuildMarker = process.env.ACTIONS_PLAN_AND_BUILD_PATCH_MARKER;
const executeCodeMarker = process.env.ACTIONS_EXECUTE_CODE_PATCH_MARKER;
const observeMarker = process.env.ACTIONS_OBSERVE_PATCH_MARKER;
const guardMarker = process.env.ACTIONS_INTERRUPTION_GUARD_PATCH_MARKER;
const parseGuardMarker = process.env.ACTIONS_PARSE_GUARD_PATCH_MARKER;
let source = readFileSync(path, 'utf8');

// Anchor on the exact array opener at the pinned commit
// (mindcraft-bots/mindcraft@35be480 src/agent/commands/actions.js L28).
const anchor = 'export const actionsList = [';
if (!source.includes(anchor)) {
    throw new Error('actionsList anchor not found — pinned fork shape changed');
}
const guardImportLine = `import { wrapInterruptedActions } from './place_here_guard.js'; // ${guardMarker}\n`;
const guardCallLine = `\nwrapInterruptedActions(actionsList); // ${guardMarker}; ${parseGuardMarker}\n`;
const runAsActionLabelNeedle = `const actionObj = actionsList.find(a => a.perform === wrappedAction);
            actionLabel = actionObj.name.substring(1); // Remove the ! prefix`;
const runAsActionLabelPatch = `const actionObj = actionsList.find(a => a.perform === wrappedAction) || this;
            const actionName = actionObj && typeof actionObj.name === 'string' ? actionObj.name : '!action';
            actionLabel = actionName.substring(1); // Remove the ! prefix`;
if (source.includes(runAsActionLabelNeedle)) {
    source = source.replace(runAsActionLabelNeedle, runAsActionLabelPatch);
} else if (!source.includes('const actionName = actionObj && typeof actionObj.name')) {
    throw new Error('runAsAction label anchor not found');
}
const runAsActionInterruptedNeedle = `if (code_return.interrupted && !code_return.timedout)
            return;
        return code_return.message;`;
const runAsActionInterruptedPatch = `if (code_return.interrupted && !code_return.timedout) {
            const detail = code_return.message || \`\${actionLabel || 'action'} interrupted before completion\`;
            return detail.startsWith('interrupted:') ? detail : \`interrupted: \${detail}\`;
        }
        return code_return.message || '';`;
if (source.includes(runAsActionInterruptedNeedle)) {
    source = source.replace(runAsActionInterruptedNeedle, runAsActionInterruptedPatch);
} else if (!source.includes("interrupted before completion")) {
    throw new Error('runAsAction interrupted-return anchor not found');
}

const actions = [
    {
        marker: bridgeMarker,
        importLine: `import { bridgePingAction } from './bridge_ping_action.js'; // ${bridgeMarker}\n`,
        itemLine: `    bridgePingAction, // ${bridgeMarker}`,
    },
    {
        marker: moveMarker,
        importLine: `import { moveAction } from './move_action.js'; // ${moveMarker}\n`,
        itemLine: `    moveAction, // ${moveMarker}`,
    },
    {
        marker: navigateMarker,
        importLine: `import { navigateAction } from './navigate_action.js'; // ${navigateMarker}\n`,
        itemLine: `    navigateAction, // ${navigateMarker}`,
    },
    {
        marker: placeMarker,
        importLine: `import { placeAction } from './place_action.js'; // ${placeMarker}\n`,
        itemLine: `    placeAction, // ${placeMarker}`,
    },
    {
        marker: breakMarker,
        importLine: `import { breakAction } from './break_action.js'; // ${breakMarker}\n`,
        itemLine: `    breakAction, // ${breakMarker}`,
    },
    {
        marker: buildFromPlanMarker,
        importLine: `import { buildFromPlanAction } from './build_from_plan_action.js'; // ${buildFromPlanMarker}\n`,
        itemLine: `    buildFromPlanAction, // ${buildFromPlanMarker}`,
    },
    {
        marker: planAndBuildMarker,
        importLine: `import { planAndBuildAction } from './plan_and_build_action.js'; // ${planAndBuildMarker}\n`,
        itemLine: `    planAndBuildAction, // ${planAndBuildMarker}`,
    },
    {
        marker: executeCodeMarker,
        importLine: `import { executeCodeAction } from './execute_code_action.js'; // ${executeCodeMarker}\n`,
        itemLine: `    executeCodeAction, // ${executeCodeMarker}`,
    },
    {
        marker: observeMarker,
        importLine: `import { observeAction } from './observe_action.js'; // ${observeMarker}\n`,
        itemLine: `    observeAction, // ${observeMarker}`,
    },
];

const missing = actions.filter((a) => !source.includes(a.marker));
if (missing.length > 0) {
    source = missing.map((a) => a.importLine).join('') + source;
    source = source.replace(anchor, `${anchor}\n${missing.map((a) => a.itemLine).join('\n')}`);
}
if (!source.includes(guardMarker)) {
    source = guardImportLine + source + guardCallLine;
}
writeFileSync(path, source);
NODE
then
    fail "Failed to inject bridgePingAction/moveAction/navigateAction/placeAction/breakAction/buildFromPlanAction/planAndBuildAction/executeCodeAction/observeAction into $ACTIONS_REL"
    exit 1
fi
ok "Injected !bridgePing, !move, !navigate, !place, !break, !buildFromPlan, !planAndBuild, !executeCode, !observe into $ACTIONS_REL"
info "  Restores $ACTIONS_REL automatically when this launch exits."

# (h) Runtime-version shim (identical to connect-stock-bot.sh — same marker /
#     restore). The pinned fork reads minecraft_version at module import,
#     before the child agent receives settings.
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
    info "  Expected to find: let mc_version = settings.minecraft_version;"
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
ok "Staged Mindcraft runtime-version shim → $MCDATA_PATH"
info "  Restores $MCDATA_REL automatically when this launch exits."

# (i) Whitelist reminder (E2 server defaults white-list=true).
echo
info "── Whitelist (E2 server defaults to white-list=true) ──"
info "In the E2 server console, run exactly:"
info "    whitelist add ${BRIDGE_BOT_NAME}"
info "Skipping this → the bot connects then is kicked with 'not whitelisted'."
echo

# (j) Launch.
ok "Launching ${BRIDGE_BOT_NAME} → ${MC_HOST}:${MC_PORT} … (Ctrl+C to stop)"
info "Then in Minecraft chat:  ${BRIDGE_BOT_NAME} !bridgePing(\"hello\")"
info "Movement smoke:          ${BRIDGE_BOT_NAME} !move(\"act-1\", \"north\", 1, 10000)"
info "Building smoke:          ${BRIDGE_BOT_NAME} !place(\"act-2\", \"dirt\", \"{\\\"x\\\":0,\\\"y\\\":65,\\\"z\\\":0}\", \"up\")"
info "                         ${BRIDGE_BOT_NAME} !break(\"act-3\", \"{\\\"x\\\":0,\\\"y\\\":65,\\\"z\\\":0}\", \"dirt\")"
info "Plan-build smoke:        ${BRIDGE_BOT_NAME} !planAndBuild(\"small shared cabin\")"
info "Raw buildFromPlan smoke: ${BRIDGE_BOT_NAME} !buildFromPlan(\"act-4\", \"{\\\"x\\\":0,\\\"y\\\":65,\\\"z\\\":0}\", \"{\\\"blocks\\\":[{\\\"dx\\\":0,\\\"dy\\\":0,\\\"dz\\\":0,\\\"block_type\\\":\\\"dirt\\\"}]}\")"
info "Code smoke:              ${BRIDGE_BOT_NAME} !executeCode(\"python\", \"print(2 + 2)\", 5)"
info "Perception smoke:        ${BRIDGE_BOT_NAME} !observe(6, \"all\", false)"
info "Success: the bot logs 'bridge pong: hello'; the Python bridge logs the"
info "agent_id + request_id. Movement/building emit perception.report + action.result."
info "Code execution returns the existing sandbox result through code.execute."
info "Observe emits a schema-shaped perception.report snapshot and no action.result."
info "A bridge failure is logged [error.code] — not a crash."
cd "$MINDCRAFT_DIR_ABS"
node main.js --profiles "$MINDCRAFT_PROFILE"
