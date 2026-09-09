"""Data access layer - repositories for database operations"""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_, update
from src.database.models import (
    Video, Music, Quote, GeneratedReel, ScheduledPost, PublishedPost,
    PostMetrics, ContentCalendar, Job, AgentLog, ScheduleConfig
)
from src.utils import datetime_helpers

# Scheduling retry policy (see issue #2): max 5 attempts total, with these
# delays between consecutive failed attempts (4 gaps between 5 attempts).
MAX_PUBLISH_ATTEMPTS = 5
RETRY_DELAYS_MINUTES = [1, 5, 15, 60]
STALE_PUBLISHING_MINUTES = 15


class VideoRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, filename: str, source: str, **kwargs):
        video = Video(filename=filename, source=source, **kwargs)
        self.session.add(video)
        self.session.commit()
        return video

    def get_by_filename(self, filename: str):
        return self.session.query(Video).filter(Video.filename == filename).first()

    def get_all(self):
        return self.session.query(Video).all()

    def get_by_theme(self, theme: str):
        return self.session.query(Video).filter(Video.theme == theme).all()

    def increment_usage(self, video_id: int):
        video = self.session.query(Video).get(video_id)
        if video:
            video.usage_count += 1
            video.last_used_at = datetime.utcnow()
            self.session.commit()
        return video

    def get_least_used(self, theme: str = None, limit: int = 10):
        """Get videos with lowest usage count, optionally filtered by theme"""
        query = self.session.query(Video)
        if theme:
            query = query.filter(Video.theme == theme)
        return query.order_by(Video.usage_count, desc(Video.last_used_at)).limit(limit).all()


class MusicRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, filename: str, source: str, **kwargs):
        music = Music(filename=filename, source=source, **kwargs)
        self.session.add(music)
        self.session.commit()
        return music

    def get_by_filename(self, filename: str):
        return self.session.query(Music).filter(Music.filename == filename).first()

    def get_all(self):
        return self.session.query(Music).all()

    def get_by_energy(self, energy_level: str):
        return self.session.query(Music).filter(Music.energy_level == energy_level).all()

    def get_bass_heavy(self, min_bass_score: float = 0.12):
        return self.session.query(Music).filter(Music.bass_score >= min_bass_score).all()

    def increment_usage(self, music_id: int):
        music = self.session.query(Music).get(music_id)
        if music:
            music.usage_count += 1
            music.last_used_at = datetime.utcnow()
            self.session.commit()
        return music

    def get_least_used(self, energy_level: str = None, limit: int = 10):
        query = self.session.query(Music)
        if energy_level:
            query = query.filter(Music.energy_level == energy_level)
        return query.order_by(Music.usage_count, desc(Music.last_used_at)).limit(limit).all()


class QuoteRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, text: str, author: str = None, **kwargs):
        quote = Quote(text=text, author=author, length=len(text), **kwargs)
        self.session.add(quote)
        self.session.commit()
        return quote

    def get_all(self):
        return self.session.query(Quote).all()

    def get_by_category(self, category: str):
        return self.session.query(Quote).filter(Quote.category == category).all()

    def get_short_quotes(self, max_length: int = 100):
        return self.session.query(Quote).filter(Quote.length <= max_length).all()

    def increment_usage(self, quote_id: int):
        quote = self.session.query(Quote).get(quote_id)
        if quote:
            quote.usage_count += 1
            quote.last_used_at = datetime.utcnow()
            self.session.commit()
        return quote

    def get_least_used(self, category: str = None, limit: int = 10):
        query = self.session.query(Quote)
        if category:
            query = query.filter(Quote.category == category)
        return query.order_by(Quote.usage_count, desc(Quote.last_used_at)).limit(limit).all()


class GeneratedReelRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, video_id: int, music_id: int, quote_id: int, **kwargs):
        reel = GeneratedReel(video_id=video_id, music_id=music_id, quote_id=quote_id, **kwargs)
        self.session.add(reel)
        self.session.commit()
        return reel

    def get_by_id(self, reel_id: int):
        return self.session.query(GeneratedReel).get(reel_id)

    def get_by_status(self, status: str):
        return self.session.query(GeneratedReel).filter(GeneratedReel.status == status).all()

    def get_pending(self):
        return self.get_by_status("pending")

    def get_approved(self):
        return self.get_by_status("approved")

    def update_status(self, reel_id: int, status: str):
        reel = self.session.query(GeneratedReel).get(reel_id)
        if reel:
            reel.status = status
            if status == "approved":
                reel.approved_at = datetime.utcnow()
            self.session.commit()
        return reel

    def count_by_status(self, status: str = None):
        query = self.session.query(GeneratedReel)
        if status:
            query = query.filter(GeneratedReel.status == status)
        return query.count()

    def get_recent(self, limit: int = 10):
        return self.session.query(GeneratedReel).order_by(desc(GeneratedReel.created_at)).limit(limit).all()


class ScheduledPostRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, reel_id: int, scheduled_time: datetime):
        post = ScheduledPost(reel_id=reel_id, scheduled_time=scheduled_time, status="pending")
        self.session.add(post)
        self.session.commit()
        return post

    def get_due_posts(self, now: Optional[datetime] = None):
        """Get pending posts scheduled for now or past (does not claim them)."""
        now = now if now is not None else datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        return self.session.query(ScheduledPost).filter(
            and_(
                ScheduledPost.scheduled_time <= now,
                ScheduledPost.status == "pending"
            )
        ).all()

    def get_claimable(self, now: Optional[datetime] = None) -> List[ScheduledPost]:
        """Get all posts eligible to be claimed for publishing right now.

        Includes fresh `pending` posts whose scheduled_time has arrived and
        `retry_wait` posts whose next_attempt_at has arrived. Does not claim
        them - callers must use `claim()` on each candidate id.
        """
        now = now if now is not None else datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        return self.session.query(ScheduledPost).filter(
            or_(
                and_(ScheduledPost.status == "pending", ScheduledPost.scheduled_time <= now),
                and_(ScheduledPost.status == "retry_wait", ScheduledPost.next_attempt_at <= now),
            )
        ).all()

    def claim(self, post_id: int, expected_status: str, now: Optional[datetime] = None) -> bool:
        """Atomically claim a single row for publishing.

        Performs a conditional UPDATE (`WHERE id = :id AND status = :expected`)
        so that concurrent workers racing on the same row can never both
        succeed - only the worker whose UPDATE actually changes a row (rowcount
        == 1) may proceed to publish. Never publishes the same ScheduledPost
        concurrently.
        """
        now = now if now is not None else datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        result = self.session.execute(
            update(ScheduledPost)
            .where(ScheduledPost.id == post_id, ScheduledPost.status == expected_status)
            .values(status="publishing", claimed_at=now, last_attempt_at=now)
        )
        self.session.commit()
        return result.rowcount == 1

    def force_claim_now(self, post_id: int) -> bool:
        """Claim a post for immediate manual publishing (/post_now, /publish_now),
        regardless of scheduled_time/next_attempt_at, as long as it is not
        already publishing/published/cancelled.
        """
        now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        result = self.session.execute(
            update(ScheduledPost)
            .where(ScheduledPost.id == post_id, ScheduledPost.status.in_(["pending", "retry_wait", "failed"]))
            .values(status="publishing", claimed_at=now, last_attempt_at=now)
        )
        self.session.commit()
        return result.rowcount == 1

    def mark_published(self, post_id: int):
        """Transition a claimed row to the terminal `published` state."""
        now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        post = self.session.query(ScheduledPost).get(post_id)
        if post:
            post.status = "published"
            post.published_at = now
            post.error_message = None
            post.next_attempt_at = None
            self.session.commit()
        return post

    def mark_retry(self, post_id: int, sanitized_error: str, retry_count: int):
        """Transition a claimed row back to `retry_wait` after a failed attempt.

        `retry_count` is the *new* attempt count (i.e. the number of attempts
        made so far, including the one that just failed).
        """
        now_aware = datetime_helpers.now_utc()
        delay_minutes = RETRY_DELAYS_MINUTES[min(retry_count - 1, len(RETRY_DELAYS_MINUTES) - 1)]
        next_attempt = datetime_helpers.utc_for_db(now_aware + timedelta(minutes=delay_minutes))
        post = self.session.query(ScheduledPost).get(post_id)
        if post:
            post.status = "retry_wait"
            post.retry_count = retry_count
            post.error_message = sanitized_error
            post.last_attempt_at = datetime_helpers.utc_for_db(now_aware)
            post.next_attempt_at = next_attempt
            self.session.commit()
        return post

    def record_failure(self, post_id: int, sanitized_error: str) -> str:
        """Record a failed publish attempt and apply the retry policy
        (max 5 attempts total; see MAX_PUBLISH_ATTEMPTS/RETRY_DELAYS_MINUTES).

        Returns the resulting status ("retry_wait" or "failed"), or
        "missing" if the post no longer exists.
        """
        post = self.session.query(ScheduledPost).get(post_id)
        if not post:
            return "missing"

        new_count = (post.retry_count or 0) + 1
        if new_count >= MAX_PUBLISH_ATTEMPTS:
            self.mark_failed(post_id, sanitized_error, new_count)
            return "failed"

        self.mark_retry(post_id, sanitized_error, new_count)
        return "retry_wait"

    def mark_failed(self, post_id: int, sanitized_error: str, retry_count: int):
        """Transition a claimed row to the terminal `failed` state (retry budget exhausted)."""
        now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        post = self.session.query(ScheduledPost).get(post_id)
        if post:
            post.status = "failed"
            post.retry_count = retry_count
            post.error_message = sanitized_error
            post.last_attempt_at = now
            post.next_attempt_at = None
            self.session.commit()
        return post

    def reset_for_manual_retry(self, post_id: int) -> Optional[ScheduledPost]:
        """Used by /retry_failed: give a `failed` post a fresh retry budget,
        immediately eligible for claiming.

        Returns the updated post, or None if it doesn't exist or isn't
        currently `failed` (a no-op - this only applies to terminal failures).
        """
        now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        post = self.session.query(ScheduledPost).get(post_id)
        if not post or post.status != "failed":
            return None

        post.status = "retry_wait"
        post.retry_count = 0
        post.next_attempt_at = now
        post.error_message = None
        self.session.commit()
        return post

    def recover_stale_publishing(self, now: Optional[datetime] = None, older_than_minutes: int = STALE_PUBLISHING_MINUTES) -> int:
        """Reclaim rows stuck in `publishing` after a crash/restart.

        Any row still `publishing` whose `claimed_at` is older than
        `older_than_minutes` is moved back to `retry_wait` with
        `next_attempt_at` set to now, so it becomes immediately claimable
        again. retry_count is preserved (a restart is not counted as a
        failed publish attempt). Returns the number of rows recovered.
        """
        now_aware = datetime_helpers.now_utc()
        now_db = datetime_helpers.utc_for_db(now_aware)
        cutoff = datetime_helpers.utc_for_db(now_aware - timedelta(minutes=older_than_minutes))

        stale = self.session.query(ScheduledPost).filter(
            ScheduledPost.status == "publishing",
            ScheduledPost.claimed_at.isnot(None),
            ScheduledPost.claimed_at <= cutoff,
        ).all()

        for post in stale:
            post.status = "retry_wait"
            post.next_attempt_at = now_db
            post.error_message = (
                (post.error_message + " | " if post.error_message else "")
                + "Recovered after restart (stale claimed_at)"
            )

        if stale:
            self.session.commit()

        return len(stale)

    def get_upcoming(self, days: int = 7):
        """Get posts scheduled within next N days"""
        now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        future = now + timedelta(days=days)
        return self.session.query(ScheduledPost).filter(
            and_(
                ScheduledPost.scheduled_time >= now,
                ScheduledPost.scheduled_time <= future,
                ScheduledPost.status == "pending"
            )
        ).order_by(ScheduledPost.scheduled_time).all()

    def update_status(self, post_id: int, status: str):
        post = self.session.query(ScheduledPost).get(post_id)
        if post:
            post.status = status
            if status == "published":
                post.published_at = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
            self.session.commit()
        return post

    def increment_retry(self, post_id: int):
        post = self.session.query(ScheduledPost).get(post_id)
        if post:
            post.retry_count += 1
            self.session.commit()
        return post

    def get_by_reel_id(self, reel_id: int):
        """Get scheduled post by reel_id"""
        return self.session.query(ScheduledPost).filter(
            ScheduledPost.reel_id == reel_id
        ).first()

    def update_scheduled_time(self, reel_id: int, new_time: datetime):
        """Update scheduled time for a reel"""
        post = self.get_by_reel_id(reel_id)
        if post:
            post.scheduled_time = new_time
            self.session.commit()
        return post

    def get_calendar_view(self, days: int = 30):
        """Get all scheduled posts for calendar view, ordered by time"""
        now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        future = now + timedelta(days=days)
        return self.session.query(ScheduledPost).filter(
            and_(
                ScheduledPost.scheduled_time >= now,
                ScheduledPost.scheduled_time <= future
            )
        ).order_by(ScheduledPost.scheduled_time).all()

    def count_by_status(self, status: str) -> int:
        return self.session.query(ScheduledPost).filter(ScheduledPost.status == status).count()

    def get_overdue_count(self, now: Optional[datetime] = None) -> int:
        """Count posts that are due but not yet claimed/published (pending or retry_wait)."""
        now = now if now is not None else datetime_helpers.utc_for_db(datetime_helpers.now_utc())
        return self.session.query(ScheduledPost).filter(
            or_(
                and_(ScheduledPost.status == "pending", ScheduledPost.scheduled_time <= now),
                and_(ScheduledPost.status == "retry_wait", ScheduledPost.next_attempt_at <= now),
            )
        ).count()

    def get_recent_failed(self, limit: int = 10):
        return self.session.query(ScheduledPost).filter(
            ScheduledPost.status == "failed"
        ).order_by(desc(ScheduledPost.last_attempt_at)).limit(limit).all()


class PublishedPostRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, reel_id: int, instagram_media_id: str = None, caption: str = None, s3_url: str = None, **kwargs):
        """Create or update a published post record.

        If a PublishedPost already exists for the given reel_id, update it
        instead of inserting a duplicate (avoids UNIQUE constraint failures).
        """
        # Try to find existing post by reel_id
        existing = self.session.query(PublishedPost).filter(PublishedPost.reel_id == reel_id).first()
        if existing:
            # Update fields
            if instagram_media_id is not None:
                existing.instagram_media_id = instagram_media_id
            if caption is not None:
                existing.caption = caption
            if s3_url is not None:
                existing.s3_url = s3_url
            # Allow other kwargs to update additional columns
            for k, v in kwargs.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            self.session.commit()
            return existing

        post = PublishedPost(
            reel_id=reel_id,
            instagram_media_id=instagram_media_id,
            caption=caption,
            s3_url=s3_url,
            **kwargs
        )
        self.session.add(post)
        self.session.commit()
        return post

    def get_by_media_id(self, media_id: str):
        return self.session.query(PublishedPost).filter(PublishedPost.instagram_media_id == media_id).first()

    def get_recent(self, days: int = 30, limit: int = 100):
        cutoff = datetime.utcnow() - timedelta(days=days)
        return self.session.query(PublishedPost).filter(
            PublishedPost.published_at >= cutoff
        ).order_by(desc(PublishedPost.published_at)).limit(limit).all()

    def get_top_by_engagement(self, days: int = 30, limit: int = 10):
        cutoff = datetime.utcnow() - timedelta(days=days)
        return self.session.query(PublishedPost).join(PostMetrics).filter(
            PublishedPost.published_at >= cutoff
        ).order_by(desc(PostMetrics.engagement_rate)).limit(limit).all()


class PostMetricsRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, post_id: int, **kwargs):
        metrics = PostMetrics(post_id=post_id, **kwargs)
        self.session.add(metrics)
        self.session.commit()
        return metrics

    def get_latest_for_post(self, post_id: int):
        return self.session.query(PostMetrics).filter(
            PostMetrics.post_id == post_id
        ).order_by(desc(PostMetrics.collected_at)).first()

    def get_average_engagement(self, days: int = 30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        metrics = self.session.query(PostMetrics).filter(
            PostMetrics.collected_at >= cutoff
        ).all()
        if not metrics:
            return 0
        avg = sum(m.engagement_rate or 0 for m in metrics) / len(metrics)
        return avg


class ContentCalendarRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, date: datetime, time_slot: str, **kwargs):
        entry = ContentCalendar(date=date, time_slot=time_slot, **kwargs)
        self.session.add(entry)
        self.session.commit()
        return entry

    def get_by_date(self, date: datetime):
        return self.session.query(ContentCalendar).filter(
            ContentCalendar.date.cast(datetime).ilike(date.date())
        ).all()

    def get_next_n_days(self, days: int = 30):
        now = datetime.utcnow()
        future = now + timedelta(days=days)
        return self.session.query(ContentCalendar).filter(
            and_(
                ContentCalendar.date >= now,
                ContentCalendar.date <= future
            )
        ).order_by(ContentCalendar.date).all()

    def get_pending_slots(self):
        return self.session.query(ContentCalendar).filter(
            ContentCalendar.status == "pending"
        ).order_by(ContentCalendar.date).all()

    def bulk_create(self, entries: list):
        """Create multiple calendar entries"""
        self.session.add_all(entries)
        self.session.commit()
        return entries


class JobRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, job_type: str, **kwargs):
        job = Job(job_type=job_type, **kwargs)
        self.session.add(job)
        self.session.commit()
        return job

    def get_pending(self, job_type: str = None):
        query = self.session.query(Job).filter(Job.status == "pending")
        if job_type:
            query = query.filter(Job.job_type == job_type)
        return query.all()

    def update_status(self, job_id: int, status: str, result: str = None):
        job = self.session.query(Job).get(job_id)
        if job:
            job.status = status
            if status == "running":
                job.started_at = datetime.utcnow()
            elif status == "completed":
                job.completed_at = datetime.utcnow()
            if result:
                job.result = result
            self.session.commit()
        return job


class ScheduleConfigRepository:
    """Repository for managing default posting schedule configuration"""

    def __init__(self, session: Session):
        self.session = session

    def create(self, day_of_week: int, time: str) -> ScheduleConfig:
        """Create new schedule config entry"""
        config = ScheduleConfig(day_of_week=day_of_week, time=time)
        self.session.add(config)
        self.session.commit()
        return config

    def get_all(self):
        """Get all enabled schedule configurations ordered by day/time"""
        return self.session.query(ScheduleConfig).filter(
            ScheduleConfig.enabled == True
        ).order_by(ScheduleConfig.day_of_week, ScheduleConfig.time).all()

    def get_by_day(self, day_of_week: int):
        """Get schedules for specific day"""
        return self.session.query(ScheduleConfig).filter(
            ScheduleConfig.day_of_week == day_of_week,
            ScheduleConfig.enabled == True
        ).order_by(ScheduleConfig.time).all()

    def update(self, config_id: int, time: str = None, enabled: bool = None):
        """Update schedule config"""
        config = self.session.query(ScheduleConfig).get(config_id)
        if config:
            if time is not None:
                config.time = time
            if enabled is not None:
                config.enabled = enabled
            config.updated_at = datetime.utcnow()
            self.session.commit()
        return config

    def delete(self, config_id: int):
        """Delete schedule config"""
        config = self.session.query(ScheduleConfig).get(config_id)
        if config:
            self.session.delete(config)
            self.session.commit()
        return config

    def find_or_create_slot(self, day_of_week: int, time: str):
        """Find existing or create new schedule slot"""
        existing = self.session.query(ScheduleConfig).filter(
            ScheduleConfig.day_of_week == day_of_week,
            ScheduleConfig.time == time
        ).first()

        if existing:
            if not existing.enabled:
                existing.enabled = True
                self.session.commit()
            return existing

        return self.create(day_of_week, time)
