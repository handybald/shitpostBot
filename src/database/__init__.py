"""Database module for ShitPostBot"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from pathlib import Path
from src.database.models import Base

DATABASE_URL = "sqlite:///./database/bot.db"


def init_db():
    """Initialize database with all tables"""
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    # Enable WAL mode for SQLite (better concurrency)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return engine


def get_session(engine=None) -> Session:
    """Get a database session"""
    if engine is None:
        engine = init_db()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


# Export
__all__ = ["init_db", "get_session", "Base"]
