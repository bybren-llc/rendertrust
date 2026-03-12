#!/usr/bin/env bash
# MIT License -- see LICENSE-MIT
#
# restore-db.sh -- PostgreSQL restore script for RenderTrust
#
# Usage: ./scripts/restore-db.sh <dump_file_or_s3_path>
#
# Arguments:
#   dump_file_or_s3_path  Path to a local .dump file or an S3 URI
#                         (e.g., s3://bucket/db/rendertrust_db_20260312_020000.dump)
#
# Environment variables (required):
#   DATABASE_URL          PostgreSQL connection string
#                         OR set PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE individually
#
# Environment variables (required if using S3 path):
#   AWS_ACCESS_KEY_ID     S3 access key (or configure via aws cli)
#   AWS_SECRET_ACCESS_KEY S3 secret key (or configure via aws cli)
#   S3_ENDPOINT_URL       S3-compatible endpoint (optional, for non-AWS S3)

set -euo pipefail

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
SCRIPT_NAME="$(basename "$0")"
TEMP_DIR="${TMPDIR:-/tmp}"

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] ${SCRIPT_NAME}: $*"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] ${SCRIPT_NAME}: $*" >&2
}

log_warn() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] ${SCRIPT_NAME}: $*" >&2
}

# ------------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------------
if [[ $# -lt 1 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    echo "Usage: ${SCRIPT_NAME} <dump_file_or_s3_path>"
    echo ""
    echo "Arguments:"
    echo "  dump_file_or_s3_path  Local .dump file or S3 URI"
    echo "                        e.g., /var/backups/rendertrust/db/rendertrust_db_20260312_020000.dump"
    echo "                        e.g., s3://my-bucket/db/rendertrust_db_20260312_020000.dump"
    echo ""
    echo "Environment variables:"
    echo "  DATABASE_URL          PostgreSQL connection string"
    echo "  S3_ENDPOINT_URL       S3-compatible endpoint (optional)"
    exit 0
fi

SOURCE="$1"
LOCAL_DUMP=""
CLEANUP_DUMP=false

# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------
if ! command -v pg_restore &>/dev/null; then
    log_error "pg_restore not found. Install PostgreSQL client tools."
    exit 2
fi

if ! command -v psql &>/dev/null; then
    log_error "psql not found. Install PostgreSQL client tools."
    exit 2
fi

# Determine database connection
if [[ -n "${DATABASE_URL:-}" ]]; then
    DB_NAME=$(echo "${DATABASE_URL}" | sed -E 's|.*\/([^?]+).*|\1|')
    log_info "Using DATABASE_URL (database: ${DB_NAME})"
elif [[ -n "${PGDATABASE:-}" ]]; then
    DB_NAME="${PGDATABASE}"
    log_info "Using PG* environment variables (database: ${DB_NAME})"
else
    log_error "Either DATABASE_URL or PGDATABASE must be set"
    exit 1
fi

# ------------------------------------------------------------------
# Resolve source (local file or S3)
# ------------------------------------------------------------------
if [[ "${SOURCE}" == s3://* ]]; then
    log_info "Source is an S3 URI: ${SOURCE}"

    if ! command -v aws &>/dev/null; then
        log_error "aws cli not found. Install it to download from S3."
        exit 2
    fi

    LOCAL_DUMP="${TEMP_DIR}/$(basename "${SOURCE}")"
    CLEANUP_DUMP=true

    S3_ARGS=()
    if [[ -n "${S3_ENDPOINT_URL:-}" ]]; then
        S3_ARGS+=(--endpoint-url "${S3_ENDPOINT_URL}")
    fi

    log_info "Downloading from S3 to ${LOCAL_DUMP}..."
    if ! aws s3 cp "${SOURCE}" "${LOCAL_DUMP}" "${S3_ARGS[@]}"; then
        log_error "Failed to download backup from S3"
        exit 4
    fi
    log_info "Download complete"
else
    LOCAL_DUMP="${SOURCE}"
    log_info "Source is a local file: ${LOCAL_DUMP}"
fi

# Verify the dump file exists and is readable
if [[ ! -f "${LOCAL_DUMP}" ]]; then
    log_error "Dump file not found: ${LOCAL_DUMP}"
    exit 3
fi

if [[ ! -r "${LOCAL_DUMP}" ]]; then
    log_error "Dump file is not readable: ${LOCAL_DUMP}"
    exit 3
fi

DUMP_SIZE=$(stat --format=%s "${LOCAL_DUMP}" 2>/dev/null || stat -f%z "${LOCAL_DUMP}" 2>/dev/null)
log_info "Dump file size: ${DUMP_SIZE} bytes"

# ------------------------------------------------------------------
# Pre-restore checks
# ------------------------------------------------------------------
log_info "=== Pre-Restore Checks ==="

# Verify dump integrity
log_info "Verifying dump file integrity..."
if ! pg_restore --list "${LOCAL_DUMP}" > /dev/null 2>&1; then
    log_error "Dump file integrity check FAILED -- file may be corrupt"
    [[ "${CLEANUP_DUMP}" == "true" ]] && rm -f "${LOCAL_DUMP}"
    exit 3
fi
log_info "Dump file integrity check passed"

# Check database connectivity
log_info "Checking database connectivity..."
if [[ -n "${DATABASE_URL:-}" ]]; then
    if ! psql "${DATABASE_URL}" -c "SELECT 1;" > /dev/null 2>&1; then
        log_error "Cannot connect to database. Check DATABASE_URL."
        [[ "${CLEANUP_DUMP}" == "true" ]] && rm -f "${LOCAL_DUMP}"
        exit 5
    fi
else
    if ! psql -c "SELECT 1;" > /dev/null 2>&1; then
        log_error "Cannot connect to database. Check PG* environment variables."
        [[ "${CLEANUP_DUMP}" == "true" ]] && rm -f "${LOCAL_DUMP}"
        exit 5
    fi
fi
log_info "Database connectivity confirmed"

# Warn about data loss
echo ""
echo "================================================================="
echo "  WARNING: This will OVERWRITE data in database '${DB_NAME}'"
echo "  This operation cannot be undone."
echo "================================================================="
echo ""

# If running interactively, prompt for confirmation
if [[ -t 0 ]]; then
    read -r -p "Are you sure you want to proceed? (yes/no): " CONFIRM
    if [[ "${CONFIRM}" != "yes" ]]; then
        log_info "Restore cancelled by user"
        [[ "${CLEANUP_DUMP}" == "true" ]] && rm -f "${LOCAL_DUMP}"
        exit 0
    fi
else
    log_warn "Non-interactive mode -- proceeding without confirmation"
fi

# ------------------------------------------------------------------
# Perform restore
# ------------------------------------------------------------------
log_info "=== Starting Restore ==="
log_info "Restoring from: ${LOCAL_DUMP}"

RESTORE_START=$(date +%s)

if [[ -n "${DATABASE_URL:-}" ]]; then
    pg_restore --dbname="${DATABASE_URL}" \
        --clean --if-exists \
        --no-owner --no-privileges \
        --verbose \
        "${LOCAL_DUMP}" 2>&1 | while IFS= read -r line; do
        log_info "pg_restore: ${line}"
    done
else
    pg_restore --clean --if-exists \
        --no-owner --no-privileges \
        --verbose \
        "${LOCAL_DUMP}" 2>&1 | while IFS= read -r line; do
        log_info "pg_restore: ${line}"
    done
fi

RESTORE_END=$(date +%s)
RESTORE_DURATION=$((RESTORE_END - RESTORE_START))
log_info "Restore completed in ${RESTORE_DURATION} seconds"

# ------------------------------------------------------------------
# Post-restore verification
# ------------------------------------------------------------------
log_info "=== Post-Restore Verification ==="

run_sql() {
    if [[ -n "${DATABASE_URL:-}" ]]; then
        psql "${DATABASE_URL}" -t -A -c "$1" 2>/dev/null
    else
        psql -t -A -c "$1" 2>/dev/null
    fi
}

# Check Alembic migration version
log_info "Checking Alembic migration version..."
MIGRATION_VERSION=$(run_sql "SELECT version_num FROM alembic_version LIMIT 1;" || echo "UNKNOWN")
log_info "Current migration version: ${MIGRATION_VERSION}"

# Get table row counts for key tables
log_info "Checking row counts for key tables..."

TABLES=("users" "credits" "transactions" "edge_nodes" "jobs")
for TABLE in "${TABLES[@]}"; do
    COUNT=$(run_sql "SELECT count(*) FROM ${TABLE};" 2>/dev/null || echo "N/A")
    log_info "  ${TABLE}: ${COUNT} rows"
done

# Basic connectivity test
log_info "Running basic connectivity test..."
CONN_TEST=$(run_sql "SELECT 'OK';" || echo "FAILED")
if [[ "${CONN_TEST}" == "OK" ]]; then
    log_info "Database connectivity: OK"
else
    log_error "Database connectivity: FAILED"
fi

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------
if [[ "${CLEANUP_DUMP}" == "true" ]]; then
    log_info "Cleaning up temporary download: ${LOCAL_DUMP}"
    rm -f "${LOCAL_DUMP}"
fi

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
log_info "=== Restore Summary ==="
log_info "Source: ${SOURCE}"
log_info "Database: ${DB_NAME}"
log_info "Migration version: ${MIGRATION_VERSION}"
log_info "Duration: ${RESTORE_DURATION} seconds"
log_info "Restore completed successfully"

exit 0
