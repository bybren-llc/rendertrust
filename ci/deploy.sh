#!/usr/bin/env bash
# MIT License -- see LICENSE-MIT
#
# RenderTrust Production Deploy Script
#
# Orchestrates zero-downtime deployments with automatic database migration.
# Migrations run in an ephemeral container so that failure does not affect
# the running application.
#
# Usage:
#   ./ci/deploy.sh                  # Standard deploy (pull + migrate + restart)
#   ./ci/deploy.sh --build          # Build from source instead of pulling
#   ./ci/deploy.sh --no-migrate     # Skip database migration step
#   ./ci/deploy.sh --rollback       # Roll back to the previous image
#
# Environment variables:
#   COMPOSE_FILE      - Docker Compose file (default: docker-compose.prod.yml)
#   COMPOSE_PROJECT   - Compose project name (default: rendertrust)
#   IMAGE_NAME        - Docker image name (default: ghcr.io/cheddarfox/rendertrust/app)
#   IMAGE_TAG         - Docker image tag (default: latest)
#   HEALTH_URL        - Health check URL (default: http://localhost:8000/health)
#   HEALTH_RETRIES    - Health check retries (default: 30)
#   HEALTH_INTERVAL   - Seconds between health checks (default: 2)
#
# Related tickets:
#   - REN-118: Auto-migration on deploy
#   - REN-115: Coolify project setup (entrypoint.sh)
#   - REN-117: Production Docker Compose

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-rendertrust}"
IMAGE_NAME="${IMAGE_NAME:-ghcr.io/cheddarfox/rendertrust/app}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-2}"

# Flags
FLAG_BUILD=false
FLAG_NO_MIGRATE=false
FLAG_ROLLBACK=false

# ── Argument Parsing ───────────────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        --build)       FLAG_BUILD=true ;;
        --no-migrate)  FLAG_NO_MIGRATE=true ;;
        --rollback)    FLAG_ROLLBACK=true ;;
        --help|-h)
            echo "Usage: $0 [--build] [--no-migrate] [--rollback]"
            echo ""
            echo "Options:"
            echo "  --build        Build image from source instead of pulling"
            echo "  --no-migrate   Skip database migration step"
            echo "  --rollback     Roll back to the previous image tag"
            echo "  --help, -h     Show this help message"
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $arg"
            echo "Run '$0 --help' for usage."
            exit 1
            ;;
    esac
done

# ── Functions ──────────────────────────────────────────────────────

log() {
    echo "[deploy] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

log_error() {
    echo "[deploy] $(date -u +%Y-%m-%dT%H:%M:%SZ) ERROR: $*" >&2
}

compose() {
    docker compose \
        -f "${PROJECT_ROOT}/${COMPOSE_FILE}" \
        -p "${COMPOSE_PROJECT}" \
        "$@"
}

# Save the current image digest so we can roll back if needed.
save_current_image() {
    local current_digest
    current_digest=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "${IMAGE_NAME}:${IMAGE_TAG}" 2>/dev/null || true)
    if [ -n "$current_digest" ]; then
        echo "$current_digest" > "${PROJECT_ROOT}/.deploy-previous-image"
        log "Saved current image digest for rollback: ${current_digest}"
    else
        log "No existing image found. Rollback will not be available."
    fi
}

pull_image() {
    log "Pulling image ${IMAGE_NAME}:${IMAGE_TAG}..."
    if ! docker pull "${IMAGE_NAME}:${IMAGE_TAG}"; then
        log_error "Failed to pull image. Aborting deploy."
        exit 1
    fi
    log "Image pulled successfully."
}

build_image() {
    log "Building image from source..."
    if ! compose build app; then
        log_error "Image build failed. Aborting deploy."
        exit 1
    fi
    log "Image built successfully."
}

run_migrations() {
    log "Running database migrations in ephemeral container..."

    # Run alembic upgrade head in a temporary container that is removed
    # after completion. This ensures migration failure does not leave
    # a broken app container running.
    if ! compose run \
        --rm \
        --no-deps \
        -e DATABASE_URL \
        app \
        alembic upgrade head; then
        log_error "Database migration failed. Aborting deploy."
        log_error "The running application has NOT been affected."
        log_error "Fix the migration and re-run, or use --no-migrate to skip."
        exit 1
    fi

    log "Database migrations completed successfully."
}

restart_services() {
    log "Restarting application services..."
    compose up -d --force-recreate --no-build app
    log "Services restarted."
}

health_check() {
    log "Running health check against ${HEALTH_URL}..."
    local retries=0

    while [ "$retries" -lt "$HEALTH_RETRIES" ]; do
        if curl -sf --max-time 5 "${HEALTH_URL}" > /dev/null 2>&1; then
            log "Health check passed."
            return 0
        fi

        retries=$((retries + 1))
        log "Health check attempt ${retries}/${HEALTH_RETRIES} failed. Retrying in ${HEALTH_INTERVAL}s..."
        sleep "$HEALTH_INTERVAL"
    done

    log_error "Health check failed after ${HEALTH_RETRIES} attempts."
    return 1
}

rollback() {
    local previous_image_file="${PROJECT_ROOT}/.deploy-previous-image"

    if [ ! -f "$previous_image_file" ]; then
        log_error "No previous image recorded. Cannot roll back."
        log_error "You may need to manually specify an image tag."
        exit 1
    fi

    local previous_image
    previous_image=$(cat "$previous_image_file")
    log "Rolling back to previous image: ${previous_image}"

    # Tag the previous image as the current tag so compose picks it up
    docker tag "$previous_image" "${IMAGE_NAME}:${IMAGE_TAG}" 2>/dev/null || true

    compose up -d --force-recreate --no-build app
    log "Rollback initiated. Running health check..."

    if health_check; then
        log "Rollback successful. Application is healthy."
    else
        log_error "Rollback health check failed. Manual intervention required."
        compose logs --tail=50 app
        exit 1
    fi
}

# ── Main ───────────────────────────────────────────────────────────

cd "$PROJECT_ROOT"

log "=========================================="
log "RenderTrust Deploy"
log "  Compose file : ${COMPOSE_FILE}"
log "  Project      : ${COMPOSE_PROJECT}"
log "  Image        : ${IMAGE_NAME}:${IMAGE_TAG}"
log "  Build        : ${FLAG_BUILD}"
log "  Migrate      : $([ "$FLAG_NO_MIGRATE" = true ] && echo 'SKIP' || echo 'YES')"
log "  Rollback     : ${FLAG_ROLLBACK}"
log "=========================================="

# Handle rollback mode
if [ "$FLAG_ROLLBACK" = true ]; then
    rollback
    exit 0
fi

# Step 1: Save current image for rollback
save_current_image

# Step 2: Get the new image
if [ "$FLAG_BUILD" = true ]; then
    build_image
else
    pull_image
fi

# Step 3: Run migrations (unless skipped)
if [ "$FLAG_NO_MIGRATE" = false ]; then
    run_migrations
fi

# Step 4: Restart the application
restart_services

# Step 5: Verify health
if health_check; then
    log "=========================================="
    log "Deploy completed successfully."
    log "=========================================="
else
    log_error "Deploy health check failed. Initiating automatic rollback..."
    rollback
    exit 1
fi
