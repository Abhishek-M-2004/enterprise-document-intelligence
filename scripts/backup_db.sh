#!/usr/bin/env bash
# Production Backup Script for Linux / Cloud VPS
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/docintel}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TARGET_DIR="${BACKUP_DIR}/${TIMESTAMP}"
mkdir -p "${TARGET_DIR}"

echo "=== Starting Backup: ${TIMESTAMP} ==="

# 1. PostgreSQL Dump
export PGPASSWORD="${POSTGRES_PASSWORD:-docintel_secure_pass_2026}"
pg_dump -h "${POSTGRES_SERVER:-localhost}" \
        -p "${POSTGRES_PORT:-5432}" \
        -U "${POSTGRES_USER:-docintel_app}" \
        -d "${POSTGRES_DB:-doc_intelligence}" \
        -F c -b -v -f "${TARGET_DIR}/postgres_${TIMESTAMP}.dump"

# 2. Document Storage Archive
if [ -d "/app/storage/documents" ]; then
    tar -czf "${TARGET_DIR}/documents_${TIMESTAMP}.tar.gz" -C /app/storage documents
fi

# 3. Retention: Delete backups older than 14 days
find "${BACKUP_DIR}" -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +

echo "=== Backup completed successfully in ${TARGET_DIR} ==="
