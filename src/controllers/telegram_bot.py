"""
Telegram Bot Controller for ShitPostBot.

Handles:
- User commands (/generate, /approve, /queue, etc.)
- Approval workflow with inline buttons
- Real-time notifications
- Admin control and monitoring
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance
from src.utils import datetime_helpers
from src.database import get_session
from src.database.repositories import (
    GeneratedReelRepository, ScheduledPostRepository,
    PublishedPostRepository, PostMetricsRepository
)
from src.database.models import ScheduledPost

logger = get_logger(__name__)


class TelegramBot:
      
    def __init__(self, orchestrator=None):
        """
        Initialize Telegram bot.

        Args:
            orchestrator: Reference to main orchestrator (injected)
        """
        self.config = get_config_instance()
        self.orchestrator = orchestrator
        self.bot_token = self.config.get("telegram.bot_token")
        self.admin_users = self.config.get("telegram.admin_users", [])

        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured")

        logger.info(f"Telegram bot initialized (admins: {len(self.admin_users)})")

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is authorized admin."""
        # If admin_users is [0], allow all users (admin not yet configured)
        if self.admin_users == [0]:
            return True
        return user_id in self.admin_users

    async def _check_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Verify user is admin, send message if not."""
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized. Admin access required.")
            logger.warning(f"Unauthorized access attempt from user {update.effective_user.id}")
            return False
        return True

    # ==================== Commands ====================

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        logger.info(f"START command received from user {update.effective_user.id}")
        logger.info(f"Admin users: {self.admin_users}")

        if not await self._check_admin(update, context):
            logger.warning(f"User {update.effective_user.id} not authorized")
            return

        logger.info(f"User {update.effective_user.id} authorized, sending welcome message")
        welcome = """
🤖 *ShitPostBot v1.0*

Welcome! I control autonomous Instagram content generation.

Available commands:
• `/status` - System status
• `/generate [count]` - Generate two-part reels (default: 3)
• `/queue` - View pending reels
• `/approve <reel_id>` - Approve reel for publishing
• `/reject <reel_id>` - Reject and delete reel
• `/reschedule <id> <date> <time>` - Reschedule post
• `/calendar [days]` - View scheduled posts calendar
• `/schedule` - View scheduled posts (next 7 days)
• `/analytics [days]` - Performance report (default: 7)
• `/help` - Show detailed command list
        """
        try:
            await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Welcome message sent to user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Failed to send welcome message: {e}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not await self._check_admin(update, context):
            return

        help_text = """
*ShitPostBot Commands*

*Generation*
• `/generate` - Generate 3 two-part reels (hook + payoff)
• `/generate 10` - Generate 10 two-part reels
• `/queue` - View pending reels awaiting approval

*Approval Workflow*
• `/approve <id>` - Approve reel #id
• `/reject <id>` - Reject reel #id
• `/preview <id>` - Preview reel metadata

*Scheduling*
• `/schedule` - View next 7 days
• `/post_now <id>` - Publish immediately (skip schedule)
• `/reschedule <id> <date> <time>` - Reschedule reel
• `/calendar [days]` - View scheduled posts calendar
• `/approve_at <id> <date> <time>` - Approve with custom time
• `/set_schedule <day> <time>` - Set default schedule
• `/get_schedule` - View current schedule

*Analytics*
• `/analytics` - Last 7 days
• `/analytics 30` - Last 30 days
• `/top` - Top performing posts
• `/insights` - AI-generated insights

*System*
• `/status` - System health & stats
• `/scheduler_status` - Scheduler health, next wake-up, pending/failed counts
• `/retry_failed <scheduled_post_id>` - Give a failed post a fresh retry budget
• `/publish_now <scheduled_post_id>` - Force-publish a scheduled post immediately
• `/pause` - Pause automation
• `/resume` - Resume automation

Use buttons below commands for quick actions.
        """
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if not await self._check_admin(update, context):
            return

        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            sched_repo = ScheduledPostRepository(session)
            pub_repo = PublishedPostRepository(session)

            pending = len(reel_repo.get_by_status("pending"))
            approved = len(reel_repo.get_by_status("approved"))
            scheduled = len(sched_repo.get_upcoming(days=7))
            published = len(pub_repo.get_recent(days=90, limit=999))

            status_msg = f"""
✅ *ShitPostBot Status*

📊 *Queue*
• Pending approval: {pending}
• Approved: {approved}
• Scheduled (next 7 days): {scheduled}
• Published (all-time): {published}

🔄 *Automation*
• Status: {"Running ▶️" if self.orchestrator and self.orchestrator.running else "Stopped ⏸️"}
• Last check: {self._format_time(datetime_helpers.utc_for_db(datetime_helpers.now_utc()))}

