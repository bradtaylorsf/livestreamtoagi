#!/usr/bin/env bash
# Launch ONE Mindcraft bot with Python-superseded features DISABLED (E3-5).
#
# This is the committed launch script referenced by
# docs/minecraft/mindcraft-stripped-features.md (issue #537, epic E3-5). It
# proves the acceptance criterion: a bot still connects and acts against the E2
# server with the redundant Mindcraft features turned OFF.
#
# It is connect-stock-bot.sh (E3-2 / #534) with ONE substantive difference: it
# stages the *stripped* settings template
# (scripts/minecraft/mindcraft-settings-stripped.js) instead of the stock one.
# It reuses the SAME committed profile (scripts/minecraft/profiles/stock-bot.json)
# and the SAME E2-server connect contract, so any behavioural change is
# attributable purely to the disabled features.
#
# Disabled by the stripped template (full table + how to reverse each in
# docs/minecraft/mindcraft-stripped-features.md):
#   - num_examples        2 -> 0      Mindcraft example retrieval superseded by
#                                      the Python 3-tier memory service (0003)
#   - relevant_docs_count 5 -> 0      Mindcraft skill-doc retrieval superseded by
#                                      the same Python memory service (0003)
#   - narrate_behavior    true -> false  Python owns surfaced/streamed output (0004)
#   - load_memory   off  Mindcraft session memory -> Python pgvector memory (E5/0003)
#   - speak         off  voice/TTS -> Python Edge TTS (0003)
#   - allow_vision  off  Mindcraft vision tier unused; cost/surface (0003)
# Deliberately KEPT: chat_bot_messages=true — decentralized bot-to-bot
# conversation is the base (decision 0004); it is NOT stripped.
#
# `./mindcraft` is git-ignored, so the committed artifacts are the stripped
# settings template, the (reused) stock profile, and the launch-time
# compatibility shim next to this script; this script STAGES them into the clone
# — exactly the pattern setup-mindcraft.sh / connect-stock-bot.sh use.
#
# Pinned defaults come from the E1 decisions (UNCHANGED from connect-stock-bot.sh):
#   - Fork commit: 35be480b4cc0bca990278e6103a1426392559d96  (E1-R1 → docs/decisions/0001)
#   - Node:        20 LTS                                     (E1-R1 → docs/decisions/0001)
#   - Minecraft:   1.21.6                                     (E1-R1 → docs/decisions/0001)
#   - host/port:   127.0.0.1 : 25565  (E2 start-server.sh default; localhost only)
#   - auth:        offline   (E1-R2 → docs/decisions/0002 — matches online-mode=false)
#   - launch shim: refresh minecraft_version after child-agent settings arrive
#                  (the pinned fork reads it too early at module import time)
# Models are LOCAL ONLY (LM Studio, decision 0003): zero external spend. No
# openrouter/... here.
#
# Usage:
#   scripts/minecraft/connect-stripped-bot.sh            # stage stripped config + launch the bot
#   scripts/minecraft/connect-stripped-bot.sh --dry-run  # print resolved plan + disabled flags; no clone/network/launch
#   scripts/minecraft/connect-stripped-bot.sh --verify   # static checks only (CI/network-safe)
#   scripts/minecraft/connect-stripped-bot.sh --help
#
# Configuration (environment variables, all optional):
#   MINDCRAFT_DIR           Where the pinned clone lives  (default: ./mindcraft)
#   MC_HOST                 E2 server host                (default: 127.0.0.1)
#   MC_PORT                 E2 server port                (default: 25565)
#   MINDCRAFT_PROFILE       Profile path inside the clone (default: ./profiles/stock-bot.json)
#   LOCAL_LLM_BASE_URL      LM Studio URL for the PRE-FLIGHT reachability check
#                           only (pnpm llm:local --list-only). Mindcraft's
#                           string-form "lmstudio/<id>" profiles (decision 0003)
#                           always talk to its built-in http://localhost:1234/v1
#                           at the pinned commit, so run LM Studio there.
#                           (default: http://localhost:1234/v1)
#   LOCAL_LLM_MODEL         LM Studio model id for the conversation tier (REQUIRED for a real run)
#   LOCAL_LLM_MODEL_BUILDING  LM Studio model id for the building/code tier (default: = LOCAL_LLM_MODEL)
#
# A real run requires the E2 server already running (docs/minecraft/server-setup.md)
# and the pinned fork already installed (docs/minecraft/mindcraft-fork.md). The
# bot username is fixed as "StockBot" (the reused stock profile); with the E2
# default white-list=true you must whitelist it (this script prints the exact
# command).
set -euo pipefail

