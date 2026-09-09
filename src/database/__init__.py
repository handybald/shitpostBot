"""Database module for ShitPostBot"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from pathlib import Path
from src.database.models import Base
from src.database.migrations import run_migrations

DATABASE_URL = "sqlite:///./database/bot.db"


def init_db(database_url: str = DATABASE_URL, run_pending_migrations: bool = True):
    """Initialize database with all tables and bring the schema up to date.

    Creates any missing tables, then runs the non-destructive Alembic
    migration chain (adds new columns to existing tables). Never drops or
    rewrites existing data.
    """
    engine = create_engine(database_url, connect_args={"check_same_thread": False})

    # Enable WAL mode for SQLite (better concurrency)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)

    if run_pending_migrations:
        run_migrations(engine)

    return engine


def get_session(engine=None) -> Session:
    """Get a database session"""
    if engine is None:
        engine = init_db()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


# Export
__all__ = ["init_db", "get_session", "Base"]
