#!/usr/bin/env bash
# Verify per-agent multi-model OpenRouter routing — TWO Mindcraft bots, each
# routing a conversation-tier `model` and a distinct building-tier `code_model`.
#
# This is the committed launch/verify script referenced by
# docs/minecraft/model-routing.md (issue #535, epic E3-3). It proves the
# conclusion of decision 0003 (E1-R3 / #520): Mindcraft routes chat vs building
# to different models per bot NATIVELY — no fork patch required. It builds on the
# stock-bot connect (#534 / E3-2) without changing that contract; our nine
# production agents are E8, explicitly NOT this issue.
#
# `./mindcraft` is git-ignored, so the committed artifacts are the routing
# settings template + the two routing profiles next to this script; this script
# STAGES them into the clone — exactly the pattern connect-stock-bot.sh uses.
#
# Two bots, four models (all LOCAL — LM Studio, decision 0003, zero external
# spend; no openrouter/... here):
#   RoutingBotA  model=lmstudio/$LLM_A_CHAT   code_model=lmstudio/$LLM_A_CODE
#   RoutingBotB  model=lmstudio/$LLM_B_CHAT   code_model=lmstudio/$LLM_B_CODE
# The committed templates carry four distinct substitution tokens
# (__LLM_A_CHAT__ / __LLM_A_CODE__ / __LLM_B_CHAT__ / __LLM_B_CODE__). The
# production openrouter/ reference mapping (A mirrors agents/vera, B mirrors
# agents/aurora) is documented in docs/minecraft/model-routing.md — a JSON
# comment is not valid JSON, so it deliberately is NOT in the profiles.
#
# Pinned defaults come from the E1 decisions (same as connect-stock-bot.sh):
#   - Fork commit: 35be480b4cc0bca990278e6103a1426392559d96  (E1-R1 → docs/decisions/0001)
#   - Node:        20 LTS                                     (E1-R1 → docs/decisions/0001)
#   - Minecraft:   1.21.6                                     (E1-R1 → docs/decisions/0001)
#   - host/port:   127.0.0.1 : 25565  (E2 start-server.sh default; localhost only)
#   - auth:        offline   (E1-R2 → docs/decisions/0002 — matches online-mode=false)
#   - launch shim: refresh minecraft_version after child-agent settings arrive
#                  (the pinned fork reads it too early at module import time)
#
# Usage:
#   scripts/minecraft/verify-model-routing.sh            # stage config + launch both bots
#   scripts/minecraft/verify-model-routing.sh --dry-run  # print the resolved 2-bot/4-model plan; no clone/network/launch
#   scripts/minecraft/verify-model-routing.sh --verify   # static checks only (CI/network-safe)
#   scripts/minecraft/verify-model-routing.sh --help
#
# Configuration (environment variables):
#   MINDCRAFT_DIR     Where the pinned clone lives  (default: ./mindcraft)
#   MC_HOST           E2 server host                (default: 127.0.0.1)
#   MC_PORT           E2 server port                (default: 25565)
#   LOCAL_LLM_BASE_URL  LM Studio URL for the PRE-FLIGHT reachability check only
#                       (pnpm llm:local --list-only). Mindcraft's string-form
#                       "lmstudio/<id>" profiles (decision 0003) always talk to
#                       its built-in http://localhost:1234/v1 at the pinned
#                       commit, so run LM Studio there. (default: http://localhost:1234/v1)
#   LLM_A_CHAT        RoutingBotA conversation-tier LM Studio model id  (REQUIRED for a real run)
#   LLM_A_CODE        RoutingBotA building-tier   LM Studio model id    (REQUIRED for a real run)
#   LLM_B_CHAT        RoutingBotB conversation-tier LM Studio model id  (REQUIRED for a real run)
#   LLM_B_CODE        RoutingBotB building-tier   LM Studio model id    (REQUIRED for a real run)
# --verify / --dry-run need NONE of the four model ids.
#
# A real run requires the E2 server already running (docs/minecraft/server-setup.md)
# and the pinned fork already installed (docs/minecraft/mindcraft-fork.md). The
# bot usernames are fixed as "RoutingBotA"/"RoutingBotB"; with the E2 default
# white-list=true you must whitelist BOTH (this script prints the commands).
set -euo pipefail