# ── Pinned E1 defaults (kept in sync with docs/decisions/0001 & 0002) ──
MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
REQUIRED_NODE_MAJOR="20"
MC_VERSION="1.21.6"                       # E1-R1 / decisions 0001 (matches start-server.sh + the settings template)
MC_HOST="${MC_HOST:-127.0.0.1}"           # E1-R2 / decisions 0002 — localhost only in offline mode
MC_PORT="${MC_PORT:-25565}"               # E2 start-server.sh default (server-port left unset)
MC_AUTH="offline"                         # E1-R2 / decisions 0002 — matches Paper online-mode=false
MINDCRAFT_PROFILE="${MINDCRAFT_PROFILE:-./profiles/stock-bot.json}"
# Pre-flight reachability-check URL only (consumed by `pnpm llm:local`, which
# reads LOCAL_LLM_BASE_URL itself). Mindcraft's string-form "lmstudio/<id>"
# profiles carry no url, so at the pinned commit the bot ALWAYS uses Mindcraft's
# built-in http://localhost:1234/v1 regardless of this value — run LM Studio there.
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:1234/v1}"
MINDCRAFT_LLM_URL="http://localhost:1234/v1"   # where the bot actually connects (Mindcraft default)
STOCK_BOT_NAME="StockBot"                 # MUST match "name" in profiles/stock-bot.json
MCDATA_REL="src/utils/mcdata.js"
MCDATA_VERSION_PATCH_MARKER="LTAG E3-2 runtime version refresh"
MINDCRAFT_DIR_ABS=""
MCDATA_BACKUP=""
MCDATA_PATH=""

# Resolve the committed template + profile relative to THIS script (not the
# caller's cwd) so the reviewed copies are used no matter where it is invoked.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-stripped.js"
PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/stock-bot.json"

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
fail() { echo "✗ $*" >&2; }

restore_mcdata_patch() {
    if [ -n "${MCDATA_BACKUP:-}" ] && [ -f "$MCDATA_BACKUP" ] && [ -n "${MCDATA_PATH:-}" ]; then
        cp "$MCDATA_BACKUP" "$MCDATA_PATH" 2> /dev/null || true
        rm -f "$MCDATA_BACKUP"
    fi
}

# Print the E3-5 disabled-feature flags + the preserved E2 connect contract.
# Shared by --verify and --dry-run so a reviewer sees, network-free, exactly
# what is off and that nothing about the E2 target changed.
print_stripped_summary() {
    info "── Disabled by E3-5 (superseded by the Python brain) ───────────────────"
    info "  num_examples=0          Mindcraft example retrieval → Python 3-tier memory (decision 0003)"
    info "  relevant_docs_count=0   Mindcraft skill-doc retrieval → Python memory; no embeddings (0003)"
    info "  narrate_behavior=false  Python owns surfaced/streamed output (decision 0004)"
    info "  load_memory=false       Mindcraft session memory → Python pgvector memory (E5 / 0003)"
    info "  speak=false             voice/TTS → Python Edge TTS (decision 0003)"
    info "  allow_vision=false      Mindcraft vision tier unused; cost/surface reduction (0003)"
    info "── Deliberately KEPT ───────────────────────────────────────────────────"
    info "  chat_bot_messages=true  decentralized bot-to-bot conversation is the base (decision 0004)"
    info "── Preserved E2 connect contract (unchanged vs. connect-stock-bot.sh) ──"
    info "  ${MC_HOST}:${MC_PORT}  auth=${MC_AUTH}  minecraft=${MC_VERSION}  profile=${MINDCRAFT_PROFILE}"
    info "Full table + how to reverse each: docs/minecraft/mindcraft-stripped-features.md"
}

