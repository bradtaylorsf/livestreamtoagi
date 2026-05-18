#!/usr/bin/env bash
# Restore a backed-up Paper Minecraft world, or RESET to a fresh one.
#
# This is the committed restore/reset script referenced by
# docs/minecraft/backup-restore.md (issue #530, epic E2-5). It is the
# counterpart to scripts/minecraft/backup.sh: it puts a prior world back, or
# wipes the world so the next start-server.sh run regenerates a clean one
# from world.config (the path experimental run mode uses — E12 wires that up;
# this issue only provides the clean reset itself).
#
# Both destructive paths take a SAFETY snapshot of the current world FIRST
# (a pre-restore-/pre-reset- archive via backup.sh) so a mistaken restore or
# reset is itself recoverable, and both REFUSE to run while the server looks
# like it is up (restoring/wiping under a live server corrupts the world).
#
# Usage:
#   scripts/minecraft/restore.sh --list             # list restorable archives
#   scripts/minecraft/restore.sh --latest            # restore the newest backup
#   scripts/minecraft/restore.sh <archive>           # restore a specific archive
#   scripts/minecraft/restore.sh --reset             # wipe → fresh world on next start
#   scripts/minecraft/restore.sh --latest --yes      # skip the confirm prompt
#   scripts/minecraft/restore.sh --help
#
# <archive> may be an absolute/relative path or just a filename inside
# BACKUP_DIR. Destructive actions confirm interactively unless --yes (-y) is
# given; with no TTY and no --yes they refuse rather than guess.
#
# Configuration (environment variables, all optional):
#   SERVER_DIR     Where the server/world lives      (default: ./minecraft-server)
#   WORLD_CONFIG   World-gen config (for LEVEL_NAME)  (default: <script dir>/world.config)
#   BACKUP_DIR     Where archives live                (default: $SERVER_DIR/backups)
#   CHILD_PID_FILE Live-server PID file to guard on   (default: $SERVER_DIR/logs/supervise-child.pid)
#
# CHILD_PID_FILE defaults to the same path supervise.sh (issue #529, E2-4)
# writes the live server PID to, so the "is it running?" guard works out of
# the box for the supervise.sh path. For the systemd path stop the unit
# (`sudo systemctl stop minecraft`) before restoring — see the docs.
set -euo pipefail

ok()   { echo "✓ $*"; }
info() { echo "  $*"; }
fail() { echo "✗ $*" >&2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

SERVER_DIR="${SERVER_DIR:-./minecraft-server}"
WORLD_CONFIG="${WORLD_CONFIG:-$SCRIPT_DIR/world.config}"
BACKUP_DIR="${BACKUP_DIR:-$SERVER_DIR/backups}"
CHILD_PID_FILE="${CHILD_PID_FILE:-$SERVER_DIR/logs/supervise-child.pid}"

MODE=""
ARCHIVE_ARG=""
ASSUME_YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --list)  MODE="list" ;;
        --reset) MODE="reset" ;;
        --latest)
            MODE="restore"; ARCHIVE_ARG="--latest" ;;
        --yes|-y) ASSUME_YES=1 ;;
        --help|-h)
            # Print the contiguous comment header (skip the shebang, stop at
            # the first non-comment line) so help never leaks script code.
            awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next}{exit}' "$0"
            exit 0
            ;;
        --*)
            echo "✗ Unknown argument: $1 (try --help)" >&2
            exit 2
            ;;
        *)
            if [ -n "$ARCHIVE_ARG" ]; then
                echo "✗ Unexpected extra argument: $1 (try --help)" >&2
                exit 2
            fi
            MODE="restore"; ARCHIVE_ARG="$1" ;;
    esac
    shift
done

if [ -z "$MODE" ]; then
    fail "Nothing to do. Pass an archive, --latest, --list, or --reset."
    info "  See: scripts/minecraft/restore.sh --help"
    exit 2
fi

# read_world_key KEY → last "KEY=value" in WORLD_CONFIG (fixed allow-list,
# never sourced). Mirrors start-server.sh / backup.sh so all three agree on
# which world folders make up "the world".
read_world_key() {
    [ -f "$WORLD_CONFIG" ] || return 0
    tr -d '\r' < "$WORLD_CONFIG" | sed -nE "s/^${1}=(.*)$/\1/p" | tail -n1
}
LEVEL_NAME="$(read_world_key LEVEL_NAME)"; LEVEL_NAME="${LEVEL_NAME:-world}"
[ -n "$LEVEL_NAME" ] || { fail "LEVEL_NAME resolved empty — check $WORLD_CONFIG"; exit 1; }

# ── --list: delegate to backup.sh so listing has ONE implementation ──
if [ "$MODE" = "list" ]; then
    exec env SERVER_DIR="$SERVER_DIR" WORLD_CONFIG="$WORLD_CONFIG" \
        BACKUP_DIR="$BACKUP_DIR" bash "$SCRIPT_DIR/backup.sh" --list
fi

# ── Refuse while the server appears to be running ──────
refuse_if_running() {
    [ -f "$CHILD_PID_FILE" ] || return 0
    local pid
    pid="$(tr -dc '0-9' < "$CHILD_PID_FILE" 2> /dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2> /dev/null; then
        fail "The server appears to be RUNNING (pid $pid via $CHILD_PID_FILE)."
        info "  Stop it first so the world is saved and consistent:"
        info "    supervise.sh path: Ctrl+C, or kill the supervisor"
        info "    systemd path:      sudo systemctl stop minecraft"
        info "  Then re-run this. Restoring/resetting under a live server"
        info "  corrupts the world."
        exit 4
    fi
}

