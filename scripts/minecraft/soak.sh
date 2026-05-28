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
# Lifecycle note: this remains a lower-level diagnostic harness. The E12
# embodied simulation supervisor in scripts/run_simulation.py owns durable
# run/simulation ids, stop conditions, and eval/report hooks, then delegates
# Minecraft launch work to this script.
#
# Usage:
#   scripts/minecraft/soak.sh
#   scripts/minecraft/soak.sh --duration-hours 2
#   scripts/minecraft/soak.sh --profile director_v2 --duration-hours 2
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
#   LOCAL_LLM_BASE_URL          Effective OpenAI-compatible local endpoint.
#                               Defaults to the LM queue proxy when enabled.
#   LOCAL_LLM_UPSTREAM_URL      Actual LM Studio upstream used by the queue
#                               proxy. Default: LOCAL_LLM_BASE_URL.
#   MINECRAFT_LLM_QUEUE_PROXY   Start the FIFO LM Studio proxy. Default: 1.
#   MINECRAFT_LLM_CONCURRENCY   Proxy request concurrency. Default: 1.
#   MINECRAFT_LLM_RETRY_ATTEMPTS
#                               Retries for transient LM Studio model-load
#                               400s such as "Model unloaded". Default: 2.
#   MINECRAFT_LLM_RETRY_DELAY_SECONDS
#                               Base delay between retry attempts. Default: 2.
#   MINECRAFT_LLM_REQUEST_TIMEOUT_SECONDS
#                               Per-request LM Studio proxy timeout. Default: 120.
#   SOAK_LLM_SMOKE_TIMEOUT_SECONDS
#                               Timeout for the preflight LM Studio chat
#                               warm-up. Default: 120.
#   SOAK_DURATION_HOURS         Default: 2.
#   SOAK_PROFILE                default or director_v2. The director_v2
#                               profile forces CONVERSATION_MODE=director_v2,
#                               DIRECTOR_V2_GATE=1, the LM queue proxy, and
#                               Director acceptance reporting. Default:
#                               default.
#   SOAK_AGENT_HOURLY_CAP_USD   Per-agent hourly cap assertion. Default: 0.01.
#   SOAK_MIN_MOVEMENT_PER_AGENT Minimum movement actions per tracked agent.
#                               Default: 5.
#   SOAK_MAX_DEATHS_PER_AGENT   Maximum death/respawn lines per tracked agent.
#                               Default: 2.
#   SOAK_MAX_STUCK_PER_AGENT    Maximum stuck/path-failure lines per tracked
#                               agent. Default: 5.
#   SOAK_MAX_RESTARTS_PER_AGENT Maximum restart/disconnect/exit signatures per
#                               tracked agent. Default: 1.
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
#   CONVERSATION_MODE           embodied (legacy #510 decentralized mode) or
#                               director_v2 (Director V2 prompt gate).
#                               Default: embodied.
#   DIRECTOR_V2_GATE            Set to 1 to gate Mindcraft prompt batches
#                               through director.gate. Automatically enabled
#                               when CONVERSATION_MODE=director_v2.
#   SOAK_BLOCK_PRIVATE_CONVERSATIONS
#                               Set to 1 to disable Mindcraft's private
#                               bot-to-bot conversation commands and force
#                               normal public Minecraft chat/action routing.
#                               Default: 0.
#   SOAK_BLOCK_SLOW_SIM_ACTIONS Set to 1 to disable slow/noisy actions such as
#                               !newAction, !observe, !navigate, generated
#                               plan building. Basic
#                               !place/!break stay available for quick builds.
#                               Default: 0.
#   SOAK_BLOCK_NEW_ACTIONS      Set to 1 to hide only Mindcraft !newAction
#                               while leaving !planAndBuild available.
#                               Default: 0.
#   SOAK_BLOCK_EXECUTE_CODE_ACTIONS
#                               Set to 1 to block arbitrary !executeCode
#                               separately from build-plan actions. Default:
#                               SOAK_BLOCK_SLOW_SIM_ACTIONS.
#   SOAK_ALLOW_BUILDER_NEW_ACTIONS
#                               Set to 1 to enable Mindcraft !newAction code
#                               generation only for SOAK_BUILDER_BOTS. Default:
#                               0.
#   SOAK_BUILDER_BOTS           Space-separated bot ids allowed to use
#                               builder-only code generation when enabled.
#                               Default: "rex fork pixel".
#   MC_SIM_MANAGEMENT_POLICY    Management review policy for bot chat:
#                               off, shadow, or enforce. Default: off.
#   MC_SIM_DISABLE_MANAGEMENT   Deprecated alias; 1 maps to policy=off,
#                               0 maps to policy=enforce when policy is unset.
#   MC_SIM_BUILDER_PROVIDER     Builder-plan provider for !planAndBuild only:
#                               local or openrouter. Default: local.
#   MC_SIM_BUILDER_OPENROUTER_API_KEY
#                               OpenRouter key for builder plans. Defaults to
#                               OPENROUTER_API_KEY when unset.
#   MC_SIM_BUILDER_OPENROUTER_MODEL
#                               OpenRouter model id for builder plans.
#   MC_SIM_BUILDER_FALLBACK     fail or local when OpenRouter config/calls
#                               fail. Default: fail.
#   MC_SIM_BUILDER_MAX_CALLS_PER_RUN
#                               Paid builder call cap. Default: 12.
#   MC_SIM_BUILDER_MAX_CALLS_PER_AGENT
#                               Paid builder call cap per agent. Default: 3.
#   MC_SIM_BUILDER_MAX_USD_PER_RUN
#                               Optional estimated USD cap for paid builder calls.
#   MC_SIM_BUILD_MAX_PER_AGENT  Max non-cached builder plan generations per
#                               agent. Default: 6.
#   MC_SIM_BUILD_COOLDOWN_SEC   Cooldown for equivalent completed builds.
#                               Default: 300.
#   MC_SIM_BUILD_ZONE_STRIDE    Per-agent build origin offset stride. Default: 12.
#   MC_SIM_BUILD_CACHE_TTL_SEC  Plan cache TTL. Default: 3600.
#   MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS
#                               Time a pending settlement phase reserves its
#                               preassigned owner before another selected
#                               planner may claim it. Default: 60000.
#   SOAK_PLAN_BUILD_BOTS        Optional comma/space-separated agent ids that
#                               may receive/use !planAndBuild for this run.
#                               Default: unrestricted. Alias for
#                               MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST.
#   MINECRAFT_PLAN_BUILD_ALLOWED_MATERIALS
#                               Optional comma/space/pipe-separated block list
#                               for builder JSON. Defaults to the easy starter kit.
#   SOAK_BUILDER_PROVIDER      Builder smoke selector: local or openrouter.
#                               Defaults to MC_SIM_BUILDER_PROVIDER.
#   SOAK_SAFE_TERRAIN_ACTIONS   Set to 1 to stage local-sim terrain guards:
#                               disable auto elbow-room/item pickup/torch modes
#                               and refuse destructive pathfinding.
#                               Default: 0.
#   MC_HEARTBEAT_ENABLED        Enable autonomous idle/stall heartbeat prompts.
#                               Default: 1.
#   MC_HEARTBEAT_IDLE_MS        Idle window before a high-level next-action
#                               prompt. Default: 90000.
#   MC_HEARTBEAT_COOLDOWN_MS    Minimum gap between heartbeat prompts.
#                               Default: 45000.
#   MC_HEARTBEAT_STALE_ACTION_MS
#                               Active-action age before the heartbeat treats it
#                               as stale. Default: 180000.
#   MC_HEARTBEAT_MAX_NO_COMMAND Repeated blank/no-command heartbeat outcomes
#                               before `heartbeat.halted`. Default: 3.
#   MC_SIM_MEMORY_CONTEXT_ENABLED
#                               Fetch Python core+recall memory before runtime
#                               prompt decisions. Default: 1.
#   MC_SIM_MEMORY_RECALL_LIMIT  Relevant recall snippets requested per fetch.
#                               Default: 3.
#   MC_SIM_MEMORY_CORE_MAX_CHARS
#                               Max core-memory characters injected. Default:
#                               1500.
#   MC_SIM_MEMORY_RECALL_MAX_CHARS
#                               Max recall characters injected. Default: 1200.
#   MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS
#                               Comma/space-separated agent ids skipped for
#                               runtime memory context. Default: management,alpha.
#   MC_SIM_SHARED_STATE_ENABLED Fetch the embodied shared-state blackboard for
#                               prompt context. Default: 1.
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
#   SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD
#                               Director V2 acceptance max LM queue depth after
#                               warm-up, exclusive. Default: 16.
#   SOAK_ACCEPTANCE_WARMUP_SECONDS
#                               Seconds ignored before acceptance queue-depth
#                               assertions. Default: 300.
#   SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO
#                               Max selected agents per scene divided by the
#                               tracked agent count. Default: 0.5.
#   SOAK_REQUIRE_DIRECTOR_ACCEPTANCE
#                               Exit nonzero when director_v2 acceptance fails.
#                               Default: 1.
#   director-decisions.ndjson    Director V2 scene/open/close and gate decision
#                               evidence under the run directory.
#   tool-parity.ndjson          Director tool calls and documented no-tool
#                               decisions under the run directory.
#   macro-evidence.ndjson       Build/gather/support macro attempts and
#                               structured results under the run directory.
#   memory-digest.ndjson        Director scene digest and memory compaction
#                               evidence under the run directory.
#   acceptance-report.json      Machine-readable Director V2 acceptance report.
#   acceptance-report.md        Human-readable Director V2 acceptance report.
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
if [ -z "${PYTHON:-}" ] && [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
fi
PYTHON="${PYTHON:-python3}"
export PYTHON

MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
LOCAL_LLM_UPSTREAM_URL="${LOCAL_LLM_UPSTREAM_URL:-$LOCAL_LLM_BASE_URL}"
MINECRAFT_LLM_QUEUE_PROXY="${MINECRAFT_LLM_QUEUE_PROXY:-1}"
MINECRAFT_LLM_CONCURRENCY="${MINECRAFT_LLM_CONCURRENCY:-1}"
MINECRAFT_LLM_RETRY_ATTEMPTS="${MINECRAFT_LLM_RETRY_ATTEMPTS:-2}"
MINECRAFT_LLM_RETRY_DELAY_SECONDS="${MINECRAFT_LLM_RETRY_DELAY_SECONDS:-2}"
MINECRAFT_LLM_REQUEST_TIMEOUT_SECONDS="${MINECRAFT_LLM_REQUEST_TIMEOUT_SECONDS:-120}"
MINECRAFT_LLM_PROXY_HOST="${MINECRAFT_LLM_PROXY_HOST:-127.0.0.1}"
MINECRAFT_LLM_PROXY_PORT="${MINECRAFT_LLM_PROXY_PORT:-1235}"
MINECRAFT_BRIDGE_URL="${MINECRAFT_BRIDGE_URL:-ws://127.0.0.1:8010/api/minecraft/bridge/ws}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://127.0.0.1:8010/api/health}"
SOAK_PROFILE="${SOAK_PROFILE:-default}"
CONVERSATION_MODE="${CONVERSATION_MODE:-embodied}"
case "$CONVERSATION_MODE" in
    embodied|director_v2) ;;
    *)
        echo "x CONVERSATION_MODE must be embodied or director_v2." >&2
        exit 2
        ;;