# ── Node / npm check (identical posture to setup-mindcraft.sh) ──
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
        info "  See docs/minecraft/mindcraft-stripped-features.md for details."
        return 1
    fi
    if [ "$node_m" != "$REQUIRED_NODE_MAJOR" ]; then
        fail "Node ${node_m} found, but the pinned Mindcraft needs Node ${REQUIRED_NODE_MAJOR} LTS."
        info "  Mindcraft warns Node 24+ breaks native deps; we pin ${REQUIRED_NODE_MAJOR} (E1-R1)."
        info "  Install Node ${REQUIRED_NODE_MAJOR} (see docs/minecraft/mindcraft-stripped-features.md) and retry."
        return 1
    fi
    if ! command -v npm > /dev/null 2>&1; then
        fail "npm not found on PATH (it ships with Node ${REQUIRED_NODE_MAJOR})."
        return 1
    fi
    ok "Node ${node_m} + npm $(npm -v) detected (need Node ${REQUIRED_NODE_MAJOR})"
}

# ── Static assertions on the committed template + profile (no Node/net/git) ──
# Defense-in-depth: the staged stripped settings.js must (a) still point at the
# E2 server, (b) actually have the E3-5 features disabled, and (c) NOT have
# stripped the deliberately-kept decentralized conversation. The profile must be
# local-only. The strict structural diff lives in
# tests/backend/test_mc_stripped_features.py.
verify_committed_assets() {
    local problems=0
    if [ ! -s "$SETTINGS_TEMPLATE" ]; then
        fail "Stripped settings template missing or empty: $SETTINGS_TEMPLATE"; problems=1
    else
        # (a) E2 connect contract preserved (byte-identical to the E3-2 template).
        grep -q '"host": "127.0.0.1"'   "$SETTINGS_TEMPLATE" || { fail "template host is not 127.0.0.1"; problems=1; }
        grep -q '"port": 25565'         "$SETTINGS_TEMPLATE" || { fail "template port is not 25565"; problems=1; }
        grep -q '"auth": "offline"'     "$SETTINGS_TEMPLATE" || { fail "template auth is not offline"; problems=1; }
        grep -q '"minecraft_version": "1.21.6"' "$SETTINGS_TEMPLATE" || { fail "template minecraft_version is not 1.21.6"; problems=1; }
        grep -q '"auto_open_ui": false' "$SETTINGS_TEMPLATE" || { fail "template auto_open_ui is not false"; problems=1; }
        grep -q '"./profiles/stock-bot.json"' "$SETTINGS_TEMPLATE" || { fail "template profile is not ./profiles/stock-bot.json"; problems=1; }
        # (b) E3-5 features actually disabled.
        grep -q '"num_examples": 0,'        "$SETTINGS_TEMPLATE" || { fail "num_examples is not stripped to 0"; problems=1; }
        grep -q '"relevant_docs_count": 0,' "$SETTINGS_TEMPLATE" || { fail "relevant_docs_count is not stripped to 0"; problems=1; }
        grep -q '"narrate_behavior": false,' "$SETTINGS_TEMPLATE" || { fail "narrate_behavior is not stripped to false"; problems=1; }
        grep -q '"load_memory": false,'     "$SETTINGS_TEMPLATE" || { fail "load_memory is not false"; problems=1; }
        grep -q '"speak": false,'           "$SETTINGS_TEMPLATE" || { fail "speak is not false"; problems=1; }
        grep -q '"allow_vision": false,'    "$SETTINGS_TEMPLATE" || { fail "allow_vision is not false"; problems=1; }
        # (c) Decentralized conversation deliberately NOT stripped (decision 0004).
        grep -q '"chat_bot_messages": true,' "$SETTINGS_TEMPLATE" || { fail "chat_bot_messages must stay true (decision 0004 — NOT stripped)"; problems=1; }
    fi
    if [ ! -s "$PROFILE_TEMPLATE" ]; then
        fail "Stock profile missing or empty: $PROFILE_TEMPLATE"; problems=1
    else
        grep -q "\"name\": \"${STOCK_BOT_NAME}\"" "$PROFILE_TEMPLATE" || { fail "profile name is not ${STOCK_BOT_NAME}"; problems=1; }
        grep -q '"model": "lmstudio/'        "$PROFILE_TEMPLATE" || { fail "profile model is not an lmstudio/ id (no external spend)"; problems=1; }
        grep -q '"code_model": "lmstudio/'   "$PROFILE_TEMPLATE" || { fail "profile code_model is not an lmstudio/ id"; problems=1; }
        if grep -q 'openrouter/' "$PROFILE_TEMPLATE"; then
            fail "profile must NOT reference openrouter/ — local validation only"; problems=1
        fi
    fi
    return $problems
}

