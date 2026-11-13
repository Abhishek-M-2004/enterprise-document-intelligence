"""Automated Database Restoration Utility.

Restores PostgreSQL database and Qdrant snapshots from backup files.
"""

import os
import sys
import subprocess
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))
from app.core.config import settings


def restore_postgresql(sql_file_path: Path):
    """Restore PostgreSQL database from a plain SQL backup file."""
    if not sql_file_path.exists():
        raise FileNotFoundError(f"Backup file not found: {sql_file_path}")

    env = os.environ.copy()
    env["PGPASSWORD"] = settings.POSTGRES_PASSWORD

    cmd = [
        "psql",
        "-h", settings.POSTGRES_SERVER,
        "-p", str(settings.POSTGRES_PORT),
        "-U", settings.POSTGRES_USER,
        "-d", settings.POSTGRES_DB,
        "-f", str(sql_file_path),
    ]

    print(f"[Restore] Restoring database '{settings.POSTGRES_DB}' from {sql_file_path}...")
    try:
        res = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        print(f"[Restore] Database successfully restored from backup.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Restore] Error during restore: {e.stderr}", file=sys.stderr)
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/restore_db.py <path_to_backup.sql>")
        sys.exit(1)
    backup_file = Path(sys.argv[1])
    restore_postgresql(backup_file)
