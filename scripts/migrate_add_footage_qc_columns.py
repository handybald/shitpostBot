"""
One-off migration for existing installations: adds the footage-QC columns to
the `videos` table and creates the new `footage_qc_log` table.

There's no alembic environment wired up in this project despite it being in
requirements.txt, so this is a plain, idempotent SQL migration instead of a
proper alembic revision. Safe to run multiple times.

Usage:
    python3 scripts/migrate_add_footage_qc_columns.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import init_db, DATABASE_URL  # noqa: E402

NEW_VIDEO_COLUMNS = {
    "qc_status": "TEXT DEFAULT 'pending'",
    "qc_composite_score": "REAL",
    "qc_scores": "TEXT",
    "qc_reason": "TEXT",
    "qc_checked_at": "TIMESTAMP",
    "phash": "TEXT",
}


def _db_path() -> str:
    # DATABASE_URL looks like "sqlite:///./database/bot.db"
    return DATABASE_URL.replace("sqlite:///", "")


def migrate() -> None:
    db_path = _db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(videos)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    for column, ddl_type in NEW_VIDEO_COLUMNS.items():
        if column in existing_columns:
            print(f"skip: videos.{column} already exists")
            continue
        cursor.execute(f"ALTER TABLE videos ADD COLUMN {column} {ddl_type}")
        print(f"added: videos.{column}")

    conn.commit()
    conn.close()

    # create_all only creates tables that don't exist yet (footage_qc_log),
    # it never alters existing ones, so it's safe to call after the manual
    # ALTER TABLE calls above.
    init_db()
    print("done: footage_qc_log table ensured")


if __name__ == "__main__":
    migrate()