esac
if [ "$CONVERSATION_MODE" = "director_v2" ]; then
    DIRECTOR_V2_GATE=1
fi
DIRECTOR_V2_GATE="${DIRECTOR_V2_GATE:-0}"
export CONVERSATION_MODE DIRECTOR_V2_GATE
SOAK_DURATION_HOURS="${SOAK_DURATION_HOURS:-2}"
SOAK_LLM_SMOKE_TIMEOUT_SECONDS="${SOAK_LLM_SMOKE_TIMEOUT_SECONDS:-120}"
SOAK_AGENT_HOURLY_CAP_USD="${SOAK_AGENT_HOURLY_CAP_USD:-0.01}"
SOAK_MIN_MOVEMENT_PER_AGENT="${SOAK_MIN_MOVEMENT_PER_AGENT:-5}"
SOAK_MAX_DEATHS_PER_AGENT="${SOAK_MAX_DEATHS_PER_AGENT:-2}"
SOAK_MAX_STUCK_PER_AGENT="${SOAK_MAX_STUCK_PER_AGENT:-5}"
SOAK_MAX_RESTARTS_PER_AGENT="${SOAK_MAX_RESTARTS_PER_AGENT:-1}"
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
SOAK_BLOCK_NEW_ACTIONS="${SOAK_BLOCK_NEW_ACTIONS:-0}"
SOAK_BLOCK_EXECUTE_CODE_ACTIONS="${SOAK_BLOCK_EXECUTE_CODE_ACTIONS:-$SOAK_BLOCK_SLOW_SIM_ACTIONS}"
SOAK_ALLOW_BUILDER_NEW_ACTIONS="${SOAK_ALLOW_BUILDER_NEW_ACTIONS:-0}"
SOAK_BUILDER_BOTS="${SOAK_BUILDER_BOTS:-rex fork pixel}"
case "$(printf '%s' "${MC_SIM_DISABLE_MANAGEMENT:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on|enabled)
    MC_SIM_MANAGEMENT_POLICY="off"
        ;;
esac
if [ -z "${MC_SIM_MANAGEMENT_POLICY:-}" ]; then
    if [ "${MC_SIM_DISABLE_MANAGEMENT:-1}" = "0" ]; then
        MC_SIM_MANAGEMENT_POLICY="enforce"
    else
        MC_SIM_MANAGEMENT_POLICY="off"
    fi
fi
case "$(printf '%s' "$MC_SIM_MANAGEMENT_POLICY" | tr '[:upper:]' '[:lower:]')" in
    off|disabled|0)
        MC_SIM_MANAGEMENT_POLICY="off"
        ;;
    shadow)
        MC_SIM_MANAGEMENT_POLICY="shadow"
        ;;
    enforce|enabled|on|1)
        MC_SIM_MANAGEMENT_POLICY="enforce"
        ;;
    *)
        echo "x MC_SIM_MANAGEMENT_POLICY must be off, shadow, or enforce." >&2
        exit 2
        ;;
esac
MINECRAFT_MANAGEMENT_REVIEW_MODE="$MC_SIM_MANAGEMENT_POLICY"
export MC_SIM_MANAGEMENT_POLICY MINECRAFT_MANAGEMENT_REVIEW_MODE
MC_SIM_BUILDER_PROVIDER="${MC_SIM_BUILDER_PROVIDER:-local}"
MC_SIM_BUILDER_FALLBACK="${MC_SIM_BUILDER_FALLBACK:-fail}"
MC_SIM_BUILDER_OPENROUTER_API_KEY="${MC_SIM_BUILDER_OPENROUTER_API_KEY:-${OPENROUTER_API_KEY:-}}"
MC_SIM_BUILDER_OPENROUTER_MODEL="${MC_SIM_BUILDER_OPENROUTER_MODEL:-}"
MC_SIM_BUILDER_MAX_CALLS_PER_RUN="${MC_SIM_BUILDER_MAX_CALLS_PER_RUN:-12}"
MC_SIM_BUILDER_MAX_CALLS_PER_AGENT="${MC_SIM_BUILDER_MAX_CALLS_PER_AGENT:-3}"
MC_SIM_BUILDER_MAX_USD_PER_RUN="${MC_SIM_BUILDER_MAX_USD_PER_RUN:-}"
MC_SIM_BUILDER_USD_PER_1K_INPUT="${MC_SIM_BUILDER_USD_PER_1K_INPUT:-}"
MC_SIM_BUILDER_USD_PER_1K_OUTPUT="${MC_SIM_BUILDER_USD_PER_1K_OUTPUT:-}"
MC_SIM_BUILD_MODE="${MC_SIM_BUILD_MODE:-single}"
MC_SIM_BUILD_MAX_PER_AGENT="${MC_SIM_BUILD_MAX_PER_AGENT:-6}"
MC_SIM_BUILD_COOLDOWN_SEC="${MC_SIM_BUILD_COOLDOWN_SEC:-300}"
MC_SIM_BUILD_ZONE_STRIDE="${MC_SIM_BUILD_ZONE_STRIDE:-12}"
MC_SIM_BUILD_CACHE_TTL_SEC="${MC_SIM_BUILD_CACHE_TTL_SEC:-3600}"
SOAK_PLAN_BUILD_BOTS="${SOAK_PLAN_BUILD_BOTS:-${MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST:-}}"
MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST="${MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST:-$SOAK_PLAN_BUILD_BOTS}"
MINECRAFT_PLAN_BUILD_ALLOWED_MATERIALS="${MINECRAFT_PLAN_BUILD_ALLOWED_MATERIALS:-${MC_SIM_PLAN_BUILD_ALLOWED_MATERIALS:-}}"
MINECRAFT_BUILD_FROM_PLAN_PLACE_REACH_BLOCKS="${MINECRAFT_BUILD_FROM_PLAN_PLACE_REACH_BLOCKS:-3.25}"
MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_TOLERANCE_BLOCKS="${MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_TOLERANCE_BLOCKS:-1}"
SOAK_BUILDER_PROVIDER="${SOAK_BUILDER_PROVIDER:-$MC_SIM_BUILDER_PROVIDER}"
SOAK_SAFE_TERRAIN_ACTIONS="${SOAK_SAFE_TERRAIN_ACTIONS:-0}"
SOAK_EASY_SPAWN="${SOAK_EASY_SPAWN:-0}"
SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS="${SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS:-5}"
if [ "$SOAK_EASY_SPAWN" = "1" ] && [ "$MC_SIM_BUILD_MODE" = "settlement" ]; then
    EASY_SETUP_BOUNDARY="${EASY_SETUP_BOUNDARY:-none}"
    EASY_SETUP_MEADOW_RADIUS="${EASY_SETUP_MEADOW_RADIUS:-96}"
    EASY_SETUP_ANIMALS="${EASY_SETUP_ANIMALS:-1}"
    MC_SIM_SETTLEMENT_ORIGIN="${MC_SIM_SETTLEMENT_ORIGIN:-0,64,0}"
else
    EASY_SETUP_BOUNDARY="${EASY_SETUP_BOUNDARY:-}"
    EASY_SETUP_MEADOW_RADIUS="${EASY_SETUP_MEADOW_RADIUS:-}"
    EASY_SETUP_ANIMALS="${EASY_SETUP_ANIMALS:-}"
fi
export EASY_SETUP_BOUNDARY EASY_SETUP_MEADOW_RADIUS EASY_SETUP_ANIMALS MC_SIM_SETTLEMENT_ORIGIN
SOAK_SETTINGS_INIT_MESSAGE="$SOAK_INIT_MESSAGE"
if [ "$SOAK_EASY_SPAWN" = "1" ]; then
    SOAK_SETTINGS_INIT_MESSAGE=""
fi
MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT="${MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT:-0}"
if [ "$SOAK_EASY_SPAWN" = "1" ] && [ -n "$SOAK_INIT_MESSAGE" ]; then
    MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT=1
