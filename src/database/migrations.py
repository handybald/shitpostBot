"""Non-destructive schema migration runner (Alembic wrapper).

`init_db()` always calls `Base.metadata.create_all()` first, which creates
any *missing tables* for a brand-new install but - critically - does NOT
add new columns to tables that already exist on disk. Since issue #2 adds
new columns to `scheduled_posts` on an existing table, a real migration is
required to bring already-deployed databases (e.g. database/bot.db) up to
date without dropping any existing reels or schedules.

This module figures out, for any given engine, which of three situations
applies and does the minimal safe thing:

  1. Brand new database (no tables at all before create_all ran): the
     schema `create_all()` just built already matches the current models,
     so we simply stamp it at `head` - no DDL needed.
  2. Existing database created before Alembic was introduced (has
     `scheduled_posts` but not the new state-machine columns): stamp at
     the `0001` baseline, then upgrade to `head`, which adds the missing
     columns via `ALTER TABLE ... ADD COLUMN` (SQLite-safe, additive only).
  3. Existing database already tracked by Alembic: just upgrade to `head`.

Never drops or rewrites existing tables/rows.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from src.utils.logger import get_logger

logger = get_logger(__name__)

ALEMBIC_INI_PATH = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


def _alembic_config() -> Config:
    return Config(str(ALEMBIC_INI_PATH))


def _stamp(engine: Engine, revision: str) -> None:
    with engine.connect() as connection:
        cfg = _alembic_config()
        cfg.attributes["connection"] = connection
        command.stamp(cfg, revision)


def _upgrade_to_head(engine: Engine) -> None:
    with engine.connect() as connection:
        cfg = _alembic_config()
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def run_migrations(engine: Engine) -> None:
    """Bring `engine`'s database up to date with the current models.

    Must be called after `Base.metadata.create_all(engine)`. Safe to call
    repeatedly (idempotent) and never destroys existing data.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.connect() as connection:
        current_heads = set(MigrationContext.configure(connection).get_current_heads())

    if current_heads:
        logger.debug(f"Database already tracked by Alembic at {current_heads}; upgrading to head")
        _upgrade_to_head(engine)
        return

    if "scheduled_posts" not in table_names:
        # Brand new database - create_all() already built the full current
        # schema (new columns included). Nothing to migrate, just stamp it.
        logger.info("Fresh database detected; stamping Alembic head (no migration needed)")
        _stamp(engine, "head")
        return

    existing_columns = {c["name"] for c in inspector.get_columns("scheduled_posts")}
    if "claimed_at" in existing_columns:
        # Table already has the new columns (e.g. created by create_all
        # after this change) but was never stamped.
        logger.info("Existing database already has current schema; stamping Alembic head")
        _stamp(engine, "head")
        return

    # Existing, pre-Alembic database missing the new state-machine columns.
    logger.info("Existing pre-Alembic database detected; stamping baseline and upgrading to head")
    _stamp(engine, "0001")
    _upgrade_to_head(engine)
    logger.info("Database migrated to head successfully; existing data preserved")
