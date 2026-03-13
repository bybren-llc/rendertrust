#!/usr/bin/env bash
# E2E test runner using Docker Compose
#
# Spins up ephemeral PostgreSQL + Redis containers, runs the full pytest
# suite against them, then tears everything down.
#
# Usage:
#   ./scripts/run-e2e.sh                     # run all tests
#   ./scripts/run-e2e.sh -k test_health      # run only matching tests
#   ./scripts/run-e2e.sh -m integration      # run integration-marked tests
set -euo pipefail

COMPOSE_FILE="docker-compose.test.yml"
PROJECT_NAME="rendertrust-test"

echo "=== RenderTrust E2E Test Runner ==="
echo "Compose file: ${COMPOSE_FILE}"
echo "Project name: ${PROJECT_NAME}"
echo ""

# Clean up any previous test containers
echo "Removing stale test containers (if any)..."
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down --volumes --remove-orphans 2>/dev/null || true

# Build pytest args: if the caller passed extra arguments, forward them
# into the container's pytest invocation via the PYTEST_ADDOPTS env var.
EXTRA_ARGS=""
if [ $# -gt 0 ]; then
    EXTRA_ARGS="$*"
    echo "Extra pytest args: ${EXTRA_ARGS}"
fi

# Run the test suite
echo ""
echo "Starting test infrastructure (PostgreSQL 16 + Redis 7)..."
if [ -n "$EXTRA_ARGS" ]; then
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run \
        --rm \
        -e PYTEST_ADDOPTS="$EXTRA_ARGS" \
        test-runner
else
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" run \
        --rm \
        test-runner
fi
EXIT_CODE=$?

# Tear down
echo ""
echo "Cleaning up test infrastructure..."
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down --volumes --remove-orphans 2>/dev/null || true

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "=== E2E tests PASSED ==="
else
    echo "=== E2E tests FAILED (exit code: ${EXIT_CODE}) ==="
fi

exit $EXIT_CODE