fi
SOAK_MIN_INTENT_TO_COMMAND_RATIO="${SOAK_MIN_INTENT_TO_COMMAND_RATIO:-0.6}"
SOAK_MIN_PARSE_SUCCESS="${SOAK_MIN_PARSE_SUCCESS:-0.8}"
SOAK_MIN_EXECUTION_RATE="${SOAK_MIN_EXECUTION_RATE:-0.7}"
SOAK_MIN_VERIFIED_SUCCESS="${SOAK_MIN_VERIFIED_SUCCESS:-0.5}"
SOAK_RELIABILITY_MIN_INTENTS="${SOAK_RELIABILITY_MIN_INTENTS:-5}"
SOAK_RELIABILITY_FAIL_ON_VIOLATION="${SOAK_RELIABILITY_FAIL_ON_VIOLATION:-1}"
SOAK_MONITOR_STALL_SECONDS="${SOAK_MONITOR_STALL_SECONDS:-120}"
SOAK_MONITOR_LLM_IDLE_SECONDS="${SOAK_MONITOR_LLM_IDLE_SECONDS:-120}"
SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD="${SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD:-16}"
SOAK_ACCEPTANCE_WARMUP_SECONDS="${SOAK_ACCEPTANCE_WARMUP_SECONDS:-300}"
SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO="${SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO:-0.5}"
SOAK_REQUIRE_DIRECTOR_ACCEPTANCE="${SOAK_REQUIRE_DIRECTOR_ACCEPTANCE:-1}"
MINECRAFT_ALLOW_DESTRUCTIVE_PATHS="${MINECRAFT_ALLOW_DESTRUCTIVE_PATHS:-1}"
MC_HEARTBEAT_ENABLED="${MC_HEARTBEAT_ENABLED:-1}"
MC_HEARTBEAT_TICK_MS="${MC_HEARTBEAT_TICK_MS:-5000}"
MC_HEARTBEAT_IDLE_MS="${MC_HEARTBEAT_IDLE_MS:-90000}"
MC_HEARTBEAT_COOLDOWN_MS="${MC_HEARTBEAT_COOLDOWN_MS:-45000}"
MC_HEARTBEAT_STALE_ACTION_MS="${MC_HEARTBEAT_STALE_ACTION_MS:-180000}"
MC_HEARTBEAT_MAX_NO_COMMAND="${MC_HEARTBEAT_MAX_NO_COMMAND:-3}"
MC_SIM_MEMORY_CONTEXT_ENABLED="${MC_SIM_MEMORY_CONTEXT_ENABLED:-1}"
MC_SIM_MEMORY_RECALL_LIMIT="${MC_SIM_MEMORY_RECALL_LIMIT:-3}"
MC_SIM_MEMORY_CORE_MAX_CHARS="${MC_SIM_MEMORY_CORE_MAX_CHARS:-1500}"
MC_SIM_MEMORY_RECALL_MAX_CHARS="${MC_SIM_MEMORY_RECALL_MAX_CHARS:-1200}"
MC_SIM_SHARED_STATE_ENABLED="${MC_SIM_SHARED_STATE_ENABLED:-1}"
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
        --profile)
            [ "$#" -ge 2 ] || { echo "x --profile needs a value" >&2; exit 2; }
            SOAK_PROFILE="$2"
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

apply_soak_profile() {
    case "$SOAK_PROFILE" in
        default|embodied)
            SOAK_PROFILE="default"
            ;;
        director_v2)
            CONVERSATION_MODE="director_v2"
            DIRECTOR_V2_GATE="1"
            MINECRAFT_LLM_QUEUE_PROXY="1"
            ;;
        *)
            fail "SOAK_PROFILE/--profile must be default or director_v2."
            exit 2
            ;;
    esac
    export SOAK_PROFILE CONVERSATION_MODE DIRECTOR_V2_GATE MINECRAFT_LLM_QUEUE_PROXY
}

apply_soak_profile

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

preflight_builder_routing() {
    case "$MC_SIM_BUILDER_PROVIDER" in
        local|openrouter) ;;
        *)
            fail "MC_SIM_BUILDER_PROVIDER must be local or openrouter."
            return 2
            ;;
    esac
    case "$MC_SIM_BUILDER_FALLBACK" in
        fail|local) ;;
        *)
            fail "MC_SIM_BUILDER_FALLBACK must be fail or local."
            return 2
            ;;
    esac
    if [ "$MC_SIM_BUILDER_PROVIDER" = "openrouter" ] \
        && [ "$MC_SIM_BUILDER_FALLBACK" != "local" ]; then
        if [ -z "$MC_SIM_BUILDER_OPENROUTER_API_KEY" ] || [ -z "$MC_SIM_BUILDER_OPENROUTER_MODEL" ]; then
            fail "OpenRouter builder routing requires MC_SIM_BUILDER_OPENROUTER_API_KEY and MC_SIM_BUILDER_OPENROUTER_MODEL (or set MC_SIM_BUILDER_FALLBACK=local)."
            return 1
        fi
    fi
    return 0
}

check_smoke_builder_openrouter() {
    [ "$SOAK_BUILDER_PROVIDER" = "openrouter" ] || return 0
    preflight_builder_routing || return $?
    info "preflight: OpenRouter builder smoke"
    MC_SIM_BUILDER_PROVIDER=openrouter \
        MC_SIM_BUILDER_FALLBACK=fail \
        MC_SIM_BUILDER_OPENROUTER_API_KEY="$MC_SIM_BUILDER_OPENROUTER_API_KEY" \
        MC_SIM_BUILDER_OPENROUTER_MODEL="$MC_SIM_BUILDER_OPENROUTER_MODEL" \
        MC_SIM_BUILDER_MAX_CALLS_PER_RUN="$MC_SIM_BUILDER_MAX_CALLS_PER_RUN" \
        MC_SIM_BUILDER_MAX_CALLS_PER_AGENT="$MC_SIM_BUILDER_MAX_CALLS_PER_AGENT" \
        MC_SIM_BUILDER_MAX_USD_PER_RUN="$MC_SIM_BUILDER_MAX_USD_PER_RUN" \
        MC_SIM_BUILDER_USD_PER_1K_INPUT="$MC_SIM_BUILDER_USD_PER_1K_INPUT" \
        MC_SIM_BUILDER_USD_PER_1K_OUTPUT="$MC_SIM_BUILDER_USD_PER_1K_OUTPUT" \
        node --experimental-default-type=module --input-type=module <<'NODE'
import {
    builderProviderSnapshot,
    resetBuilderProviderState,
    resolveBuilderModel,
} from './scripts/minecraft/fork-src/agent/skills/builder_provider.js';

resetBuilderProviderState();
const agent = { name: 'soak-builder-smoke', prompter: { code_model: null } };
const resolved = resolveBuilderModel(agent);
const content = await resolved.sendRequest(
    [{ role: 'user', content: 'Return a one-block marker plan.' }],
    'Return strict JSON: {"blocks":[{"dx":0,"dy":0,"dz":0,"block_type":"oak_log"}]}.',
    { purpose: 'plan_generation', traceId: 'trace-soak-builder-openrouter-smoke' },
);
const snapshot = builderProviderSnapshot(agent);
if (resolved.provider !== 'openrouter' || snapshot.request_count_run < 1) {
    throw new Error(`expected one OpenRouter builder call, got ${JSON.stringify(snapshot)}`);
}
process.stdout.write(JSON.stringify({ provider: resolved.provider, content, snapshot }) + '\n');
NODE
    ok "OpenRouter builder smoke recorded a paid builder call"
}

check_smoke_builder_local() {
    [ "$SOAK_BUILDER_PROVIDER" = "openrouter" ] && return 0
    info "preflight: local builder smoke"
    MC_SIM_BUILDER_PROVIDER=local \
        MC_SIM_BUILDER_MAX_CALLS_PER_RUN="$MC_SIM_BUILDER_MAX_CALLS_PER_RUN" \
        MC_SIM_BUILDER_MAX_CALLS_PER_AGENT="$MC_SIM_BUILDER_MAX_CALLS_PER_AGENT" \
        node --experimental-default-type=module --input-type=module <<'NODE'
import {
    builderProviderSnapshot,
    resetBuilderProviderState,
    resolveBuilderModel,
} from './scripts/minecraft/fork-src/agent/skills/builder_provider.js';

resetBuilderProviderState();
const agent = {
    name: 'soak-builder-local-smoke',
    prompter: {
        code_model: {
            model_name: 'local/smoke',
            async sendRequest() {
                return '{"blocks":[{"dx":0,"dy":0,"dz":0,"block_type":"oak_log"}]}';
            },
        },
    },
};
const resolved = resolveBuilderModel(agent);
const snapshot = builderProviderSnapshot(agent);
if (resolved.provider !== 'local' || snapshot.request_count_run !== 0) {
    throw new Error(`expected local builder with zero OpenRouter calls, got ${JSON.stringify(snapshot)}`);
}
process.stdout.write(JSON.stringify({ provider: resolved.provider, snapshot }) + '\n');
NODE
    ok "Local builder smoke kept OpenRouter call count at zero"
}

