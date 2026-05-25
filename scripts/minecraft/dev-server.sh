#!/usr/bin/env bash
# Start the local Minecraft dev server in Docker.
#
# This is the low-friction dev wrapper used by `pnpm dev:minecraft` and the
# root `pnpm dev` command. It exists so local development does not require
# remembering the long Docker command or installing Java 21 on the host.
#
# It runs the same E1/E2-pinned Paper target as start-server.sh:
#   - Minecraft/Paper: 1.21.6, Paper build 48
#   - local/private auth: online-mode=false
#   - localhost port: 25565
#   - whitelist disabled by default so dev clients and StockBot can join
#
# For durable 24/7 hosting, use scripts/minecraft/start-server.sh plus the
# supervision/backup runbooks. This wrapper is intentionally dev-only.
#
# Usage:
#   scripts/minecraft/dev-server.sh            # start/reuse Docker Paper server + follow logs
#   scripts/minecraft/dev-server.sh --no-tail  # start/reuse Docker Paper server and exit
#   scripts/minecraft/dev-server.sh --dry-run  # print resolved Docker config; start nothing
#   scripts/minecraft/dev-server.sh --stop     # stop/remove the dev container
#   scripts/minecraft/dev-server.sh --help
#
# Configuration (environment variables, all optional):
#   MC_CONTAINER_NAME  Docker container name        (default: ltag-minecraft-dev)
#   MC_IMAGE           Docker image                 (default: itzg/minecraft-server:java21)
#   MC_VERSION         Minecraft/Paper version      (default: 1.21.6)
#   PAPER_BUILD        Paper build number           (default: 48)
#   MC_PORT            Host port mapped to 25565    (default: 25565)
#   MEM                Server heap in container     (default: 1G)
#   ONLINE_MODE        Mojang auth verification     (default: FALSE)
#   ENABLE_WHITELIST   Whitelist enforcement        (default: FALSE)
#   DEV_MINECRAFT_WAIT_TIMEOUT  Seconds to wait for "Done (" (default: 180)
set -euo pipefail

MC_CONTAINER_NAME="${MC_CONTAINER_NAME:-ltag-minecraft-dev}"
MC_IMAGE="${MC_IMAGE:-itzg/minecraft-server:java21}"
MC_VERSION="${MC_VERSION:-1.21.6}"
PAPER_BUILD="${PAPER_BUILD:-48}"
MC_PORT="${MC_PORT:-25565}"
MEM="${MEM:-1G}"
ONLINE_MODE="${ONLINE_MODE:-FALSE}"
ENABLE_WHITELIST="${ENABLE_WHITELIST:-FALSE}"
DEV_MINECRAFT_WAIT_TIMEOUT="${DEV_MINECRAFT_WAIT_TIMEOUT:-180}"

MODE="run"
TAIL_LOGS="true"
if [ "${1:-}" = "--" ]; then
    shift
fi
case "${1:-}" in
    --dry-run) MODE="dry-run"; TAIL_LOGS="false" ;;
    --stop) MODE="stop"; TAIL_LOGS="false" ;;
    --no-tail) TAIL_LOGS="false" ;;
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

ok() { echo "✓ $*"; }
info() { echo "  $*"; }
fail() { echo "✗ $*" >&2; }

lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

is_false() {
    case "$(lower "$1")" in
        false|0|no|off) return 0 ;;
        *) return 1 ;;
    esac
}

check_docker() {
    if ! command -v docker > /dev/null 2>&1; then
        fail "Docker not found on PATH. Install/start Docker Desktop and retry."
        return 1
    fi
    if ! docker info > /dev/null 2>&1; then
        fail "Docker is not responding. Start Docker Desktop and retry."
        return 1
    fi
}

container_exists() {
    docker inspect "$MC_CONTAINER_NAME" > /dev/null 2>&1
}

container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$MC_CONTAINER_NAME" 2>/dev/null || true)" = "true" ]
}

print_config() {
    ok "Minecraft dev server (Docker)"
    info "container:       $MC_CONTAINER_NAME"
    info "image:           $MC_IMAGE"
    info "minecraft:       $MC_VERSION (Paper build $PAPER_BUILD)"
    info "port:            127.0.0.1:${MC_PORT} -> container:25565"
    info "memory:          $MEM"
    info "online-mode:     $ONLINE_MODE"
    info "enable-whitelist:$ENABLE_WHITELIST"
}