# ── Pinned E1 defaults (kept in sync with docs/decisions/0001 & 0002) ──
MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
REQUIRED_NODE_MAJOR="20"
MC_VERSION="1.21.6"                       # E1-R1 / decisions 0001 (matches start-server.sh + the settings template)
MC_HOST="${MC_HOST:-127.0.0.1}"           # E1-R2 / decisions 0002 — localhost only in offline mode
MC_PORT="${MC_PORT:-25565}"               # E2 start-server.sh default (server-port left unset)
MC_AUTH="offline"                         # E1-R2 / decisions 0002 — matches Paper online-mode=false
PROFILE_A_REL="./profiles/routing-bot-a.json"
PROFILE_B_REL="./profiles/routing-bot-b.json"
BOT_A_NAME="RoutingBotA"                  # MUST match "name" in profiles/routing-bot-a.json
BOT_B_NAME="RoutingBotB"                  # MUST match "name" in profiles/routing-bot-b.json
# Pre-flight reachability-check URL only (consumed by `pnpm llm:local`, which
# reads LOCAL_LLM_BASE_URL itself). Mindcraft's string-form "lmstudio/<id>"
# profiles carry no url, so at the pinned commit the bots ALWAYS use Mindcraft's
# built-in http://localhost:1234/v1 regardless of this value — run LM Studio there.
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
MINDCRAFT_LLM_URL="http://localhost:1234/v1"   # where the bots actually connect (Mindcraft default)
MCDATA_REL="src/utils/mcdata.js"
MCDATA_VERSION_PATCH_MARKER="LTAG E3-2 runtime version refresh"
MINDCRAFT_DIR_ABS=""
MCDATA_BACKUP=""
MCDATA_PATH=""

# Resolve the committed template + profiles relative to THIS script (not the
# caller's cwd) so the reviewed copies are used no matter where it is invoked.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-routing.js"
PROFILE_A_TEMPLATE="$SCRIPT_DIR/profiles/routing-bot-a.json"
PROFILE_B_TEMPLATE="$SCRIPT_DIR/profiles/routing-bot-b.json"

MODE="run"
case "${1:-}" in
    --dry-run) MODE="dry-run" ;;
    --verify)  MODE="verify" ;;
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
warn() { echo "⚠ $*" >&2; }
fail() { echo "✗ $*" >&2; }

# Advisory on the RESOLVED runtime model ids (verify_committed_assets only
# checks the committed template tokens, which are always distinct). The whole
# point of E3-3 is each bot routes a conversation `model` to a DIFFERENT
# building `code_model`; warn loudly (non-fatal — a local connectivity smoke may
# legitimately reuse one loaded model) when the operator's ids collapse that.
warn_runtime_model_ids() {
    [ -n "$LLM_A_CHAT" ] && [ -n "$LLM_A_CODE" ] \
        && [ -n "$LLM_B_CHAT" ] && [ -n "$LLM_B_CODE" ] || return 0
    if [ "$LLM_A_CHAT" = "$LLM_A_CODE" ] && [ "$LLM_A_CHAT" = "$LLM_B_CHAT" ] \
        && [ "$LLM_A_CHAT" = "$LLM_B_CODE" ]; then
        warn "All four model ids are '$LLM_A_CHAT' — the routing demo is vacuous."
        info "  Export at least two distinct LM Studio ids so chat vs code routing"
        info "  is observable (pnpm llm:local --list-only to list served ids)."
        return 0
    fi
    if [ "$LLM_A_CHAT" = "$LLM_A_CODE" ]; then
        warn "$BOT_A_NAME chat == code id ('$LLM_A_CHAT') — that tier split is unobservable."
    fi
    if [ "$LLM_B_CHAT" = "$LLM_B_CODE" ]; then
        warn "$BOT_B_NAME chat == code id ('$LLM_B_CHAT') — that tier split is unobservable."
    fi
    return 0
}

restore_mcdata_patch() {
    if [ -n "${MCDATA_BACKUP:-}" ] && [ -f "$MCDATA_BACKUP" ] && [ -n "${MCDATA_PATH:-}" ]; then
        cp "$MCDATA_BACKUP" "$MCDATA_PATH" 2> /dev/null || true
        rm -f "$MCDATA_BACKUP"
    fi
}