check_smoke_builder_routing() {
    case "$SOAK_BUILDER_PROVIDER" in
        local) check_smoke_builder_local ;;
        openrouter) check_smoke_builder_openrouter ;;
        *)
            fail "SOAK_BUILDER_PROVIDER must be local or openrouter."
            return 2
            ;;
    esac
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
    [ -s "$SCRIPT_DIR/build_director_acceptance_report.py" ] || { fail "missing director acceptance report builder: $SCRIPT_DIR/build_director_acceptance_report.py"; problems=1; }
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
    grep -q 'restart_count' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document restart_count"
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
    grep -q 'director-v2-acceptance-soak.md' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must link the Director V2 acceptance soak"
        problems=1
    }
    grep -q 'Heartbeat & Idle Recovery' "$REPO_ROOT/docs/minecraft/multi-agent-soak.md" 2> /dev/null || {
        fail "multi-agent soak doc must document autonomous heartbeat idle recovery"
        problems=1
    }
    [ -s "$REPO_ROOT/docs/minecraft/director-v2-acceptance-soak.md" ] || {
        fail "Director V2 acceptance soak doc is missing"
        problems=1
    }
    grep -q 'acceptance-report.json' "$REPO_ROOT/docs/minecraft/director-v2-acceptance-soak.md" 2> /dev/null || {
        fail "Director V2 acceptance soak doc must document acceptance-report.json"
        problems=1
    }
    grep -q '#511' "$REPO_ROOT/docs/minecraft/director-v2-acceptance-soak.md" 2> /dev/null || {
        fail "Director V2 acceptance soak doc must name downstream blockers"
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

    # E21 keystone wiring: the settlement objective seed must be invoked before
    # the launch_bot loop, gated to settlement mode, and share one exported
    # LTAG_SIMULATION_ID with the bots. Markers are split with '' so these checks
    # never match their own source lines.
    [ -s "$SCRIPT_DIR/seed_settlement_objectives.py" ] || {
        fail "missing settlement objective seed script: $SCRIPT_DIR/seed_settlement_objectives.py"
        problems=1
    }
    local seed_marker loop_marker gate_marker export_marker seed_line loop_line
    seed_marker='seed_settlement''_objectives.py'
    loop_marker='launch_bot ''"$bot" "$BOT_INDEX"'
    gate_marker='settlement-mode only: seed shared ''objective board'
    export_marker='export LTAG_''SIMULATION_ID'
    seed_line="$(grep -nF -m1 "$seed_marker" "$SCRIPT_DIR/soak.sh" | cut -d: -f1 || true)"
    loop_line="$(grep -nF -m1 "$loop_marker" "$SCRIPT_DIR/soak.sh" | cut -d: -f1 || true)"
    if [ -n "$seed_line" ] && [ -n "$loop_line" ] && [ "$seed_line" -lt "$loop_line" ]; then
        ok "settlement objective seed runs before bot launch ($seed_line < $loop_line)"
    else
        fail "settlement objective seed must be invoked before the launch_bot loop"
        problems=1
    fi
    if grep -qF "$gate_marker" "$SCRIPT_DIR/soak.sh"; then
        ok "settlement objective seed is gated to settlement mode"
    else
        fail "settlement objective seed settlement-mode gate missing"
        problems=1
    fi
    if grep -qF "$export_marker" "$SCRIPT_DIR/soak.sh"; then
        ok "LTAG_SIMULATION_ID is exported for the seed and bots"
    else
        fail "LTAG_SIMULATION_ID export missing"
        problems=1
    fi

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
    info "profile:        $SOAK_PROFILE"
    info "log root:       $SOAK_LOG_ROOT"
    info "work root:      ${SOAK_WORK_ROOT:-<per-run temp>}"
    info "bridge:         $MINECRAFT_BRIDGE_URL"
    info "conversation:   mode=${CONVERSATION_MODE} director_gate=${DIRECTOR_V2_GATE}"
    info "backend health: $BACKEND_HEALTH_URL"
    info "LM Studio:      $LOCAL_LLM_BASE_URL"
    if [ "$MINECRAFT_LLM_QUEUE_PROXY" = "1" ]; then
        info "LM queue:       enabled concurrency=${MINECRAFT_LLM_CONCURRENCY} upstream=${LOCAL_LLM_UPSTREAM_URL} retries=${MINECRAFT_LLM_RETRY_ATTEMPTS} timeout=${MINECRAFT_LLM_REQUEST_TIMEOUT_SECONDS}s"
    else
        info "LM queue:       disabled"
    fi
    info "chat model:     ${LOCAL_LLM_MODEL:-<unset>}"
    info "build model:    ${LOCAL_LLM_MODEL_BUILDING:-${LOCAL_LLM_MODEL:-<unset>}}"
    info "builder route:  provider=${MC_SIM_BUILDER_PROVIDER} fallback=${MC_SIM_BUILDER_FALLBACK} openrouter_model=${MC_SIM_BUILDER_OPENROUTER_MODEL:-<unset>} caps run=${MC_SIM_BUILDER_MAX_CALLS_PER_RUN} agent=${MC_SIM_BUILDER_MAX_CALLS_PER_AGENT} usd=${MC_SIM_BUILDER_MAX_USD_PER_RUN:-<unset>}"
    info "build governor: max_per_agent=${MC_SIM_BUILD_MAX_PER_AGENT} cooldown=${MC_SIM_BUILD_COOLDOWN_SEC}s zone_stride=${MC_SIM_BUILD_ZONE_STRIDE} cache_ttl=${MC_SIM_BUILD_CACHE_TTL_SEC}s"
    info "plan builders:  ${MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST:-<unrestricted>}"
    info "management:    policy=${MC_SIM_MANAGEMENT_POLICY}"
    info "hourly cap:     \$${SOAK_AGENT_HOURLY_CAP_USD} per agent"
    info "auto-start MC:  $SOAK_START_MINECRAFT_IF_DOWN"
    info "keep MC alive:  $SOAK_KEEP_MINECRAFT_RUNNING"
    info "MC boot wait:   ${SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS}s"
    info "MC target:      ${MC_HOST:-127.0.0.1}:${MC_PORT:-${SERVER_PORT:-25565}}"
    info "server dir:     ${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
    info "world config:   ${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
    info "MindServer:     ${SOAK_MINDSERVER_BASE_PORT}+ per bot"
    info "behavior:       require=${SOAK_REQUIRE_BEHAVIOR_GATE}; movement>=${SOAK_MIN_MOVEMENT_PER_AGENT}/agent; deaths<=${SOAK_MAX_DEATHS_PER_AGENT}/agent; stuck<=${SOAK_MAX_STUCK_PER_AGENT}/agent; restarts<=${SOAK_MAX_RESTARTS_PER_AGENT}/agent; chat>=${SOAK_MIN_PUBLIC_CHAT_COHORT}; gather+build>=${SOAK_MIN_GATHER_OR_BUILD_COHORT}; shared>=${SOAK_MIN_SHARED_ARTIFACTS}"
    info "reliability:    intent>=${SOAK_MIN_INTENT_TO_COMMAND_RATIO} parse>=${SOAK_MIN_PARSE_SUCCESS} exec>=${SOAK_MIN_EXECUTION_RATE} verified>=${SOAK_MIN_VERIFIED_SUCCESS} min_intents=${SOAK_RELIABILITY_MIN_INTENTS} fail=${SOAK_RELIABILITY_FAIL_ON_VIOLATION}"
    info "heartbeat:      enabled=${MC_HEARTBEAT_ENABLED} idle=${MC_HEARTBEAT_IDLE_MS}ms cooldown=${MC_HEARTBEAT_COOLDOWN_MS}ms stale_action=${MC_HEARTBEAT_STALE_ACTION_MS}ms max_no_command=${MC_HEARTBEAT_MAX_NO_COMMAND}"
    info "memory context: enabled=${MC_SIM_MEMORY_CONTEXT_ENABLED} recall_limit=${MC_SIM_MEMORY_RECALL_LIMIT} core_max=${MC_SIM_MEMORY_CORE_MAX_CHARS} recall_max=${MC_SIM_MEMORY_RECALL_MAX_CHARS} exclude=${MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS:-management,alpha}"
    info "shared state:  enabled=${MC_SIM_SHARED_STATE_ENABLED}"
    info "timeline:       timeline.ndjson + timeline-totals.json"
    info "monitor:        monitor.html (stall>${SOAK_MONITOR_STALL_SECONDS}s llm_idle>${SOAK_MONITOR_LLM_IDLE_SECONDS}s)"
    if [ "$SOAK_PROFILE" = "director_v2" ]; then
        info "acceptance:     queue<${SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD} after ${SOAK_ACCEPTANCE_WARMUP_SECONDS}s; selected_ratio<=${SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO}; require=${SOAK_REQUIRE_DIRECTOR_ACCEPTANCE}"
        info "evidence:       director-decisions.ndjson tool-parity.ndjson macro-evidence.ndjson memory-digest.ndjson acceptance-report.json"
    fi
    if [ "$SOAK_BLOCK_PRIVATE_CONVERSATIONS" = "1" ]; then
        info "private conv:   blocked (!startConversation/!endConversation)"
    else
        info "private conv:   allowed"
    fi
    if [ "$SOAK_BLOCK_SLOW_SIM_ACTIONS" = "1" ]; then
        info "slow actions:   blocked (!newAction/!observe/!navigate/plan actions)"
    else
        info "slow actions:   allowed"
    fi
    if [ "$SOAK_BLOCK_NEW_ACTIONS" = "1" ]; then
        info "newAction:      blocked (!newAction only; plan actions still available)"
    fi
    if [ "$SOAK_BLOCK_EXECUTE_CODE_ACTIONS" = "1" ]; then
        info "execute code:   blocked (!executeCode)"
    else
        info "execute code:   allowed"
    fi
    if [ "$SOAK_ALLOW_BUILDER_NEW_ACTIONS" = "1" ]; then
        info "newAction:      builder-only enabled ($SOAK_BUILDER_BOTS)"
    else
        info "newAction:      normal Mindcraft setting (allow_insecure_coding remains unchanged)"
    fi
    if [ "$SOAK_SAFE_TERRAIN_ACTIONS" = "1" ]; then
        info "safe terrain:   enabled (no auto elbow-room/pickup/torch modes; no destructive pathing; blocks !place/!break/!observe/!collectBlocks)"
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
        if [ "$SOAK_EASY_SPAWN" = "1" ]; then
            info "init delivery:  after easy-spawn starter kit"
        fi
    else
        info "init prompt:    <none>"
    fi
    info "bots:           $SOAK_BOTS"
    info "cost agents:    $SOAK_COST_AGENTS"
    info "Mindcraft base: $MINDCRAFT_DIR"
    info "isolation:      temp local clones with node_modules symlink"
}

build_settings_json() {
    if [ -z "$SOAK_SETTINGS_INIT_MESSAGE" ] \
        && [ "$SOAK_BLOCK_PRIVATE_CONVERSATIONS" != "1" ] \
        && [ "$SOAK_BLOCK_SLOW_SIM_ACTIONS" != "1" ] \
        && [ "$SOAK_BLOCK_NEW_ACTIONS" != "1" ] \
        && [ "$SOAK_SAFE_TERRAIN_ACTIONS" != "1" ]; then
        return 0
    fi
    SETTINGS_JSON="$(
        SETTINGS_JSON_CURRENT="${SETTINGS_JSON:-}" \
        SOAK_SETTINGS_INIT_MESSAGE="$SOAK_SETTINGS_INIT_MESSAGE" \
        SOAK_BLOCK_PRIVATE_CONVERSATIONS="$SOAK_BLOCK_PRIVATE_CONVERSATIONS" \
        SOAK_BLOCK_SLOW_SIM_ACTIONS="$SOAK_BLOCK_SLOW_SIM_ACTIONS" \
        SOAK_BLOCK_NEW_ACTIONS="$SOAK_BLOCK_NEW_ACTIONS" \
        SOAK_SAFE_TERRAIN_ACTIONS="$SOAK_SAFE_TERRAIN_ACTIONS" \
        SOAK_BLOCK_EXECUTE_CODE_ACTIONS="$SOAK_BLOCK_EXECUTE_CODE_ACTIONS" \
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

if (process.env.SOAK_SETTINGS_INIT_MESSAGE && !Object.hasOwn(settings, 'init_message')) {
    settings.init_message = process.env.SOAK_SETTINGS_INIT_MESSAGE;
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
        '!planAndBuild',
    ]) {
        if (!blocked.includes(command)) blocked.push(command);
    }
    settings.blocked_actions = blocked;
}

