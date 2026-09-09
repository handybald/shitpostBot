"""Verifies the Alembic migration path is non-destructive: an existing
pre-issue-#2 database gets the new scheduled_posts columns added without
losing any existing rows, and the whole thing is idempotent.
"""

import os
import sqlite3
import tempfile

from sqlalchemy import inspect, text

from src.database import init_db


def _create_pre_issue_2_schema(path: str) -> None:
    """Recreate the exact scheduled_posts/generated_reels schema that
    existed before issue #2, with one populated row, simulating a real
    deployed database/bot.db predating this change."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE generated_reels (
            id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL, music_id INTEGER NOT NULL,
            quote_id INTEGER, output_path VARCHAR(500) NOT NULL, caption TEXT, duration FLOAT,
            status VARCHAR(50) DEFAULT 'pending', render_time FLOAT, file_size INTEGER,
            quality_score FLOAT, created_at DATETIME, approved_at DATETIME
        )
    """)
    cur.execute("""
        CREATE TABLE scheduled_posts (
            id INTEGER PRIMARY KEY, reel_id INTEGER NOT NULL UNIQUE, scheduled_time DATETIME NOT NULL,
            status VARCHAR(50) DEFAULT 'pending', retry_count INTEGER DEFAULT 0, error_message TEXT,
            created_at DATETIME, published_at DATETIME
        )
    """)
    cur.execute("INSERT INTO generated_reels (id, video_id, music_id, output_path) VALUES (1, 1, 1, 'existing_user_reel.mp4')")
    cur.execute(
        "INSERT INTO scheduled_posts (id, reel_id, scheduled_time, status, retry_count) "
        "VALUES (1, 1, '2026-09-11 18:00:00', 'pending', 0)"
    )
    conn.commit()
    conn.close()


class TestNonDestructiveMigration:
    def test_upgrades_existing_database_without_losing_data(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            _create_pre_issue_2_schema(path)

            engine = init_db(database_url=f"sqlite:///{path}")

            inspector = inspect(engine)
            columns = {c["name"] for c in inspector.get_columns("scheduled_posts")}
            for expected in ("last_attempt_at", "next_attempt_at", "claimed_at", "retry_count", "error_message"):
                assert expected in columns

            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id, reel_id, status, retry_count FROM scheduled_posts WHERE id = 1")
                ).fetchone()
            assert row == (1, 1, "pending", 0)

            with engine.connect() as conn:
                reel_row = conn.execute(
                    text("SELECT output_path FROM generated_reels WHERE id = 1")
                ).fetchone()
            assert reel_row[0] == "existing_user_reel.mp4"
        finally:
            os.remove(path)

    def test_migration_is_idempotent(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            _create_pre_issue_2_schema(path)

            init_db(database_url=f"sqlite:///{path}")
            # Running it again must not raise or duplicate/alter anything.
            engine = init_db(database_url=f"sqlite:///{path}")

            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM scheduled_posts")).fetchone()[0]
            assert count == 1
        finally:
            os.remove(path)

    def test_fresh_database_gets_full_schema_and_stamps_head(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)  # init_db must create it from scratch
        try:
            engine = init_db(database_url=f"sqlite:///{path}")
            columns = {c["name"] for c in inspect(engine).get_columns("scheduled_posts")}
            assert {"last_attempt_at", "next_attempt_at", "claimed_at"}.issubset(columns)

            with engine.connect() as conn:
                heads = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            assert len(heads) == 1
        finally:
            if os.path.exists(path):
                os.remove(path)
