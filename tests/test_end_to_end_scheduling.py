"""End-to-end scheduling reliability tests: a reel scheduled a couple of
minutes ahead publishes exactly once even across a simulated bot restart,
using an accelerated fake clock and the real background job
(`publish_scheduled_job`) plus real startup recovery (`_recover_stale_publishing`).
"""

import pytest
from datetime import timedelta

from src.database.repositories import ScheduledPostRepository, PublishedPostRepository
from src.database.models import PublishedPost, ScheduledPost
from src.services.instagram import PublishResult
from src.utils import datetime_helpers as dh

from tests.helpers import FakeTelegramBot, ScriptedInstagram, make_orchestrator


class TestScheduledTwoMinutesAheadPublishesOnce:
    @pytest.mark.asyncio
    async def test_publishes_once_using_accelerated_clock(self, monkeypatch, make_session, make_reel, fake_clock, tmp_path):
        video_file = tmp_path / "reel.mp4"
        video_file.write_bytes(b"fake video bytes")
        reel = make_reel(output_path=str(video_file))

        instagram = ScriptedInstagram(outcomes=[PublishResult(media_id="ig-media-1", container_id="container-1")])
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram, instagram=instagram)

        # Schedule two minutes ahead.
        session = make_session()
        sched_repo = ScheduledPostRepository(session)
        due_at = dh.utc_for_db(fake_clock.now() + timedelta(minutes=2))
        post = sched_repo.create(reel_id=reel.id, scheduled_time=due_at)
        post_id = post.id
        session.close()

        # Tick #1: not due yet - nothing should happen.
        await orch.publish_scheduled_job()
        session = make_session()
        still_pending = session.query(ScheduledPost).get(post_id)
        assert still_pending.status == "pending"
        assert instagram.calls == 0
        session.close()

        # Advance the accelerated clock past the due time and tick again.
        fake_clock.advance(minutes=3)
        await orch.publish_scheduled_job()

        session = make_session()
        published = session.query(ScheduledPost).get(post_id)
        assert published.status == "published"
        assert instagram.calls == 1
        pub_count = session.query(PublishedPost).filter_by(reel_id=reel.id).count()
        assert pub_count == 1
        session.close()

        # A further tick must not publish it again.
        await orch.publish_scheduled_job()
        assert instagram.calls == 1


class TestRestartBeforeDueTime:
    @pytest.mark.asyncio
    async def test_restart_before_due_time_still_results_in_one_publication(
        self, monkeypatch, make_session, make_reel, fake_clock, tmp_path
    ):
        video_file = tmp_path / "reel.mp4"
        video_file.write_bytes(b"fake video bytes")
        reel = make_reel(output_path=str(video_file))

        instagram = ScriptedInstagram(outcomes=[PublishResult(media_id="ig-media-2", container_id="container-2")])
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram, instagram=instagram)

        session = make_session()
        sched_repo = ScheduledPostRepository(session)
        due_at = dh.utc_for_db(fake_clock.now() + timedelta(minutes=2))
        post = sched_repo.create(reel_id=reel.id, scheduled_time=due_at)
        post_id = post.id
        session.close()

        # Simulate a bot restart *before* the post is due: startup recovery
        # runs (should be a no-op - nothing is `publishing` yet), then the
        # scheduler resumes ticking.
        recovered = orch._recover_stale_publishing()
        assert recovered == 0

        fake_clock.advance(minutes=3)
        await orch.publish_scheduled_job()

        session = make_session()
        published = session.query(ScheduledPost).get(post_id)
        assert published.status == "published"
        assert instagram.calls == 1
        session.close()

        # Another restart (recovery) after success must not re-trigger publishing.
        recovered_again = orch._recover_stale_publishing()
        assert recovered_again == 0
        await orch.publish_scheduled_job()
        assert instagram.calls == 1


class TestRestartDuringPublishingRecovers:
    @pytest.mark.asyncio
    async def test_restart_recovery_reclaims_stale_publishing_work(
        self, monkeypatch, make_session, make_reel, fake_clock, tmp_path
    ):
        video_file = tmp_path / "reel.mp4"
        video_file.write_bytes(b"fake video bytes")
        reel = make_reel(output_path=str(video_file))

        instagram = ScriptedInstagram(outcomes=[PublishResult(media_id="ig-media-3", container_id="container-3")])
        telegram = FakeTelegramBot()
        orch = make_orchestrator(monkeypatch, make_session, telegram_bot=telegram, instagram=instagram)

        # Simulate a process that claimed the row (status=publishing) and
        # then crashed before finishing - claimed_at is now stale.
        session = make_session()
        sched_repo = ScheduledPostRepository(session)
        post = sched_repo.create(reel_id=reel.id, scheduled_time=dh.utc_for_db(fake_clock.now()))
        post_id = post.id
        sched_repo.claim(post_id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))
        session.close()

        fake_clock.advance(minutes=20)  # past the 15-minute staleness threshold

        recovered = orch._recover_stale_publishing()
        assert recovered == 1

        # It should now be immediately claimable again and get published.
        await orch.publish_scheduled_job()

        session = make_session()
        final = session.query(ScheduledPost).get(post_id)
        assert final.status == "published"
        assert instagram.calls == 1
        session.close()