# ── Node / npm check (identical posture to connect-stock-bot.sh) ──
# A real run needs Node $REQUIRED_NODE_MAJOR LTS. In --dry-run/--verify we only
# warn so config/static checks stay verifiable on a machine without (or with a
# different) Node — same posture as the Java check in start-server.sh.
node_major() {
    command -v node > /dev/null 2>&1 || return 1
    local out major
    out="$(node -v 2>&1)" || return 1   # e.g. "v20.11.1"
    major="$(printf '%s\n' "$out" | sed -nE 's/^v?([0-9]+).*/\1/p')"
    [ -n "$major" ] || return 1
    printf '%s\n' "$major"
}

check_node() {
    local node_m
    node_m="$(node_major || true)"
    if [ -z "${node_m:-}" ]; then
        fail "Node.js not found on PATH. Install Node ${REQUIRED_NODE_MAJOR} LTS:"
        info "  nvm:           nvm install ${REQUIRED_NODE_MAJOR} && nvm use ${REQUIRED_NODE_MAJOR}"
        info "  macOS:         brew install node@${REQUIRED_NODE_MAJOR}"
        info "  See docs/minecraft/model-routing.md for details."
        return 1
    fi
    if [ "$node_m" != "$REQUIRED_NODE_MAJOR" ]; then
        fail "Node ${node_m} found, but the pinned Mindcraft needs Node ${REQUIRED_NODE_MAJOR} LTS."
        info "  Mindcraft warns Node 24+ breaks native deps; we pin ${REQUIRED_NODE_MAJOR} (E1-R1)."
        info "  Install Node ${REQUIRED_NODE_MAJOR} (see docs/minecraft/model-routing.md) and retry."
        return 1
    fi
    if ! command -v npm > /dev/null 2>&1; then
        fail "npm not found on PATH (it ships with Node ${REQUIRED_NODE_MAJOR})."
        return 1
    fi
    ok "Node ${node_m} + npm $(npm -v) detected (need Node ${REQUIRED_NODE_MAJOR})"
}