if (process.env.SOAK_BLOCK_NEW_ACTIONS === '1') {
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [...baseBlockedActions];
    if (!blocked.includes('!newAction')) blocked.push('!newAction');
    settings.blocked_actions = blocked;
}

if (process.env.SOAK_SAFE_TERRAIN_ACTIONS === '1') {
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [...baseBlockedActions];
    for (const command of ["!break", "!observe", "!place", "!collectBlocks", "!collectAllBlocks"]) {
        if (!blocked.includes(command)) blocked.push(command);
    }
    settings.blocked_actions = blocked;
}

if (process.env.SOAK_BLOCK_EXECUTE_CODE_ACTIONS === '1') {
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [...baseBlockedActions];
    if (!blocked.includes('!executeCode')) blocked.push('!executeCode');
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
    SETTINGS_JSON_INPUT="$SETTINGS_JSON" BOT_ID="$bot" SOAK_SETTINGS_INIT_MESSAGE="$SOAK_SETTINGS_INIT_MESSAGE" SOAK_ALLOW_BUILDER_NEW_ACTIONS="$SOAK_ALLOW_BUILDER_NEW_ACTIONS" SOAK_BUILDER_BOTS="$SOAK_BUILDER_BOTS" \
        node --input-type=module <<'NODE'
const settings = JSON.parse(process.env.SETTINGS_JSON_INPUT);
if (process.env.BOT_ID === 'bridge' && process.env.SOAK_SETTINGS_INIT_MESSAGE) {
    settings.init_message = '';
}
if (process.env.SOAK_ALLOW_BUILDER_NEW_ACTIONS === '1') {
    const botId = String(process.env.BOT_ID || '').toLowerCase();
    const builderBots = new Set(
        String(process.env.SOAK_BUILDER_BOTS || '')
            .split(/\s+/)
            .map((item) => item.trim().toLowerCase())
            .filter(Boolean),
    );
    const blocked = Array.isArray(settings.blocked_actions)
        ? [...settings.blocked_actions]
        : [];
    if (builderBots.has(botId)) {
        settings.allow_insecure_coding = true;
    } else {
        settings.allow_insecure_coding = false;
        if (!blocked.includes('!newAction')) blocked.push('!newAction');
    }
    settings.blocked_actions = blocked;
}
process.stdout.write(JSON.stringify(settings));
NODE
}

compute_behavior_table() {
    local run_dir="${1:-$RUN_DIR}"
    mkdir -p "$run_dir"
    "${PYTHON:-python3}" - "$run_dir" <<'PY'
from __future__ import annotations

import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_AGENTS = "alpha vera rex aurora pixel fork sentinel grok"


def int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc


run_dir = Path(sys.argv[1])
agent_source = (
    os.environ.get("SOAK_BEHAVIOR_AGENTS")
    or os.environ.get("SOAK_BOTS")
    or os.environ.get("SOAK_COST_AGENTS")
    or DEFAULT_AGENTS
)
agents = [
    agent.strip().lower()
    for agent in agent_source.split()
    if agent.strip() and agent.strip().lower() != "bridge"
]
agent_set = set(agents)

min_movement = int_env("SOAK_MIN_MOVEMENT_PER_AGENT", 5)
max_deaths = int_env("SOAK_MAX_DEATHS_PER_AGENT", 2)
max_stuck = int_env("SOAK_MAX_STUCK_PER_AGENT", 5)
max_restarts = int_env("SOAK_MAX_RESTARTS_PER_AGENT", 1)
min_public_chat = int_env("SOAK_MIN_PUBLIC_CHAT_COHORT", 10)
min_gather_or_build = int_env("SOAK_MIN_GATHER_OR_BUILD_COHORT", 3)
min_shared_artifacts = int_env("SOAK_MIN_SHARED_ARTIFACTS", 1)
settlement_mode = os.environ.get("MC_SIM_BUILD_MODE", "").strip().lower() == "settlement"

movement_re = re.compile(r"!(move|goToPlayer|goToCoordinates|searchForBlock|searchForEntity|navigate)\b", re.IGNORECASE)
death_re = re.compile(r"\b(died|death|respawn(?:ed)?)\b", re.IGNORECASE)
drowning_re = re.compile(r"\bdrown(?:ed|ing)?\b", re.IGNORECASE)
stuck_re = re.compile(r"\b(stuck|cannot reach|path.*failed|unable to (move|reach))\b", re.IGNORECASE)
stuck_prompt_context_re = re.compile(
    r"^\s*(?:\*\*\s*Danger/stuck reports\s*:\s*\*\*|Memory updated to:|Local observations:)",
    re.IGNORECASE,
)
restart_re = re.compile(
    r"(Exiting\.|\bprocess exited with code\s+[1-9]\d*\b|\brejoining\b|\bbot disconnected\b|"
    r"\bsupervisor.*restart\b|\brestart(?:ed|ing)?\b|heartbeat\.halted|heartbeat.*max-no-command)",
    re.IGNORECASE,
)
timestamp_re = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-][0-2]\d:?[0-5]\d)?)"
)
dig_hole_re = re.compile(r"(dig.?hole|stuck in (a )?hole|trapped)", re.IGNORECASE)
gather_re = re.compile(r"!(collectBlocks|collectAllBlocks|consume|equip|smeltItem)\b", re.IGNORECASE)
build_re = re.compile(r"!(place|placeHere|placeBlock|build|buildFromPlan|planAndBuild)\b", re.IGNORECASE)
distress_re = re.compile(
    r"(distress_reported|distress\.reported|\"operation\"\s*:\s*\"danger_report\"|"
    r"shared_state\.write.*danger_report)",
    re.IGNORECASE,
)
distress_resolved_re = re.compile(
    r"(distress_resolved|distress\.resolved|\"operation\"\s*:\s*\"danger_resolve\"|"
    r"recovery_status[\"']?\s*[:=]\s*[\"']?(resolved|escaped|teleported))",
    re.IGNORECASE,
)
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


def count_stuck(lines: list[str]) -> int:
    return sum(
        1
        for line in lines
        if stuck_re.search(line) and not stuck_prompt_context_re.search(line)
    )


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
    "total_unresolved_distress": 0,
    "total_restarts": 0,
    "total_restart_recurrences": 0,
}


def timestamp_epoch(line: str) -> float | None:
    match = timestamp_re.search(line)
    if not match:
        return None
    raw = match.group("ts").replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", raw):
        raw = raw[:-2] + ":" + raw[-2:]
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def restart_epochs(lines: list[str]) -> list[float]:
    epochs = []
    for line in lines:
        if restart_re.search(line):
            epoch = timestamp_epoch(line)
            if epoch is not None:
                epochs.append(epoch)
    return sorted(epochs)


def has_recurrent_restart(lines: list[str], window_seconds: int = 300) -> bool:
    epochs = restart_epochs(lines)
    for previous, current in zip(epochs, epochs[1:]):
        if current - previous <= window_seconds:
            return True
    return False

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
    stuck = count_stuck(counter_lines)
    distress_reports = count_regex(counter_lines, distress_re)
    distress_resolved = count_regex(counter_lines, distress_resolved_re)
    unresolved_distress = max(0, distress_reports - distress_resolved)
    restart_count = count_regex(counter_lines, restart_re)
    recurrent_restarts = 1 if has_recurrent_restart(counter_lines) else 0
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
    active_actions = movement + gather + build
    settlement_builder_active = settlement_mode and build > 0 and active_actions >= min_movement
    if movement < min_movement and not settlement_builder_active:
        agent_unmet.append(f"agent {agent} movement expected >= {min_movement} got {movement}")
    if deaths > max_deaths:
        agent_unmet.append(f"agent {agent} deaths expected <= {max_deaths} got {deaths}")
    if stuck > max_stuck:
        agent_unmet.append(f"agent {agent} stuck expected <= {max_stuck} got {stuck}")
    if restart_count > max_restarts:
        agent_unmet.append(
            f"agent {agent} restarts expected <= {max_restarts} got {restart_count}"
        )
    if unresolved_distress:
        agent_unmet.append(f"agent {agent} unresolved distress expected 0 got {unresolved_distress}")
    if recurrent_restarts:
        agent_unmet.append(f"agent {agent} repeated restarts within 300s")
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
        "unresolved_distress": unresolved_distress,
        "restart_count": restart_count,
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
    totals["total_unresolved_distress"] += unresolved_distress
    totals["total_restarts"] += restart_count
    totals["total_restart_recurrences"] += recurrent_restarts


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
    "unresolved_distress",
    "restart_count",
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
        echo "total_restarts: $(behavior_metric "$run_dir" total_restarts)"
        echo "total_restart_recurrences: $(behavior_metric "$run_dir" total_restart_recurrences)"
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
    check_smoke_builder_routing || exit $?
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

if [ -z "${LOCAL_LLM_MODEL:-}" ]; then
    fail "LOCAL_LLM_MODEL is not set. List local ids with: pnpm llm:local --list-only"
    exit 1
fi
export LOCAL_LLM_MODEL_BUILDING="${LOCAL_LLM_MODEL_BUILDING:-$LOCAL_LLM_MODEL}"
preflight_builder_routing || exit $?

if [ -z "${MINECRAFT_BRIDGE_TOKEN:-}" ]; then
    fail "MINECRAFT_BRIDGE_TOKEN is not set; bridge auth is fail-closed."
    exit 1
