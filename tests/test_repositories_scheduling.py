"""Tests for the ScheduledPost state-machine repository methods: atomic
claiming, retry policy, and stale-publishing recovery.

Uses a shared file-backed SQLite DB and independent sessions to simulate
two concurrent workers/processes racing over the same row.
"""

from datetime import timedelta

from src.database.repositories import ScheduledPostRepository, MAX_PUBLISH_ATTEMPTS
from src.utils import datetime_helpers as dh


def _schedule_now(session, reel, fake_clock):
    repo = ScheduledPostRepository(session)
    due = dh.utc_for_db(fake_clock.now())
    return repo.create(reel_id=reel.id, scheduled_time=due)


class TestAtomicClaim:
    def test_due_row_is_claimed_once_under_two_concurrent_workers(self, make_session, make_reel, fake_clock):
        reel = make_reel()
        session_a = make_session()
        post = _schedule_now(session_a, reel, fake_clock)
        session_a.commit()

        session_b = make_session()

        repo_a = ScheduledPostRepository(session_a)
        repo_b = ScheduledPostRepository(session_b)

        now_db = dh.utc_for_db(fake_clock.now())

        claimed_a = repo_a.claim(post.id, expected_status="pending", now=now_db)
        claimed_b = repo_b.claim(post.id, expected_status="pending", now=now_db)

        assert claimed_a is True
        assert claimed_b is False  # second worker must not also claim it

        session_b.refresh_all = None  # no-op, just documenting intent
        refreshed = session_b.query(type(post)).get(post.id)
        session_b.refresh(refreshed)
        assert refreshed.status == "publishing"

    def test_claim_fails_if_status_already_changed(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)

        now_db = dh.utc_for_db(fake_clock.now())
        assert repo.claim(post.id, expected_status="pending", now=now_db) is True
        # Already publishing now - claiming again as "pending" must fail.
        assert repo.claim(post.id, expected_status="pending", now=now_db) is False


class TestRetryPolicy:
    def test_first_failure_enters_retry_wait_and_increments_retry_count(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)
        repo.claim(post.id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))

        status = repo.record_failure(post.id, "simulated Instagram API failure")

        db_session.refresh(post)
        assert status == "retry_wait"
        assert post.status == "retry_wait"
        assert post.retry_count == 1
        assert "simulated Instagram API failure" in post.error_message
        assert post.next_attempt_at is not None

    def test_fifth_failure_enters_failed(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)

        status = None
        for attempt in range(MAX_PUBLISH_ATTEMPTS):
            repo.claim(post.id, expected_status=("pending" if attempt == 0 else "retry_wait"), now=dh.utc_for_db(fake_clock.now()))
            status = repo.record_failure(post.id, f"attempt {attempt + 1} failed")
            fake_clock.advance(hours=2)  # jump past any retry delay

        db_session.refresh(post)
        assert status == "failed"
        assert post.status == "failed"
        assert post.retry_count == MAX_PUBLISH_ATTEMPTS

    def test_retry_delays_increase_per_attempt(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)

        repo.claim(post.id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))
        repo.record_failure(post.id, "fail 1")
        db_session.refresh(post)
        first_delay = post.next_attempt_at - dh.utc_for_db(fake_clock.now())
        assert first_delay == timedelta(minutes=1)

        fake_clock.advance(minutes=1)
        repo.claim(post.id, expected_status="retry_wait", now=dh.utc_for_db(fake_clock.now()))
        repo.record_failure(post.id, "fail 2")
        db_session.refresh(post)
        second_delay = post.next_attempt_at - dh.utc_for_db(fake_clock.now())
        assert second_delay == timedelta(minutes=5)


class TestManualRetryReset:
    def test_reset_for_manual_retry_only_applies_to_failed(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)

        # Not failed yet - should be a no-op.
        assert repo.reset_for_manual_retry(post.id) is None

        for attempt in range(MAX_PUBLISH_ATTEMPTS):
            repo.claim(post.id, expected_status=("pending" if attempt == 0 else "retry_wait"), now=dh.utc_for_db(fake_clock.now()))
            repo.record_failure(post.id, f"attempt {attempt + 1}")
            fake_clock.advance(hours=2)

        db_session.refresh(post)
        assert post.status == "failed"

        reset_post = repo.reset_for_manual_retry(post.id)
        assert reset_post.status == "retry_wait"
        assert reset_post.retry_count == 0
        assert reset_post.next_attempt_at is not None


class TestStaleRecovery:
    def test_recover_stale_publishing_reclaims_old_claims(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)
        repo.claim(post.id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))

        db_session.refresh(post)
        assert post.status == "publishing"

        # Simulate a crash: 20 minutes pass with no resolution.
        fake_clock.advance(minutes=20)

        recovered = repo.recover_stale_publishing()
        assert recovered == 1

        db_session.refresh(post)
        assert post.status == "retry_wait"
        assert post.next_attempt_at <= dh.utc_for_db(fake_clock.now())
        assert post.retry_count == 0  # a restart is not counted as a failed attempt

    def test_recent_publishing_claim_is_not_recovered(self, db_session, make_reel, fake_clock):
        reel = make_reel()
        post = _schedule_now(db_session, reel, fake_clock)
        repo = ScheduledPostRepository(db_session)
        repo.claim(post.id, expected_status="pending", now=dh.utc_for_db(fake_clock.now()))

        fake_clock.advance(minutes=5)  # under the 15-minute staleness threshold

        recovered = repo.recover_stale_publishing()
        assert recovered == 0

        db_session.refresh(post)
        assert post.status == "publishing"
