#!/bin/bash
# PostgreSQL backup script — run via cron or CI/CD
#
# Usage:
#   ./scripts/backup.sh
#
# Environment variables:
#   POSTGRES_HOST (default: localhost)
#   POSTGRES_PORT (default: 5432)
#   POSTGRES_USER (default: appforge)
#   POSTGRES_DB   (default: appforge)
#   PGPASSWORD    (required for non-interactive use)
#   BACKUP_DIR    (default: /backups)
#   BACKUP_RETENTION_DAYS (default: 30)
#   S3_BACKUP_BUCKET (optional — upload to S3 if set)

set -euo pipefail

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-appforge}"
POSTGRES_DB="${POSTGRES_DB:-appforge}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting backup of ${POSTGRES_DB}..."

# Dump and compress
pg_dump \
  -h "${POSTGRES_HOST}" \
  -p "${POSTGRES_PORT}" \
  -U "${POSTGRES_USER}" \
  -d "${POSTGRES_DB}" \
  --format=custom \
  --compress=9 \
  -f "${BACKUP_FILE}"

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date)] Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"

# Upload to S3 if configured
if [ -n "${S3_BACKUP_BUCKET:-}" ]; then
  S3_KEY="backups/${POSTGRES_DB}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"
  aws s3 cp "${BACKUP_FILE}" "s3://${S3_BACKUP_BUCKET}/${S3_KEY}"
  echo "[$(date)] Uploaded to s3://${S3_BACKUP_BUCKET}/${S3_KEY}"
fi

# Cleanup old local backups
find "${BACKUP_DIR}" -name "${POSTGRES_DB}_*.sql.gz" -mtime "+${BACKUP_RETENTION_DAYS}" -delete
echo "[$(date)] Cleaned up backups older than ${BACKUP_RETENTION_DAYS} days"

echo "[$(date)] Backup complete"
