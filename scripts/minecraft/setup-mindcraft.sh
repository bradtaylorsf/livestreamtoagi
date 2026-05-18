#!/usr/bin/env bash
# Fork-pinned, reproducible Mindcraft install (beginner walkthrough).
#
# This is the committed setup script referenced by docs/minecraft/mindcraft-fork.md
# (issue #533, epic E3). It is safe to run repeatedly: it clones the pinned fork
# once, re-checks out the exact pinned commit, and installs deterministically.
#
# Pinned defaults come from the E1 decisions:
#   - Fork:   bradtaylorsf/mindcraft  (org fork of mindcraft-bots/mindcraft)
#   - Commit: 35be480b4cc0bca990278e6103a1426392559d96  (E1-R1 → docs/decisions/0001)
#   - Node:   20 LTS                                     (E1-R1 → docs/decisions/0001)
# docs/decisions/0001-minecraft-version-and-server.md (lines 26-30) is the
# authoritative source of truth once merged; the defaults below are kept in
# sync with it and can be overridden via env vars.
#
# Upstream Mindcraft commits NO lockfile at the pinned commit, so determinism
# comes from the committed, reviewed copy next to this script
# (scripts/minecraft/mindcraft-package-lock.json). The script stages that copy
# into the clone and runs `npm ci`, which itself aborts if the lockfile and the
# pinned package.json ever drift apart.
#
# Usage:
#   scripts/minecraft/setup-mindcraft.sh            # clone + pin + npm ci
#   scripts/minecraft/setup-mindcraft.sh --dry-run  # print resolved config; no clone/network/install
#   scripts/minecraft/setup-mindcraft.sh --verify   # static checks only (CI/network-safe)
#   scripts/minecraft/setup-mindcraft.sh --help
#
# Configuration (environment variables, all optional):
#   MINDCRAFT_REPO    Git URL of the pinned fork  (default: https://github.com/bradtaylorsf/mindcraft.git)
#   MINDCRAFT_COMMIT  Exact commit to pin to      (default: 35be480b4cc0bca990278e6103a1426392559d96)
#   MINDCRAFT_DIR     Where the clone lives       (default: ./mindcraft)
#
# Customizations are explicitly OUT of scope for this issue — this only forks,
# pins, and reproducibly installs. Pointing a bot at the E2 server is E3-2
# (#534); model routing is E3-3 (#535). This issue has no LLM runtime path.
set -euo pipefail

# ── Pinned E1 defaults (kept in sync with docs/decisions/0001 lines 26-30) ──
MINDCRAFT_REPO="${MINDCRAFT_REPO:-https://github.com/bradtaylorsf/mindcraft.git}"
MINDCRAFT_COMMIT="${MINDCRAFT_COMMIT:-35be480b4cc0bca990278e6103a1426392559d96}"
MINDCRAFT_DIR="${MINDCRAFT_DIR:-./mindcraft}"
REQUIRED_NODE_MAJOR="20"

# Resolve the committed lockfile relative to THIS script (not the caller's cwd)
# so the reviewed copy is used no matter where the script is invoked from.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMMITTED_LOCK="$SCRIPT_DIR/mindcraft-package-lock.json"
NPM_CI_LOG=""
cleanup() {
    if [ -n "${NPM_CI_LOG:-}" ]; then
        rm -f "$NPM_CI_LOG"
    fi
}
trap cleanup EXIT

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

# ── (a) Node / npm check ───────────────────────────────
# A real run requires Node $REQUIRED_NODE_MAJOR LTS and npm. In --dry-run and
# --verify we only warn so the config/static checks stay verifiable on a
# machine without (or with a different) Node — same posture as the Java check
# in start-server.sh.
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
        info "  Debian/Ubuntu: see https://github.com/nodesource/distributions"
        info "  See docs/minecraft/mindcraft-fork.md for details."
        return 1
    fi
    if [ "$node_m" != "$REQUIRED_NODE_MAJOR" ]; then
        fail "Node ${node_m} found, but the pinned Mindcraft needs Node ${REQUIRED_NODE_MAJOR} LTS."
        info "  Mindcraft warns Node 24+ breaks native deps; we pin ${REQUIRED_NODE_MAJOR} (E1-R1)."
        info "  Install Node ${REQUIRED_NODE_MAJOR} (see docs/minecraft/mindcraft-fork.md) and retry."
        return 1
    fi
    if ! command -v npm > /dev/null 2>&1; then
        fail "npm not found on PATH (it ships with Node ${REQUIRED_NODE_MAJOR})."
        return 1
    fi
    ok "Node ${node_m} + npm $(npm -v) detected (need Node ${REQUIRED_NODE_MAJOR})"
}

# ── (b) Resolve + print config (shared by every mode) ──
ok "Pinned Mindcraft fork"
info "repo:    $MINDCRAFT_REPO"
info "commit:  $MINDCRAFT_COMMIT"
info "dir:     $MINDCRAFT_DIR"
info "lock:    $COMMITTED_LOCK"
info "node:    ${REQUIRED_NODE_MAJOR} LTS  (install: npm ci)"

# ── --verify: static, CI/network-safe checks only ──────
# Used by the headless verifier. Asserts the vendored lockfile is present and
# well-formed without touching the network, Node, or git. The strict JSON
# parse lives in tests/backend/test_minecraft_setup_mindcraft.py.
if [ "$MODE" = "verify" ]; then
    if [ ! -s "$COMMITTED_LOCK" ]; then
        fail "Committed lockfile missing or empty: $COMMITTED_LOCK"
        exit 1
    fi
    if ! grep -q '"lockfileVersion"' "$COMMITTED_LOCK"; then
        fail "Committed lockfile has no lockfileVersion: $COMMITTED_LOCK"
        exit 1
    fi
    if ! grep -q '"name": *"mindcraft"' "$COMMITTED_LOCK"; then
        fail "Committed lockfile is not for the mindcraft package: $COMMITTED_LOCK"
        exit 1
    fi
    ok "Static verify passed: vendored lockfile present and well-formed."
    info "(No clone, no network, no install — run without --verify to install.)"
    exit 0