fi

NODE_MAJOR="$(node_major || true)"
if [ "$NODE_MAJOR" != "$REQUIRED_NODE_MAJOR" ]; then
    fail "Node ${NODE_MAJOR:-<missing>} found, but Mindcraft soak requires Node $REQUIRED_NODE_MAJOR LTS."
    exit 1
fi
check_smoke_builder_routing || exit $?
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
# One explicit simulation scope shared by the objective seed step and every bot.
# python_bridge.js / memory_context.js resolve their Redis scope from
# LTAG_SIMULATION_ID (falling back to the all-zero default), so the seed and the
# bots MUST agree on a single UUID or the seed writes to a scope no bot reads.
if [ -z "${LTAG_SIMULATION_ID:-}" ]; then
    LTAG_SIMULATION_ID="$("${PYTHON:-python3}" -c \
        'import sys, uuid; print(uuid.uuid5(uuid.NAMESPACE_URL, "ltag-soak/" + sys.argv[1]))' \
        "$RUN_ID")"
fi
export LTAG_SIMULATION_ID
mkdir -p "$SOAK_LOG_ROOT"
SOAK_LOG_ROOT="$(cd -- "$SOAK_LOG_ROOT" && pwd)"
RUN_DIR="$SOAK_LOG_ROOT/$RUN_ID"
SOAK_WORK_ROOT="${SOAK_WORK_ROOT:-${TMPDIR:-/tmp}/livestreamtoagi-soak-worktrees/$RUN_ID}"
mkdir -p "$SOAK_WORK_ROOT"
SOAK_WORK_ROOT="$(cd -- "$SOAK_WORK_ROOT" && pwd)"
mkdir -p "$RUN_DIR"/{bots,preflight,logs,timeline-raw}
printf '%s\n' "$SOAK_WORK_ROOT" > "$RUN_DIR/worktrees.path"
PID_FILE="$RUN_DIR/pids.tsv"
TAIL_PID_FILE="$RUN_DIR/tail-pids.txt"
LLM_PROXY_PID_FILE="$RUN_DIR/lmstudio-queue-proxy.pid"
EARLY_EXIT_FILE="$RUN_DIR/early-exits.tsv"
HEARTBEAT_HALT_FILE="$RUN_DIR/heartbeat-halts.tsv"
: > "$PID_FILE"
: > "$TAIL_PID_FILE"
: > "$EARLY_EXIT_FILE"
: > "$HEARTBEAT_HALT_FILE"

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
        echo "ltag_simulation_id=$LTAG_SIMULATION_ID"
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
        echo "local_llm_upstream_url=$LOCAL_LLM_UPSTREAM_URL"
        echo "minecraft_llm_queue_proxy=$MINECRAFT_LLM_QUEUE_PROXY"
        echo "minecraft_llm_concurrency=$MINECRAFT_LLM_CONCURRENCY"
        echo "minecraft_llm_retry_attempts=$MINECRAFT_LLM_RETRY_ATTEMPTS"
        echo "minecraft_llm_retry_delay_seconds=$MINECRAFT_LLM_RETRY_DELAY_SECONDS"
        echo "minecraft_llm_request_timeout_seconds=$MINECRAFT_LLM_REQUEST_TIMEOUT_SECONDS"
        echo "minecraft_llm_proxy_host=$MINECRAFT_LLM_PROXY_HOST"
        echo "minecraft_llm_proxy_port=$MINECRAFT_LLM_PROXY_PORT"
        echo "local_llm_model=$LOCAL_LLM_MODEL"
        echo "local_llm_model_building=$LOCAL_LLM_MODEL_BUILDING"
        echo "llm_smoke_timeout_seconds=$SOAK_LLM_SMOKE_TIMEOUT_SECONDS"
        echo "soak_profile=$SOAK_PROFILE"
        echo "builder_provider=$MC_SIM_BUILDER_PROVIDER"
        echo "management_policy=$MC_SIM_MANAGEMENT_POLICY"
        echo "minecraft_management_review_mode=$MINECRAFT_MANAGEMENT_REVIEW_MODE"
        echo "builder_openrouter_model=$MC_SIM_BUILDER_OPENROUTER_MODEL"
        echo "builder_openrouter_key_set=$([ -n "$MC_SIM_BUILDER_OPENROUTER_API_KEY" ] && echo yes || echo no)"
        echo "builder_fallback=$MC_SIM_BUILDER_FALLBACK"
        echo "builder_max_calls_per_run=$MC_SIM_BUILDER_MAX_CALLS_PER_RUN"
        echo "builder_max_calls_per_agent=$MC_SIM_BUILDER_MAX_CALLS_PER_AGENT"
        echo "builder_max_usd_per_run=$MC_SIM_BUILDER_MAX_USD_PER_RUN"
        echo "build_mode=$MC_SIM_BUILD_MODE"
        echo "build_max_per_agent=$MC_SIM_BUILD_MAX_PER_AGENT"
        echo "build_cooldown_sec=$MC_SIM_BUILD_COOLDOWN_SEC"
        echo "build_zone_stride=$MC_SIM_BUILD_ZONE_STRIDE"
        echo "build_cache_ttl_sec=$MC_SIM_BUILD_CACHE_TTL_SEC"
        echo "settlement_pending_owner_grace_ms=${MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS:-60000}"
        echo "settlement_owner_order=$MC_SIM_SETTLEMENT_OWNER_ORDER"
        echo "plan_build_agent_allowlist=$MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST"
        echo "plan_build_allowed_materials=${MINECRAFT_PLAN_BUILD_ALLOWED_MATERIALS:-starter}"
        echo "bridge_url=$MINECRAFT_BRIDGE_URL"
        echo "bridge_token_set=yes"
        echo "conversation_mode=$CONVERSATION_MODE"
        echo "director_v2_gate=$DIRECTOR_V2_GATE"
        echo "agent_hourly_cap_usd=$SOAK_AGENT_HOURLY_CAP_USD"
        echo "min_movement_per_agent=$SOAK_MIN_MOVEMENT_PER_AGENT"
        echo "max_deaths_per_agent=$SOAK_MAX_DEATHS_PER_AGENT"
        echo "max_stuck_per_agent=$SOAK_MAX_STUCK_PER_AGENT"
        echo "max_restarts_per_agent=$SOAK_MAX_RESTARTS_PER_AGENT"
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
        echo "block_new_actions=$SOAK_BLOCK_NEW_ACTIONS"
        echo "block_execute_code_actions=$SOAK_BLOCK_EXECUTE_CODE_ACTIONS"
        echo "allow_builder_new_actions=$SOAK_ALLOW_BUILDER_NEW_ACTIONS"
        echo "builder_bots=$SOAK_BUILDER_BOTS"
        echo "safe_terrain_actions=$SOAK_SAFE_TERRAIN_ACTIONS"
        echo "suppress_empty_init_chat=$MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT"
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
        echo "acceptance_queue_depth_threshold=$SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD"
        echo "acceptance_warmup_seconds=$SOAK_ACCEPTANCE_WARMUP_SECONDS"
        echo "acceptance_max_selected_agent_ratio=$SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO"
        echo "require_director_acceptance=$SOAK_REQUIRE_DIRECTOR_ACCEPTANCE"
        echo "allow_destructive_paths=$MINECRAFT_ALLOW_DESTRUCTIVE_PATHS"
        echo "heartbeat_enabled=$MC_HEARTBEAT_ENABLED"
        echo "heartbeat_tick_ms=$MC_HEARTBEAT_TICK_MS"
        echo "heartbeat_idle_ms=$MC_HEARTBEAT_IDLE_MS"
        echo "heartbeat_cooldown_ms=$MC_HEARTBEAT_COOLDOWN_MS"
        echo "heartbeat_stale_action_ms=$MC_HEARTBEAT_STALE_ACTION_MS"
        echo "heartbeat_max_no_command=$MC_HEARTBEAT_MAX_NO_COMMAND"
        echo "memory_context_enabled=$MC_SIM_MEMORY_CONTEXT_ENABLED"
        echo "memory_context_recall_limit=$MC_SIM_MEMORY_RECALL_LIMIT"
        echo "memory_context_core_max_chars=$MC_SIM_MEMORY_CORE_MAX_CHARS"
        echo "memory_context_recall_max_chars=$MC_SIM_MEMORY_RECALL_MAX_CHARS"
        echo "memory_context_exclude_agents=${MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS:-management,alpha}"
        echo "shared_state_enabled=$MC_SIM_SHARED_STATE_ENABLED"
        echo "minecraft_host=${MC_HOST:-127.0.0.1}"
        echo "minecraft_port=${MC_PORT:-${SERVER_PORT:-25565}}"
        echo "server_dir=${SERVER_DIR:-$REPO_ROOT/minecraft-server}"
        echo "world_config=${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
        if [ -n "$SOAK_INIT_MESSAGE" ]; then
            echo "init_message_set=yes"
            echo "init_message_chars=${#SOAK_INIT_MESSAGE}"
            if [ "$SOAK_EASY_SPAWN" = "1" ]; then
                echo "init_message_delivery=after_easy_spawn_starter_kit"
            else
                echo "init_message_delivery=settings_startup"
            fi
        else
            echo "init_message_set=no"
            echo "init_message_chars=0"
            echo "init_message_delivery=none"
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

