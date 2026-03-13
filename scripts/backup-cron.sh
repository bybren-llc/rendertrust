#!/usr/bin/env bash
# MIT License -- see LICENSE-MIT
#
# backup-cron.sh -- Cron wrapper for automated PostgreSQL backups
#
# This script is designed to be called by cron. It runs backup-db.sh
# with the --upload flag, logs output, and sends an alert on failure.
#
# Crontab entry:
#   0 2 * * * /opt/rendertrust/scripts/backup-cron.sh
#
# Environment variables (required):
#   DATABASE_URL          PostgreSQL connection string
#   BACKUP_S3_BUCKET      S3 bucket for backup storage
#
# Environment variables (optional):
#   ALERT_WEBHOOK_URL     Webhook URL for failure alerts (e.g., Slack incoming webhook)
#   BACKUP_LOG_DIR        Log directory (default: /var/log/rendertrust)
#   BACKUP_RETENTION_DAYS Retention period in days (default: 7)

set -euo pipefail

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup-db.sh"
BACKUP_LOG_DIR="${BACKUP_LOG_DIR:-/var/log/rendertrust}"
LOG_FILE="${BACKUP_LOG_DIR}/backup.log"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
HOSTNAME="$(hostname -f 2>/dev/null || hostname)"

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] ${SCRIPT_NAME}: $*" | tee -a "${LOG_FILE}"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] ${SCRIPT_NAME}: $*" | tee -a "${LOG_FILE}" >&2
}

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

# Ensure log directory exists
if [[ ! -d "${BACKUP_LOG_DIR}" ]]; then
    mkdir -p "${BACKUP_LOG_DIR}"
fi

# Rotate log file if it exceeds 10MB
LOG_MAX_SIZE=$((10 * 1024 * 1024))
if [[ -f "${LOG_FILE}" ]]; then
    LOG_CURRENT_SIZE=$(stat --format=%s "${LOG_FILE}" 2>/dev/null || stat -f%z "${LOG_FILE}" 2>/dev/null || echo 0)
    if [[ "${LOG_CURRENT_SIZE}" -gt "${LOG_MAX_SIZE}" ]]; then
        mv "${LOG_FILE}" "${LOG_FILE}.$(date +%Y%m%d_%H%M%S).old"
        log_info "Log file rotated (was ${LOG_CURRENT_SIZE} bytes)"
    fi
fi

# ------------------------------------------------------------------
# Alert function
# ------------------------------------------------------------------
send_alert() {
    local message="$1"
    local severity="${2:-error}"

    if [[ -n "${ALERT_WEBHOOK_URL:-}" ]]; then
        local payload
        payload=$(cat <<ALERT_EOF
{
  "text": "[${severity^^}] RenderTrust Backup Alert",
  "attachments": [
    {
      "color": "danger",
      "title": "Backup Failure on ${HOSTNAME}",
      "text": "${message}",
      "ts": $(date +%s)
    }
  ]
}
ALERT_EOF
)

        if curl -s -o /dev/null -w "%{http_code}" \
            -X POST \
            -H "Content-Type: application/json" \
            -d "${payload}" \
            "${ALERT_WEBHOOK_URL}" | grep -q "^2"; then
            log_info "Alert sent successfully"
        else
            log_error "Failed to send alert to webhook"
        fi
    else
        log_error "ALERT_WEBHOOK_URL not set -- cannot send alert"
        log_error "Alert message: ${message}"
    fi
}

# ------------------------------------------------------------------
# Pre-flight checks
# ------------------------------------------------------------------
log_info "=========================================="
log_info "Starting scheduled backup"
log_info "=========================================="

if [[ ! -x "${BACKUP_SCRIPT}" ]]; then
    MSG="Backup script not found or not executable: ${BACKUP_SCRIPT}"
    log_error "${MSG}"
    send_alert "${MSG}"
    exit 1
fi

# ------------------------------------------------------------------
# Run backup
# ------------------------------------------------------------------
BACKUP_START=$(date +%s)
EXIT_CODE=0

if "${BACKUP_SCRIPT}" --upload --retention-days "${RETENTION_DAYS}" >> "${LOG_FILE}" 2>&1; then
    BACKUP_END=$(date +%s)
    BACKUP_DURATION=$((BACKUP_END - BACKUP_START))
    log_info "Backup completed successfully in ${BACKUP_DURATION} seconds"
else
    EXIT_CODE=$?
    BACKUP_END=$(date +%s)
    BACKUP_DURATION=$((BACKUP_END - BACKUP_START))

    MSG="PostgreSQL backup FAILED with exit code ${EXIT_CODE} after ${BACKUP_DURATION}s on ${HOSTNAME}"
    log_error "${MSG}"
    send_alert "${MSG}"
fi

log_info "=========================================="
log_info "Scheduled backup finished (exit code: ${EXIT_CODE})"
log_info "=========================================="

exit ${EXIT_CODE}
