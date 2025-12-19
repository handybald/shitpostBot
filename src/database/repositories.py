"""Data access layer - repositories for database operations"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from src.database.models import (
    Video, Music, Quote, GeneratedReel, ScheduledPost, PublishedPost,
    PostMetrics, ContentCalendar, Job, AgentLog
)


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
        post = ScheduledPost(reel_id=reel_id, scheduled_time=scheduled_time)
        self.session.add(post)
        self.session.commit()
        return post

    def get_due_posts(self):
        """Get posts scheduled for now or past"""
        now = datetime.utcnow()
        return self.session.query(ScheduledPost).filter(
            and_(
                ScheduledPost.scheduled_time <= now,
                ScheduledPost.status == "pending"
            )
        ).all()

    def get_upcoming(self, days: int = 7):
        """Get posts scheduled within next N days"""
        now = datetime.utcnow()
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
                post.published_at = datetime.utcnow()
            self.session.commit()
        return post

    def increment_retry(self, post_id: int):
        post = self.session.query(ScheduledPost).get(post_id)
        if post:
            post.retry_count += 1
            self.session.commit()
        return post


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