start_lm_queue_proxy() {
    [ "$MINECRAFT_LLM_QUEUE_PROXY" = "1" ] || return 0
    local proxy_host="$MINECRAFT_LLM_PROXY_HOST"
    local proxy_port="$MINECRAFT_LLM_PROXY_PORT"
    local proxy_concurrency="$MINECRAFT_LLM_CONCURRENCY"
    local upstream_url="$LOCAL_LLM_UPSTREAM_URL"
    local proxy_url="http://${proxy_host}:${proxy_port}/v1"
    info "starting LM Studio queue proxy $proxy_url -> $upstream_url"
    MC_RUN_DIR="$RUN_DIR" "${PYTHON:-python3}" "$SCRIPT_DIR/lmstudio_queue_proxy.py" \
            --host "$proxy_host" \
            --port "$proxy_port" \
            --upstream "$upstream_url" \
            --concurrency "$proxy_concurrency" \
            --retry-attempts "$MINECRAFT_LLM_RETRY_ATTEMPTS" \
            --retry-delay-seconds "$MINECRAFT_LLM_RETRY_DELAY_SECONDS" \
            --request-timeout-seconds "$MINECRAFT_LLM_REQUEST_TIMEOUT_SECONDS" \
            --telemetry "$RUN_DIR/timeline-raw/llm-queue.ndjson" \
            > "$RUN_DIR/logs/lmstudio-queue-proxy.log" 2>&1 &
    echo "$!" > "$LLM_PROXY_PID_FILE"
    LOCAL_LLM_BASE_URL="$proxy_url"
    export LOCAL_LLM_BASE_URL LOCAL_LLM_UPSTREAM_URL MINECRAFT_LLM_CONCURRENCY
    export MINECRAFT_LLM_RETRY_ATTEMPTS MINECRAFT_LLM_RETRY_DELAY_SECONDS

    local proxy_pid
    proxy_pid="$(cat "$LLM_PROXY_PID_FILE" 2> /dev/null || true)"
    local waited=0
    while [ "$waited" -lt 20 ]; do
        if [ -n "$proxy_pid" ] && ! kill -0 "$proxy_pid" 2> /dev/null; then
            fail "LM Studio queue proxy exited before becoming ready; see $RUN_DIR/logs/lmstudio-queue-proxy.log"
            return 1
        fi
        if curl --connect-timeout 1 --max-time 2 -fsS "${proxy_url%/v1}/healthz" > "$RUN_DIR/preflight/lmstudio-queue-health.json" 2> /dev/null; then
            ok "LM Studio queue proxy ready"
            return 0
        fi
        if [ -n "$proxy_pid" ] && ! kill -0 "$proxy_pid" 2> /dev/null; then
            fail "LM Studio queue proxy exited before becoming ready; see $RUN_DIR/logs/lmstudio-queue-proxy.log"
            return 1
        fi
        sleep 0.25
        waited=$((waited + 1))
    done
    fail "LM Studio queue proxy did not become ready; see $RUN_DIR/logs/lmstudio-queue-proxy.log"
    return 1
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
    apply_suppress_empty_init_chat_patch "$dest"
    apply_director_tool_guard_patch "$dest"
    apply_safe_terrain_patch "$dest"
    printf '%s\n' "$dest"
}

apply_suppress_empty_init_chat_patch() {
    local dest="$1" agent_path
    [ "$MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT" = "1" ] || return 0
    agent_path="$dest/src/agent/agent.js"
    if [ ! -f "$agent_path" ]; then
        fail "Deferred init patch could not find Mindcraft agent file in $dest"
        return 1
    fi
    DEFERRED_INIT_AGENT_PATH="$agent_path" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.DEFERRED_INIT_AGENT_PATH;
const marker = 'LTAG deferred init suppress empty hello';
let source = readFileSync(path, 'utf8');
if (!source.includes(marker)) {
    const needle = `        else {
            this.openChat("Hello world! I am "+this.name);
        }
`;
    const patch = `        else {
            if (process.env.MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT === '1') { // ${marker}
                console.log(this.name, 'waiting for deferred init message');
            }
            else {
                this.openChat("Hello world! I am "+this.name);
            }
        }
`;
    if (!source.includes(needle)) {
        throw new Error('empty init hello chat anchor not found');
    }
    source = source.replace(needle, patch);
    writeFileSync(path, source);
}
NODE
}

apply_director_tool_guard_patch() {
    local dest="$1" commands_path
    commands_path="$dest/src/agent/commands/index.js"
    if [ ! -f "$commands_path" ]; then
        fail "Director tool guard patch could not find Mindcraft commands file in $dest"
        return 1
    fi
    DIRECTOR_TOOL_GUARD_COMMANDS_PATH="$commands_path" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const path = process.env.DIRECTOR_TOOL_GUARD_COMMANDS_PATH;
const marker = 'LTAG director v2 runtime tool guard';
let source = readFileSync(path, 'utf8');
if (!source.includes(marker)) {
    const needle = `        const command = getCommand(parsed.commandName);
        let numArgs = 0;
`;
    const patch = `        const command = getCommand(parsed.commandName);
        const directorContext = agent && agent.__ltagDirectorContext;
        const directorGrantedTools = Array.isArray(directorContext?.granted_tools)
            ? directorContext.granted_tools
            : null;
        const directorGateEnabled = process.env.DIRECTOR_V2_GATE !== '0'
            && String(process.env.CONVERSATION_MODE || '').trim().toLowerCase() === 'director_v2';
        if (directorGateEnabled && directorGrantedTools && String(parsed.commandName || '').startsWith('!')
            && !directorGrantedTools.includes(parsed.commandName)) { // ${marker}
            console.warn('Director V2 blocked unavailable command:', parsed.commandName);
            return \`Command \${parsed.commandName} is not available for this Director V2 turn.\`;
        }
        let numArgs = 0;
`;
    if (!source.includes(needle)) {
        throw new Error('executeCommand command lookup anchor not found');
    }
    source = source.replace(needle, patch);
    writeFileSync(path, source);
}
NODE
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
        export LOCAL_LLM_MODEL LOCAL_LLM_MODEL_BUILDING LOCAL_LLM_BASE_URL LOCAL_LLM_UPSTREAM_URL
        export MINECRAFT_LLM_QUEUE_PROXY MINECRAFT_LLM_CONCURRENCY
        export MINECRAFT_BRIDGE_URL MINECRAFT_BRIDGE_TOKEN
        export MC_RUN_DIR="$RUN_DIR"
        export MC_TIMELINE_NDJSON="$RUN_DIR/timeline-raw/$bot.ndjson"
        export MC_HOST MC_PORT
        export LTAG_RUN_ID="${LTAG_RUN_ID:-$RUN_ID}"
        export LTAG_SIMULATION_ID="${LTAG_SIMULATION_ID:-}"
        export LTAG_SIM_AGENTS="$SOAK_BOTS"
        export MINECRAFT_ALLOW_DESTRUCTIVE_PATHS
        export MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT
        export MC_SIM_MANAGEMENT_POLICY
        export MINECRAFT_MANAGEMENT_REVIEW_MODE MINECRAFT_MANAGEMENT_REVIEW_DEADLINE_MS
        export MC_SIM_MEMORY_CONTEXT_ENABLED MC_SIM_MEMORY_RECALL_LIMIT
        export MC_SIM_MEMORY_CORE_MAX_CHARS MC_SIM_MEMORY_RECALL_MAX_CHARS
        export MC_SIM_SHARED_STATE_ENABLED
        if [ -n "${MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS+x}" ]; then
            export MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS
        fi
        export MC_SIM_BUILDER_PROVIDER MC_SIM_BUILDER_FALLBACK
        export MC_SIM_BUILDER_OPENROUTER_API_KEY MC_SIM_BUILDER_OPENROUTER_MODEL
        export MC_SIM_BUILDER_MAX_CALLS_PER_RUN MC_SIM_BUILDER_MAX_CALLS_PER_AGENT
        export MC_SIM_BUILDER_MAX_USD_PER_RUN MC_SIM_BUILDER_USD_PER_1K_INPUT MC_SIM_BUILDER_USD_PER_1K_OUTPUT
        export MC_SIM_BUILD_MODE
        export MC_SIM_BUILD_MAX_PER_AGENT MC_SIM_BUILD_COOLDOWN_SEC MC_SIM_BUILD_ZONE_STRIDE MC_SIM_BUILD_CACHE_TTL_SEC
        export EASY_SETUP_BOUNDARY EASY_SETUP_MEADOW_RADIUS
        export MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS
        export MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST SOAK_PLAN_BUILD_BOTS
        export MINECRAFT_PLAN_BUILD_ALLOWED_MATERIALS
        export MINECRAFT_BUILD_FROM_PLAN_PLACE_REACH_BLOCKS
        export MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_TOLERANCE_BLOCKS
        export MC_HEARTBEAT_ENABLED MC_HEARTBEAT_TICK_MS MC_HEARTBEAT_IDLE_MS
        export MC_HEARTBEAT_COOLDOWN_MS MC_HEARTBEAT_STALE_ACTION_MS MC_HEARTBEAT_MAX_NO_COMMAND
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

send_deferred_init_message() {
    [ "$SOAK_EASY_SPAWN" = "1" ] || return 0
    [ -n "$SOAK_INIT_MESSAGE" ] || return 0
    MINDCRAFT_BASE_ABS="$MINDCRAFT_BASE_ABS" \
    SOAK_BOTS="$SOAK_BOTS" \
    SOAK_MINDSERVER_BASE_PORT="$SOAK_MINDSERVER_BASE_PORT" \
    SOAK_INIT_MESSAGE="$SOAK_INIT_MESSAGE" \
        node --input-type=module <<'NODE'
import { createRequire } from 'node:module';

const mindcraftDir = process.env.MINDCRAFT_BASE_ABS;
const require = createRequire(`${mindcraftDir}/package.json`);
const { io } = require('socket.io-client');

const botNames = new Map([
    ['alpha', 'Alpha'],
    ['vera', 'Vera'],
    ['rex', 'Rex'],
    ['aurora', 'Aurora'],
    ['pixel', 'Pixel'],
    ['fork', 'Fork'],
    ['sentinel', 'Sentinel'],
    ['grok', 'Grok'],
    ['bridge', 'BridgeBot'],
]);
const bots = String(process.env.SOAK_BOTS || '').trim().split(/\s+/).filter(Boolean);
const basePort = Number.parseInt(process.env.SOAK_MINDSERVER_BASE_PORT || '8080', 10);
const message = process.env.SOAK_INIT_MESSAGE || '';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function agentNameFor(bot) {
    return botNames.get(bot) || `${bot.slice(0, 1).toUpperCase()}${bot.slice(1)}`;
}

function connect(socket) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('connect timeout')), 1500);
        socket.once('connect', () => {
            clearTimeout(timer);
            resolve();
        });
        socket.once('connect_error', (err) => {
            clearTimeout(timer);
            reject(err);
        });
    });
}

