"""Integration-style tests for the orchestrator's reliable publish pipeline:
claim -> publish -> durable state, using an injected fake clock and a fake
(mocked) Instagram publisher. No test in this module makes a real network
request - `requests` is monkeypatched to explode if anything tries (see
conftest.py's autouse `no_real_network` fixture).
"""

import pytest

from src.database.repositories import (
    ScheduledPostRepository, PublishedPostRepository,
    MAX_PUBLISH_ATTEMPTS,
)
from src.database.models import PublishedPost
from src.services.instagram import InstagramContainerError
from src.utils import datetime_helpers as dh

from tests.helpers import FakeTelegramBot, ScriptedInstagram, make_orchestrator


class TestApprovalReportsScheduleFailure:
    @pytest.mark.asyncio
    async def test_schedule_db_failure_does_not_report_success(self, monkeypatch, make_session, make_reel, fake_clock):
        reel = make_reel()
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram)

        # Simulate a DB failure while creating the ScheduledPost row.
        def _boom_create(self, reel_id, scheduled_time):
            raise RuntimeError("simulated DB failure creating scheduled_posts row")

        monkeypatch.setattr(ScheduledPostRepository, "create", _boom_create)

        success, message = await orch.schedule_reel(reel.id)

        assert success is False
        assert "error" in message.lower()
        assert not any(n["level"] == "success" for n in telegram.notifications)

    @pytest.mark.asyncio
    async def test_schedule_success_reports_success(self, monkeypatch, make_session, make_reel, fake_clock):
        reel = make_reel()
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram)

        success, message = await orch.schedule_reel(reel.id)

        assert success is True
        assert any(n["level"] == "success" for n in telegram.notifications)


class TestPublishRetryAndFailure:
    @pytest.mark.asyncio
    async def test_api_failure_enters_retry_wait_and_increments_retry_count(
        self, monkeypatch, make_session, make_reel, fake_clock, tmp_path
    ):
        video_file = tmp_path / "reel.mp4"
        video_file.write_bytes(b"fake video bytes")
        reel = make_reel(output_path=str(video_file))

        instagram = ScriptedInstagram(outcomes=[InstagramContainerError("processing failed")])
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram, instagram=instagram)

        session = make_session()
        sched_repo = ScheduledPostRepository(session)
        post = sched_repo.create(reel_id=reel.id, scheduled_time=dh.utc_for_db(fake_clock.now()))
        assert sched_repo.claim(post.id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))

        success, message = await orch._execute_publish(session, post.id, reel.id, notify=True)

        assert success is False
        session.refresh(post)
        assert post.status == "retry_wait"
        assert post.retry_count == 1
        assert instagram.calls == 1
        # Interim retries don't spam Telegram - only the terminal failure does.
        assert telegram.notifications == []

    @pytest.mark.asyncio
    async def test_fifth_failure_enters_failed_and_notifies_once(
        self, monkeypatch, make_session, make_reel, fake_clock, tmp_path
    ):
        video_file = tmp_path / "reel.mp4"
        video_file.write_bytes(b"fake video bytes")
        reel = make_reel(output_path=str(video_file))

        outcomes = [InstagramContainerError(f"fail {i}") for i in range(MAX_PUBLISH_ATTEMPTS)]
        instagram = ScriptedInstagram(outcomes=outcomes)
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram, instagram=instagram)

        session = make_session()
        sched_repo = ScheduledPostRepository(session)
        post = sched_repo.create(reel_id=reel.id, scheduled_time=dh.utc_for_db(fake_clock.now()))

        for attempt in range(MAX_PUBLISH_ATTEMPTS):
            expected_status = "pending" if attempt == 0 else "retry_wait"
            assert sched_repo.claim(post.id, expected_status=expected_status, now=dh.utc_for_db(fake_clock.now()))
            await orch._execute_publish(session, post.id, reel.id, notify=True)
            fake_clock.advance(hours=2)

        session.refresh(post)
        assert post.status == "failed"
        assert post.retry_count == MAX_PUBLISH_ATTEMPTS
        assert instagram.calls == MAX_PUBLISH_ATTEMPTS

        failure_notifications = [n for n in telegram.notifications if n["level"] == "error"]
        assert len(failure_notifications) == 1  # notified exactly once, on the terminal failure


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_existing_published_post_prevents_duplicate_publication(
        self, monkeypatch, make_session, make_reel, fake_clock, tmp_path
    ):
        video_file = tmp_path / "reel.mp4"
        video_file.write_bytes(b"fake video bytes")
        reel = make_reel(output_path=str(video_file))

        instagram = ScriptedInstagram(outcomes=[AssertionError("must not call Instagram for an already-published reel")])
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram, instagram=instagram)

        session = make_session()
        pub_repo = PublishedPostRepository(session)
        pub_repo.create(reel_id=reel.id, instagram_media_id="already-published-id")

        sched_repo = ScheduledPostRepository(session)
        post = sched_repo.create(reel_id=reel.id, scheduled_time=dh.utc_for_db(fake_clock.now()))
        assert sched_repo.claim(post.id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))

        success, message = await orch._execute_publish(session, post.id, reel.id, notify=True)

        assert success is True
        assert instagram.calls == 0  # never actually called Instagram again
        session.refresh(post)
        assert post.status == "published"

        # Still exactly one PublishedPost row for this reel.
        count = session.query(PublishedPost).filter_by(reel_id=reel.id).count()
        assert count == 1
