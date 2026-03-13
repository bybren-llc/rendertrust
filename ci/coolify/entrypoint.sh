#!/usr/bin/env bash
# MIT License -- see LICENSE-MIT
#
# RenderTrust Production Entrypoint
#
# This script is the ENTRYPOINT for the production Docker image.
# It handles:
#   1. Waiting for PostgreSQL to become available
#   2. Running Alembic database migrations
#   3. Starting the uvicorn application server
#   4. Forwarding signals for graceful shutdown
#
# Environment variables used:
#   DATABASE_URL  - PostgreSQL connection string (required)
#   APP_HOST      - Bind address (default: 0.0.0.0)
#   APP_PORT      - Bind port (default: 8000)

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────

# Extract host and port from DATABASE_URL for the readiness check.
# DATABASE_URL format: postgresql+asyncpg://user:pass@host:port/dbname
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
MAX_RETRIES="${DB_WAIT_MAX_RETRIES:-30}"
RETRY_INTERVAL="${DB_WAIT_RETRY_INTERVAL:-2}"

APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"

# ── Functions ──────────────────────────────────────────────────────

log() {
    echo "[entrypoint] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

wait_for_postgres() {
    log "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
    local retries=0

    while [ "$retries" -lt "$MAX_RETRIES" ]; do
        # Use Python to attempt a TCP connection since pg_isready may not
        # be installed in the slim image.
        if python -c "
import socket, sys
try:
    s = socket.create_connection(('${DB_HOST}', ${DB_PORT}), timeout=5)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            log "PostgreSQL is ready."
            return 0
        fi

        retries=$((retries + 1))
        log "PostgreSQL not ready (attempt ${retries}/${MAX_RETRIES}). Retrying in ${RETRY_INTERVAL}s..."
        sleep "$RETRY_INTERVAL"
    done

    log "ERROR: PostgreSQL did not become ready within $((MAX_RETRIES * RETRY_INTERVAL))s. Exiting."
    exit 1
}

run_migrations() {
    log "Running Alembic database migrations..."
    if alembic upgrade head; then
        log "Migrations completed successfully."
    else
        log "ERROR: Alembic migrations failed. Exiting."
        exit 1
    fi
}

start_server() {
    log "Starting uvicorn on ${APP_HOST}:${APP_PORT}..."
    # exec replaces this shell process with uvicorn, ensuring that
    # signals (SIGTERM, SIGINT) are delivered directly to uvicorn
    # for graceful shutdown.
    exec uvicorn \
        core.main:app \
        --host "$APP_HOST" \
        --port "$APP_PORT" \
        --workers 1 \
        --log-level info \
        --proxy-headers \
        --forwarded-allow-ips "*"
}

# ── Main ───────────────────────────────────────────────────────────

log "RenderTrust production entrypoint starting..."
wait_for_postgres
run_migrations
start_server