function nextAgentsStatus(socket) {
    return new Promise((resolve) => {
        const timer = setTimeout(() => resolve([]), 1500);
        socket.once('agents-status', (agents) => {
            clearTimeout(timer);
            resolve(Array.isArray(agents) ? agents : []);
        });
    });
}

async function sendToBot(bot, index) {
    if (bot === 'bridge') {
        return { bot, agentName: agentNameFor(bot), skipped: true, reason: 'bridge receives no init prompt' };
    }
    const port = basePort + index;
    const agentName = agentNameFor(bot);
    const deadline = Date.now() + 30000;
    let lastError = 'agent not observed in game';
    while (Date.now() < deadline) {
        const socket = io(`http://localhost:${port}`, {
            transports: ['websocket'],
            timeout: 1500,
            reconnection: false,
            forceNew: true,
        });
        const statusPromise = nextAgentsStatus(socket);
        try {
            await connect(socket);
            const agents = await statusPromise;
            const status = agents.find((agent) => agent && agent.name === agentName);
            if (status?.in_game && status?.socket_connected !== false) {
                socket.emit('send-message', agentName, { from: 'system', message });
                await sleep(100);
                socket.disconnect();
                return { bot, agentName, port, sent: true };
            }
            lastError = status
                ? `status in_game=${status.in_game} socket_connected=${status.socket_connected}`
                : `agent ${agentName} missing from agents-status`;
        } catch (err) {
            lastError = err && err.message ? err.message : String(err);
        } finally {
            socket.disconnect();
        }
        await sleep(500);
    }
    throw new Error(`Timed out sending deferred init to ${agentName} on MindServer :${port}: ${lastError}`);
}

const results = [];
for (let index = 0; index < bots.length; index += 1) {
    results.push(await sendToBot(bots[index], index));
}
process.stdout.write(`${JSON.stringify(results, null, 2)}\n`);
NODE
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
    stop_process_file "$LLM_PROXY_PID_FILE"
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
            if grep -q '"event_type":"heartbeat.halted"' "$RUN_DIR/timeline-raw/$bot.ndjson" 2> /dev/null; then
                if ! grep -q "^${bot}[[:space:]]" "$HEARTBEAT_HALT_FILE" 2> /dev/null; then
                    printf '%s\t%s\t%s\n' "$bot" "$pid" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$HEARTBEAT_HALT_FILE"
                    fail "$bot heartbeat halted; stopping bot process for supervisor visibility"
                    signal_process_tree "$pid" TERM
                    had_early_exit=1
                fi
            fi
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
    local end_iso="$1" early_count heartbeat_halt_count bridge_drops management_events crash_lines runaway_lines
    early_count="$(wc -l < "$EARLY_EXIT_FILE" | tr -d ' ')"
    heartbeat_halt_count="$(wc -l < "$HEARTBEAT_HALT_FILE" | tr -d ' ')"
    bridge_drops="$(count_matches 'bridge[-_ ]down|bridge_(connect_failed|send_failed)|bridge unavailable|WebSocket.*(closed|disconnect)|ECONN' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log)"
    management_events="$(count_matches 'management_review_event|Management|intervene|shadow' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log)"
    build_feedback_records="$(count_matches 'build_feedback|Build quality feedback|build-quality feedback' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log "$RUN_DIR"/timeline-raw/*.ndjson)"
    crash_lines="$(count_matches 'uncaught|unhandled|fatal|segmentation|crash|exception|heartbeat\.halted|max-no-command' "$RUN_DIR"/bots/*.log "$RUN_DIR"/logs/*.log "$RUN_DIR"/timeline-raw/*.ndjson)"
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
        echo "heartbeat_halts: $heartbeat_halt_count"
        echo "bridge_drop_lines: $bridge_drops"
        echo "management_event_lines: $management_events"
        echo "build_quality_feedback_records: $build_feedback_records"
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
        echo "Heartbeat halts"
        if [ -s "$HEARTBEAT_HALT_FILE" ]; then
            cat "$HEARTBEAT_HALT_FILE"
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

heartbeat = data.get("counts_by_event_type", {})
print("heartbeat_counts:")
for key in ("heartbeat.fired", "heartbeat.skipped", "heartbeat.outcome", "heartbeat.halted"):
    print(f"- {key}: {heartbeat.get(key, 0)}")

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

builder = data.get("builder_usage", {})
print("builder_usage:")
print(f"- paid_calls: {builder.get('paid_calls', 0)}")
print(f"- local_calls: {builder.get('local_calls', 0)}")
print(f"- estimated_usd: {builder.get('estimated_usd', 0)}")
print(f"- failures: {builder.get('failures', 0)}")
print(f"- fallbacks: {builder.get('fallbacks', 0)}")
providers = builder.get("by_provider", {})
print("builder_usage_by_provider:")
if providers:
    for key, value in sorted(providers.items()):
        print(
            f"- {key}: calls={value.get('calls', 0)} paid={value.get('paid_calls', 0)} "
            f"tokens={value.get('total_tokens', 0)} usd={value.get('estimated_usd', 0)}"
        )
else:
    print("- none")
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

run_director_acceptance_report() {
    [ "$SOAK_PROFILE" = "director_v2" ] || return 0
    "${PYTHON:-python3}" "$SCRIPT_DIR/build_director_acceptance_report.py" \
        --run-dir "$RUN_DIR" \
        --queue-threshold "$SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD" \
        --warmup-seconds "$SOAK_ACCEPTANCE_WARMUP_SECONDS" \
        --max-selected-agent-ratio "$SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO"
}

append_director_acceptance_summary() {
    local status="$1" status_label
    [ "$SOAK_PROFILE" = "director_v2" ] || return 0
    if [ "$status" -eq 0 ]; then
        status_label="pass"
    else
        status_label="fail"
    fi
    {
        echo
        echo "Director V2 acceptance"
        echo "status: $status_label"
        echo "report_json: $RUN_DIR/acceptance-report.json"
        echo "report_md: $RUN_DIR/acceptance-report.md"
        echo "director_decisions: $RUN_DIR/director-decisions.ndjson"
        echo "tool_parity: $RUN_DIR/tool-parity.ndjson"
        echo "macro_evidence: $RUN_DIR/macro-evidence.ndjson"
        echo "memory_digest: $RUN_DIR/memory-digest.ndjson"
    } >> "$RUN_DIR/summary.txt"
}

start_lm_queue_proxy
print_plan
write_metadata

run_checked "docker services" "$RUN_DIR/preflight/check-services.txt" bash "$REPO_ROOT/scripts/check-services.sh"
run_checked "LM Studio models" "$RUN_DIR/preflight/llm-local.txt" pnpm llm:local --list-only
run_checked "LM Studio chat warm-up" "$RUN_DIR/preflight/llm-local-chat.txt" \
    pnpm llm:local --timeout "$SOAK_LLM_SMOKE_TIMEOUT_SECONDS" \
        --prompt "Reply with exactly: minecraft smoke ready"
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

# settlement-mode only: seed shared objective board the bots read (E21 keystone).
# Emergent mode seeds nothing (owned by E21-7c). Runs after the docker-services
# preflight (Redis confirmed up) and before any bot launches.
if [ "$MC_SIM_BUILD_MODE" = "settlement" ]; then
    run_checked "seed settlement objectives" "$RUN_DIR/preflight/seed-settlement-objectives.txt" \
        env MC_RUN_DIR="$RUN_DIR" "${PYTHON:-python3}" "$SCRIPT_DIR/seed_settlement_objectives.py"
fi

BOT_INDEX=0
for bot in $SOAK_BOTS; do
    launch_bot "$bot" "$BOT_INDEX"
    BOT_INDEX=$((BOT_INDEX + 1))
done

if [ "$SOAK_EASY_SPAWN" = "1" ]; then
    sleep "$SOAK_EASY_SPAWN_ONLINE_DELAY_SECONDS"
    run_checked "easy spawn starter kit" "$RUN_DIR/preflight/easy-spawn-kit.txt" \
        node "$SCRIPT_DIR/setup-easy-spawn.mjs"
    if [ -n "$SOAK_INIT_MESSAGE" ]; then
        run_checked "easy spawn deferred init" "$RUN_DIR/preflight/easy-spawn-init.txt" \
            send_deferred_init_message
    fi
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
ACCEPTANCE_STATUS=0
if [ "$SOAK_PROFILE" = "director_v2" ]; then
    run_director_acceptance_report || ACCEPTANCE_STATUS=$?
    append_director_acceptance_summary "$ACCEPTANCE_STATUS"
fi

EXCEEDED="$(cat "$RUN_DIR/cost-cap-exceeded.count" 2> /dev/null || echo 1)"
BEHAVIOR_GATE_STATUS="$(cat "$RUN_DIR/behavior-gate-status.txt" 2> /dev/null || echo fail)"
if [ -s "$HEARTBEAT_HALT_FILE" ]; then
    fail "Soak failed: at least one bot heartbeat halted. See $HEARTBEAT_HALT_FILE"
    exit 1
fi
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
if [ "$SOAK_PROFILE" = "director_v2" ] && [ "$SOAK_REQUIRE_DIRECTOR_ACCEPTANCE" = "1" ] && [ "$ACCEPTANCE_STATUS" -ne 0 ]; then
    fail "Director V2 acceptance failed. See $RUN_DIR/acceptance-report.md"
    exit 1
fi
if [ "$BEHAVIOR_GATE_STATUS" != "pass" ]; then
    info "behavior gate failed but SOAK_REQUIRE_BEHAVIOR_GATE=$SOAK_REQUIRE_BEHAVIOR_GATE; document the deviation in docs/minecraft/cohort-report.md"
fi

ok "Soak completed without unrecovered bot exits, within hourly cap, with acceptable action-command reliability, behavior_gate_status=$BEHAVIOR_GATE_STATUS, and director_acceptance_status=${ACCEPTANCE_STATUS:-0}"
info "evidence: $RUN_DIR"