# ── (b) Resolve + print config (shared by every mode) ──
ok "Stripped Mindcraft bot → E2 server (E3-5: Python-superseded features off)"
info "bot name:  $STOCK_BOT_NAME  (fixed; whitelist this exact name)"
info "server:    ${MC_HOST}:${MC_PORT}  auth=${MC_AUTH}  minecraft=${MC_VERSION}"
info "clone:     $MINDCRAFT_DIR  (pinned $MINDCRAFT_COMMIT)"
info "profile:   $MINDCRAFT_PROFILE  (staged from $PROFILE_TEMPLATE)"
info "settings:  staged from $SETTINGS_TEMPLATE  (stripped)"
info "LM Studio: bot connects to ${MINDCRAFT_LLM_URL}  (Mindcraft built-in for"
info "           string-form lmstudio/ profiles — run LM Studio there; local"
info "           only, zero external spend, decision 0003)"
info "           pre-flight check (pnpm llm:local) uses ${LOCAL_LLM_BASE_URL}"

# ── --verify: static, CI/network-safe checks only ──────
if [ "$MODE" = "verify" ]; then
    if verify_committed_assets; then
        ok "Static verify passed: stripped template disables the E3-5 features,"
        info "keeps the decentralized conversation (0004), still points at the E2"
        info "server, and the reused stock profile is local-only (lmstudio/)."
        echo
        print_stripped_summary
        info "(No clone, no network, no Node, no launch — run without --verify to connect.)"
        exit 0
    fi
    fail "Static verify FAILED — see messages above."
    exit 1
fi

# Resolve the LM Studio model ids. A real run requires the conversation model;
# the building model defaults to it (single-model local validation is fine for
# a stock bot — decision 0003 says set LOCAL_LLM_MODEL_BUILDING when available).
LLM_MODEL="${LOCAL_LLM_MODEL:-}"
LLM_MODEL_BUILDING="${LOCAL_LLM_MODEL_BUILDING:-$LLM_MODEL}"

# ── --dry-run: print the resolved plan, do NOT clone/network/launch ──
if [ "$MODE" = "dry-run" ]; then
    check_node || true   # advisory only in dry-run
    verify_committed_assets || true
    echo
    ok "Dry run complete — no clone, no network, nothing launched."
    info "host:        $MC_HOST"
    info "port:        $MC_PORT"
    info "auth:        $MC_AUTH"
    info "minecraft:   $MC_VERSION"
    info "profile:     $MINDCRAFT_PROFILE  (bot name $STOCK_BOT_NAME)"
    if [ -n "$LLM_MODEL" ]; then
        info "model:       lmstudio/$LLM_MODEL  (conversation tier)"
        info "code_model:  lmstudio/$LLM_MODEL_BUILDING  (building tier)"
    else
        info "model:       (LOCAL_LLM_MODEL unset — REQUIRED for a real run;"
        info "             list ids with: pnpm llm:local --list-only)"
    fi
    echo
    print_stripped_summary
    echo
    info "Would assert: $MINDCRAFT_DIR HEAD == $MINDCRAFT_COMMIT"
    info "Would stage:  $SETTINGS_TEMPLATE → $MINDCRAFT_DIR/settings.js  (stripped)"
    info "Would stage:  $PROFILE_TEMPLATE  → $MINDCRAFT_DIR/${MINDCRAFT_PROFILE#./} (models substituted)"
    info "Would stage:  runtime-version shim in $MINDCRAFT_DIR/$MCDATA_REL (restored on exit)"
    info "Would launch: (cd $MINDCRAFT_DIR && node main.js --profiles $MINDCRAFT_PROFILE)"
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

# (b) The conversation model is mandatory for a real run (local LM Studio only).
if [ -z "$LLM_MODEL" ]; then
    fail "LOCAL_LLM_MODEL is not set — a real run needs a local LM Studio model id."
    info "  List the models LM Studio is serving, then export one:"
    info "    pnpm llm:local --list-only      # or: .venv/bin/python scripts/check_local_llm.py --list-only"
    info "    export LOCAL_LLM_MODEL=<model-id-from-the-list>"
    info "  Optionally also: export LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>"
    info "  This keeps validation 100% local — zero external model spend (decision 0003)."
    exit 1
