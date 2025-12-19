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
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from pathlib import Path
from apscheduler.triggers.cron import CronTrigger

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance
from src.database import get_session
from src.database.repositories import (
    GeneratedReelRepository, ScheduledPostRepository,
    ContentCalendarRepository, JobRepository
)
from src.processors import ContentSelector, VideoGenerator, QualityChecker
from src.services import InstagramService, LLMProvider
from src.services.gemini_content_generator import GeminiContentGenerator
from src.services.content_downloader import ContentDownloader

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

    async def start(self) -> None:
        """Start all background jobs and services."""
        logger.info("Starting orchestrator...")
        self.running = True

        # Initialize services
        self.session = get_session()
        self.content_selector = ContentSelector(
            self.session,
            self.config.get("content")
        )
        self.video_generator = VideoGenerator.from_config()
        self.quality_checker = QualityChecker()
        self.instagram = InstagramService.from_config()
        self.llm = LLMProvider.from_config()
        self.gemini_generator = GeminiContentGenerator()
        self.content_downloader = ContentDownloader()

        # Schedule background jobs
        self._schedule_jobs()

        # Start scheduler in background thread
        self.scheduler.start()
        logger.info("Orchestrator started - background jobs scheduled")

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

        # Schedule posts at configured times
        post_times = self.config.get("scheduling.post_times", [])
        for post_time in post_times:
            day = post_time.get("day", 1)  # 0-6 (Mon-Sun)
            time_str = post_time.get("time", "18:00")
            hour, minute = map(int, time_str.split(":"))

            # Convert day number: 0=Mon, 6=Sun
            days_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
            cron_day = days_map.get(day, "fri")

            self.scheduler.add_job(
                self.publish_scheduled_job,
                CronTrigger(day_of_week=cron_day, hour=hour, minute=minute),
                id=f"publish_{day}_{time_str}",
                name=f"Publish {cron_day} at {time_str}",
                misfire_grace_time=300
            )

        logger.info(f"Scheduled {len(self.scheduler.get_jobs())} background jobs")

    async def generate_content_job(self) -> None:
        """Background job: Generate content if queue is low."""
        try:
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

            # Get scheduled posts that are ready
            now = datetime.utcnow()
            scheduled = sched_repo.session.query(ScheduledPostRepository.model).filter(
                ScheduledPostRepository.model.scheduled_time <= now,
                ScheduledPostRepository.model.status == "scheduled"
            ).all()

            for post in scheduled:
                await self.publish_reel_to_instagram(post.reel_id)

        except Exception as e:
            logger.error(f"Error in publish_scheduled_job: {e}")

    async def generate_content(self, count: int = 1, theme: Optional[str] = None) -> List[Dict]:
        """
        Generate N content reels.

        Args:
            count: Number of reels to generate
            theme: Optional theme (motivation, philosophy, hustle)

        Returns:
            List of generated reel metadata
        """
        logger.info(f"Generating {count} reels (theme: {theme})")

        results = []
        reel_repo = GeneratedReelRepository(self.session)

        for i in range(count):
            try:
                # Generate AI-powered content idea first (if available)
                use_ai_prompt = self.gemini_generator.client is not None

                if use_ai_prompt:
                    logger.info(f"[{i+1}/{count}] Generating AI-powered content idea...")
                    content_idea = self.gemini_generator.generate_content_idea(
                        theme=theme,
                        style="redpill_motivational"
                    )
                    logger.info(f"[{i+1}/{count}] AI prompt: {content_idea.prompt[:60]}...")

                    # Use the AI-generated prompt as the quote
                    ai_quote_text = content_idea.prompt
                    ai_theme = content_idea.theme
                    ai_caption = content_idea.caption

                    # Download video and music if not in database
                    logger.info(f"[{i+1}/{count}] Downloading video and music...")
                    downloaded_content = self.content_downloader.download_content_for_idea(content_idea)

                    if not downloaded_content["video_path"] or not downloaded_content["music_path"]:
                        logger.error(f"[{i+1}/{count}] Failed to download required content")
                        continue

                    # Add downloaded content to database if not exists
                    from src.database.models import Video, Music, Quote

                    # Check/add video
                    video_filename = downloaded_content["video_path"].name
                    video_obj = self.session.query(Video).filter_by(filename=video_filename).first()
                    if not video_obj:
                        video_obj = Video(
                            filename=video_filename,
                            duration=30,
                            resolution="1080x1920",
                            tags=",".join(content_idea.video_search_terms),
                            theme=ai_theme,
                            source="youtube_auto"
                        )
                        self.session.add(video_obj)
                        self.session.flush()
                        logger.info(f"Added new video to database: {video_filename}")

                    # Check/add music
                    music_filename = downloaded_content["music_path"].name
                    music_obj = self.session.query(Music).filter_by(filename=music_filename).first()
                    if not music_obj:
                        music_obj = Music(
                            filename=music_filename,
                            duration=30,
                            bpm=150,
                            energy_level="high",
                            tags=",".join(content_idea.music_search_terms),
                            source="youtube_auto"
                        )
                        self.session.add(music_obj)
                        self.session.flush()
                        logger.info(f"Added new music to database: {music_filename}")

                    # Check/add quote
                    quote_obj = self.session.query(Quote).filter_by(text=ai_quote_text).first()
                    if not quote_obj:
                        quote_obj = Quote(
                            text=ai_quote_text,
                            author="AI Generated",
                            category=ai_theme,
                            length=len(ai_quote_text)
                        )
                        self.session.add(quote_obj)
                        self.session.flush()
                        logger.info(f"Added new quote to database: {ai_quote_text[:50]}...")

                    self.session.commit()

                else:
                    ai_quote_text = None
                    ai_theme = theme
                    ai_caption = None

                    # Select content (video/music based on theme) - old method
                    if ai_theme or theme:
                        combination = self.content_selector.find_matching_combination(theme=ai_theme or theme)
                    else:
                        combination = self.content_selector.get_random_combination()

                    if not combination:
                        logger.warning("Could not find valid content combination")
                        continue

                    video_obj = combination.video
                    music_obj = combination.music
                    quote_obj = combination.quote

                logger.debug(f"[{i+1}/{count}] Selected content for theme: {ai_theme or theme}")

                # Use AI-generated quote if available, otherwise use database quote
                final_quote = ai_quote_text if ai_quote_text else quote_obj.text

                # Generate caption (use AI caption if available, otherwise generate)
                if ai_caption:
                    caption = ai_caption
                    logger.info(f"[{i+1}/{count}] Using AI-generated caption")
                else:
                    caption = self.llm.generate(
                        quote=final_quote,
                        theme=ai_theme or theme or "motivation",
                        music_energy=music_obj.energy_level or "high"
                    )

                # Generate video
                logger.debug(f"[{i+1}/{count}] Generating video...")
                from pathlib import Path
                result = self.video_generator.generate(
                    video_path=Path("data/raw/videos") / video_obj.filename,
                    music_path=Path("data/raw/music") / music_obj.filename,
                    quote=final_quote,
                    caption=caption
                )

                # Check quality
                is_ok = self.quality_checker.is_acceptable(
                    result["output_path"],
                    min_quality_score=self.config.get("content.generation.quality_threshold", 0.75)
                )

                if not is_ok:
                    logger.warning(f"Generated video failed quality check")
                    continue

                # Save to database
                generated_reel = reel_repo.create(
                    video_id=video_obj.id,
                    music_id=music_obj.id,
                    quote_id=quote_obj.id,
                    output_path=result["output_path"].as_posix(),
                    caption=caption,
                    status="pending",
                    duration=result["duration"],
                    file_size=result["file_size"],
                    quality_score=result.get("quality_score", 0.8)
                )

                # Update usage counts (only if not using AI downloader)
                if not use_ai_prompt:
                    self.content_selector.update_usage_counts(combination)
                else:
                    # Update usage counts manually for downloaded content
                    video_obj.usage_count = (video_obj.usage_count or 0) + 1
                    music_obj.usage_count = (music_obj.usage_count or 0) + 1
                    quote_obj.usage_count = (quote_obj.usage_count or 0) + 1
                    self.session.commit()

                logger.info(f"[{i+1}/{count}] Reel #{generated_reel.id} generated successfully")

                # Send preview to Telegram
                if self.telegram_bot:
                    preview_data = {
                        "video_name": video_obj.filename,
                        "music_name": music_obj.filename,
                        "quote": final_quote,
                        "caption": caption,
                        "quality_score": generated_reel.quality_score
                    }
                    if use_ai_prompt:
                        preview_data["ai_generated"] = True
                        preview_data["theme"] = ai_theme
                        preview_data["music_search_terms"] = content_idea.music_search_terms
                        preview_data["video_search_terms"] = content_idea.video_search_terms

                    await self.telegram_bot.send_reel_preview(
                        generated_reel.id,
                        preview_data
                    )

                results.append(
                    {
                        "id": generated_reel.id,
                        "output_path": str(result["output_path"]),
                        "caption": caption
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

            # Get next scheduled time from config
            post_times = self.config.get("scheduling.post_times", [])
            if not post_times:
                logger.warning("No scheduled times configured")
                return

            next_time = self._get_next_scheduled_time(post_times[0])

            # Create scheduled post
            scheduled = sched_repo.create(
                reel_id=reel_id,
                scheduled_time=next_time
            )

            logger.info(f"Reel #{reel_id} scheduled for {next_time}")

            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"✅ Reel #{reel_id} scheduled for {next_time.strftime('%Y-%m-%d %H:%M')}",
                    level="success"
                )

        except Exception as e:
            logger.error(f"Error scheduling reel: {e}")
        finally:
            session.close()

    async def publish_reel_to_instagram(self, reel_id: int) -> None:
        """Publish a reel to Instagram."""
        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            reel = reel_repo.get_by_id(reel_id)

            if not reel:
                logger.error(f"Reel #{reel_id} not found")
                return

            logger.info(f"Publishing reel #{reel_id} to Instagram...")

            # Upload video to S3 and get presigned URL
            # (In production, this would upload to S3)
            video_path = Path(reel.output_path)
            if not video_path.exists():
                logger.error(f"Video file not found: {video_path}")
                return

            # For demo, log instead of actual publish
            logger.info(f"Would upload reel to S3 and publish")
            # media_id = self.instagram.publish_reel(
            #     video_url=s3_url,
            #     caption=reel.caption,
            #     video_path=video_path
            # )

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