fi

# ── --dry-run: print resolved plan, do NOT clone/network/install ──
if [ "$MODE" = "dry-run" ]; then
    check_node || true   # advisory only in dry-run
    echo
    ok "Dry run complete — no clone, no network, nothing installed."
    info "Would clone:    $MINDCRAFT_REPO → $MINDCRAFT_DIR"
    info "Would checkout: $MINDCRAFT_COMMIT (then hard-assert HEAD == that SHA)"
    info "Would stage:    $COMMITTED_LOCK → $MINDCRAFT_DIR/package-lock.json"
    info "Would install:  npm ci  (deterministic, lockfile-pinned)"
    exit 0
fi

# ── Real run ───────────────────────────────────────────
check_node || exit 1

command -v git > /dev/null 2>&1 || { fail "git not found on PATH."; exit 1; }

# ── (c) Idempotent clone-or-fetch ──────────────────────
if [ -d "$MINDCRAFT_DIR/.git" ]; then
    ok "Reusing existing clone at $MINDCRAFT_DIR"
    # A stale clone may point `origin` at a different remote (e.g. upstream
    # instead of our fork). Realign it before fetching so we pin from the
    # intended repo, not whatever this tree happened to be cloned from.
    EXISTING_ORIGIN="$(git -C "$MINDCRAFT_DIR" remote get-url origin 2>/dev/null || true)"
    if [ -z "$EXISTING_ORIGIN" ]; then
        info "origin remote is missing; adding $MINDCRAFT_REPO"
        git -C "$MINDCRAFT_DIR" remote add origin "$MINDCRAFT_REPO"
    elif [ "$EXISTING_ORIGIN" != "$MINDCRAFT_REPO" ]; then
        info "origin is '$EXISTING_ORIGIN'; repointing it at $MINDCRAFT_REPO"
        git -C "$MINDCRAFT_DIR" remote set-url origin "$MINDCRAFT_REPO"
    fi
    info "Fetching latest refs so the pinned commit is available locally…"
    git -C "$MINDCRAFT_DIR" fetch --quiet --tags origin
else
    info "Cloning $MINDCRAFT_REPO → $MINDCRAFT_DIR"
    git clone --quiet "$MINDCRAFT_REPO" "$MINDCRAFT_DIR"
fi

# ── (d) Pin to the exact commit + hard-assert ──────────
git -C "$MINDCRAFT_DIR" checkout --quiet --detach "$MINDCRAFT_COMMIT"
HEAD_SHA="$(git -C "$MINDCRAFT_DIR" rev-parse HEAD)"
if [ "$HEAD_SHA" != "$MINDCRAFT_COMMIT" ]; then
    fail "Pinned-commit assertion FAILED."
    info "  HEAD is     $HEAD_SHA"
    info "  expected    $MINDCRAFT_COMMIT"
    info "  Refusing to install an unpinned tree."
    exit 1
fi
ok "Checked out the pinned commit $MINDCRAFT_COMMIT"

# ── (e) Stage the vendored lockfile (drift guard) ───────
CLONE_LOCK="$MINDCRAFT_DIR/package-lock.json"
if [ -f "$CLONE_LOCK" ]; then
    # The pinned upstream ships no lockfile today. If a future re-pin adds
    # one, it MUST byte-match our reviewed copy or the install is not the one
    # we vetted — fail loudly rather than silently install something else.
    if ! diff -q "$COMMITTED_LOCK" "$CLONE_LOCK" > /dev/null 2>&1; then
        fail "Lockfile drift detected."
        info "  $CLONE_LOCK differs from the committed $COMMITTED_LOCK."
        info "  Upstream changed its lockfile at the pinned commit. Re-vet and"
        info "  refresh scripts/minecraft/mindcraft-package-lock.json first."
        exit 1
    fi
    ok "Upstream lockfile matches the committed vendored copy"
else
    cp "$COMMITTED_LOCK" "$CLONE_LOCK"
    ok "Staged the vendored lockfile → $CLONE_LOCK (upstream commits none)"
fi

# ── (f) Deterministic install ──────────────────────────
# `npm ci` installs strictly from package-lock.json and aborts if the lockfile
# and package.json are out of sync — that IS the drift check for the pinned
# package.json (the SHA assertion above fixes package.json content).
info "Installing dependencies: npm ci (deterministic, lockfile-pinned)…"
NPM_CI_LOG="$(mktemp -t mindcraft-npm-ci.XXXXXX)"
if ! ( cd "$MINDCRAFT_DIR" && npm ci 2>&1 | tee "$NPM_CI_LOG" ); then
    fail "npm ci failed. See the output above."
    exit 1
fi
if grep -q \
    -e '^\*\*ERROR\*\* Failed to apply patch' \
    -e 'Warning: patch-package detected a patch file version mismatch' \
    "$NPM_CI_LOG"; then
    fail "patch-package reported a failed patch or version mismatch during npm ci."
    info "  The vendored lockfile must resolve package versions that match upstream patches."
    info "  Refresh scripts/minecraft/mindcraft-package-lock.json and re-run."
    exit 1
fi

ok "Mindcraft installed deterministically at the pinned commit."
info "Next: E3-2 (#534) points one stock bot at the E2 server. This issue stops"
info "      at a reproducible install — no customizations, no LLM runtime."