# Extract a top-level "key": "value" string from a committed profile template.
# The committed format is one double-quoted key per line — no jq/node needed,
# matching connect-stock-bot.sh's grep-only static posture (strict JSON parsing
# lives in tests/backend/test_mc_model_routing.py).
json_str() {
    sed -nE "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"([^\"]*)\".*/\1/p" "$1" | head -n1
}

# ── Static assertions on the committed template + both profiles (no Node/net/git) ──
# Defense-in-depth: the staged settings.js must point at the E2 server with the
# two routing profiles + prompt logging on, and each profile must route a
# conversation `model` to a DIFFERENT building `code_model`, all local-only.
verify_committed_assets() {
    local problems=0
    if [ ! -s "$SETTINGS_TEMPLATE" ]; then
        fail "Routing settings template missing or empty: $SETTINGS_TEMPLATE"; problems=1
    else
        grep -q '"host": "127.0.0.1"'   "$SETTINGS_TEMPLATE" || { fail "template host is not 127.0.0.1"; problems=1; }
        grep -q '"port": 25565'         "$SETTINGS_TEMPLATE" || { fail "template port is not 25565"; problems=1; }
        grep -q '"auth": "offline"'     "$SETTINGS_TEMPLATE" || { fail "template auth is not offline"; problems=1; }
        grep -q '"minecraft_version": "1.21.6"' "$SETTINGS_TEMPLATE" || { fail "template minecraft_version is not 1.21.6"; problems=1; }
        grep -q '"auto_open_ui": false' "$SETTINGS_TEMPLATE" || { fail "template auto_open_ui is not false"; problems=1; }
        grep -q '"log_all_prompts": true' "$SETTINGS_TEMPLATE" || { fail "template log_all_prompts is not true (no routing evidence)"; problems=1; }
        grep -q '"./profiles/routing-bot-a.json"' "$SETTINGS_TEMPLATE" || { fail "template does not list routing-bot-a.json"; problems=1; }
        grep -q '"./profiles/routing-bot-b.json"' "$SETTINGS_TEMPLATE" || { fail "template does not list routing-bot-b.json"; problems=1; }
    fi

    local p name model code
    local a_name="" b_name="" a_chat="" a_code="" b_chat="" b_code=""
    for p in "$PROFILE_A_TEMPLATE" "$PROFILE_B_TEMPLATE"; do
        if [ ! -s "$p" ]; then
            fail "Routing profile missing or empty: $p"; problems=1; continue
        fi
        name="$(json_str "$p" name)"
        model="$(json_str "$p" model)"
        code="$(json_str "$p" code_model)"
        if [ -z "$name" ] || [ -z "$model" ] || [ -z "$code" ]; then
            fail "Profile $p is missing name/model/code_model"; problems=1; continue
        fi
        case "$model" in lmstudio/*) ;; *) fail "$p model is not an lmstudio/ id (no external spend): $model"; problems=1 ;; esac
        case "$code"  in lmstudio/*) ;; *) fail "$p code_model is not an lmstudio/ id: $code"; problems=1 ;; esac
        if grep -q 'openrouter/' "$p"; then
            fail "$p must NOT reference openrouter/ — local validation only (decision 0003)"; problems=1
        fi
        if [ "$model" = "$code" ]; then
            fail "$p routes the same model for chat and code — the point of E3-3 is they differ ($model)"; problems=1
        fi
        case "$p" in
            *routing-bot-a.json) a_name="$name"; a_chat="$model"; a_code="$code" ;;
            *routing-bot-b.json) b_name="$name"; b_chat="$model"; b_code="$code" ;;
        esac
    done

    if [ "$a_name" = "$BOT_A_NAME" ] && [ "$b_name" = "$BOT_B_NAME" ]; then
        :
    else
        fail "Profile names must be ${BOT_A_NAME}/${BOT_B_NAME} (got '$a_name'/'$b_name')"; problems=1
    fi
    if [ -n "$a_name" ] && [ "$a_name" = "$b_name" ]; then
        fail "The two profiles must use DIFFERENT names (both '$a_name')"; problems=1
    fi
    # The four substitution tokens must not all be identical — otherwise the
    # "two bots, distinct chat vs code model" demonstration is vacuous.
    if [ -n "$a_chat" ] \
        && [ "$a_chat" = "$a_code" ] \
        && [ "$a_chat" = "$b_chat" ] \
        && [ "$a_chat" = "$b_code" ]; then
        fail "All four model tokens are identical — routing demo would be vacuous"; problems=1
    fi
    return $problems
}

# ── (b) Resolve + print config (shared by every mode) ──
ok "Per-agent multi-model routing → E2 server (2 bots, 4 models)"
info "decision: native routing, NO fork patch (docs/decisions/0003, E1-R3/#520)"
info "bot A:    $BOT_A_NAME  (profile $PROFILE_A_REL)"
info "bot B:    $BOT_B_NAME  (profile $PROFILE_B_REL)"
info "server:   ${MC_HOST}:${MC_PORT}  auth=${MC_AUTH}  minecraft=${MC_VERSION}"
info "clone:    $MINDCRAFT_DIR  (pinned $MINDCRAFT_COMMIT)"
info "settings: staged from $SETTINGS_TEMPLATE (log_all_prompts:true)"
info "LM Studio: bots connect to ${MINDCRAFT_LLM_URL}  (Mindcraft built-in for"
info "           string-form lmstudio/ profiles — run LM Studio there; local"
info "           only, zero external spend, decision 0003)"
info "           pre-flight check (pnpm llm:local) uses ${LOCAL_LLM_BASE_URL}"

# ── --verify: static, CI/network-safe checks only ──────
if [ "$MODE" = "verify" ]; then
    if verify_committed_assets; then
        ok "Static verify passed: routing settings point at the E2 server with"
        info "both routing profiles + log_all_prompts; each profile routes a"
        info "conversation model != a building code_model, both local-only"
        info "(lmstudio/), names ${BOT_A_NAME}/${BOT_B_NAME} differ."
        info "(No clone, no network, no Node, no launch — run without --verify to connect.)"
        exit 0
    fi
    fail "Static verify FAILED — see messages above."
    exit 1
fi

# Resolve the four LM Studio model ids. All four are mandatory for a real run
# (the whole point is two bots × two tiers = four routed models, local only).
LLM_A_CHAT="${LLM_A_CHAT:-}"
LLM_A_CODE="${LLM_A_CODE:-}"
LLM_B_CHAT="${LLM_B_CHAT:-}"
LLM_B_CODE="${LLM_B_CODE:-}"

# ── --dry-run: print the resolved plan, do NOT clone/network/launch ──
if [ "$MODE" = "dry-run" ]; then
    check_node || true   # advisory only in dry-run
    verify_committed_assets || true
    echo
    ok "Dry run complete — no clone, no network, nothing launched."
    info "host:       $MC_HOST"
    info "port:       $MC_PORT"
    info "auth:       $MC_AUTH"
    info "minecraft:  $MC_VERSION"
    if [ -n "$LLM_A_CHAT" ] && [ -n "$LLM_A_CODE" ] && [ -n "$LLM_B_CHAT" ] && [ -n "$LLM_B_CODE" ]; then
        info "$BOT_A_NAME  model: lmstudio/$LLM_A_CHAT   code_model: lmstudio/$LLM_A_CODE"
        info "$BOT_B_NAME  model: lmstudio/$LLM_B_CHAT   code_model: lmstudio/$LLM_B_CODE"
        warn_runtime_model_ids
    else
        info "models:     (LLM_A_CHAT/LLM_A_CODE/LLM_B_CHAT/LLM_B_CODE unset — all"
        info "             four REQUIRED for a real run; list ids with:"
        info "             pnpm llm:local --list-only)"
    fi
    info "Would assert: $MINDCRAFT_DIR HEAD == $MINDCRAFT_COMMIT"
    info "Would stage:  $SETTINGS_TEMPLATE → $MINDCRAFT_DIR/settings.js"
    info "Would stage:  $PROFILE_A_TEMPLATE → $MINDCRAFT_DIR/${PROFILE_A_REL#./} (tokens substituted)"
    info "Would stage:  $PROFILE_B_TEMPLATE → $MINDCRAFT_DIR/${PROFILE_B_REL#./} (tokens substituted)"
    info "Would stage:  runtime-version shim in $MINDCRAFT_DIR/$MCDATA_REL (restored on exit)"
    info "Would launch: (cd $MINDCRAFT_DIR && node main.js --profiles $PROFILE_A_REL $PROFILE_B_REL)"
    exit 0
fi

# ── Real run ───────────────────────────────────────────
verify_committed_assets || { fail "Refusing to launch with bad committed assets."; exit 1; }
check_node || exit 1
command -v git > /dev/null 2>&1 || { fail "git not found on PATH."; exit 1; }

# (a) The pinned fork must already be installed (E3-1 / #533).
if [ ! -d "$MINDCRAFT_DIR/.git" ]; then
    fail "No Mindcraft clone at $MINDCRAFT_DIR."
    info "  Install the pinned fork first:"
    info "    scripts/minecraft/setup-mindcraft.sh"
    info "  (see docs/minecraft/mindcraft-fork.md)"
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

# (b) All four model ids are mandatory for a real run (local LM Studio only).
missing=""
[ -z "$LLM_A_CHAT" ] && missing="$missing LLM_A_CHAT"
[ -z "$LLM_A_CODE" ] && missing="$missing LLM_A_CODE"
[ -z "$LLM_B_CHAT" ] && missing="$missing LLM_B_CHAT"
[ -z "$LLM_B_CODE" ] && missing="$missing LLM_B_CODE"
if [ -n "$missing" ]; then
    fail "Missing required model id(s):$missing"
    info "  This issue routes TWO bots × TWO tiers = four LM Studio models."
    info "  List the models LM Studio is serving, then export all four:"
    info "    pnpm llm:local --list-only      # or: .venv/bin/python scripts/check_local_llm.py --list-only"
    info "    export LLM_A_CHAT=<conversation-model-id>   # RoutingBotA chat"
    info "    export LLM_A_CODE=<building-model-id>       # RoutingBotA code"
    info "    export LLM_B_CHAT=<conversation-model-id>   # RoutingBotB chat"
    info "    export LLM_B_CODE=<building-model-id>       # RoutingBotB code"
    info "  Pick at least two distinct ids so the routing is observable."
    info "  This keeps validation 100% local — zero external model spend (decision 0003)."
    exit 1
fi
# Non-fatal: warn if the operator's ids collapse the chat-vs-code tier split
# the issue is meant to demonstrate (the committed-template check above cannot
# see runtime env values — these are the resolved ids the bots will actually use).
warn_runtime_model_ids

# (c) LM Studio pre-flight reachability check (lists the served model ids).
ok "LM Studio pre-flight (pnpm llm:local --list-only @ ${LOCAL_LLM_BASE_URL})"
if command -v pnpm > /dev/null 2>&1; then
    LOCAL_LLM_BASE_URL="$LOCAL_LLM_BASE_URL" pnpm llm:local --list-only \
        || { fail "LM Studio not reachable — load a model and retry."; exit 1; }
elif [ -x ".venv/bin/python" ]; then
    LOCAL_LLM_BASE_URL="$LOCAL_LLM_BASE_URL" .venv/bin/python scripts/check_local_llm.py --list-only \
        || { fail "LM Studio not reachable — load a model and retry."; exit 1; }
else
    fail "Neither pnpm nor .venv/bin/python found for the LM Studio pre-flight check."
    exit 1
fi

# (d) Stage settings.js (host/port substituted; everything else is the reviewed
#     template verbatim — including the two routing profiles + log_all_prompts).
#     Line-anchored so the comment header is never touched.
DEST_SETTINGS="$MINDCRAFT_DIR_ABS/settings.js"
if ! sed -E \
    -e "s|^([[:space:]]*\"host\":[[:space:]]*\")[^\"]*(\".*)$|\1${MC_HOST}\2|" \
    -e "s|^([[:space:]]*\"port\":[[:space:]]*)[0-9]+(,.*)$|\1${MC_PORT}\2|" \
    "$SETTINGS_TEMPLATE" > "$DEST_SETTINGS"; then
    fail "Failed to stage settings.js → $DEST_SETTINGS"
    exit 1
fi
ok "Staged settings.js → $DEST_SETTINGS (host=${MC_HOST} port=${MC_PORT}, 2 routing profiles, log_all_prompts)"

# (e) Stage both profiles with the four LM Studio model ids substituted in.
stage_profile() {
    local template="$1" rel="$2" chat="$3" code="$4" chat_tok="$5" code_tok="$6"
    local dest="$MINDCRAFT_DIR_ABS/${rel#./}"
    mkdir -p "$(dirname -- "$dest")"
    if ! TEMPLATE_PATH="$template" DEST_PATH="$dest" CHAT_MODEL="$chat" CODE_MODEL="$code" \
        CHAT_TOKEN="$chat_tok" CODE_TOKEN="$code_tok" node --input-type=module <<'NODE'
import { readFileSync, writeFileSync } from 'node:fs';

const templatePath = process.env.TEMPLATE_PATH;
const destPath = process.env.DEST_PATH;
const chatModel = process.env.CHAT_MODEL;
const codeModel = process.env.CODE_MODEL;
const chatToken = process.env.CHAT_TOKEN;
const codeToken = process.env.CODE_TOKEN;

const profile = JSON.parse(readFileSync(templatePath, 'utf8'));
if (profile.model !== `lmstudio/${chatToken}` || profile.code_model !== `lmstudio/${codeToken}`) {
    throw new Error(`Unexpected routing placeholders in ${templatePath}`);
}

profile.model = `lmstudio/${chatModel}`;
profile.code_model = `lmstudio/${codeModel}`;
writeFileSync(destPath, `${JSON.stringify(profile, null, 4)}\n`);
NODE
    then
        fail "Failed to stage profile → $dest"
        exit 1
    fi
    ok "Staged profile → $dest"
    info "  model:      lmstudio/${chat}  (conversation tier)"
    info "  code_model: lmstudio/${code}  (building tier — distinct from chat)"
}
stage_profile "$PROFILE_A_TEMPLATE" "$PROFILE_A_REL" "$LLM_A_CHAT" "$LLM_A_CODE" "__LLM_A_CHAT__" "__LLM_A_CODE__"
stage_profile "$PROFILE_B_TEMPLATE" "$PROFILE_B_REL" "$LLM_B_CHAT" "$LLM_B_CODE" "__LLM_B_CHAT__" "__LLM_B_CODE__"

# (f) Apply the SAME launch-time runtime-version shim as connect-stock-bot.sh.
#     At the pinned commit, mcdata.js captures settings.minecraft_version at
#     module import time, before the child process receives settings from the
#     MindServer. We patch only the local clone during this launch and restore
#     it on exit.
MCDATA_PATH="$MINDCRAFT_DIR_ABS/$MCDATA_REL"
if [ ! -f "$MCDATA_PATH" ]; then
    fail "Mindcraft source file missing: $MCDATA_PATH"
    exit 1
fi
if grep -q "$MCDATA_VERSION_PATCH_MARKER" "$MCDATA_PATH"; then
    info "Found a previous runtime-version shim in $MCDATA_REL; restoring the pinned source first."
    if ! git -C "$MINDCRAFT_DIR_ABS" show "HEAD:$MCDATA_REL" > "$MCDATA_PATH"; then
        fail "Could not restore pinned $MCDATA_REL before applying runtime-version shim."
        exit 1
    fi
fi
if ! grep -q 'let mc_version = settings.minecraft_version;' "$MCDATA_PATH"; then
    fail "Mindcraft source shape changed; cannot apply runtime-version shim."
    info "  Expected to find: let mc_version = settings.minecraft_version;"
    info "  Re-check the pinned fork before launching."
    exit 1
fi
MCDATA_BACKUP="$(mktemp -t mindcraft-mcdata.XXXXXX)"
cp "$MCDATA_PATH" "$MCDATA_BACKUP"
trap restore_mcdata_patch EXIT
trap 'restore_mcdata_patch; exit 130' INT
trap 'restore_mcdata_patch; exit 143' TERM
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

# (g) Whitelist reminder. start-server.sh defaults white-list=true, so the E2
#     server will REJECT the bots until BOTH names are whitelisted.
echo
info "── Whitelist (E2 server defaults to white-list=true) ───────────────────"
info "In the E2 server console, run exactly:"
info "    whitelist add ${BOT_A_NAME}"
info "    whitelist add ${BOT_B_NAME}"
info "Or restart the E2 server with the whitelist off (dev only, localhost):"
info "    WHITELIST=false scripts/minecraft/start-server.sh"
info "Skipping this → the bots connect then are kicked with 'not whitelisted'."
echo

# (h) How to exercise BOTH tiers and where the evidence lands.
info "── Exercising both tiers (per-bot, per-tier routing evidence) ──────────"
info "Join the E2 server with a normal Minecraft client, then in chat:"
info "  1. Conversation tier (hits each bot's \`model\`):"
info "       ${BOT_A_NAME} hello, who are you?"
info "       ${BOT_B_NAME} hello, who are you?"
info "  2. Building tier (hits each bot's \`code_model\`):"
info "       ${BOT_A_NAME} !newAction(\"place a block in front of you\")"
info "       ${BOT_B_NAME} !newAction(\"place a block in front of you\")"
info "Evidence of WHICH model id served each call:"
info "  - LM Studio → server request logs (the model id per request)."
info "  - ./mindcraft/bots/${BOT_A_NAME}/logs and ./mindcraft/bots/${BOT_B_NAME}/logs"
info "    (log_all_prompts:true in the routing settings)."
info "Expected: ${BOT_A_NAME} chat=lmstudio/${LLM_A_CHAT} code=lmstudio/${LLM_A_CODE};"
info "          ${BOT_B_NAME} chat=lmstudio/${LLM_B_CHAT} code=lmstudio/${LLM_B_CODE}."
echo

# (i) Launch both bots. Mindcraft reads ./settings.js; --profiles is passed
#     explicitly so the launch command itself documents which bots are starting.
ok "Launching ${BOT_A_NAME} + ${BOT_B_NAME} → ${MC_HOST}:${MC_PORT} … (Ctrl+C to stop)"
info "Success looks like: both names in the E2 'list' output, each bot's prompt"
info "logs naming its own chat vs code LM Studio model id."
cd "$MINDCRAFT_DIR_ABS"
node main.js --profiles "$PROFILE_A_REL" "$PROFILE_B_REL"