# ── Interactive confirmation gate (unless --yes) ───────
confirm() {  # $1 = human description of the destructive action
    [ "$ASSUME_YES" -eq 1 ] && return 0
    if [ ! -t 0 ]; then
        fail "Refusing to $1 without confirmation and no TTY."
        info "  Re-run with --yes if you are sure."
        exit 3
    fi
    printf '  This will %s. Type "yes" to continue: ' "$1"
    local reply
    read -r reply
    if [ "$reply" != "yes" ]; then
        info "Aborted — no changes made."
        exit 0
    fi
}

# ── Take a pre-op safety snapshot of the current world ──
snapshot() {  # $1 = archive prefix (pre-restore | pre-reset)
    if [ ! -d "$SERVER_DIR/$LEVEL_NAME" ]; then
        info "No current '$LEVEL_NAME' world — skipping the $1 safety backup."
        return 0
    fi
    info "Saving a $1 safety backup of the current world first…"
    env SERVER_DIR="$SERVER_DIR" WORLD_CONFIG="$WORLD_CONFIG" \
        BACKUP_DIR="$BACKUP_DIR" BACKUP_PREFIX="$1" \
        bash "$SCRIPT_DIR/backup.sh"
}

# ── Remove the world folders (overworld + nether + end) ─
remove_world_folders() {
    local d
    for d in "$LEVEL_NAME" "${LEVEL_NAME}_nether" "${LEVEL_NAME}_the_end"; do
        if [ -e "$SERVER_DIR/$d" ]; then
            # ${SERVER_DIR:?} guards against an empty var → rm -rf "/...".
            rm -rf "${SERVER_DIR:?}/$d"
            info "removed $d"
        fi
    done
}

# ── RESET: clean world on next start (the experimental-mode path) ──
if [ "$MODE" = "reset" ]; then
    refuse_if_running
    confirm "DELETE the current '$LEVEL_NAME' world and reset to a fresh one"
    snapshot "pre-reset"
    remove_world_folders
    # Also drop the generated server.properties so start-server.sh writes a
    # fresh one from world.config (E2-2). start-server.sh never clobbers an
    # existing server.properties, so leaving it would pin the OLD world gen.
    if [ -f "$SERVER_DIR/server.properties" ]; then
        rm -f "$SERVER_DIR/server.properties"
        info "removed server.properties (start-server.sh will regenerate it)"
    fi
    ok "Reset complete — '$SERVER_DIR' is clean."
    info "Next 'scripts/minecraft/start-server.sh' run generates a fresh"
    info "world from $WORLD_CONFIG (issue #527). A pre-reset safety backup"
    info "was saved in $BACKUP_DIR if there was a world to keep."
    exit 0
fi

# ── RESTORE: resolve which archive ─────────────────────
resolve_archive() {
    if [ "$ARCHIVE_ARG" = "--latest" ]; then
        # Newest periodic backup (the scheduled "world-" series), chosen by
        # the embedded UTC timestamp — same ordering rule backup.sh uses, so
        # this does not depend on scraping backup.sh's human output.
        local f ts latest
        latest=""
        # shellcheck disable=SC2086  # intentional glob on the world- series
        for f in "$BACKUP_DIR"/world-*.tar.gz; do
            [ -e "$f" ] || continue
            ts="$(printf '%s\n' "$f" \
                | sed -nE 's#.*-([0-9]{8}T[0-9]{6}Z)\.tar\.gz$#\1#p')"
            [ -n "$ts" ] || continue
            if [ -z "$latest" ] || [ "$ts" \> "${latest%%$'\t'*}" ]; then
                latest="$ts"$'\t'"$f"
            fi
        done
        [ -n "$latest" ] || { fail "No 'world-' backups found in $BACKUP_DIR."; exit 1; }
        printf '%s\n' "${latest#*$'\t'}"
        return 0
    fi
    if [ -f "$ARCHIVE_ARG" ]; then
        printf '%s\n' "$ARCHIVE_ARG"; return 0
    fi
    if [ -f "$BACKUP_DIR/$ARCHIVE_ARG" ]; then
        printf '%s\n' "$BACKUP_DIR/$ARCHIVE_ARG"; return 0
    fi
    fail "Archive not found: $ARCHIVE_ARG"
    info "  Looked at '$ARCHIVE_ARG' and '$BACKUP_DIR/$ARCHIVE_ARG'."
    info "  List options: scripts/minecraft/restore.sh --list"
    exit 1
}

ARCHIVE="$(resolve_archive)"
if ! tar -tzf "$ARCHIVE" > /dev/null 2>&1; then
    fail "Not a readable .tar.gz archive: $ARCHIVE"
    exit 1
fi

refuse_if_running
confirm "REPLACE the current '$LEVEL_NAME' world with $(basename "$ARCHIVE")"
snapshot "pre-restore"
remove_world_folders

mkdir -p "$SERVER_DIR"
if ! tar -C "$SERVER_DIR" -xzf "$ARCHIVE"; then
    fail "Restore failed while extracting $ARCHIVE into $SERVER_DIR"
    info "  A pre-restore safety backup of the previous world is in $BACKUP_DIR."
    exit 1
fi
ok "Restored world from $(basename "$ARCHIVE") into $SERVER_DIR"
info "The archive's server.properties was restored too, so this is the"
info "exact world configuration that was backed up. Start the server with"
info "scripts/minecraft/start-server.sh."