⚙️ *Configuration*
• Theme rotation: {self.config.get("content.selection.theme_rotation", True)}
• Queue target: {self.config.get("content.generation.queue_target", 7)}
• LLM provider: {self.config.get("llm.provider", "openai")}
            """
            await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Status command error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /schedule command - show upcoming scheduled posts."""
        if not await self._check_admin(update, context):
            return

        session = get_session()
        try:
            sched_repo = ScheduledPostRepository(session)
            upcoming = sched_repo.get_upcoming(days=7)

            if not upcoming:
                await update.message.reply_text("📅 No posts scheduled for the next 7 days")
                return

            schedule_msg = "📅 *Scheduled Posts (Next 7 Days)*\n\n"
            for post in upcoming:
                time_str = self._format_time(post.scheduled_time)
                schedule_msg += f"• Reel #{post.reel_id}: {time_str}\n"

            await update.message.reply_text(schedule_msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Schedule command error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /generate command - generate reels with hook+payoff quotes.

        Usage: /generate [count]
        Generates reels with eye-catching hook (4s) + powerful payoff
        Perfect for TikTok/Reels first-3-seconds engagement
        """
        if not await self._check_admin(update, context):
            return

        try:
            count = int(context.args[0]) if context.args else 3
            count = min(count, 10)  # Max 10 two-part videos at a time (slower to generate)

            await update.message.reply_text(
                f"🎬 Generating {count} two-part reels with hook+payoff...\n\n"
                f"⏱️ Hook: Eye-catching yellow text (4 seconds)\n"
                f"💥 Payoff: Powerful white text (remaining time)\n\n"
                f"This may take several minutes.",
                parse_mode=ParseMode.MARKDOWN
            )

            if not self.orchestrator:
                await update.message.reply_text("⚠️ Orchestrator not available")
                return

            # Generate two-part content
            results = await self.orchestrator.generate_two_part_content(count=count)
            
            await update.message.reply_text(
                f"✅ Generated {len(results)} two-part reels\n\n"
                f"Reel IDs: {', '.join([str(r['id']) for r in results])}\n\n"
                f"Use `/approve <reel_id>` to approve or `/queue` to view all pending.",
                parse_mode=ParseMode.MARKDOWN
            )

        except ValueError:
            await update.message.reply_text(
                "❌ Usage: /generate [count]\n\n"
                "Example: /generate 5\n\n"
                "Generates high-engagement reels with:\n"
                "• Eye-catching hook (random color, 4 sec)\n"
                "• Powerful payoff (magenta→cyan, 9 sec)\n"
                "• 13 second total duration"
            )
        except Exception as e:
            logger.error(f"Generate error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def post_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /post_now command - immediately publish a reel by ID, bypassing schedule."""
        if not await self._check_admin(update, context):
            return

        try:
            reel_id = int(context.args[0]) if context.args else None
            if not reel_id:
                await update.message.reply_text("❌ Usage: /post_now <reel_id>")
                return

            if not self.orchestrator:
                await update.message.reply_text("⚠️ Orchestrator not available")
                return

            await update.message.reply_text(f"🚀 Publishing reel #{reel_id} now...", parse_mode=ParseMode.MARKDOWN)
            success, message = await self.orchestrator.publish_reel_to_instagram(reel_id)
            if success:
                await update.message.reply_text(f"✅ {message}", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ {message}", parse_mode=ParseMode.MARKDOWN)

        except ValueError:
            await update.message.reply_text("❌ Invalid reel ID (must be a number)")
        except Exception as e:
            logger.error(f"Post now error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /queue command."""
        if not await self._check_admin(update, context):
            return

        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)

            pending = reel_repo.get_by_status("pending")[:10]  # Show first 10

            if not pending:
                await update.message.reply_text("✅ Queue is empty! No pending reels.")
                return

            queue_msg = "*📋 Pending Reels*\n\n"
            for i, reel in enumerate(pending, 1):
                queue_msg += f"{i}. ID: `{reel.id}`\n"
                queue_msg += f"   Video: {reel.video.filename}\n"
                queue_msg += f"   Music: {reel.music.filename}\n"
                queue_msg += f"   Quote: {reel.quote.text[:40]}...\n"
                queue_msg += f"   Quality: {reel.quality_score:.2f}\n\n"

            await update.message.reply_text(queue_msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Queue error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /preview command - preview a reel from queue."""
        if not await self._check_admin(update, context):
            return

        try:
            reel_id = int(context.args[0]) if context.args else None
            if not reel_id:
                await update.message.reply_text("❌ Usage: /preview <reel_id>")
                return

            session = get_session()
            try:
                reel_repo = GeneratedReelRepository(session)
                reel = reel_repo.get_by_id(reel_id)

                if not reel:
                    await update.message.reply_text(f"❌ Reel #{reel_id} not found")
                    return

                # Send the video file as preview
                video_path = Path(reel.output_path)
                if video_path.exists():
                    logger.info(f"Sending reel preview {reel_id}: {video_path}")
                    with open(video_path, 'rb') as video_file:
                        preview_caption = f"""
🎬 *Reel #{reel_id}*

📹 Video: `{reel.video.filename}`
🎵 Music: `{reel.music.filename}`
💬 Quote: {reel.quote.text[:60]}...
✍️ Caption: {reel.caption}
⭐ Quality: {reel.quality_score:.2f}
Status: {reel.status}
                        """

                        # Create action buttons
                        keyboard = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{reel_id}"),
                                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{reel_id}"),
                            ]
                        ])

                        await update.message.reply_video(
                            video=video_file,
                            caption=preview_caption,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
                else:
                    await update.message.reply_text(f"⚠️ Video file not found: {video_path}")

            finally:
                session.close()

        except ValueError:
            await update.message.reply_text("❌ Invalid reel ID (must be a number)")
        except Exception as e:
            logger.error(f"Preview error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /approve command."""
        if not await self._check_admin(update, context):
            return

        try:
            reel_id = int(context.args[0]) if context.args else None
            if not reel_id:
                await update.message.reply_text("❌ Usage: /approve <reel_id>")
                return

            session = get_session()
            try:
                reel_repo = GeneratedReelRepository(session)
                reel = reel_repo.get_by_id(reel_id)

                if not reel:
                    await update.message.reply_text(f"❌ Reel #{reel_id} not found")
                    return

                # Update status to approved
                reel_repo.update_status(reel_id, "approved")

                # Schedule for posting - only report "scheduled" if it
                # actually succeeded (a DB failure here must never be
                # reported as success).
                if self.orchestrator:
                    success, message = await self.orchestrator.schedule_reel(reel_id)
                    if success:
                        await update.message.reply_text(
                            f"✅ Reel #{reel_id} approved and scheduled for publishing\n{message}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        logger.info(f"Reel #{reel_id} approved and scheduled by user {update.effective_user.id}")
                    else:
                        await update.message.reply_text(
                            f"⚠️ Reel #{reel_id} approved but scheduling FAILED: {message}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        logger.error(f"Reel #{reel_id} approved but scheduling failed: {message}")
                else:
                    await update.message.reply_text(
                        f"✅ Reel #{reel_id} approved (orchestrator unavailable, not scheduled)",
                        parse_mode=ParseMode.MARKDOWN
                    )

            finally:
                session.close()

        except ValueError:
            await update.message.reply_text("❌ Invalid reel ID")
        except Exception as e:
            logger.error(f"Approve error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reject command - delete a reel (pending or approved)."""
        if not await self._check_admin(update, context):
            return

        try:
            reel_id = int(context.args[0]) if context.args else None
            if not reel_id:
                await update.message.reply_text("❌ Usage: /reject <reel_id>")
                return

            session = get_session()
            try:
                reel_repo = GeneratedReelRepository(session)
                reel = reel_repo.get_by_id(reel_id)

                if not reel:
                    await update.message.reply_text(f"❌ Reel #{reel_id} not found")
                    return

                # If approved, also delete from schedule
                if reel.status == "approved":
                    sched_repo = ScheduledPostRepository(session)
                    scheduled = sched_repo.session.query(ScheduledPost).filter(
                        ScheduledPost.reel_id == reel_id
                    ).first()
                    if scheduled:
                        sched_repo.session.delete(scheduled)
                        sched_repo.session.commit()
                        logger.info(f"Reel #{reel_id} removed from schedule")

                # Delete the reel
                reel_repo.update_status(reel_id, "rejected")

                await update.message.reply_text(
                    f"❌ Reel #{reel_id} rejected and deleted",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Reel #{reel_id} rejected by user {update.effective_user.id}")

            finally:
                session.close()

        except ValueError:
            await update.message.reply_text("❌ Invalid reel ID")
        except Exception as e:
            logger.error(f"Reject error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /analytics command."""
        if not await self._check_admin(update, context):
            return

        session = get_session()
        try:
            days = int(context.args[0]) if context.args else 7
            days = min(days, 90)  # Max 90 days

            metrics_repo = PostMetricsRepository(session)
            pub_repo = PublishedPostRepository(session)

            # Get average engagement
            avg_engagement = metrics_repo.get_average_engagement(days=days)

            # Get recent published posts
            published_posts = pub_repo.get_recent(days=days)
            total_posts = len(published_posts)

            analytics_msg = f"""
📊 *Analytics (Last {days} days)*

📈 Posts Published: {total_posts}
⚡ Avg Engagement: {avg_engagement:.2%}

💡 Performance Tracking enabled
Data updates as you get engagement on Instagram
            """
            await update.message.reply_text(analytics_msg, parse_mode=ParseMode.MARKDOWN)

        except ValueError:
            await update.message.reply_text("❌ Usage: /analytics [days]")
        except Exception as e:
            logger.error(f"Analytics error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def insights(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /insights command - show top performing reels."""
        if not await self._check_admin(update, context):
            return

        session = get_session()
        try:
            pub_repo = PublishedPostRepository(session)

            # Get top performing posts by engagement
            top_posts = pub_repo.get_top_by_engagement(days=30, limit=5)

            if not top_posts:
                await update.message.reply_text("📊 No published posts yet")
                return

            insights_msg = "🏆 *Top Performing Reels (Last 30 Days)*\n\n"
            for i, post in enumerate(top_posts, 1):
                engagement = post.engagement_rate or 0
                insights_msg += f"{i}. Reel #{post.reel_id}\n"
                insights_msg += f"   👍 Likes: {post.likes or 0}\n"
                insights_msg += f"   💬 Comments: {post.comments or 0}\n"
                insights_msg += f"   ⚡ Engagement: {engagement:.2%}\n\n"

            await update.message.reply_text(insights_msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Insights error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def top(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /top command - alias for /insights."""
        await self.insights(update, context)

    async def deleteschedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /deleteschedule command - delete a scheduled reel."""
        if not await self._check_admin(update, context):
            return

        if not context.args:
            await update.message.reply_text("❌ Usage: /deleteschedule <reel_id>")
            return

        session = get_session()
        try:
            reel_id = int(context.args[0])
            sched_repo = ScheduledPostRepository(session)

            # Find and delete the scheduled post
            scheduled = sched_repo.session.query(ScheduledPost).filter(
                ScheduledPost.reel_id == reel_id
            ).first()

            if not scheduled:
                await update.message.reply_text(f"❌ Reel #{reel_id} is not scheduled")
                return

            sched_repo.session.delete(scheduled)
            sched_repo.session.commit()

            await update.message.reply_text(f"✅ Reel #{reel_id} removed from schedule")
            logger.info(f"Reel #{reel_id} deleted from schedule by user {update.effective_user.id}")

        except ValueError:
            await update.message.reply_text("❌ Invalid reel ID (must be a number)")
        except Exception as e:
            logger.error(f"Delete schedule error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def schedulepreview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /schedulepreview command - preview a scheduled reel."""
        if not await self._check_admin(update, context):
            return

        if not context.args:
            await update.message.reply_text("❌ Usage: /schedulepreview <reel_id>")
            return

        session = get_session()
        try:
            reel_id = int(context.args[0])
            reel_repo = GeneratedReelRepository(session)
            reel = reel_repo.get_by_id(reel_id)

            if not reel:
                await update.message.reply_text(f"❌ Reel #{reel_id} not found")
                return

            # Send the video file as preview
            video_path = Path(reel.output_path)
            if video_path.exists():
                logger.info(f"Sending scheduled reel preview {reel_id}: {video_path}")
                with open(video_path, 'rb') as video_file:
                    preview_caption = f"""
📹 *Scheduled Reel #{reel_id}*

📹 Video: `{reel.video.filename}`
🎵 Music: `{reel.music.filename}`
💬 Quote: {reel.quote.text[:60]}...
✍️ Caption: {reel.caption}
⭐ Quality: {reel.quality_score:.2f}
                    """
                    await update.message.reply_video(
                        video=video_file,
                        caption=preview_caption,
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await update.message.reply_text(f"⚠️ Video file not found: {video_path}")

        except ValueError:
            await update.message.reply_text("❌ Invalid reel ID (must be a number)")
        except Exception as e:
            logger.error(f"Schedule preview error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            session.close()

    # ==================== Button Callbacks ====================

    async def button_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle approve button callback."""
        query = update.callback_query
        reel_id = int(query.data.split("_")[1])

        await self.approve_reel(query, reel_id, context)

    async def button_reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle reject button callback - delete from pending or approved."""
        query = update.callback_query
        reel_id = int(query.data.split("_")[1])

        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            reel = reel_repo.get_by_id(reel_id)

            if not reel:
                await query.answer("❌ Reel not found", show_alert=True)
                return

            # If approved, also delete from schedule
            if reel.status == "approved":
                sched_repo = ScheduledPostRepository(session)
                scheduled = sched_repo.session.query(ScheduledPost).filter(
                    ScheduledPost.reel_id == reel_id
                ).first()
                if scheduled:
                    sched_repo.session.delete(scheduled)
                    sched_repo.session.commit()
                    logger.info(f"Reel #{reel_id} removed from schedule during reject")

            # Delete the reel
            reel_repo.update_status(reel_id, "rejected")

            await query.answer("❌ Reel rejected and deleted", show_alert=True)

            # Try to edit caption if it's a video message, otherwise edit text
            try:
                await query.edit_message_caption(
                    caption=f"❌ *Reel #{reel_id} Rejected*\n\nDeleted from queue",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                # Fallback if message is text-only
                try:
                    await query.edit_message_text("❌ Reel rejected and deleted from queue")
                except:
                    pass

            logger.info(f"Reel #{reel_id} rejected by user {update.effective_user.id}")

        except Exception as e:
            logger.error(f"Reject error: {e}")
            await query.answer(f"Error: {str(e)}", show_alert=True)
        finally:
            session.close()

    async def button_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle preview button callback."""
        from telegram.error import BadRequest

        query = update.callback_query
        logger.info(f"Preview button clicked: {query.data}")

        try:
            reel_id = int(query.data.split("_")[1])
            logger.info(f"Preview requested for reel {reel_id}")
        except Exception as e:
            logger.error(f"Failed to parse preview data: {e}")
            try:
                await query.answer(f"Invalid preview data")
            except BadRequest:
                logger.warning("Query timeout - callback expired")
            return

        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            reel = reel_repo.get_by_id(reel_id)

            if not reel:
                logger.warning(f"Reel {reel_id} not found in database")
                try:
                    await query.answer("Reel not found")
                except BadRequest:
                    logger.warning("Query timeout - callback expired")
                return

            # Acknowledge the callback immediately to avoid timeout
            try:
                await query.answer("⏳ Loading preview...", show_alert=False)
            except BadRequest:
                logger.warning("Query timeout - could not acknowledge callback")

            # Send the actual video file as preview
            video_path = Path(reel.output_path)
            if video_path.exists():
                logger.info(f"Sending video preview for reel {reel_id}: {video_path}")
                with open(video_path, 'rb') as video_file:
                    # Create preview caption with buttons
                    preview_caption = f"""
🎬 *Reel Preview*

📹 Video: `{reel.video.filename}`
🎵 Music: `{reel.music.filename}`
💬 Quote: {reel.quote.text}
✍️ Caption: {reel.caption}
⭐ Quality: {reel.quality_score:.2f}
                    """

                    # Create action buttons
                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{reel_id}"),
                            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{reel_id}"),
                        ]
                    ])

                    try:
                        # Edit both media and caption with buttons
                        await query.edit_message_media(
                            media=InputMediaVideo(media=video_file)
                        )
                        await query.edit_message_caption(
                            caption=preview_caption,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
                    except Exception as e:
                        logger.warning(f"Could not replace media, showing preview as text: {e}")
                        # Fallback to text-only preview with buttons
                        await query.edit_message_text(
                            preview_caption,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
            else:
                # Fallback to text preview if file not found
                logger.warning(f"Video file not found: {video_path}")
                preview_text = f"""
🎬 *Reel Preview*

📹 Video: `{reel.video.filename}`
🎵 Music: `{reel.music.filename}`
💬 Quote: {reel.quote.text}
✍️ Caption: {reel.caption}
⭐ Quality: {reel.quality_score:.2f}

⚠️ Video file not found: {video_path}
                """
                await query.edit_message_text(preview_text, parse_mode=ParseMode.MARKDOWN)

        except BadRequest as e:
            if "Query is too old" in str(e) or "response timeout" in str(e):
                logger.warning(f"Preview request timed out (callback expired): {e}")
            else:
                logger.error(f"Telegram API error: {e}")
        except Exception as e:
            logger.error(f"Preview error: {e}")
            try:
                await query.answer(f"Error: {str(e)}", show_alert=True)
            except BadRequest:
                logger.warning("Query timeout - could not send error message")
        finally:
            session.close()

    async def send_reel_preview(self, reel_id: int, reel_data: Dict[str, Any]) -> None:
        """Send reel preview to admin for approval."""
        if not self.admin_users:
            logger.warning("No admin users configured for notifications")
            return

        try:
            app = Application.builder().token(self.bot_token).build()

            # Handle both single-part (quote) and two-part (hook+payoff) reels
            is_two_part = reel_data.get('is_two_part', False)
            if is_two_part:
                hook = reel_data.get('hook', 'N/A')
                payoff = reel_data.get('payoff', 'N/A')
                quote_text = f"🎣 *Hook:* {hook}\n💥 *Payoff:* {payoff}"
            else:
                quote = reel_data.get('quote', 'N/A')
                quote_text = f"💬 *Quote:* {quote}"

            caption = reel_data.get('caption', 'N/A')
            preview_msg = f"""
🎬 *New Reel Generated*

📹 Video: `{reel_data.get('video_name', 'N/A')}`
🎵 Music: `{reel_data.get('music_name', 'N/A')}`
{quote_text}
✍️ *Caption:* {caption}
⭐ Quality: {reel_data.get('quality_score', 0):.2f}

Ready for approval?
            """

            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{reel_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{reel_id}"),
                ],
                [
                    InlineKeyboardButton("👁️ Preview", callback_data=f"preview_{reel_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            for admin_id in self.admin_users:
                try:
                    await app.bot.send_message(
                        chat_id=admin_id,
                        text=preview_msg,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Failed to send preview to admin {admin_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to send reel preview: {e}")

    async def send_notification(self, message: str, level: str = "info") -> None:
        """Send notification to all admins."""
        if not self.admin_users or not self.bot_token:
            return

        try:
            app = Application.builder().token(self.bot_token).build()

            emoji = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}.get(
                level, "ℹ️"
            )

            for admin_id in self.admin_users:
                try:
                    await app.bot.send_message(
                        chat_id=admin_id,
                        text=f"{emoji} {message}"
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to admin {admin_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    async def approve_reel(
        self,
        query,
        reel_id: int,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Approve a reel from button callback."""
        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            reel_repo.update_status(reel_id, "approved")

            success = False
            message = "Orchestrator unavailable"
            if self.orchestrator:
                success, message = await self.orchestrator.schedule_reel(reel_id)

            if success:
                await query.answer("✅ Reel approved and scheduled!", show_alert=True)
                caption = f"✅ *Reel #{reel_id} Approved*\n\n✓ {message}"
                text = f"✅ Reel #{reel_id} approved and scheduled"
            else:
                await query.answer(f"⚠️ Approved but scheduling failed: {message}", show_alert=True)
                caption = f"⚠️ *Reel #{reel_id} Approved*\n\n❌ Scheduling failed: {message}"
                text = f"⚠️ Reel #{reel_id} approved but scheduling failed: {message}"

            # Try to edit caption if it's a video message, otherwise edit text
            try:
                await query.edit_message_caption(caption=caption, parse_mode=ParseMode.MARKDOWN)
            except:
                # Fallback if message is text-only
                try:
                    await query.edit_message_text(text)
                except:
                    pass  # Message already edited by Telegram

            logger.info(f"Reel #{reel_id} approved via button (scheduled: {success})")

        except Exception as e:
            logger.error(f"Approve error: {e}")
            await query.answer(f"Error: {str(e)}", show_alert=True)
        finally:
            session.close()

    @staticmethod
    def _format_time(dt: datetime) -> str:
        """Format datetime for display."""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    # ==================== New Scheduling Commands ====================

    async def reschedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reschedule command - reschedule a reel to new date/time.

        Usage: /reschedule <reel_id> <date> <time>
        Example: /reschedule 123 2025-12-25 18:00
        """
        if not await self._check_admin(update, context):
            return

        try:
            if not context.args or len(context.args) < 3:
                await update.message.reply_text(
                    "❌ Usage: /reschedule <reel_id> <date> <time>\n"
                    "Example: /reschedule 123 2025-12-25 18:00"
                )
                return

            reel_id = int(context.args[0])
            date_str = context.args[1]  # YYYY-MM-DD
            time_str = context.args[2]  # HH:MM

            # Parse the datetime
            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            dt_utc, error = datetime_helpers.parse_datetime_string(date_str, time_str, tz_name)

            if error:
                await update.message.reply_text(f"❌ {error}")
                return

            # Call orchestrator
            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            success, message = await self.orchestrator.reschedule_reel(reel_id, dt_utc)

            if success:
                await update.message.reply_text(f"✅ {message}")
            else:
                await update.message.reply_text(f"❌ {message}")

        except ValueError:
            await update.message.reply_text("❌ Invalid reel_id. Must be a number.")
        except Exception as e:
            logger.error(f"Reschedule error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def calendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /calendar command - view scheduled posts calendar.

        Usage: /calendar [days]
        Example: /calendar 30 (default 30, max 90)
        """
        if not await self._check_admin(update, context):
            return

        try:
            days = int(context.args[0]) if context.args else 30
            days = min(days, 90)  # Max 90 days

            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            calendar = await self.orchestrator.get_calendar_view(days=days)

            if not calendar:
                await update.message.reply_text(f"📅 No posts scheduled for the next {days} days")
                return

            # Group by date
            by_date = {}
            for entry in calendar:
                date_str = entry["scheduled_time"].split(" ")[0]  # Extract date part
                if date_str not in by_date:
                    by_date[date_str] = []
                by_date[date_str].append(entry)

            # Format message
            msg = f"📅 *Calendar (Next {days} Days)*\n\n"

            for date in sorted(by_date.keys()):
                msg += f"*📆 {date}*\n"
                for entry in by_date[date]:
                    time_part = entry["scheduled_time"].split(" ")[1]  # Extract time
                    quality = entry["quality"]
                    quote_preview = entry["quote"][:50] if entry["quote"] else "(no quote)"
                    msg += (
                        f"  • Reel #{entry['reel_id']}: {time_part}\n"
                        f"    💬 {quote_preview}\n"
                        f"    ⭐ Quality: {quality:.2f}\n"
                    )

                msg += "\n"

            # Handle message length limit (4096 chars)
            if len(msg) > 4000:
                # Send in chunks
                parts = msg.split("\n\n")
                current_msg = ""
                for part in parts:
                    if len(current_msg) + len(part) + 2 > 4000:
                        if current_msg:
                            await update.message.reply_text(current_msg, parse_mode=ParseMode.MARKDOWN)
                        current_msg = part + "\n\n"
                    else:
                        current_msg += part + "\n\n"

                if current_msg:
                    await update.message.reply_text(current_msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        except ValueError:
            await update.message.reply_text("❌ Invalid days count. Must be a number (1-90)")
        except Exception as e:
            logger.error(f"Calendar error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def approve_at(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /approve_at command - approve reel with custom scheduling time.

        Usage: /approve_at <reel_id> <date> <time>
        Example: /approve_at 456 2025-12-26 14:00
        """
        if not await self._check_admin(update, context):
            return

        try:
            if not context.args or len(context.args) < 3:
                await update.message.reply_text(
                    "❌ Usage: /approve_at <reel_id> <date> <time>\n"
                    "Example: /approve_at 456 2025-12-26 14:00"
                )
                return

            reel_id = int(context.args[0])
            date_str = context.args[1]  # YYYY-MM-DD
            time_str = context.args[2]  # HH:MM

            # Parse the datetime
            tz_name = self.config.get("scheduling.timezone", "Europe/Istanbul")
            dt_utc, error = datetime_helpers.parse_datetime_string(date_str, time_str, tz_name)

            if error:
                await update.message.reply_text(f"❌ {error}")
                return

            # Call orchestrator
            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            success, message = await self.orchestrator.schedule_reel_at(reel_id, dt_utc)

            if success:
                await update.message.reply_text(f"✅ {message}")
            else:
                await update.message.reply_text(f"❌ {message}")

        except ValueError:
            await update.message.reply_text("❌ Invalid reel_id. Must be a number.")
        except Exception as e:
            logger.error(f"Approve_at error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def set_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set_schedule command - set default posting schedule.

        Usage: /set_schedule <day> <time>
        Days: 0=Monday, 1=Tuesday, ..., 6=Sunday
        Example: /set_schedule 1 18:00 (Tuesday at 18:00)
        """
        if not await self._check_admin(update, context):
            return

        try:
            if not context.args or len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Usage: /set_schedule <day> <time>\n"
                    "Days: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun\n"
                    "Example: /set_schedule 1 18:00"
                )
                return

            day = int(context.args[0])
            time_str = context.args[1]

            # Validate
            is_valid, error = datetime_helpers.validate_day_of_week(day)
            if not is_valid:
                await update.message.reply_text(f"❌ {error}")
                return

            time_tuple, error = datetime_helpers.parse_time_string(time_str)
            if error:
                await update.message.reply_text(f"❌ {error}")
                return

            # Call orchestrator
            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            success, message = await self.orchestrator.update_schedule_config(day, time_str)

            if success:
                await update.message.reply_text(f"✅ {message}")
            else:
                await update.message.reply_text(f"❌ {message}")

        except ValueError:
            await update.message.reply_text("❌ Invalid day or time format.")
        except Exception as e:
            logger.error(f"Set_schedule error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /get_schedule command - view current default posting schedule."""
        if not await self._check_admin(update, context):
            return

        try:
            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            schedules = await self.orchestrator.get_schedule_config()

            if not schedules:
                await update.message.reply_text("⚙️ No schedule configured")
                return

            msg = "⚙️ *Default Posting Schedule*\n\n"

            # Extract timezone info
            tz_name = "Europe/Istanbul"
            for sched in schedules:
                if sched.get("type") == "info":
                    tz_name = sched.get("timezone", "Europe/Istanbul")
                    continue

                msg += f"• {sched.get('day')}: {sched.get('time')}\n"

            msg += f"\n📍 Timezone: {tz_name}"

            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Get_schedule error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def scheduler_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /scheduler_status command - scheduler health overview."""
        if not await self._check_admin(update, context):
            return

        try:
            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            status = await self.orchestrator.get_scheduler_status()
            counts = status["counts"]

            now_local_str = status["now_local"].strftime("%Y-%m-%d %H:%M:%S %Z")
            now_utc_str = status["now_utc"].strftime("%Y-%m-%d %H:%M:%S UTC")
            next_wakeup = status["next_wakeup_utc"]
            next_wakeup_str = next_wakeup.strftime("%Y-%m-%d %H:%M:%S %Z") if next_wakeup else "unknown"

            msg = f"""
🩺 *Scheduler Status*

Running: {"▶️ yes" if status["running"] else "⏸️ no"}
Now (UTC): {now_utc_str}
Now ({status["timezone"]}): {now_local_str}
Next wake-up: {next_wakeup_str}

📊 *Scheduled posts*
• Pending: {counts.get("pending", 0)}
• Publishing: {counts.get("publishing", 0)}
• Retry wait: {counts.get("retry_wait", 0)}
• Failed: {counts.get("failed", 0)}
• Overdue (due but not yet claimed): {status["overdue"]}
            """

            if status["recent_failed"]:
                msg += "\n❌ *Recent failures*\n"
                for f in status["recent_failed"]:
                    err = (f["error"] or "unknown error")[:150]
                    msg += f"• Scheduled #{f['id']} (reel #{f['reel_id']}): {err}\n"

            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Scheduler status error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def retry_failed(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /retry_failed <scheduled_post_id> - give a failed post a fresh retry budget."""
        if not await self._check_admin(update, context):
            return

        try:
            post_id = int(context.args[0]) if context.args else None
            if not post_id:
                await update.message.reply_text("❌ Usage: /retry_failed <scheduled_post_id>")
                return

            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            success, message = await self.orchestrator.retry_failed(post_id)
            await update.message.reply_text(f"{'✅' if success else '❌'} {message}", parse_mode=ParseMode.MARKDOWN)

        except ValueError:
            await update.message.reply_text("❌ Invalid scheduled_post_id. Must be a number.")
        except Exception as e:
            logger.error(f"Retry_failed error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def publish_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /publish_now <scheduled_post_id> - force-publish a specific scheduled post immediately."""
        if not await self._check_admin(update, context):
            return

        try:
            post_id = int(context.args[0]) if context.args else None
            if not post_id:
                await update.message.reply_text("❌ Usage: /publish_now <scheduled_post_id>")
                return

            if not self.orchestrator:
                await update.message.reply_text("❌ Orchestrator not available")
                return

            success, message = await self.orchestrator.publish_now(post_id)
            await update.message.reply_text(f"{'✅' if success else '❌'} {message}", parse_mode=ParseMode.MARKDOWN)

        except ValueError:
            await update.message.reply_text("❌ Invalid scheduled_post_id. Must be a number.")
        except Exception as e:
            logger.error(f"Publish_now error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def start_polling(self) -> None:
        """Start Telegram bot polling."""
        if not self.bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return

        logger.info("Starting Telegram bot polling...")

        application = Application.builder().token(self.bot_token).build()

        # Add command handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status))
        application.add_handler(CommandHandler("generate", self.generate))
        application.add_handler(CommandHandler("queue", self.queue))
        application.add_handler(CommandHandler("schedule", self.schedule))
        application.add_handler(CommandHandler("approve", self.approve))
        application.add_handler(CommandHandler("reject", self.reject))
        application.add_handler(CommandHandler("analytics", self.analytics))
        application.add_handler(CommandHandler("insights", self.insights))
        application.add_handler(CommandHandler("top", self.top))
        application.add_handler(CommandHandler("deleteschedule", self.deleteschedule))
        application.add_handler(CommandHandler("schedulepreview", self.schedulepreview))
        application.add_handler(CommandHandler("preview", self.preview))
        application.add_handler(CommandHandler("post_now", self.post_now))

        # Add new scheduling command handlers
        application.add_handler(CommandHandler("reschedule", self.reschedule))
        application.add_handler(CommandHandler("calendar", self.calendar))
        application.add_handler(CommandHandler("approve_at", self.approve_at))
        application.add_handler(CommandHandler("set_schedule", self.set_schedule))
        application.add_handler(CommandHandler("get_schedule", self.get_schedule))

        # Add scheduler reliability command handlers
        application.add_handler(CommandHandler("scheduler_status", self.scheduler_status))
        application.add_handler(CommandHandler("retry_failed", self.retry_failed))
        application.add_handler(CommandHandler("publish_now", self.publish_now))

        # Add button callbacks
        application.add_handler(CallbackQueryHandler(self.button_approve, pattern="^approve_"))
        application.add_handler(CallbackQueryHandler(self.button_reject, pattern="^reject_"))
        application.add_handler(CallbackQueryHandler(self.button_preview, pattern="^preview_"))

        # Start polling with proper cleanup
        logger.info("Telegram application initialized - listening for messages")

        try:
            # Start the application
            await application.initialize()
            await application.start()

            # Start polling without trying to manage the event loop
            # (it's already running from the main.py event loop)
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            logger.info("Telegram bot polling active (event loop managed externally)")

            # Keep polling alive - this will block here
            while application.updater.running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Telegram bot polling cancelled")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
        finally:
            # Cleanup
            try:
                if application.updater.running:
                    await application.updater.stop()
                await application.stop()
                await application.shutdown()
            except:
                pass