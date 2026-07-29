"""
Main Orchestrator - Coordinates all services and background jobs.

Handles:
- Content generation pipeline
- Job scheduling with APScheduler
- Queue management
- Error recovery
- Metrics collection
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from pathlib import Path
from apscheduler.triggers.cron import CronTrigger

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance
from src.utils import datetime_helpers
from src.database import get_session
from src.database.models import PublishedPost, Video, Music, Quote
from src.database.repositories import (
    GeneratedReelRepository, ScheduledPostRepository,
    PublishedPostRepository,
    ContentCalendarRepository, JobRepository, ScheduleConfigRepository
)
from src.processors import VideoGenerator, QualityChecker, FootageQC
from src.services import InstagramService
from src.services.gemini_content_generator import GeminiContentGenerator, BeatSheet
from src.services.content_downloader import ContentDownloader
from src.services.tts_provider import ElevenLabsTTSProvider, TTSProviderError

logger = get_logger(__name__)


class BotOrchestrator:
    """Main coordinator for all ShitPostBot operations."""

    def __init__(self, telegram_bot=None):
        """
        Initialize orchestrator.

        Args:
            telegram_bot: Reference to TelegramBot controller
        """
        self.config = get_config_instance()
        self.telegram_bot = telegram_bot
        self.running = False
        # Use the currently running event loop if available
        try:
            loop = asyncio.get_running_loop()
            self.scheduler = AsyncIOScheduler(event_loop=loop)
        except RuntimeError:
            # No running loop yet, will set one during start
            self.scheduler = AsyncIOScheduler()

        logger.info("Orchestrator initialized")

    async def start(self, blocking: bool = True) -> None:
        """
        Start all background jobs and services.
        
        Args:
            blocking: If True, blocks until stopped. If False, returns after initialization.
        """
        logger.info("Starting orchestrator...")
        self.running = True

        # Initialize services
        self.session = get_session()
        self.video_generator = VideoGenerator.from_config()
        self.quality_checker = QualityChecker()
        self.footage_qc = FootageQC.from_config()
        self.instagram = InstagramService.from_config()
        self.gemini_generator = GeminiContentGenerator()
        self.content_downloader = ContentDownloader()
        self.tts_provider = ElevenLabsTTSProvider.from_config()

        # Schedule background jobs
        self._schedule_jobs()

        # Start scheduler in background thread
        self.scheduler.start()
        logger.info("Orchestrator started - background jobs scheduled")

        if not blocking:
            if self.telegram_bot:
                logger.info("Starting Telegram bot polling in background...")
                asyncio.create_task(self.telegram_bot.start_polling())
            return

        # Start Telegram bot polling concurrently
        if self.telegram_bot:
            logger.info("Starting Telegram bot polling...")
            # Create a task for Telegram polling to run concurrently
            telegram_task = asyncio.create_task(self.telegram_bot.start_polling())

            # Keep running and monitor both tasks
            try:
                await telegram_task
            except KeyboardInterrupt:
                await self.stop()
        else:
            # Keep running if no Telegram bot
            try:
                while self.running:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                await self.stop()

    async def stop(self) -> None:
        """Stop all jobs and services."""
        logger.info("Stopping orchestrator...")
        self.running = False
        self.scheduler.shutdown()
        if self.session:
            self.session.close()
        logger.info("Orchestrator stopped")

    def _schedule_jobs(self) -> None:
        """Schedule all background jobs."""
        generate_interval = self.config.get("automation.generate_interval", 21600)  # 6 hours
        metrics_interval = self.config.get("automation.metrics_interval", 10800)  # 3 hours
        queue_check_interval = self.config.get("automation.queue_check_interval", 3600)  # 1 hour
        calendar_check_interval = self.config.get("automation.calendar_check_interval", 300)  # 5 min

        # Generate content periodically
        self.scheduler.add_job(
            self.generate_content_job,
            IntervalTrigger(seconds=generate_interval),
            id="generate_content",
            name="Generate content",
            misfire_grace_time=60,
            coalesce=True
        )

        # Check queue and warn if low
        self.scheduler.add_job(
            self.queue_check_job,
            IntervalTrigger(seconds=queue_check_interval),
            id="queue_check",
            name="Check queue",
            misfire_grace_time=60
        )

        # Check calendar and publish due posts
        self.scheduler.add_job(
            self.calendar_check_job,
            IntervalTrigger(seconds=calendar_check_interval),
            id="calendar_check",
            name="Check calendar",
            misfire_grace_time=60
        )

        # Collect metrics
        self.scheduler.add_job(
            self.metrics_job,
            IntervalTrigger(seconds=metrics_interval),
            id="collect_metrics",
            name="Collect metrics",
            misfire_grace_time=60
        )

        # Check for scheduled posts frequently (every 2 minutes)
        # This replaces the specific CronTimes to ensure we catch any dynamically scheduled/rescheduled posts
        self.scheduler.add_job(
            self.publish_scheduled_job,
            IntervalTrigger(seconds=120),  # Check every 2 mins
            id="publish_scheduled_check",
            name="Check scheduled posts",
            misfire_grace_time=60
        )
        
        logger.info(f"Scheduled {len(self.scheduler.get_jobs())} background jobs")

    async def generate_content_job(self) -> None:
        """Background job: Generate content if queue is low."""
        try:
            # Check if auto-generation is enabled (default to False to prevent unwanted generation)
            if not self.config.get("automation.auto_generate", False):
                logger.debug("Auto-generation disabled - skipping")
                return

            logger.debug("Running generate_content_job")

            reel_repo = GeneratedReelRepository(self.session)
            pending = reel_repo.get_by_status("pending")
            approved = reel_repo.get_by_status("approved")

            queue_size = len(pending) + len(approved)
            queue_target = self.config.get("content.generation.queue_target", 7)

            if queue_size < queue_target:
                shortage = queue_target - queue_size
                await self.generate_content(count=shortage)

        except Exception as e:
            logger.error(f"Error in generate_content_job: {e}")
            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"Content generation error: {e}",
                    level="error"
                )

    async def queue_check_job(self) -> None:
        """Background job: Monitor queue and alert if low."""
        try:
            logger.debug("Running queue_check_job")

            reel_repo = GeneratedReelRepository(self.session)
            pending = len(reel_repo.get_by_status("pending"))

            if pending < 3:
                msg = f"⚠️ Queue running low ({pending} pending)"
                logger.warning(msg)
                if self.telegram_bot:
                    await self.telegram_bot.send_notification(msg, level="warning")

        except Exception as e:
            logger.error(f"Error in queue_check_job: {e}")

    async def calendar_check_job(self) -> None:
        """Background job: Check and publish due calendar entries."""
        try:
            logger.debug("Running calendar_check_job")

            now = datetime.utcnow()
            cal_repo = ContentCalendarRepository(self.session)

            # Get entries due for publishing - use ContentCalendar model directly
            from src.database.models import ContentCalendar
            due_entries = self.session.query(ContentCalendar).filter(
                ContentCalendar.date <= now,
                ContentCalendar.status == "approved"
            ).all()

            for entry in due_entries:
                await self.publish_scheduled_entry(entry)

        except Exception as e:
            logger.error(f"Error in calendar_check_job: {e}")

    async def metrics_job(self) -> None:
        """Background job: Collect Instagram metrics."""
        try:
            logger.debug("Running metrics_job")

            # In Phase 5, this will fetch Instagram metrics
            # For now, just log that it ran
            logger.info("Metrics collection job executed")

        except Exception as e:
            logger.error(f"Error in metrics_job: {e}")

    async def publish_scheduled_job(self) -> None:
        """Background job: Publish scheduled posts."""
        try:
            logger.debug("Running publish_scheduled_job")

            reel_repo = GeneratedReelRepository(self.session)
            sched_repo = ScheduledPostRepository(self.session)

            # Get scheduled posts that are ready (using UTC for DB comparison)
            now_utc = datetime.utcnow()
            logger.debug(f"Checking for scheduled posts. Current UTC time: {now_utc}")
            
            from src.database.models import ScheduledPost
            scheduled = sched_repo.session.query(ScheduledPost).filter(
                ScheduledPost.scheduled_time <= now_utc,
                ScheduledPost.status.in_(["scheduled", "pending"]) # Check both just in case
            ).all()

            logger.debug(f"Found {len(scheduled)} scheduled posts ready to publish")

            for post in scheduled:
                logger.info(f"Publishing scheduled reel #{post.reel_id} (scheduled for {post.scheduled_time})")
                await self.publish_reel_to_instagram(post.reel_id)

        except Exception as e:
            logger.error(f"Error in publish_scheduled_job: {e}")

    async def generate_content(self, count: int = 1, theme: Optional[str] = None) -> List[Dict]:
        """
        Generate N reels: beat-sheet script -> ElevenLabs voiceover (this is
        what drives duration - no fixed reel length) -> footage candidates
        run through the QC decision tree -> music -> Remotion render ->
        quality check -> DB save.

        Args:
            count: Number of reels to generate
            theme: Optional theme (see config.yaml `content.themes`)

        Returns:
            List of generated reel metadata
        """
        logger.info(f"Generating {count} reels (theme: {theme})")

        results = []
        reel_repo = GeneratedReelRepository(self.session)

        for i in range(count):
            try:
                beat_sheet = self.gemini_generator.generate_beat_sheet(theme=theme)
                logger.info(f"[{i+1}/{count}] Hook: {beat_sheet.hook[:50]}...")

                try:
                    voiceover = self.tts_provider.generate(beat_sheet.full_voiceover_text)
                except TTSProviderError as e:
                    logger.error(f"[{i+1}/{count}] Voiceover generation failed: {e}")
                    continue

                video_objs = await self._select_qc_approved_videos(
                    beat_sheet, target_duration=voiceover.duration, i=i, count=count
                )
                if not video_objs:
                    logger.warning(
                        f"[{i+1}/{count}] No footage passed QC for theme '{beat_sheet.theme}' - skipping"
                    )
                    continue

                music_obj = self._select_music(beat_sheet)
                if not music_obj:
                    logger.warning(
                        f"[{i+1}/{count}] No music available for theme '{beat_sheet.theme}' - skipping"
                    )
                    continue

                quote_obj = self.session.query(Quote).filter_by(text=beat_sheet.full_voiceover_text).first()
                if not quote_obj:
                    quote_obj = Quote(
                        text=beat_sheet.full_voiceover_text,
                        author="AI Generated",
                        category=beat_sheet.theme,
                        length=len(beat_sheet.full_voiceover_text),
                    )
                    self.session.add(quote_obj)
                    self.session.flush()

                self.session.commit()

                logger.debug(f"[{i+1}/{count}] Rendering video...")
                clip_paths = [Path("data/raw/videos") / v.filename for v in video_objs]
                music_path = Path("data/raw/music") / music_obj.filename
                result = self.video_generator.generate(
                    background_clips=clip_paths,
                    voiceover=voiceover,
                    caption=beat_sheet.caption,
                    music_path=music_path,
                )

                # Check quality
                quality_result = self.quality_checker.check_integrity(result["output_path"])
                quality_score = quality_result["quality_score"]
                is_ok = quality_score >= self.config.get("content.generation.quality_threshold", 0.75)

                if not is_ok:
                    logger.warning(f"Generated video failed quality check (score: {quality_score:.2f})")
                    continue

                # Save to database (primary video for the FK - all clips used
                # are tracked in the metadata sidecar the renderer writes)
                primary_video = video_objs[0]
                generated_reel = reel_repo.create(
                    video_id=primary_video.id,
                    music_id=music_obj.id,
                    quote_id=quote_obj.id,
                    output_path=result["output_path"].as_posix(),
                    caption=beat_sheet.caption,
                    status="pending",
                    duration=result["duration"],
                    file_size=result["file_size"],
                    quality_score=quality_score
                )

                # Update usage counts for all content
                for video_obj in video_objs:
                    video_obj.usage_count = (video_obj.usage_count or 0) + 1
                    video_obj.last_used_at = datetime.utcnow()

                music_obj.usage_count = (music_obj.usage_count or 0) + 1
                music_obj.last_used_at = datetime.utcnow()

                quote_obj.usage_count = (quote_obj.usage_count or 0) + 1
                quote_obj.last_used_at = datetime.utcnow()

                self.session.commit()

                logger.info(f"[{i+1}/{count}] Reel #{generated_reel.id} generated successfully")

                # Send preview to Telegram
                if self.telegram_bot:
                    preview_data = {
                        "video_names": [v.filename for v in video_objs],
                        "music_name": music_obj.filename,
                        "hook": beat_sheet.hook,
                        "body": beat_sheet.body,
                        "payoff": beat_sheet.payoff,
                        "caption": beat_sheet.caption,
                        "quality_score": generated_reel.quality_score,
                        "theme": beat_sheet.theme,
                        "duration": result["duration"],
                    }
                    await self.telegram_bot.send_reel_preview(
                        generated_reel.id,
                        preview_data
                    )

                results.append(
                    {
                        "id": generated_reel.id,
                        "output_path": str(result["output_path"]),
                        "caption": beat_sheet.caption,
                        "hook": beat_sheet.hook,
                        "payoff": beat_sheet.payoff,
                    }
                )

            except Exception as e:
                logger.error(f"Error generating reel {i+1}: {e}")
                if self.telegram_bot:
                    await self.telegram_bot.send_notification(
                        f"Error generating reel: {e}",
                        level="error"
                    )

        logger.info(f"Generated {len(results)} reels successfully")
        return results

    async def _select_qc_approved_videos(
        self, beat_sheet: BeatSheet, target_duration: float, i: int, count: int
    ) -> List[Video]:
        """
        Downloads over-fetched footage candidates, runs each through the QC
        decision tree, and returns the top-scoring accepted clips needed to
        cover `target_duration` (the voiceover's length). Falls back to
        reusing previously accepted clips from this theme's pool if nothing
        fresh passes QC, and alerts (rather than silently produces nothing)
        if the theme's pool is running thin.
        """
        vibe_description = f"{beat_sheet.theme}: {', '.join(beat_sheet.video_search_terms)}"
        candidates = self.content_downloader.download_video_candidates(
            search_terms=beat_sheet.video_search_terms,
            theme=beat_sheet.theme,
            count=self.config.get("footage_qc.video_over_fetch_count", 10),
        )

        scored: List[Tuple[float, Video]] = []
        for candidate in candidates:
            result = self.footage_qc.evaluate(
                candidate_path=candidate["path"],
                theme=beat_sheet.theme,
                vibe_description=vibe_description,
                session=self.session,
                source=candidate["source"],
            )
            if not result.accepted:
                continue

            video_obj = self.session.query(Video).filter_by(filename=candidate["path"].name).first()
            if not video_obj:
                video_obj = Video(
                    filename=candidate["path"].name,
                    source=candidate["source"],
                    url=candidate.get("url"),
                    theme=beat_sheet.theme,
                    tags=",".join(beat_sheet.video_search_terms),
                    qc_status="accepted",
                    qc_composite_score=result.composite_score,
                    qc_scores=json.dumps(result.scores, default=str),
                    qc_reason=result.reason,
                    qc_checked_at=datetime.utcnow(),
                    phash=result.phash,
                )
                self.session.add(video_obj)
                self.session.flush()
            scored.append((result.composite_score or 0.0, video_obj))

        self.session.commit()

        health = self.footage_qc.check_pool_health(beat_sheet.theme, self.session)
        if not health.healthy:
            logger.warning(
                f"[{i+1}/{count}] Footage pool for '{beat_sheet.theme}' is thin "
                f"({health.accepted_count}/{health.floor} accepted clips) - widen search "
                f"terms or add a curated source for this theme"
            )
            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"Footage pool for '{beat_sheet.theme}' is thin "
                    f"({health.accepted_count}/{health.floor} accepted clips) - reels for "
                    f"this theme may start reusing the same footage",
                    level="warning",
                )

        needed = VideoGenerator._max_usable_clips(target_duration)

        if not scored:
            logger.warning(f"[{i+1}/{count}] No fresh candidates passed QC, reusing existing pool")
            return (
                self.session.query(Video)
                .filter(Video.theme == beat_sheet.theme, Video.qc_status == "accepted")
                .order_by(Video.usage_count.asc())
                .limit(needed)
                .all()
            )

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [video for _, video in scored[:needed]]

    def _select_music(self, beat_sheet: BeatSheet) -> Optional[Music]:
        """Downloads music candidates and picks the first usable one, with a
        pool-reuse fallback if nothing fresh is available."""
        candidates = self.content_downloader.download_music_candidates(
            search_terms=beat_sheet.music_search_terms,
            theme=beat_sheet.theme,
            count=self.config.get("footage_qc.music_over_fetch_count", 5),
        )

        if not candidates:
            return (
                self.session.query(Music)
                .filter(Music.tags.contains(beat_sheet.theme))
                .order_by(Music.usage_count.asc())
                .first()
            )

        chosen = candidates[0]
        music_obj = self.session.query(Music).filter_by(filename=chosen["path"].name).first()
        if not music_obj:
            music_obj = Music(
                filename=chosen["path"].name,
                source=chosen["source"],
                url=chosen.get("url"),
                tags=",".join(beat_sheet.music_search_terms),
                energy_level="high",
            )
            self.session.add(music_obj)
            self.session.flush()
        return music_obj

    async def schedule_reel(self, reel_id: int) -> None:
        """Schedule an approved reel for publishing."""
        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            sched_repo = ScheduledPostRepository(session)

            reel = reel_repo.get_by_id(reel_id)
            if not reel:
                logger.error(f"Reel #{reel_id} not found")
                return

            # Get next scheduled time from database config
            next_time = self._get_next_scheduled_time_from_db()
            if not next_time:
                logger.warning("No scheduled times configured")
                return

            # Create scheduled post
            scheduled = sched_repo.create(
                reel_id=reel_id,
                scheduled_time=next_time
            )

            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            formatted_time = datetime_helpers.format_datetime_for_display(next_time, tz_name)

            logger.info(f"Reel #{reel_id} scheduled for {formatted_time}")

            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"✅ Reel #{reel_id} scheduled for {formatted_time}",
                    level="success"
                )

        except Exception as e:
            logger.error(f"Error scheduling reel: {e}")
        finally:
            session.close()

    async def publish_reel_to_instagram(self, reel_id: int) -> None:
        """Publish a reel to Instagram using Graph API with S3 storage."""
        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            pub_repo = PublishedPostRepository(session)
            sched_repo = ScheduledPostRepository(session)
            
            reel = reel_repo.get_by_id(reel_id)

            if not reel:
                logger.error(f"Reel #{reel_id} not found")
                return

            # Check if already published
            existing_pub = session.query(PublishedPost).filter_by(reel_id=reel_id).first()
            if existing_pub:
                logger.warning(f"Reel #{reel_id} already published (media_id: {existing_pub.instagram_media_id})")
                if self.telegram_bot:
                    await self.telegram_bot.send_notification(
                        f"⚠️ Reel #{reel_id} was already published\nMedia ID: {existing_pub.instagram_media_id}",
                        level="info"
                    )
                
                # Ensure scheduled post is marked as published to stop the loop
                sched_post = sched_repo.get_by_reel_id(reel_id)
                if sched_post:
                    sched_repo.update_status(sched_post.id, "published")
                return

            logger.info(f"Publishing reel #{reel_id} to Instagram via Graph API...")

            video_path = Path(reel.output_path)
            if not video_path.exists():
                logger.error(f"Video file not found: {video_path}")
                return

            # Get config
            config = get_config_instance()
            s3_bucket = config.get("aws.s3_bucket_name")
            s3_region = config.get("aws.region", "us-east-1")
            
            if not s3_bucket:
                logger.error("S3 bucket not configured")
                if self.telegram_bot:
                    await self.telegram_bot.send_notification(
                        "❌ S3 bucket not configured. Add AWS credentials to .env",
                        level="error"
                    )
                return

            from src.services import InstagramService
            instagram = InstagramService.from_config()
            
            # Upload to S3 reels/ directory
            s3_key = f"reels/{video_path.name}"
            logger.info(f"Uploading to S3: s3://{s3_bucket}/{s3_key}")
            
            s3_url = instagram.s3_upload_and_presign(
                local_path=video_path,
                bucket=s3_bucket,
                region=s3_region,
                s3_key=s3_key,
                expires=7200
            )
            
            logger.info(f"S3 upload complete: {s3_url}")
            logger.info(f"Publishing to Instagram via Graph API...")
            
            # Publish using Graph API
            media_id = instagram.publish_reel(
                video_url=s3_url,
                caption=reel.caption,
                video_path=video_path,
                poll_seconds=10,
                max_polls=60
            )
            
            logger.info(f"✅ Reel #{reel_id} published successfully (media_id: {media_id})")

            # Save to database
            pub_repo.create(
                reel_id=reel_id,
                instagram_media_id=media_id,
                caption=reel.caption,
                s3_url=f"s3://{s3_bucket}/{s3_key}"
            )
            
            # Update reel status
            reel_repo.update_status(reel_id, "published")

            # Update scheduled post status
            sched_post = sched_repo.get_by_reel_id(reel_id)
            if sched_post:
                sched_repo.update_status(sched_post.id, "published")

            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"✅ Reel #{reel_id} published to Instagram!\n"
                    f"Media ID: {media_id}\n"
                    f"S3: s3://{s3_bucket}/{s3_key}",
                    level="success"
                )

            logger.info(f"✅ Reel #{reel_id} published successfully")

            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"✅ Reel #{reel_id} published to Instagram!",
                    level="success"
                )

        except Exception as e:
            logger.error(f"Error publishing reel: {e}")
            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"❌ Failed to publish reel #{reel_id}: {e}",
                    level="error"
                )
        finally:
            session.close()

    async def publish_scheduled_entry(self, entry) -> None:
        """Publish a calendar entry."""
        if entry.reel_id:
            await self.publish_reel_to_instagram(entry.reel_id)

    @staticmethod
    def _get_next_scheduled_time(post_time_config: Dict) -> datetime:
        """Get the next scheduled time from config."""
        day = post_time_config.get("day", 1)
        time_str = post_time_config.get("time", "18:00")
        hour, minute = map(int, time_str.split(":"))

        now = datetime.utcnow()
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If time has passed today, schedule for next week
        if scheduled <= now:
            scheduled += timedelta(days=7 - now.weekday() + day if day >= now.weekday() else day)

        return scheduled

    def _get_next_scheduled_time_from_db(self) -> Optional[datetime]:
        """
        Get next scheduled time from database ScheduleConfig.
        Falls back to config.yaml if DB is empty.

        Returns:
            UTC datetime for next scheduled post, or None if no schedule found
        """
        session = get_session()
        try:
            config_repo = ScheduleConfigRepository(session)

            # Get all enabled schedule configs
            schedules = config_repo.get_all()

            if not schedules:
                # Fall back to config.yaml
                post_times = self.config.get("scheduling.post_times", [])
                if post_times:
                    return self._get_next_scheduled_time(post_times[0])
                logger.warning("No schedules configured in DB or config.yaml")
                return None

            # Find the next scheduled time
            now_utc = datetime.utcnow()
            tz = datetime_helpers.get_timezone()

            # Convert UTC to local timezone to properly compare with scheduled times
            from pytz import utc
            import pytz
            now_utc_aware = utc.localize(now_utc)
            now_local = now_utc_aware.astimezone(tz)

            current_weekday = now_local.weekday()
            current_hour = now_local.hour
            current_minute = now_local.minute

            # Sort schedules by day and time
            sorted_schedules = sorted(schedules, key=lambda s: (s.day_of_week, s.time))

            # Find the next scheduled slot
            for schedule in sorted_schedules:
                schedule_hour, schedule_minute = map(int, schedule.time.split(":"))

                # Check if this schedule is for today and still in the future
                if schedule.day_of_week == current_weekday and (schedule_hour, schedule_minute) > (current_hour, current_minute):
                    # Create a local time and convert back to UTC
                    next_local = now_local.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
                    return next_local.astimezone(utc).replace(tzinfo=None)

                # Check if this schedule is for a future day this week
                if schedule.day_of_week > current_weekday:
                    days_ahead = schedule.day_of_week - current_weekday
                    next_local = now_local + timedelta(days=days_ahead)
                    next_local = next_local.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
                    return next_local.astimezone(utc).replace(tzinfo=None)

            # All schedules have passed this week, use first schedule for next week
            first_schedule = sorted_schedules[0]
            schedule_hour, schedule_minute = map(int, first_schedule.time.split(":"))
            days_ahead = 7 - current_weekday + first_schedule.day_of_week
            next_local = now_local + timedelta(days=days_ahead)
            next_local = next_local.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
            return next_local.astimezone(utc).replace(tzinfo=None)

        except Exception as e:
            logger.error(f"Error getting next scheduled time from DB: {e}")
            # Fall back to config.yaml
            post_times = self.config.get("scheduling.post_times", [])
            if post_times:
                return self._get_next_scheduled_time(post_times[0])
            return None
        finally:
            session.close()

    async def reschedule_reel(self, reel_id: int, new_datetime: datetime) -> Tuple[bool, str]:
        """
        Reschedule a reel to a new date/time.

        Args:
            reel_id: ID of the reel to reschedule
            new_datetime: New UTC datetime for scheduling

        Returns:
            Tuple of (success, message)
        """
        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)
            reel_repo = GeneratedReelRepository(session)

            # Check if reel exists
            reel = reel_repo.get_by_id(reel_id)
            if not reel:
                return False, f"Reel #{reel_id} not found"

            # Check if reel is already scheduled
            scheduled = sched_repo.get_by_reel_id(reel_id)
            if not scheduled:
                return False, f"Reel #{reel_id} is not scheduled"

            # Update the scheduled time
            sched_repo.update_scheduled_time(reel_id, new_datetime)

            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            formatted_time = datetime_helpers.format_datetime_for_display(new_datetime, tz_name)

            logger.info(f"Reel #{reel_id} rescheduled to {formatted_time}")
            return True, f"Reel #{reel_id} rescheduled to {formatted_time}"

        except Exception as e:
            logger.error(f"Error rescheduling reel: {e}")
            return False, f"Error rescheduling reel: {e}"
        finally:
            session.close()

    async def schedule_reel_at(self, reel_id: int, specific_datetime: datetime) -> Tuple[bool, str]:
        """
        Schedule an approved reel at a specific date/time.

        Args:
            reel_id: ID of the reel to schedule
            specific_datetime: Specific UTC datetime for scheduling

        Returns:
            Tuple of (success, message)
        """
        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            sched_repo = ScheduledPostRepository(session)

            # Check if reel exists
            reel = reel_repo.get_by_id(reel_id)
            if not reel:
                return False, f"Reel #{reel_id} not found"

            # Check if reel is already scheduled
            existing = sched_repo.get_by_reel_id(reel_id)
            if existing:
                return False, f"Reel #{reel_id} is already scheduled for {existing.scheduled_time}"

            # Mark reel as approved
            reel_repo.update_status(reel_id, "approved")

            # Create scheduled post
            sched_repo.create(reel_id=reel_id, scheduled_time=specific_datetime)

            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            formatted_time = datetime_helpers.format_datetime_for_display(specific_datetime, tz_name)

            logger.info(f"Reel #{reel_id} approved and scheduled for {formatted_time}")
            return True, f"Reel #{reel_id} approved and scheduled for {formatted_time}"

        except Exception as e:
            logger.error(f"Error scheduling reel at specific time: {e}")
            return False, f"Error scheduling reel: {e}"
        finally:
            session.close()

    async def get_calendar_view(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get formatted calendar view of scheduled posts.

        Args:
            days: Number of days to include in calendar (default 30, max 90)

        Returns:
            List of calendar entries with date, time, reel info, quote, and quality
        """
        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)

            # Get calendar view from repository
            entries = sched_repo.get_calendar_view(days=min(days, 90))

            calendar = []
            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")

            for entry in entries:
                reel = entry.get("reel")
                scheduled_post = entry.get("scheduled_post")

                if reel and scheduled_post:
                    # Format the scheduled time
                    formatted_time = datetime_helpers.format_datetime_for_display(
                        scheduled_post.scheduled_time,
                        tz_name
                    )

                    # Get quote text (if exists)
                    quote_text = ""
                    if reel.quote:
                        quote_text = reel.quote.text[:100]  # First 100 chars
                        if len(reel.quote.text) > 100:
                            quote_text += "..."

                    calendar.append({
                        "reel_id": reel.id,
                        "scheduled_time": formatted_time,
                        "quote": quote_text,
                        "quality": reel.quality_score,
                        "duration": reel.duration,
                        "status": scheduled_post.status
                    })

            return calendar

        except Exception as e:
            logger.error(f"Error getting calendar view: {e}")
            return []
        finally:
            session.close()

    async def update_schedule_config(self, day: int, time: str) -> Tuple[bool, str]:
        """
        Update or create default schedule configuration.

        Args:
            day: Day of week (0-6, 0=Monday)
            time: Time in HH:MM format

        Returns:
            Tuple of (success, message)
        """
        session = get_session()
        try:
            config_repo = ScheduleConfigRepository(session)

            # Validate day and time
            is_valid, error = datetime_helpers.validate_day_of_week(day)
            if not is_valid:
                return False, error

            # Validate time format
            time_tuple, error = datetime_helpers.parse_time_string(time)
            if error:
                return False, error

            # Find or create schedule entry
            existing = config_repo.get_by_day(day)

            if existing:
                # Update existing
                config_repo.update(existing[0].id, time=time, enabled=True)
            else:
                # Create new
                config_repo.create(day_of_week=day, time=time)

            day_name = datetime_helpers.day_name(day)
            logger.info(f"Default schedule updated: {day_name} at {time}")
            return True, f"Default schedule updated: {day_name} at {time}"

        except Exception as e:
            logger.error(f"Error updating schedule config: {e}")
            return False, f"Error updating schedule: {e}"
        finally:
            session.close()

    async def get_schedule_config(self) -> List[Dict[str, Any]]:
        """
        Get current default schedule configuration.

        Returns:
            List of schedule entries with day name, time, and source
        """
        session = get_session()
        try:
            config_repo = ScheduleConfigRepository(session)

            # Get all enabled schedules
            schedules = config_repo.get_all()

            if not schedules:
                # Fall back to config.yaml
                config_schedules = self.config.get("scheduling.post_times", [])
                result = []
                for sched in config_schedules:
                    day = sched.get("day", 0)
                    time = sched.get("time", "18:00")
                    result.append({
                        "day": datetime_helpers.day_name(day),
                        "time": time,
                        "source": "config.yaml"
                    })
                return result

            # Format database schedules
            result = []
            for schedule in schedules:
                result.append({
                    "day": datetime_helpers.day_name(schedule.day_of_week),
                    "time": schedule.time,
                    "source": "database"
                })

            # Add timezone info
            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            result.append({
                "timezone": tz_name,
                "type": "info"
            })

            return result

        except Exception as e:
            logger.error(f"Error getting schedule config: {e}")
            return []
        finally:
            session.close()
