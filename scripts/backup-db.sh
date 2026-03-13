#!/usr/bin/env bash
# MIT License -- see LICENSE-MIT
#
# backup-db.sh -- PostgreSQL backup script for RenderTrust
#
# Usage: ./scripts/backup-db.sh [--upload] [--retention-days N]
#
# Options:
#   --upload            Upload the backup to S3 after creation
#   --retention-days N  Number of days to retain local backups (default: 7)
#
# Environment variables (required):
#   DATABASE_URL        PostgreSQL connection string
#                       OR set PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE individually
#
# Environment variables (required if --upload):
#   BACKUP_S3_BUCKET    S3 bucket name for backup storage
#   AWS_ACCESS_KEY_ID   S3 access key (or configure via aws cli)
#   AWS_SECRET_ACCESS_KEY S3 secret key (or configure via aws cli)
#   S3_ENDPOINT_URL     S3-compatible endpoint (optional, for non-AWS S3)

set -euo pipefail

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
SCRIPT_NAME="$(basename "$0")"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/rendertrust/db}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILENAME="rendertrust_db_${TIMESTAMP}.dump"
DUMP_PATH="${BACKUP_DIR}/${DUMP_FILENAME}"

# ------------------------------------------------------------------
# Defaults
# ------------------------------------------------------------------
UPLOAD=false
RETENTION_DAYS=7

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
while [[ $# -gt 0 ]]; do
    case "$1" in
        --upload)
            UPLOAD=true
            shift
            ;;
        --retention-days)
            if [[ -z "${2:-}" ]] || ! [[ "$2" =~ ^[0-9]+$ ]]; then
                log_error "--retention-days requires a positive integer argument"
                exit 1
            fi
            RETENTION_DAYS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ${SCRIPT_NAME} [--upload] [--retention-days N]"
            echo ""
            echo "Options:"
            echo "  --upload            Upload the backup to S3 after creation"
            echo "  --retention-days N  Number of days to retain local backups (default: 7)"
            echo ""
            echo "Environment variables:"
            echo "  DATABASE_URL        PostgreSQL connection string"
            echo "  BACKUP_S3_BUCKET    S3 bucket name (required if --upload)"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------
if ! command -v pg_dump &>/dev/null; then
    log_error "pg_dump not found. Install PostgreSQL client tools."
    exit 2
fi

if [[ "${UPLOAD}" == "true" ]]; then
    if ! command -v aws &>/dev/null; then
        log_error "aws cli not found. Install it to enable S3 upload."
        exit 2
    fi
    if [[ -z "${BACKUP_S3_BUCKET:-}" ]]; then
        log_error "BACKUP_S3_BUCKET environment variable is required for --upload"
        exit 1
    fi
fi

# Parse DATABASE_URL if set, otherwise rely on PG* env vars
if [[ -n "${DATABASE_URL:-}" ]]; then
    log_info "Using DATABASE_URL for connection"
    export PGCONNSTRING="${DATABASE_URL}"
else
    if [[ -z "${PGDATABASE:-}" ]]; then
        log_error "Either DATABASE_URL or PGDATABASE must be set"
        exit 1
    fi
    log_info "Using PG* environment variables for connection"
fi

# ------------------------------------------------------------------
# Create backup directory
# ------------------------------------------------------------------
if [[ ! -d "${BACKUP_DIR}" ]]; then
    log_info "Creating backup directory: ${BACKUP_DIR}"
    mkdir -p "${BACKUP_DIR}"
fi

# ------------------------------------------------------------------
# Perform backup
# ------------------------------------------------------------------
log_info "Starting PostgreSQL backup..."
log_info "Output: ${DUMP_PATH}"

if [[ -n "${DATABASE_URL:-}" ]]; then
    pg_dump --format=custom --compress=6 --verbose \
        "${DATABASE_URL}" \
        --file="${DUMP_PATH}" 2>&1 | while IFS= read -r line; do
        log_info "pg_dump: ${line}"
    done
else
    pg_dump --format=custom --compress=6 --verbose \
        --file="${DUMP_PATH}" 2>&1 | while IFS= read -r line; do
        log_info "pg_dump: ${line}"
    done
fi

# Verify the dump file was created and is non-empty
if [[ ! -f "${DUMP_PATH}" ]]; then
    log_error "Backup file was not created: ${DUMP_PATH}"
    exit 3
fi

DUMP_SIZE=$(stat --format=%s "${DUMP_PATH}" 2>/dev/null || stat -f%z "${DUMP_PATH}" 2>/dev/null)
if [[ "${DUMP_SIZE}" -lt 1024 ]]; then
    log_warn "Backup file is suspiciously small (${DUMP_SIZE} bytes): ${DUMP_PATH}"
fi

log_info "Backup created successfully: ${DUMP_PATH} (${DUMP_SIZE} bytes)"

# Verify backup integrity
log_info "Verifying backup integrity..."
if pg_restore --list "${DUMP_PATH}" > /dev/null 2>&1; then
    log_info "Backup integrity check passed"
else
    log_error "Backup integrity check FAILED -- the dump file may be corrupt"
    exit 3
fi

# ------------------------------------------------------------------
# Upload to S3 (if requested)
# ------------------------------------------------------------------
if [[ "${UPLOAD}" == "true" ]]; then
    log_info "Uploading backup to S3: s3://${BACKUP_S3_BUCKET}/db/${DUMP_FILENAME}"

    S3_ARGS=()
    if [[ -n "${S3_ENDPOINT_URL:-}" ]]; then
        S3_ARGS+=(--endpoint-url "${S3_ENDPOINT_URL}")
    fi

    if aws s3 cp "${DUMP_PATH}" "s3://${BACKUP_S3_BUCKET}/db/${DUMP_FILENAME}" "${S3_ARGS[@]}"; then
        log_info "Upload to S3 completed successfully"
    else
        log_error "Failed to upload backup to S3"
        exit 4
    fi
fi

# ------------------------------------------------------------------
# Clean up old local backups
# ------------------------------------------------------------------
log_info "Cleaning up local backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=0
while IFS= read -r -d '' old_file; do
    log_info "Removing old backup: ${old_file}"
    rm -f "${old_file}"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done < <(find "${BACKUP_DIR}" -name "rendertrust_db_*.dump" -type f -mtime "+${RETENTION_DAYS}" -print0 2>/dev/null)

log_info "Cleaned up ${DELETED_COUNT} old backup(s)"

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
log_info "=== Backup Summary ==="
log_info "File: ${DUMP_PATH}"
log_info "Size: ${DUMP_SIZE} bytes"
log_info "Upload: ${UPLOAD}"
log_info "Retention: ${RETENTION_DAYS} days"
log_info "Backup completed successfully"

exit 0
