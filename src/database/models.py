"""
SQLAlchemy models for ShitPostBot database
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class Video(Base):
    """Stock vertical video clips"""
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), unique=True, nullable=False)
    source = Column(String(50))  # pexels, pixabay, local
    url = Column(String(500))
    duration = Column(Float)  # seconds
    resolution = Column(String(50))  # e.g., "1080x1920"
    tags = Column(String(500))  # comma-separated keywords
    theme = Column(String(100))  # motivation, philosophy, hustle
    usage_count = Column(Integer, default=0)
    quality_score = Column(Float, default=0.8)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)

    generated_reels = relationship("GeneratedReel", back_populates="video")

    def __repr__(self):
        return f"<Video {self.filename}>"


class Music(Base):
    """Music/audio tracks"""
    __tablename__ = "music"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), unique=True, nullable=False)
    source = Column(String(50))  # freesound, local
    url = Column(String(500))
    duration = Column(Float)  # seconds
    bpm = Column(Integer)
    tags = Column(String(500))  # comma-separated
    bass_score = Column(Float)  # 0-1, higher = more bass
    energy_level = Column(String(20))  # low, medium, high
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)

    generated_reels = relationship("GeneratedReel", back_populates="music")

    def __repr__(self):
        return f"<Music {self.filename}>"


class Quote(Base):
    """Motivational quotes"""
    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    author = Column(String(255))
    category = Column(String(100))  # motivation, wisdom, hustle, philosophy
    length = Column(Integer)  # character count
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)

    generated_reels = relationship("GeneratedReel", back_populates="quote")

    def __repr__(self):
        return f"<Quote {self.text[:50]}...>"


class GeneratedReel(Base):
    """Generated video reels waiting for approval/publishing"""
    __tablename__ = "generated_reels"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    music_id = Column(Integer, ForeignKey("music.id"), nullable=False)
    quote_id = Column(Integer, ForeignKey("quotes.id"), nullable=False)

    output_path = Column(String(500), nullable=False)  # local file path
    caption = Column(Text)  # AI-generated caption
    duration = Column(Float)  # video duration in seconds

    # Status: pending, approved, rejected, published
    status = Column(String(50), default="pending")

    # Metadata
    render_time = Column(Float)  # seconds taken to generate
    file_size = Column(Integer)  # bytes
    quality_score = Column(Float)  # 0-1

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)
    scheduled_post = relationship("ScheduledPost", uselist=False, back_populates="reel")
    published_post = relationship("PublishedPost", uselist=False, back_populates="reel")

    # Relationships
    video = relationship("Video", back_populates="generated_reels")
    music = relationship("Music", back_populates="generated_reels")
    quote = relationship("Quote", back_populates="generated_reels")

    def __repr__(self):
        return f"<GeneratedReel {self.id} status={self.status}>"


class ScheduledPost(Base):
    """Posts scheduled for publishing"""
    __tablename__ = "scheduled_posts"

    id = Column(Integer, primary_key=True)
    reel_id = Column(Integer, ForeignKey("generated_reels.id"), nullable=False, unique=True)
    scheduled_time = Column(DateTime, nullable=False)

    status = Column(String(50), default="pending")  # pending, published, failed, cancelled
    retry_count = Column(Integer, default=0)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)

    # Relationship
    reel = relationship("GeneratedReel", back_populates="scheduled_post")

    def __repr__(self):
        return f"<ScheduledPost {self.id} scheduled={self.scheduled_time}>"


class PublishedPost(Base):
    """Successfully published posts"""
    __tablename__ = "published_posts"

    id = Column(Integer, primary_key=True)
    reel_id = Column(Integer, ForeignKey("generated_reels.id"), nullable=False, unique=True)
    instagram_media_id = Column(String(255), unique=True)
    instagram_url = Column(String(500))
    caption = Column(Text)

    published_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    reel = relationship("GeneratedReel", back_populates="published_post")
    metrics = relationship("PostMetrics", back_populates="published_post")

    def __repr__(self):
        return f"<PublishedPost {self.instagram_media_id}>"


class PostMetrics(Base):
    """Instagram engagement metrics for published posts"""
    __tablename__ = "post_metrics"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("published_posts.id"), nullable=False)

    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    reach = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    impressions = Column(Integer, default=0)

    engagement_rate = Column(Float)  # calculated: (likes+comments+shares) / reach

    collected_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    published_post = relationship("PublishedPost", back_populates="metrics")

    def __repr__(self):
        return f"<PostMetrics post={self.post_id} engagement={self.engagement_rate}>"


class ContentCalendar(Base):
    """Content scheduling calendar"""
    __tablename__ = "content_calendar"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    time_slot = Column(String(50))  # HH:MM format
    theme = Column(String(100))  # motivation, philosophy, hustle

    # References
    reel_id = Column(Integer, ForeignKey("generated_reels.id"))
    scheduled_post_id = Column(Integer, ForeignKey("scheduled_posts.id"))

    # Status
    status = Column(String(50), default="pending")  # pending, approved, published, skipped

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ContentCalendar {self.date} theme={self.theme}>"


class Job(Base):
    """Background job tracking"""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    job_type = Column(String(100), nullable=False)  # generate_content, publish_scheduled, collect_metrics
    status = Column(String(50), default="pending")  # pending, running, completed, failed

    params = Column(Text)  # JSON-encoded parameters
    result = Column(Text)  # JSON-encoded result
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    retry_count = Column(Integer, default=0)

    def __repr__(self):
        return f"<Job {self.job_type} status={self.status}>"


class AgentLog(Base):
    """Agent activity logs"""
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True)
    agent_name = Column(String(100), nullable=False)
    action = Column(String(255))
    result = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AgentLog {self.agent_name} {self.action}>"
