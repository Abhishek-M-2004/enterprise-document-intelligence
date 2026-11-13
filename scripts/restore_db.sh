#!/usr/bin/env bash
# Production Restore Script for Linux / Cloud VPS
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <path_to_backup_directory_or_dump>"
    exit 1
fi

TARGET="$1"
export PGPASSWORD="${POSTGRES_ADMIN_PASSWORD:-postgres_password_change_me}"

echo "=== Restoring Database from ${TARGET} ==="

if [[ "${TARGET}" == *.dump ]]; then
    pg_restore -h "${POSTGRES_SERVER:-localhost}" \
               -p "${POSTGRES_PORT:-5432}" \
               -U "${POSTGRES_ADMIN_USER:-postgres}" \
               -d "${POSTGRES_DB:-doc_intelligence}" \
               --clean --if-exists -v "${TARGET}"
elif [ -d "${TARGET}" ]; then
    DUMP_FILE=$(find "${TARGET}" -name "*.dump" | head -n 1)
    if [ -n "${DUMP_FILE}" ]; then
        pg_restore -h "${POSTGRES_SERVER:-localhost}" \
                   -p "${POSTGRES_PORT:-5432}" \
                   -U "${POSTGRES_ADMIN_USER:-postgres}" \
                   -d "${POSTGRES_DB:-doc_intelligence}" \
                   --clean --if-exists -v "${DUMP_FILE}"
    fi

    DOC_TAR=$(find "${TARGET}" -name "documents_*.tar.gz" | head -n 1)
    if [ -n "${DOC_TAR}" ]; then
        tar -xzf "${DOC_TAR}" -C /app/storage
    fi
fi

echo "=== Restore completed successfully ==="