fi

# (c) Stage the STRIPPED settings.js (host/port/profile substituted; everything
#     else is the reviewed stripped template verbatim). Line-anchored so the
#     comment header is never touched — only the actual setting lines match.
DEST_SETTINGS="$MINDCRAFT_DIR_ABS/settings.js"
if ! sed -E \
    -e "s|^([[:space:]]*\"host\":[[:space:]]*\")[^\"]*(\".*)$|\1${MC_HOST}\2|" \
    -e "s|^([[:space:]]*\"port\":[[:space:]]*)[0-9]+(,.*)$|\1${MC_PORT}\2|" \
    -e "s|^([[:space:]]*\")\\./profiles/stock-bot\\.json(\".*)$|\1${MINDCRAFT_PROFILE}\2|" \
    "$SETTINGS_TEMPLATE" > "$DEST_SETTINGS"; then
    fail "Failed to stage stripped settings.js → $DEST_SETTINGS"
    exit 1
fi
ok "Staged stripped settings.js → $DEST_SETTINGS (host=${MC_HOST} port=${MC_PORT} profile=${MINDCRAFT_PROFILE})"
info "  E3-5 features OFF; chat_bot_messages KEPT (decision 0004)"

# (d) Stage the profile with the LM Studio model ids substituted in.
#     Strip a leading "./" so the on-disk path stays clean (no "..././/...").
DEST_PROFILE="$MINDCRAFT_DIR_ABS/${MINDCRAFT_PROFILE#./}"
mkdir -p "$(dirname -- "$DEST_PROFILE")"
if ! sed \
    -e "s|__LOCAL_LLM_MODEL__|${LLM_MODEL}|g" \
    -e "s|__LOCAL_LLM_MODEL_BUILDING__|${LLM_MODEL_BUILDING}|g" \
    "$PROFILE_TEMPLATE" > "$DEST_PROFILE"; then
    fail "Failed to stage profile → $DEST_PROFILE"
    exit 1
fi
ok "Staged profile → $DEST_PROFILE"
info "  model:      lmstudio/${LLM_MODEL}        (conversation tier — decision 0003)"
info "  code_model: lmstudio/${LLM_MODEL_BUILDING}  (building tier — decision 0003)"

# (e) Apply a tiny launch-time compatibility shim to the disposable clone.
#     At the pinned commit, mcdata.js captures settings.minecraft_version at
#     module import time, before the child process receives settings from the
#     MindServer. That makes Mineflayer auto-select its newest supported
#     protocol (currently 1.21.11) instead of the E2-pinned 1.21.6. We patch
#     only the local clone during this launch and restore it on exit. This is
#     the same shim connect-stock-bot.sh uses (same marker, same restore).
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

# (f) Whitelist reminder. start-server.sh defaults white-list=true, so the E2
#     server will REJECT the bot until "$STOCK_BOT_NAME" is whitelisted.
echo
info "── Whitelist (E2 server defaults to white-list=true) ───────────────────"
info "In the E2 server console, run exactly:"
info "    whitelist add ${STOCK_BOT_NAME}"
info "Or restart the E2 server with the whitelist off (dev only, localhost):"
info "    WHITELIST=false scripts/minecraft/start-server.sh"
info "Skipping this → the bot connects then is kicked with 'not whitelisted'."
echo

# (g) Launch. Mindcraft reads ./settings.js; --profiles is passed explicitly so
#     the launch command itself documents which bot is starting (per the plan).
ok "Launching ${STOCK_BOT_NAME} (stripped) → ${MC_HOST}:${MC_PORT} … (Ctrl+C to stop)"
info "Success looks like: '${STOCK_BOT_NAME} joined the game' in the E2 server"
info "console, ${STOCK_BOT_NAME} in its 'list' output, and the bot moving in-world"
info "(it still acts with the E3-5 features off — the acceptance criterion)."
cd "$MINDCRAFT_DIR_ABS"
node main.js --profiles "$MINDCRAFT_PROFILE"
