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
from typing import Optional, List, Dict, Any, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from pathlib import Path
from apscheduler.triggers.cron import CronTrigger

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance
from src.utils import datetime_helpers
from src.database import get_session
from src.database.models import PublishedPost, ScheduledPost
from src.database.repositories import (
    GeneratedReelRepository, ScheduledPostRepository,
    PublishedPostRepository,
    ContentCalendarRepository, JobRepository, ScheduleConfigRepository,
    MAX_PUBLISH_ATTEMPTS
)
from src.processors import ContentSelector, VideoGenerator, QualityChecker
from src.services import InstagramService, LLMProvider
from src.services.instagram import InstagramAuthError, sanitize_error_text
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

        # Read-only credential/permission validation - never publishes.
        await self._run_instagram_preflight()

        # Reclaim any rows stuck in `publishing` from a previous process
        # that crashed/restarted mid-publish, before we start scheduling
        # new work.
        self._recover_stale_publishing()

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

            now = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
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
        """Background job: claim and publish due scheduled posts.

        Uses a fresh database session for the entire job (never the
        orchestrator's long-lived session), closed in `finally`, so that
        schedule writes and the due-job path never share a session. Each
        candidate row is claimed atomically (conditional UPDATE) before
        being published, so the same ScheduledPost can never be published
        concurrently by two workers/ticks.
        """
        session = get_session()
        try:
            logger.debug("Running publish_scheduled_job")
            sched_repo = ScheduledPostRepository(session)

            now_utc_aware = datetime_helpers.now_utc()
            now_db = datetime_helpers.utc_for_db(now_utc_aware)
            logger.debug(f"Checking for scheduled posts. Current UTC time: {now_db}")

            candidates = sched_repo.get_claimable(now=now_db)
            logger.debug(f"Found {len(candidates)} scheduled posts eligible to claim")

            for candidate in candidates:
                claimed = sched_repo.claim(candidate.id, expected_status=candidate.status, now=now_db)
                if not claimed:
                    # Another worker/tick already claimed this row.
                    continue

                logger.info(
                    f"Claimed scheduled post #{candidate.id} for reel #{candidate.reel_id} "
                    f"(scheduled for {candidate.scheduled_time})"
                )
                await self._execute_publish(session, candidate.id, candidate.reel_id, notify=True)

        except Exception as e:
            logger.error(f"Error in publish_scheduled_job: {e}")
        finally:
            session.close()

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
                    video_meta = downloaded_content.get("video_data", {})
                    video_obj = self.session.query(Video).filter_by(filename=video_filename).first()
                    if not video_obj:
                        video_obj = Video(
                            filename=video_filename,
                            duration=30,
                            resolution="1080x1920",
                            tags=",".join(content_idea.video_search_terms),
                            theme=ai_theme,
                            source=video_meta.get("source", "youtube_auto"),
                            url=video_meta.get("url")
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
                quality_result = self.quality_checker.check_integrity(result["output_path"])
                quality_score = quality_result["quality_score"]
                is_ok = quality_score >= self.config.get("content.generation.quality_threshold", 0.75)

                if not is_ok:
                    logger.warning(f"Generated video failed quality check (score: {quality_score:.2f})")
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
                    quality_score=quality_score
                )

                # Update usage counts for all content
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

    async def generate_two_part_content(self, count: int = 1, theme: Optional[str] = None) -> List[Dict]:
        """
        Generate N content reels with two-part quotes (hook + payoff).

        Perfect for TikTok/Reels: eye-catching hook (4s) + powerful payoff
        
        Args:
            count: Number of reels to generate
            theme: Optional theme (motivation, philosophy, hustle)

        Returns:
            List of generated reel metadata
        """
        logger.info(f"Generating {count} two-part reels (theme: {theme})")

        results = []
        reel_repo = GeneratedReelRepository(self.session)

        for i in range(count):
            try:
                # Generate AI-powered two-part quote (with uniqueness check)
                logger.info(f"[{i+1}/{count}] Generating AI-powered two-part quote...")
                
                from src.database.models import Quote
                quote_data = None
                
                # Retry up to 3 times to get a unique quote
                for attempt in range(3):
                    candidate_data = self.gemini_generator.generate_two_part_quote()
                    hook = candidate_data.get("hook", "")
                    payoff = candidate_data.get("payoff", "")
                    full_text = f"{hook} {payoff}"
                    
                    # Check if this quote text already exists in DB
                    existing_quote = self.session.query(Quote).filter(Quote.text == full_text).first()
                    
                    if not existing_quote:
                        quote_data = candidate_data
                        break
                    else:
                        logger.warning(f"Generated duplicate quote, retrying... ({full_text[:30]}...)")
                
                if not quote_data:
                    logger.warning(f"Could not generate unique quote after 3 attempts, using last one")
                    quote_data = candidate_data

                hook = quote_data.get("hook", "")
                payoff = quote_data.get("payoff", "")
                
                logger.info(f"[{i+1}/{count}] Hook: {hook[:40]}...")
                logger.info(f"[{i+1}/{count}] Payoff: {payoff[:40]}...")

                # Generate AI content idea for video/music selection
                logger.info(f"[{i+1}/{count}] Generating content idea for video/music...")
                content_idea = self.gemini_generator.generate_content_idea(
                    theme=theme,
                    style="redpill_motivational"
                )

                # Generate engaging caption for the two-part quote
                logger.info(f"[{i+1}/{count}] Generating caption for two-part quote...")
                full_quote = f"{hook} {payoff}"
                caption = self.llm.generate(
                    quote=full_quote,
                    theme=content_idea.theme or theme or "motivation",
                    music_energy="high"
                )

                # Download video and music (with uniqueness check)
                logger.info(f"[{i+1}/{count}] Downloading video and music...")
                
                # Fetch existing video URLs to ensure uniqueness
                from src.database.models import Video
                existing_urls = set()
                try:
                    # Get all non-null URLs from video table
                    urls = self.session.query(Video.url).filter(Video.url.isnot(None)).all()
                    existing_urls = {u[0] for u in urls if u[0]}
                except Exception as e:
                    logger.warning(f"Failed to fetch existing video URLs: {e}")
                
                downloaded_content = self.content_downloader.download_content_for_idea(
                    content_idea,
                    excluded_urls=existing_urls
                )

                if not downloaded_content["video_path"] or not downloaded_content["music_path"]:
                    logger.error(f"[{i+1}/{count}] Failed to download required content")
                    continue

                # Add downloaded content to database if not exists
                from src.database.models import Video, Music, Quote

                # Check/add video
                video_filename = downloaded_content["video_path"].name
                video_meta = downloaded_content.get("video_data", {})
                video_obj = self.session.query(Video).filter_by(filename=video_filename).first()
                if not video_obj:
                    video_obj = Video(
                        filename=video_filename,
                        duration=30,
                        resolution="1080x1920",
                        tags=",".join(content_idea.video_search_terms),
                        theme=content_idea.theme,
                        source=video_meta.get("source", "youtube_auto"),
                        url=video_meta.get("url")
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

                # Generate two-part video
                logger.debug(f"[{i+1}/{count}] Generating two-part video...")
                from pathlib import Path
                result = self.video_generator.generate_two_part(
                    video_path=Path("data/raw/videos") / video_obj.filename,
                    music_path=Path("data/raw/music") / music_obj.filename,
                    hook=hook,
                    payoff=payoff,
                    caption=caption
                )

                # Check quality
                quality_result = self.quality_checker.check_integrity(result["output_path"])
                quality_score = quality_result["quality_score"]
                is_ok = quality_score >= self.config.get("content.generation.quality_threshold", 0.75)

                if not is_ok:
                    logger.warning(f"Generated video failed quality check (score: {quality_score:.2f})")
                    continue

                # Create Quote record with merged hook+payoff text
                logger.debug(f"[{i+1}/{count}] Creating quote record...")
                from src.database.models import Quote
                merged_quote_text = f"{hook} {payoff}"
                quote_obj = self.session.query(Quote).filter(Quote.text == merged_quote_text).first()
                if not quote_obj:
                    quote_obj = Quote(
                        text=merged_quote_text,
                        category="two_part_reel",
                        length=len(merged_quote_text)
                    )
                    self.session.add(quote_obj)
                    self.session.flush()
                    logger.debug(f"Created new quote record: {quote_obj.id}")
                else:
                    logger.debug(f"Using existing quote record: {quote_obj.id}")

                # Save to database
                logger.debug(f"[{i+1}/{count}] Saving reel to database...")
                generated_reel = reel_repo.create(
                    video_id=video_obj.id,
                    music_id=music_obj.id,
                    quote_id=quote_obj.id,
                    output_path=str(result["output_path"]),
                    caption=caption,
                    duration=result["duration"],
                    file_size=result["file_size"],
                    quality_score=quality_score
                )

                # Update usage counts for all content
                video_obj.usage_count = (video_obj.usage_count or 0) + 1
                video_obj.last_used_at = datetime.utcnow()

                music_obj.usage_count = (music_obj.usage_count or 0) + 1
                music_obj.last_used_at = datetime.utcnow()

                quote_obj.usage_count = (quote_obj.usage_count or 0) + 1
                quote_obj.last_used_at = datetime.utcnow()

                self.session.commit()

                logger.info(f"[{i+1}/{count}] Two-part reel #{generated_reel.id} generated successfully")

                # Send preview to Telegram
                if self.telegram_bot:
                    preview_data = {
                        "video_name": video_obj.filename,
                        "music_name": music_obj.filename,
                        "hook": hook,
                        "payoff": payoff,
                        "caption": caption,
                        "quality_score": generated_reel.quality_score,
                        "is_two_part": True
                    }
                    await self.telegram_bot.send_reel_preview(
                        generated_reel.id,
                        preview_data
                    )

                results.append(
                    {
                        "id": generated_reel.id,
                        "output_path": str(result["output_path"]),
                        "caption": caption,
                        "hook": hook,
                        "payoff": payoff
                    }
                )

            except Exception as e:
                logger.error(f"Error generating two-part reel {i+1}: {e}")
                if self.telegram_bot:
                    await self.telegram_bot.send_notification(
                        f"Error generating two-part reel: {e}",
                        level="error"
                    )

        logger.info(f"Generated {len(results)} two-part reels successfully")
        return results

    async def schedule_reel(self, reel_id: int) -> Tuple[bool, str]:
        """Schedule an approved reel for publishing.

        Returns (success, message) so callers (Telegram) can only report
        "scheduled" when this actually succeeded - a DB failure here must
        never be reported as success.
        """
        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            sched_repo = ScheduledPostRepository(session)

            reel = reel_repo.get_by_id(reel_id)
            if not reel:
                return False, f"Reel #{reel_id} not found"

            existing = sched_repo.get_by_reel_id(reel_id)
            if existing:
                return False, f"Reel #{reel_id} is already scheduled"

            # Get next scheduled time from database config
            next_time = self._get_next_scheduled_time_from_db()
            if not next_time:
                return False, "No scheduled times configured"

            # Create scheduled post
            sched_repo.create(reel_id=reel_id, scheduled_time=next_time)

            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            formatted_time = datetime_helpers.format_datetime_for_display(next_time, tz_name)

            message = f"Reel #{reel_id} scheduled for {formatted_time}"
            logger.info(message)

            if self.telegram_bot:
                await self.telegram_bot.send_notification(f"✅ {message}", level="success")

            return True, message

        except Exception as e:
            logger.error(f"Error scheduling reel: {e}")
            return False, f"Error scheduling reel: {e}"
        finally:
            session.close()

    async def publish_reel_to_instagram(self, reel_id: int) -> Tuple[bool, str]:
        """Manually publish a reel right now (used by /post_now and the
        legacy content-calendar path), bypassing the schedule but going
        through the exact same claim + state-machine + typed-exception
        pipeline as the background job.

        Returns (success, message).
        """
        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)

            scheduled_post = sched_repo.get_by_reel_id(reel_id)
            if not scheduled_post:
                now_db = datetime_helpers.utc_for_db(datetime_helpers.now_utc())
                scheduled_post = sched_repo.create(reel_id=reel_id, scheduled_time=now_db)

            if not sched_repo.force_claim_now(scheduled_post.id):
                # Refresh to report the actual current state (e.g. already
                # publishing/published by another path).
                session.refresh(scheduled_post)
                return False, f"Reel #{reel_id} could not be claimed (status: {scheduled_post.status})"

            outcome = await self._execute_publish(session, scheduled_post.id, reel_id, notify=False)
            return outcome
        finally:
            session.close()

    async def publish_scheduled_entry(self, entry) -> None:
        """Publish a calendar entry."""
        if entry.reel_id:
            await self.publish_reel_to_instagram(entry.reel_id)

    async def retry_failed(self, scheduled_post_id: int) -> Tuple[bool, str]:
        """Handle /retry_failed <id>: give a `failed` scheduled post a fresh
        retry budget and attempt to publish it immediately."""
        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)
            post = sched_repo.reset_for_manual_retry(scheduled_post_id)
            if not post:
                return False, f"Scheduled post #{scheduled_post_id} is not in a failed state"

            if not sched_repo.force_claim_now(post.id):
                return False, f"Scheduled post #{scheduled_post_id} could not be claimed for retry"

            return await self._execute_publish(session, post.id, post.reel_id, notify=False)
        finally:
            session.close()

    async def publish_now(self, scheduled_post_id: int) -> Tuple[bool, str]:
        """Handle /publish_now <id>: force-publish a specific scheduled post
        right now regardless of its due time."""
        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)
            post = session.query(ScheduledPost).get(scheduled_post_id)
            if not post:
                return False, f"Scheduled post #{scheduled_post_id} not found"

            if not sched_repo.force_claim_now(post.id):
                session.refresh(post)
                return False, f"Scheduled post #{scheduled_post_id} could not be claimed (status: {post.status})"

            return await self._execute_publish(session, post.id, post.reel_id, notify=False)
        finally:
            session.close()

    async def _execute_publish(
        self, session, scheduled_post_id: int, reel_id: int, notify: bool = True
    ) -> Tuple[bool, str]:
        """Core publish routine shared by the background job and every
        manual-trigger command. `scheduled_post_id` must already be claimed
        (status == 'publishing') by the caller before this is invoked.

        Never swallows a publish failure into a fake success - every branch
        ends in a durable, persisted terminal-or-retry state, and returns
        (success, message) so callers know exactly what happened.
        """
        reel_repo = GeneratedReelRepository(session)
        pub_repo = PublishedPostRepository(session)
        sched_repo = ScheduledPostRepository(session)

        reel = reel_repo.get_by_id(reel_id)
        if not reel:
            sanitized = f"Reel #{reel_id} not found"
            sched_repo.record_failure(scheduled_post_id, sanitized)
            if notify and self.telegram_bot:
                await self.telegram_bot.send_notification(f"❌ {sanitized}", level="error")
            return False, sanitized

        # Idempotent success: if this reel was already published (e.g. a
        # previous attempt succeeded but the process crashed before updating
        # this row), converge state without calling Instagram again and
        # without re-notifying.
        existing_pub = session.query(PublishedPost).filter_by(reel_id=reel_id).first()
        if existing_pub:
            logger.info(
                f"Reel #{reel_id} already has a PublishedPost (media_id: "
                f"{existing_pub.instagram_media_id}); marking scheduled post #{scheduled_post_id} published"
            )
            sched_repo.mark_published(scheduled_post_id)
            reel_repo.update_status(reel_id, "published")
            return True, f"Reel #{reel_id} was already published (media_id: {existing_pub.instagram_media_id})"

        video_path = Path(reel.output_path)
        if not video_path.exists():
            return await self._fail_attempt(session, scheduled_post_id, reel_id, f"Video file not found: {video_path}", notify)

        s3_bucket = self.config.get("aws.s3_bucket_name")
        s3_region = self.config.get("aws.region", "us-east-1")

        # An unset env var with no default substitutes to the literal
        # "${VAR}" placeholder (truthy!) rather than None - never treat
        # that as a configured bucket name.
        if not s3_bucket or (isinstance(s3_bucket, str) and s3_bucket.startswith("${") and s3_bucket.endswith("}")):
            return await self._fail_attempt(session, scheduled_post_id, reel_id, "S3 bucket not configured", notify)

        instagram = getattr(self, "instagram", None) or InstagramService.from_config()

        try:
            s3_key = f"reels/{video_path.name}"
            logger.info(f"Uploading to S3: s3://{s3_bucket}/{s3_key}")
            s3_url = instagram.s3_upload_and_presign(
                local_path=video_path,
                bucket=s3_bucket,
                region=s3_region,
                s3_key=s3_key,
                expires=7200
            )

            logger.info("Publishing to Instagram via Graph API...")
            result = instagram.publish_reel(
                video_url=s3_url,
                caption=reel.caption,
                video_path=video_path,
                poll_seconds=10,
                max_polls=60
            )
        except Exception as e:
            sanitized = sanitize_error_text(str(e))
            return await self._fail_attempt(session, scheduled_post_id, reel_id, sanitized, notify)

        media_id = result.media_id
        logger.info(f"Reel #{reel_id} published successfully (media_id: {media_id})")

        pub_repo.create(
            reel_id=reel_id,
            instagram_media_id=media_id,
            caption=reel.caption,
            s3_url=f"s3://{s3_bucket}/{s3_key}"
        )
        reel_repo.update_status(reel_id, "published")
        sched_repo.mark_published(scheduled_post_id)

        message = f"Reel #{reel_id} published to Instagram! Media ID: {media_id}"
        if notify and self.telegram_bot:
            await self.telegram_bot.send_notification(f"✅ {message}", level="success")

        return True, message

    async def _fail_attempt(
        self, session, scheduled_post_id: int, reel_id: int, sanitized_error: str, notify: bool
    ) -> Tuple[bool, str]:
        """Persist a failed publish attempt (durable state, never swallowed)
        and apply the retry policy. Notifies Telegram exactly once, only
        when the retry budget is exhausted (terminal `failed`)."""
        sched_repo = ScheduledPostRepository(session)
        logger.error(f"Publish attempt failed for reel #{reel_id}: {sanitized_error}")

        resulting_status = sched_repo.record_failure(scheduled_post_id, sanitized_error)

        if resulting_status == "failed":
            message = f"Reel #{reel_id} failed permanently after {MAX_PUBLISH_ATTEMPTS} attempts: {sanitized_error}"
            if notify and self.telegram_bot:
                await self.telegram_bot.send_notification(f"❌ {message}", level="error")
            return False, message

        message = f"Reel #{reel_id} publish attempt failed, will retry: {sanitized_error}"
        return False, message

    async def _run_instagram_preflight(self) -> None:
        """Read-only startup validation of Instagram credentials/permissions.
        Never publishes anything. A failure is surfaced but does not crash
        the bot - scheduling still starts so failures remain visible via
        /scheduler_status and normal publish attempts.
        """
        try:
            instagram = getattr(self, "instagram", None) or InstagramService.from_config()
            instagram.preflight_check()
            logger.info("Instagram preflight check passed")
        except InstagramAuthError as e:
            logger.error(f"Instagram preflight auth check FAILED: {e}")
            if self.telegram_bot:
                await self.telegram_bot.send_notification(
                    f"❌ Instagram credentials preflight check failed: {e}", level="error"
                )
        except Exception as e:
            logger.warning(f"Instagram preflight check could not complete: {e}")

    def _recover_stale_publishing(self) -> int:
        """On startup, reclaim rows stuck in `publishing` whose claimed_at
        is older than the staleness threshold (a previous process crashed
        or was restarted mid-publish). Uses a fresh session, closed here."""
        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)
            recovered = sched_repo.recover_stale_publishing()
            if recovered:
                logger.warning(f"Recovered {recovered} stale publishing scheduled post(s) after restart")
            return recovered
        finally:
            session.close()

    async def get_scheduler_status(self) -> Dict[str, Any]:
        """Data for /scheduler_status: running state, current time, next
        wake-up, per-state counts and overdue count."""
        tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
        now_aware = datetime_helpers.now_utc()

        next_wakeup = None
        try:
            job = self.scheduler.get_job("publish_scheduled_check")
            if job and job.next_run_time:
                next_wakeup = job.next_run_time
        except Exception:
            pass

        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)
            now_db = datetime_helpers.utc_for_db(now_aware)
            counts = {
                status: sched_repo.count_by_status(status)
                for status in ("pending", "publishing", "retry_wait", "failed")
            }
            overdue = sched_repo.get_overdue_count(now=now_db)
            recent_failed = sched_repo.get_recent_failed(limit=3)
        finally:
            session.close()

        return {
            "running": self.running,
            "now_utc": now_aware,
            "now_local": now_aware.astimezone(datetime_helpers.get_timezone(tz_name)),
            "timezone": tz_name,
            "next_wakeup_utc": next_wakeup,
            "counts": counts,
            "overdue": overdue,
            "recent_failed": [
                {"id": p.id, "reel_id": p.reel_id, "error": p.error_message}
                for p in recent_failed
            ],
        }

    @staticmethod
    def _get_next_scheduled_time(post_time_config: Dict) -> datetime:
        """Get the next scheduled time (naive UTC, for DB storage) from a
        single config.yaml post_times entry, using the real clock."""
        schedules = [{"day_of_week": post_time_config.get("day", 0), "time": post_time_config.get("time", "18:00")}]
        next_slot = datetime_helpers.compute_next_slot(
            schedules, now=datetime_helpers.now_utc(), tz_name=datetime_helpers.DEFAULT_TIMEZONE
        )
        return datetime_helpers.utc_for_db(next_slot)

    def _get_next_scheduled_time_from_db(self) -> Optional[datetime]:
        """
        Get next scheduled time (naive UTC, for DB storage) from database
        ScheduleConfig. Falls back to config.yaml if DB is empty. Delegates
        the actual calculation to the pure, unit-tested
        `datetime_helpers.compute_next_slot`.

        Returns:
            Naive UTC datetime for next scheduled post, or None if no
            schedule found.
        """
        session = get_session()
        try:
            config_repo = ScheduleConfigRepository(session)
            schedules_db = config_repo.get_all()

            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")

            if schedules_db:
                schedules = [{"day_of_week": s.day_of_week, "time": s.time} for s in schedules_db]
            else:
                post_times = self.config.get("scheduling.post_times", [])
                if not post_times:
                    logger.warning("No schedules configured in DB or config.yaml")
                    return None
                schedules = [{"day_of_week": p.get("day", 0), "time": p.get("time", "18:00")} for p in post_times]

            next_slot = datetime_helpers.compute_next_slot(schedules, now=datetime_helpers.now_utc(), tz_name=tz_name)
            return datetime_helpers.utc_for_db(next_slot) if next_slot else None

        except Exception as e:
            logger.error(f"Error getting next scheduled time from DB: {e}")
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
