#!/usr/bin/env bash
# Validate that all development services are running and healthy.
set -euo pipefail

PASS=0
FAIL=0

check() {
    local name="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        echo "✓ $name"
        PASS=$((PASS + 1))
    else
        echo "✗ $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "Checking development services..."
echo

# Redis
check "Redis PING/PONG" docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD:-devpassword}" ping

# PostgreSQL readiness
check "PostgreSQL ready" docker compose exec -T postgres pg_isready -U agi -d livestream_agi

# pgvector extension
check "pgvector extension" bash -c 'docker compose exec -T postgres \
    psql -U agi -d livestream_agi -tAc \
    "SELECT 1 FROM pg_extension WHERE extname = '"'"'vector'"'"';" | grep -q 1'

# pg_trgm extension
check "pg_trgm extension" bash -c 'docker compose exec -T postgres \
    psql -U agi -d livestream_agi -tAc \
    "SELECT 1 FROM pg_extension WHERE extname = '"'"'pg_trgm'"'"';" | grep -q 1'

# Langfuse HTTP
LANGFUSE_PORT="${LANGFUSE_PORT:-3100}"
check "Langfuse UI (port $LANGFUSE_PORT)" curl -sf "http://localhost:$LANGFUSE_PORT"

# Minecraft server liveness — OPT-IN (E2-6, issue #531). Off by default so
# the 5-service dev gate and CI (which run with no Minecraft server present)
# keep passing unchanged. Set CHECK_MINECRAFT=1 to include it. The probe
# (scripts/minecraft/health.sh --quiet) resolves the port from SERVER_PORT
# or server.properties; see docs/minecraft/health.md.
if [ "${CHECK_MINECRAFT:-0}" = "1" ]; then
    MC_HOST="${SERVER_HOST:-127.0.0.1}"
    MC_PORT="${SERVER_PORT:-auto}"
    check "Minecraft server ($MC_HOST:$MC_PORT)" \
        bash "$(dirname "$0")/minecraft/health.sh" --quiet
fi

echo
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    echo
    echo "Troubleshooting:"
    echo "  - If extensions are missing, run:"
    echo "    docker compose exec postgres psql -U agi -d livestream_agi -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;'"
    echo "  - Or reset volumes: docker compose down -v && docker compose up -d"
    exit 1
fi
