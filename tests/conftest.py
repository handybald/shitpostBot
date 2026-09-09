"""Shared pytest fixtures.

Tests use a real, file-backed SQLite database (not `:memory:`) so that
multiple independent sessions/connections - needed to simulate two
concurrent workers racing to claim the same row - see the same committed
data, exactly like the production bot does with database/bot.db.

No test ever makes a real network request: `requests`, `boto3`, and
`python-telegram-bot`'s `Application` are never exercised in scheduling
tests - a fake/mock publisher and a fake Telegram bot stand in for them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Video, Music, Quote, GeneratedReel
from src.utils import datetime_helpers


@pytest.fixture()
def db_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    os.remove(path)


@pytest.fixture()
def make_session(db_engine):
    """Factory fixture: call it to get a brand-new session bound to the
    shared test engine, simulating `get_session()` per-job/per-worker."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    sessions = []

    def _make():
        s = SessionLocal()
        sessions.append(s)
        return s

    yield _make

    for s in sessions:
        s.close()


@pytest.fixture()
def db_session(make_session):
    return make_session()


@pytest.fixture()
def make_reel(db_session):
    """Factory fixture to quickly create a GeneratedReel (and its Video/Music)
    ready to be scheduled/published, without touching the filesystem."""

    def _make(output_path: str = "data/output/fake.mp4", caption: str = "test caption") -> GeneratedReel:
        video = Video(filename=f"video-{os.urandom(4).hex()}.mp4", source="local")
        music = Music(filename=f"music-{os.urandom(4).hex()}.mp3", source="local")
        db_session.add(video)
        db_session.add(music)
        db_session.flush()

        reel = GeneratedReel(
            video_id=video.id,
            music_id=music.id,
            output_path=output_path,
            caption=caption,
            status="approved",
        )
        db_session.add(reel)
        db_session.commit()
        return reel

    return _make


class FakeClock:
    """Controllable clock for deterministic scheduling tests. Patches
    `src.utils.datetime_helpers.now_utc` so any code under test that calls
    `datetime_helpers.now_utc()` sees this fake time instead of the real
    clock."""

    def __init__(self, start: datetime):
        assert start.tzinfo is not None, "FakeClock requires an aware datetime"
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        assert dt.tzinfo is not None
        self._now = dt

    def advance(self, **kwargs) -> None:
        self._now = self._now + timedelta(**kwargs)


@pytest.fixture()
def fake_clock(monkeypatch):
    clock = FakeClock(datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc))  # a Monday
    monkeypatch.setattr(datetime_helpers, "now_utc", clock.now)
    return clock


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Guarantee no test in this suite ever makes a real network call.
    Scheduling/publishing tests must only ever exercise fakes/mocks."""
    import requests

    def _boom(*args, **kwargs):
        raise AssertionError("a test tried to make a real network request via `requests`")

    monkeypatch.setattr(requests, "request", _boom)
    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)
