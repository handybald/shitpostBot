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
• `/generate [count]` - Generate N reels (default: 5)
• `/queue` - View pending reels
• `/approve <reel_id>` - Approve reel for publishing
• `/reject <reel_id>` - Reject and delete reel
• `/schedule` - View scheduled posts (next 7 days)
• `/analytics [days]` - Performance report (default: 7)
• `/help` - Show this message
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
• `/generate` - Generate 5 reels
• `/generate 10` - Generate 10 reels
• `/queue` - View pending reels awaiting approval

*Approval Workflow*
• `/approve <id>` - Approve reel #id
• `/reject <id>` - Reject reel #id
• `/preview <id>` - Preview reel metadata

*Scheduling*
• `/schedule` - View next 7 days
• `/post_now <id>` - Publish immediately (skip schedule)

*Analytics*
• `/analytics` - Last 7 days
• `/analytics 30` - Last 30 days
• `/top` - Top performing posts
• `/insights` - AI-generated insights

*System*
• `/status` - System health & stats
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
• Last check: {self._format_time(datetime.utcnow())}

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
        """Handle /generate command."""
        if not await self._check_admin(update, context):
            return

        try:
            count = int(context.args[0]) if context.args else 5
            count = min(count, 20)  # Max 20 per command

            await update.message.reply_text(
                f"🎬 Generating {count} reels...\n\nThis may take a few minutes.",
                parse_mode=ParseMode.MARKDOWN
            )

            if self.orchestrator:
                results = await self.orchestrator.generate_content(count=count)
                await update.message.reply_text(
                    f"✅ Generated {len(results)} reels",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "⚠️ Orchestrator not available",
                    parse_mode=ParseMode.MARKDOWN
                )

        except ValueError:
            await update.message.reply_text("❌ Usage: /generate [count]")
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
            await self.orchestrator.publish_reel_to_instagram(reel_id)
            await update.message.reply_text(f"✅ Reel #{reel_id} published to Instagram!", parse_mode=ParseMode.MARKDOWN)

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
💬 Quote: {reel.quote.text[:50]}...
✍️ Caption: {reel.caption[:100]}...
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

                # Schedule for posting
                if self.orchestrator:
                    await self.orchestrator.schedule_reel(reel_id)

                await update.message.reply_text(
                    f"✅ Reel #{reel_id} approved and scheduled for publishing",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Reel #{reel_id} approved by user {update.effective_user.id}")

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
💬 Quote: {reel.quote.text[:50]}...
✍️ Caption: {reel.caption[:100]}...
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
        query = update.callback_query
        logger.info(f"Preview button clicked: {query.data}")

        try:
            reel_id = int(query.data.split("_")[1])
            logger.info(f"Preview requested for reel {reel_id}")
        except Exception as e:
            logger.error(f"Failed to parse preview data: {e}")
            await query.answer(f"Invalid preview data")
            return

        session = get_session()
        try:
            reel_repo = GeneratedReelRepository(session)
            reel = reel_repo.get_by_id(reel_id)

            if not reel:
                logger.warning(f"Reel {reel_id} not found in database")
                await query.answer("Reel not found")
                return

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
💬 Quote: {reel.quote.text[:50]}...
✍️ Caption: {reel.caption[:100]}...
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

                await query.answer("✅ Preview loaded with actions", show_alert=False)
            else:
                # Fallback to text preview if file not found
                logger.warning(f"Video file not found: {video_path}")
                preview_text = f"""
🎬 *Reel Preview*

📹 Video: `{reel.video.filename}`
🎵 Music: `{reel.music.filename}`
💬 Quote: {reel.quote.text[:50]}...
✍️ Caption: {reel.caption[:100]}...
⭐ Quality: {reel.quality_score:.2f}

⚠️ Video file not found: {video_path}
                """
                await query.edit_message_text(preview_text, parse_mode=ParseMode.MARKDOWN)
                await query.answer("⚠️ Video file missing", show_alert=True)

        except Exception as e:
            logger.error(f"Preview error: {e}")
            await query.answer(f"Error: {str(e)}", show_alert=True)
        finally:
            session.close()

    async def send_reel_preview(self, reel_id: int, reel_data: Dict[str, Any]) -> None:
        """Send reel preview to admin for approval."""
        if not self.admin_users:
            logger.warning("No admin users configured for notifications")
            return

        try:
            app = Application.builder().token(self.bot_token).build()

            preview_msg = f"""
🎬 *New Reel Generated*

📹 Video: `{reel_data.get('video_name', 'N/A')}`
🎵 Music: `{reel_data.get('music_name', 'N/A')}`
💬 Quote: {reel_data.get('quote', 'N/A')[:60]}
✍️ Caption: {reel_data.get('caption', 'N/A')[:80]}
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
                        text=f"{emoji} {message}",
                        parse_mode=ParseMode.MARKDOWN
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

            if self.orchestrator:
                await self.orchestrator.schedule_reel(reel_id)

            await query.answer("✅ Reel approved and scheduled!", show_alert=True)

            # Try to edit caption if it's a video message, otherwise edit text
            try:
                await query.edit_message_caption(
                    caption=f"✅ *Reel #{reel_id} Approved*\n\n✓ Scheduled for posting",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                # Fallback if message is text-only
                try:
                    await query.edit_message_text(f"✅ Reel #{reel_id} approved and scheduled")
                except:
                    pass  # Message already edited by Telegram

            logger.info(f"Reel #{reel_id} approved via button")

        except Exception as e:
            logger.error(f"Approve error: {e}")
            await query.answer(f"Error: {str(e)}", show_alert=True)
        finally:
            session.close()

    @staticmethod
    def _format_time(dt: datetime) -> str:
        """Format datetime for display."""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

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