print_docker_run_command() {
    printf '  docker run -d --rm'
    printf ' --name %q' "$MC_CONTAINER_NAME"
    printf ' -p %q' "${MC_PORT}:25565"
    printf ' -e %q' "EULA=TRUE"
    printf ' -e %q' "TYPE=PAPER"
    printf ' -e %q' "VERSION=${MC_VERSION}"
    printf ' -e %q' "PAPER_BUILD=${PAPER_BUILD}"
    printf ' -e %q' "ONLINE_MODE=${ONLINE_MODE}"
    printf ' -e %q' "ENABLE_WHITELIST=${ENABLE_WHITELIST}"
    printf ' -e %q' "ENABLE_RCON=TRUE"
    printf ' -e %q' "MEMORY=${MEM}"
    printf ' %q\n' "$MC_IMAGE"
}

stop_container() {
    check_docker || exit 1
    if container_exists; then
        docker rm -f "$MC_CONTAINER_NAME" > /dev/null
        ok "Stopped Minecraft dev container: $MC_CONTAINER_NAME"
    else
        ok "Minecraft dev container is not running: $MC_CONTAINER_NAME"
    fi
}

wait_until_ready() {
    local deadline
    deadline=$((SECONDS + DEV_MINECRAFT_WAIT_TIMEOUT))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if ! container_running; then
            fail "Minecraft dev container exited before it was ready."
            docker logs "$MC_CONTAINER_NAME" 2>&1 | tail -n 80 || true
            return 1
        fi
        if docker logs "$MC_CONTAINER_NAME" 2>&1 | grep -q 'Done ('; then
            ok "Minecraft dev server is ready on localhost:${MC_PORT}"
            return 0
        fi
        sleep 2
    done

    fail "Timed out waiting for Minecraft dev server to print 'Done ('."
    docker logs "$MC_CONTAINER_NAME" 2>&1 | tail -n 120 || true
    return 1
}

start_container() {
    check_docker || exit 1
    print_config

    if container_running; then
        ok "Reusing running Minecraft dev container: $MC_CONTAINER_NAME"
    elif container_exists; then
        ok "Starting existing Minecraft dev container: $MC_CONTAINER_NAME"
        docker start "$MC_CONTAINER_NAME" > /dev/null
    else
        ok "Creating Minecraft dev container: $MC_CONTAINER_NAME"
        docker run -d --rm \
            --name "$MC_CONTAINER_NAME" \
            -p "${MC_PORT}:25565" \
            -e EULA=TRUE \
            -e TYPE=PAPER \
            -e "VERSION=${MC_VERSION}" \
            -e "PAPER_BUILD=${PAPER_BUILD}" \
            -e "ONLINE_MODE=${ONLINE_MODE}" \
            -e "ENABLE_WHITELIST=${ENABLE_WHITELIST}" \
            -e ENABLE_RCON=TRUE \
            -e "MEMORY=${MEM}" \
            "$MC_IMAGE" > /dev/null
    fi

    wait_until_ready

    if is_false "$ENABLE_WHITELIST"; then
        # The Docker image uses ENABLE_WHITELIST; this command also fixes older
        # containers accidentally started with WHITELIST=FALSE as a player name.
        docker exec "$MC_CONTAINER_NAME" rcon-cli 'whitelist off' > /dev/null 2>&1 || true
    fi

    info "Connect Minecraft Java Edition 1.21.6 to localhost:${MC_PORT}"
    info "For the visible bot demo, set LOCAL_LLM_MODEL and run: pnpm mc:bot"

    if [ "$TAIL_LOGS" = "true" ]; then
        info "Following server logs. Ctrl+C stops log following; run 'pnpm stop:minecraft' to stop the server."
        docker logs -f "$MC_CONTAINER_NAME"
    fi
}

if [ "$MODE" = "dry-run" ]; then
    print_config
    info "Would run:"
    print_docker_run_command
    info "Dry run only — no Docker container started."
    exit 0
fi

if [ "$MODE" = "stop" ]; then
    stop_container
    exit 0
fi

start_container
