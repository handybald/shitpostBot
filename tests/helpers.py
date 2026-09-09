"""Shared fakes/helpers for orchestrator scheduling tests."""

from dataclasses import dataclass, field
from typing import List, Optional

import src.controllers.orchestrator as orchestrator_module
from src.controllers.orchestrator import BotOrchestrator


class FakeConfig:
    """Minimal stand-in for Config - dotted-key lookup over a plain dict,
    with the same `.get(key, default)` contract the real Config exposes."""

    def __init__(self, data: Optional[dict] = None):
        self._data = data or {}

    def get(self, key: str, default=None):
        value = self._data
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return default
        return value if value is not None else default


class FakeTelegramBot:
    def __init__(self):
        self.notifications: List[dict] = []

    async def send_notification(self, message: str, level: str = "info"):
        self.notifications.append({"message": message, "level": level})


class FakeScheduler:
    """Stand-in for APScheduler's AsyncIOScheduler - only what
    get_scheduler_status() touches."""

    def get_job(self, job_id):
        return None


@dataclass
class ScriptedInstagram:
    """Fake Instagram publisher: replays a scripted sequence of outcomes,
    one per call to `publish_reel`. Never touches the network."""
    outcomes: List[object]
    calls: int = 0

    def s3_upload_and_presign(self, **kwargs) -> str:
        return "https://example-bucket.s3.amazonaws.com/fake-presigned-url"

    def publish_reel(self, **kwargs):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


DEFAULT_CONFIG_DATA = {
    "scheduling": {
        "timezone": "Europe/Istanbul",
        "post_times": [{"day": 0, "time": "18:00"}],
    },
    "aws": {"s3_bucket_name": "test-bucket", "region": "us-east-1"},
}


def make_orchestrator(monkeypatch, make_session, telegram_bot=None, instagram=None, config_data=None):
    """Build a BotOrchestrator with only the attributes scheduling logic
    needs, bypassing __init__ (which wires up video generation, content
    selection, Gemini, etc. - all irrelevant to and heavier than what these
    tests exercise)."""
    orch = BotOrchestrator.__new__(BotOrchestrator)
    orch.config = FakeConfig(config_data if config_data is not None else DEFAULT_CONFIG_DATA)
    orch.telegram_bot = telegram_bot
    orch.running = True
    orch.instagram = instagram
    orch.scheduler = FakeScheduler()

    # Every `get_session()` call inside orchestrator.py must resolve to a
    # fresh session bound to the *test* engine, never the real bot.db.
    monkeypatch.setattr(orchestrator_module, "get_session", make_session)
    return orch
