#!/usr/bin/env python3
"""
Local smoke test for the reliable scheduler (issue #2).

Schedules a reel two minutes ahead with a FAKE Instagram publisher (no
credentials needed, no network calls made) against a throwaway SQLite
database, then drives it through the real state machine
(ScheduledPostRepository.claim + BotOrchestrator._execute_publish),
printing every state transition: pending -> publishing -> published.

Usage:
    python3 scripts/smoke_test_scheduler.py            # simulated clock (instant)
    python3 scripts/smoke_test_scheduler.py --real-time # actually waits ~2 minutes

Never touches database/bot.db and never makes a real Instagram/network call.
"""

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database import init_db, get_session
from src.database.models import Video, Music, GeneratedReel, ScheduledPost
from src.database.repositories import ScheduledPostRepository
from src.services.instagram import PublishResult
from src.utils import datetime_helpers as dh


class FakePublisher:
    """Fake Instagram publisher - never touches the network. Always
    succeeds on the first attempt so the smoke test demonstrates the happy
    path end to end."""

    def s3_upload_and_presign(self, **kwargs) -> str:
        return "https://example-bucket.s3.amazonaws.com/fake-presigned-url"

    def publish_reel(self, **kwargs) -> PublishResult:
        return PublishResult(media_id="smoke-test-media-id", container_id="smoke-test-container-id")


class FakeTelegramBot:
    async def send_notification(self, message: str, level: str = "info") -> None:
        print(f"    [telegram:{level}] {message}")


class FakeConfig:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default=None):
        value = self._data
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return default
        return value if value is not None else default


def build_orchestrator(instagram, telegram):
    from src.controllers.orchestrator import BotOrchestrator

    orch = BotOrchestrator.__new__(BotOrchestrator)
    orch.config = FakeConfig({
        "scheduling": {"timezone": "Europe/Istanbul"},
        "aws": {"s3_bucket_name": "smoke-test-bucket", "region": "us-east-1"},
    })
    orch.telegram_bot = telegram
    orch.running = True
    orch.instagram = instagram
    return orch


def log_state(label: str) -> None:
    print(f"[{dh.now_utc().isoformat()}] {label}")


async def run(args) -> bool:
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    print(f"Using throwaway database: {db_path}")

    engine = init_db(database_url=f"sqlite:///{db_path}")

    video_dir = Path(tempfile.mkdtemp())
    video_path = video_dir / "smoke_test_reel.mp4"
    video_path.write_bytes(b"not a real video, just for the smoke test")

    session = get_session(engine)
    try:
        video = Video(filename="smoke-test-video.mp4", source="local")
        music = Music(filename="smoke-test-music.mp3", source="local")
        session.add(video)
        session.add(music)
        session.flush()

        reel = GeneratedReel(
            video_id=video.id, music_id=music.id,
            output_path=str(video_path), caption="Smoke test reel", status="approved",
        )
        session.add(reel)
        session.commit()
        reel_id = reel.id

        sched_repo = ScheduledPostRepository(session)
        scheduled_time_utc = dh.now_utc() + timedelta(minutes=2)
        post = sched_repo.create(reel_id=reel_id, scheduled_time=dh.utc_for_db(scheduled_time_utc))
        post_id = post.id

        log_state(
            f"scheduled reel #{reel_id} (scheduled_post #{post_id}) for "
            f"{scheduled_time_utc.isoformat()} (2 minutes ahead) - state: pending"
        )

        if args.real_time:
            print("Waiting for real wall-clock time to reach the due time (~2 minutes)...")
            while dh.now_utc() < scheduled_time_utc:
                time.sleep(5)
        else:
            print("Simulated clock: jumping straight to the due time (use --real-time to actually wait).")
            future = scheduled_time_utc + timedelta(seconds=1)
            dh.now_utc = lambda: future

        instagram = FakePublisher()
        telegram = FakeTelegramBot()
        orch = build_orchestrator(instagram, telegram)

        now_db = dh.utc_for_db(dh.now_utc())
        claimed = sched_repo.claim(post_id, expected_status="pending", now=now_db)
        if not claimed:
            log_state("FAILED to claim the due post - unexpected concurrent claim?")
            return False
        log_state("state transition: pending -> publishing")

        success, message = await orch._execute_publish(session, post_id, reel_id, notify=True)

        session.refresh(post)
        log_state(f"state transition: publishing -> {post.status}")
        print(f"Result: {message}")

        if post.status == "published":
            print("\nSmoke test PASSED: reel published exactly once.")
        else:
            print("\nSmoke test FAILED: reel did not reach the published state.")

        return success
    finally:
        session.close()
        os.remove(db_path)
        shutil.rmtree(video_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--real-time", action="store_true",
        help="Actually wait ~2 minutes instead of simulating the clock (default: simulated, instant)"
    )
    args = parser.parse_args()

    real_now_utc = dh.now_utc
    try:
        ok = asyncio.run(run(args))
    finally:
        dh.now_utc = real_now_utc

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
